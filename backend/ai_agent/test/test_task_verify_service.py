"""Test TaskVerifyService: xác minh claim "đã hoàn thành" mà KHÔNG tự đổi tasks.status.

Bất biến quan trọng được test:
  - task chưa DONE -> nhắc user tự cập nhật, KHÔNG có UPDATE tasks.
  - task DONE -> confirm & cảm ơn.
  - không có ngữ cảnh -> hỏi lại user task nào, không ghi follow-up.
  - không phải assignee -> không ghi gì.

Không gọi LLM/mạng: dùng _FakeSession trả kết quả theo SQL substring, và
_FakeLLM để ép tất định (TaskVerifyService(llm=...)).
"""
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ai_agent.task_update.task_verify_service import TaskFacts, TaskVerifyService


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Trả kết quả theo SQL substring. responses: dict[substring, list[rows]]."""

    def __init__(self, responses):
        self.responses = responses
        self.statements = []

    async def execute(self, statement, params=None):
        sql = str(statement).lower()
        self.statements.append((sql, params))
        for key, rows in self.responses.items():
            if key in sql:
                return _Result(rows)
        return _Result([])

    async def commit(self):
        pass


PROFILE = {"full_name": "Trần Tấn Lực"}


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    """LLM giả: trả content cố định, hoặc raise nếu fail=True."""

    def __init__(self, content="", fail=False):
        self._content = content
        self._fail = fail

    def invoke(self, prompt):
        if self._fail:
            raise RuntimeError("LLM down")
        return _FakeMessage(self._content)


def _agent():
    # Dùng FakeLLM(fail=True) để ép fallback tất định — KHÔNG gọi LLM/mạng thật.
    # (Truyền llm=None sẽ khiến __init__ tự tạo ChatOpenAI từ env, mất tất định.)
    return TaskVerifyService(llm=_FakeLLM(fail=True))


def test_pending_followup_not_done_returns_nudge():
    db = _FakeSession({
        "from agent_follow_ups": [(99, 5)],          # follow_up_id=99, task_id=5
        "from tasks": [(5, "[1.4] Tỷ giá hối đoái tự động", "IN_PROGRESS")],
    })
    out = asyncio.run(_agent().verify(
        message="tôi update rồi", user_id="10", thread_id="t1",
        user_profile=PROFILE, db=db,
    ))
    assert out["resolved"] is True and out["status"] == "IN_PROGRESS"
    assert "[1.4] Tỷ giá hối đoái tự động" in out["message"]
    assert "vẫn" in out["message"] and "Đang làm" in out["message"]
    # Đã đánh dấu follow-up REPLIED, KHÔNG update tasks
    assert any("update agent_follow_ups" in s for s, _ in db.statements)
    assert not any("update tasks" in s for s, _ in db.statements)


def test_pending_followup_done_returns_confirm():
    db = _FakeSession({
        "from agent_follow_ups": [(99, 5)],
        "from tasks": [(5, "[1.4] Tỷ giá hối đoái tự động", "DONE")],
    })
    out = asyncio.run(_agent().verify(
        message="xong rồi", user_id="10", thread_id="t1", user_profile=PROFILE, db=db,
    ))
    assert out["status"] == "DONE"
    assert "Hoàn thành" in out["message"] and "Cảm ơn" in out["message"]
    assert any("update agent_follow_ups" in s for s, _ in db.statements)
    assert not any("update tasks" in s for s, _ in db.statements)


def test_no_context_asks_user():
    db = _FakeSession({})  # không follow-up, không audit
    out = asyncio.run(_agent().verify(
        message="done", user_id="10", thread_id="t1", user_profile=PROFILE, db=db,
    ))
    assert out["resolved"] is False and out["task_id"] is None
    assert "task nào" in out["message"]
    assert not any("update agent_follow_ups" in s for s, _ in db.statements)


def test_not_assignee_no_writes():
    db = _FakeSession({
        "from agent_follow_ups": [(99, 5)],
        # tasks query trả rỗng (không phải assignee)
    })
    out = asyncio.run(_agent().verify(
        message="đã xong", user_id="10", thread_id="t1", user_profile=PROFILE, db=db,
    ))
    assert out["resolved"] is False
    assert not any("update agent_follow_ups" in s for s, _ in db.statements)


def test_audit_fallback_resolves_single_task():
    # Không có follow-up PENDING, nhưng audit log có 1 task -> resolve được.
    db = _FakeSession({
        "from agent_audit_log": [({"thread_id": "t1", "task_ids": [7]},)],
        "from tasks": [(7, "Task X", "TODO")],
    })
    out = asyncio.run(_agent().verify(
        message="làm xong", user_id="10", thread_id="t1", user_profile=PROFILE, db=db,
    ))
    assert out["resolved"] is True and out["task_id"] == 7
    assert "Cần làm" in out["message"]
    # Resolve qua audit -> không có follow-up row để cập nhật
    assert not any("update agent_follow_ups" in s for s, _ in db.statements)


def test_narrate_prompt_forbids_praise_when_not_done():
    # Prompt narrate cho ca CHƯA done phải chứa ràng buộc cấm khen + nêu rõ chưa xong.
    agent = TaskVerifyService(llm=_FakeLLM(fail=True))
    facts = TaskFacts(
        task_id=5, follow_up_id=99, task_name="[1.4] Tỷ giá hối đoái tự động",
        status="IN_PROGRESS", is_assignee=True,
    )
    prompt = agent._narrate_prompt(facts, PROFILE)
    assert "CHƯA Hoàn thành" in prompt
    assert "KHÔNG khen" in prompt
    assert "Đang làm" in prompt  # nhãn trạng thái thực tế được nhúng


def test_llm_error_falls_back_to_deterministic():
    # LLM raise -> narrate phải trả câu fallback tất định (chứa "vẫn"/"Đang làm").
    db = _FakeSession({
        "from agent_follow_ups": [(99, 5)],
        "from tasks": [(5, "[1.4] Tỷ giá hối đoái tự động", "IN_PROGRESS")],
    })
    agent = TaskVerifyService(llm=_FakeLLM(fail=True))
    out = asyncio.run(agent.verify(
        message="tôi update rồi", user_id="10", thread_id="t1",
        user_profile=PROFILE, db=db,
    ))
    assert "vẫn" in out["message"] and "Đang làm" in out["message"]
    assert "Hoàn thành. Cảm ơn" not in out["message"]  # không khen nhầm


def test_llm_narration_used_when_available():
    # LLM ok -> dùng output của LLM (không phải template).
    db = _FakeSession({
        "from agent_follow_ups": [(99, 5)],
        "from tasks": [(5, "Task X", "IN_PROGRESS")],
    })
    agent = TaskVerifyService(llm=_FakeLLM(content="Câu do LLM sinh."))
    out = asyncio.run(agent.verify(
        message="tôi update rồi", user_id="10", thread_id="t1",
        user_profile=PROFILE, db=db,
    ))
    assert out["message"] == "Câu do LLM sinh."
    # Vẫn mark follow-up REPLIED, KHÔNG update tasks
    assert any("update agent_follow_ups" in s for s, _ in db.statements)
    assert not any("update tasks" in s for s, _ in db.statements)
