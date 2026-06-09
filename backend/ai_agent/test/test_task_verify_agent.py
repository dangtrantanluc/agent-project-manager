"""Test TaskVerifyAgent: xác minh claim "đã hoàn thành" mà KHÔNG tự đổi tasks.status.

Bất biến quan trọng được test:
  - task chưa DONE -> nhắc user tự cập nhật, KHÔNG có UPDATE tasks.
  - task DONE -> confirm & cảm ơn.
  - không có ngữ cảnh -> hỏi lại user task nào, không ghi follow-up.
  - không phải assignee -> không ghi gì.

Không gọi LLM/mạng: dùng _FakeSession trả kết quả theo SQL substring.
ConversationAgent() được khởi tạo trong TaskVerifyAgent chỉ để dùng _first_name
(không phát request).
"""
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ai_agent.task_update.task_verify_agent import TaskVerifyAgent


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


def _agent():
    return TaskVerifyAgent()


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
