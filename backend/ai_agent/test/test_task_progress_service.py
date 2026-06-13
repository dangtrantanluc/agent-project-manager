"""Test TaskProgressService: cập nhật tiến độ % từ chat (Luồng 3, ⑬⑭).

Bất biến quan trọng:
  - có % + đúng assignee -> UPDATE tasks (progress + status suy ra) + ghi audit_log.
  - 100% -> status DONE; 1..99% -> IN_PROGRESS; 0% -> giữ nguyên status.
  - task CANCELLED -> KHÔNG update.
  - không xác định được task -> hỏi lại, KHÔNG update.
  - không có % -> uỷ cho TaskVerifyService (hành vi cũ), KHÔNG update tasks.

Không gọi LLM/mạng: _FakeSession trả theo SQL substring; verify dùng _FakeLLM(fail=True).
"""
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ai_agent.task_update.task_verify_service import TaskVerifyService
from app.services.task_progress_service import (
    TaskProgressService, extract_percent, has_percent, _status_from_percent,
)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
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


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    def __init__(self, content="", fail=False):
        self._content, self._fail = content, fail

    def invoke(self, prompt):
        if self._fail:
            raise RuntimeError("LLM down")
        return _FakeMessage(self._content)


PROFILE = {"full_name": "Trần Tấn Lực"}


def _svc():
    # verify_service dùng FakeLLM(fail=True) -> narrate fallback tất định.
    verify = TaskVerifyService(llm=_FakeLLM(fail=True))
    return TaskProgressService(verify_service=verify)


def _updated_tasks_params(db):
    return [p for s, p in db.statements if "update tasks" in s]


# ── extract_percent / helpers ─────────────────────────────────────────────────
def test_extract_percent_variants():
    assert extract_percent("đã xong 80%") == 80
    assert extract_percent("xong 80 %") == 80
    assert extract_percent("được 80 phần trăm rồi") == 80
    assert extract_percent("hoàn thành 100%") == 100
    assert extract_percent("mới 0%") == 0
    assert extract_percent("120%") is None       # ngoài 0..100
    assert extract_percent("không có số") is None
    assert has_percent("task X 50%") is True
    assert has_percent("xong rồi") is False


def test_status_from_percent():
    assert _status_from_percent(100, "IN_PROGRESS") == "DONE"
    assert _status_from_percent(80, "TODO") == "IN_PROGRESS"
    assert _status_from_percent(0, "IN_PROGRESS") is None   # giữ nguyên


# ── update path ───────────────────────────────────────────────────────────────
def test_update_in_progress_writes_task_and_audit():
    db = _FakeSession({
        "from agent_follow_ups": [(99, 5)],
        "from tasks": [(5, "Task X", "TODO")],
        "update tasks": [(None,)],          # RETURNING milestone_id -> None
    })
    out = asyncio.run(_svc().update(
        message="đã làm task X xong 80%", user_id="10", thread_id="t1",
        user_profile=PROFILE, db=db,
    ))
    assert out["resolved"] is True
    assert out["status"] == "IN_PROGRESS" and out["progress"] == 80
    assert "80%" in out["message"]
    ups = _updated_tasks_params(db)
    assert ups and ups[0]["p"] == 80 and ups[0]["st"] == "IN_PROGRESS"
    assert any("insert into agent_audit_log" in s for s, _ in db.statements)
    # đã đánh dấu follow-up REPLIED
    assert any("update agent_follow_ups" in s for s, _ in db.statements)


def test_update_100_percent_marks_done():
    db = _FakeSession({
        "from agent_follow_ups": [(99, 5)],
        "from tasks": [(5, "Task X", "IN_PROGRESS")],
        "update tasks": [(None,)],
    })
    out = asyncio.run(_svc().update(
        message="task X hoàn thành 100%", user_id="10", thread_id="t1",
        user_profile=PROFILE, db=db,
    ))
    assert out["status"] == "DONE" and out["progress"] == 100
    assert "Hoàn thành" in out["message"]
    assert _updated_tasks_params(db)[0]["st"] == "DONE"


def test_update_zero_percent_keeps_status():
    db = _FakeSession({
        "from agent_follow_ups": [(99, 5)],
        "from tasks": [(5, "Task X", "IN_PROGRESS")],
        "update tasks": [(None,)],
    })
    out = asyncio.run(_svc().update(
        message="mới làm được 0% thôi", user_id="10", thread_id="t1",
        user_profile=PROFILE, db=db,
    ))
    assert out["progress"] == 0 and out["status"] == "IN_PROGRESS"
    # UPDATE không kèm status cast (giữ nguyên) -> params không có 'st'
    params = _updated_tasks_params(db)[0]
    assert "st" not in params and params["p"] == 0


def test_cancelled_task_not_updated():
    db = _FakeSession({
        "from agent_follow_ups": [(99, 5)],
        "from tasks": [(5, "Task X", "CANCELLED")],
    })
    out = asyncio.run(_svc().update(
        message="task X xong 80%", user_id="10", thread_id="t1",
        user_profile=PROFILE, db=db,
    ))
    assert "Đã huỷ" in out["message"]
    assert not _updated_tasks_params(db)


def test_not_resolved_asks_and_no_update():
    db = _FakeSession({})  # không follow-up, không audit
    out = asyncio.run(_svc().update(
        message="xong 80%", user_id="10", thread_id="t1", user_profile=PROFILE, db=db,
    ))
    assert out["resolved"] is False
    assert "task nào" in out["message"]
    assert not _updated_tasks_params(db)


def test_ambiguous_update_delegates_to_verify():
    # "update rồi" không phải câu hoàn thành rõ ràng, không có % -> verify (hỏi/kiểm),
    # KHÔNG tự đổi tasks.
    db = _FakeSession({
        "from agent_follow_ups": [(99, 5)],
        "from tasks": [(5, "Task X", "DONE")],
    })
    out = asyncio.run(_svc().update(
        message="tôi update rồi nhé", user_id="10", thread_id="t1", user_profile=PROFILE, db=db,
    ))
    assert out["status"] == "DONE"
    assert not _updated_tasks_params(db)


def test_completion_word_sets_done():
    # "đã xong" (không kèm số) + resolve follow-up -> set DONE (progress 100).
    db = _FakeSession({
        "from agent_follow_ups": [(99, 5)],
        "from tasks": [(5, "Task X", "IN_PROGRESS")],
        "update tasks": [(None,)],
    })
    out = asyncio.run(_svc().update(
        message="task X đã xong rồi nhé", user_id="10", thread_id="t1",
        user_profile=PROFILE, db=db,
    ))
    assert out["status"] == "DONE" and out["progress"] == 100
    assert _updated_tasks_params(db)[0]["st"] == "DONE"


def test_negated_100_percent_not_done():
    # "không chắc 100% là kịp" có '100%' nhưng là câu PHỦ ĐỊNH/không chắc ->
    # TUYỆT ĐỐI không set DONE; rơi về verify (không update tasks).
    db = _FakeSession({
        "from agent_follow_ups": [(99, 5)],
        "from tasks": [(5, "Task X", "IN_PROGRESS")],
    })
    out = asyncio.run(_svc().update(
        message="em không chắc 100% là kịp deadline đâu", user_id="10", thread_id="t1",
        user_profile=PROFILE, db=db,
    ))
    assert not _updated_tasks_params(db)
    assert out["status"] == "IN_PROGRESS"


def test_negation_with_low_percent_still_updates():
    # "chưa xong, mới 30%" là báo tiến độ hợp lệ -> vẫn update 30.
    db = _FakeSession({
        "from agent_follow_ups": [(99, 5)],
        "from tasks": [(5, "Task X", "TODO")],
        "update tasks": [(None,)],
    })
    out = asyncio.run(_svc().update(
        message="task X chưa xong đâu, mới được 30%", user_id="10", thread_id="t1",
        user_profile=PROFILE, db=db,
    ))
    assert out["progress"] == 30 and out["status"] == "IN_PROGRESS"


def test_audit_logs_old_progress():
    # Audit phải ghi old_progress đọc từ DB (không còn None cố định).
    # "select progress" phải đứng TRƯỚC "from tasks": FakeSession khớp substring
    # theo thứ tự, mà query old-progress cũng chứa "from tasks".
    db = _FakeSession({
        "from agent_follow_ups": [(99, 5)],
        "select progress": [(40,)],
        "from tasks": [(5, "Task X", "IN_PROGRESS")],
        "update tasks": [(None,)],
    })
    asyncio.run(_svc().update(
        message="task X được 60% rồi", user_id="10", thread_id="t1",
        user_profile=PROFILE, db=db,
    ))
    audits = [p for s, p in db.statements if "insert into agent_audit_log" in s]
    assert audits and '"old_progress": 40' in audits[0]["args"]


def test_resolve_by_task_code_then_done():
    # "update task [2.4] ... done" KHÔNG có follow-up -> resolve theo mã [2.4] trong
    # tin nhắn -> set DONE. _resolve_from_message khớp tasks.name ILIKE '%[2.4]%'.
    db = _FakeSession({
        # không follow-up, không audit
        "name ilike any": [(5,)],                  # _resolve_from_message: 1 task khớp mã [2.4]
        "status::text as status": [(5, "[2.4] Gửi báo giá", "IN_PROGRESS")],  # facts SELECT
        "update tasks": [(None,)],
    })
    out = asyncio.run(_svc().update(
        message="update task [2.4] Gửi báo giá qua email/WhatsApp done cho tôi nha",
        user_id="10", thread_id="t1", user_profile=PROFILE, db=db,
    ))
    assert out["status"] == "DONE" and out["progress"] == 100
    assert _updated_tasks_params(db)[0]["st"] == "DONE"


def test_fuzzy_match_auto_pick_single():
    # "gửi báo giá qua mail done" (gõ tắt, KHÔNG mã) -> khớp mờ 1 task -> set DONE.
    # _gather_facts không ra (no follow-up/code) -> _resolve_candidates token overlap.
    db = _FakeSession({
        # _resolve_candidates: 1 task open của user
        "status::text not in ('done','cancelled')": [(5, "[2.4] Gửi báo giá qua email/WhatsApp")],
        # _facts_for_task: SELECT id,name,status WHERE id AND assignee
        "status::text as status": [(5, "[2.4] Gửi báo giá qua email/WhatsApp", "IN_PROGRESS")],
        "update tasks": [(None,)],
    })
    out = asyncio.run(_svc().update(
        message="bạn updae task gửi báo giá qua mail thành done cho tôi di",
        user_id="10", thread_id="t1", user_profile=PROFILE, db=db,
    ))
    assert out["status"] == "DONE" and out["progress"] == 100


def test_fuzzy_match_ambiguous_returns_menu():
    # 2 task cùng "báo giá" -> trả menu nút bấm, KHÔNG update.
    db = _FakeSession({
        "status::text not in ('done','cancelled')": [
            (5, "[2.4] Gửi báo giá qua email"),
            (6, "[3.1] Gửi báo giá lần 2"),
        ],
    })
    out = asyncio.run(_svc().update(
        message="cập nhật task gửi báo giá xong rồi", user_id="10", thread_id="t1",
        user_profile=PROFILE, db=db,
    ))
    assert out["type"] == "choose_task"
    assert len(out["menu"]) == 2
    assert all(m["payload"].startswith("TASKUPD|") and m["payload"].endswith("|100") for m in out["menu"])
    assert not _updated_tasks_params(db)


def test_apply_payload_updates_chosen_task():
    # Bấm nút "TASKUPD|5|80" -> cập nhật task 5 lên 80%.
    db = _FakeSession({
        "status::text as status": [(5, "Task X", "TODO")],
        "update tasks": [(None,)],
    })
    out = asyncio.run(_svc().apply_payload("TASKUPD|5|80", user_id="10", db=db))
    assert out["status"] == "IN_PROGRESS" and out["progress"] == 80
    assert _updated_tasks_params(db)[0]["p"] == 80


def test_negation_not_completion():
    # "chưa xong" -> KHÔNG coi là hoàn thành -> verify, không update.
    db = _FakeSession({
        "from agent_follow_ups": [(99, 5)],
        "from tasks": [(5, "Task X", "IN_PROGRESS")],
    })
    out = asyncio.run(_svc().update(
        message="task X chưa xong đâu", user_id="10", thread_id="t1",
        user_profile=PROFILE, db=db,
    ))
    assert not _updated_tasks_params(db)
