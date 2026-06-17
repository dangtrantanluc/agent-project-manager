"""Test TaskOutcomeService (thuần, không DB thật, không LLM).

Phủ:
  - extract_outcome fallback (LLM None): tách result/issues theo mốc từ khoá.
  - is_skip: "bỏ qua" -> True; "không có khó khăn, kết quả X" -> False.
  - apply_reply RESULT_ISSUES: ghi tasks.result/issues + mark replied + audit.
  - apply_reply BLOCKER_REASON: ghi task_blockers.description (+ issues).
  - apply_reply skip: không ghi tasks, chỉ đóng follow-up.
  - find_pending: đúng 1 PENDING -> dict; nhiều -> None.
"""
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ai_agent.task_update.task_verify_service import TaskVerifyService
from app.services.task_outcome_service import TaskOutcomeService, TaskFacts


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Trả rows theo SQL substring; ghi lại mọi statement để assert."""
    def __init__(self, responses):
        self.responses = responses
        self.statements = []
        self.committed = False

    async def execute(self, statement, params=None):
        sql = str(statement).lower()
        self.statements.append((sql, params or {}))
        for key, rows in self.responses.items():
            if key in sql:
                return _Result(rows)
        return _Result([])

    async def commit(self):
        self.committed = True

    def find(self, needle: str):
        return [(s, p) for s, p in self.statements if needle in s]


def _service():
    # verify với LLM None -> extract_outcome dùng fallback rule-based (không gọi mạng).
    verify = TaskVerifyService(llm=None)
    return TaskOutcomeService(verify_service=verify)


# ── extract_outcome fallback ──────────────────────────────────────────────────
def test_extract_splits_result_and_issues():
    svc = _service()
    out = svc.extract_outcome("kết quả: API chạy ổn. khó khăn: thiếu doc Gapo")
    assert out["result"] and "API" in out["result"]
    assert out["issues"] and "doc Gapo" in out["issues"]
    assert out["has_difficulty"] is True


def test_extract_no_difficulty_is_all_result():
    svc = _service()
    out = svc.extract_outcome("đã hoàn thành màn hình booking")
    assert out["result"] and "booking" in out["result"]
    assert out["issues"] is None
    assert out["has_difficulty"] is False


def test_is_skip():
    svc = _service()
    assert svc.is_skip("bỏ qua") is True
    assert svc.is_skip("không") is True
    assert svc.is_skip("không có khó khăn, kết quả ổn") is False


# ── apply_reply RESULT_ISSUES ────────────────────────────────────────────────
def test_apply_reply_result_issues_writes_and_audits():
    svc = _service()
    db = _FakeSession({
        "update tasks set": [(5,)],          # _write_result_issues RETURNING id
    })
    fu = {"follow_up_id": 9, "task_id": 5, "kind": "RESULT_ISSUES"}
    res = asyncio.run(svc.apply_reply(db, fu, "kết quả API ổn, khó khăn thiếu doc", "10", {}))
    assert res["task_id"] == 5 and "lưu" in res["message"].lower()
    assert db.committed is True
    assert db.find("update tasks set")          # đã ghi result/issues
    assert db.find("update agent_follow_ups")   # đã mark REPLIED
    assert db.find("agent_audit_log")           # đã audit


def test_apply_reply_skip_does_not_write_tasks():
    svc = _service()
    db = _FakeSession({})
    fu = {"follow_up_id": 9, "task_id": 5, "kind": "RESULT_ISSUES"}
    res = asyncio.run(svc.apply_reply(db, fu, "bỏ qua", "10", {}))
    assert "bỏ qua" in res["message"].lower()
    assert not db.find("update tasks set")      # KHÔNG ghi tasks
    assert db.find("update agent_follow_ups")   # vẫn đóng follow-up


def test_apply_reply_not_assignee_rejected():
    svc = _service()
    db = _FakeSession({"update tasks set": []})  # RETURNING rỗng -> không phải assignee
    fu = {"follow_up_id": 9, "task_id": 5, "kind": "RESULT_ISSUES"}
    res = asyncio.run(svc.apply_reply(db, fu, "kết quả ổn", "10", {}))
    assert "chưa ghi được" in res["message"].lower()
    assert not db.find("agent_audit_log")        # không audit khi ghi hỏng


# ── apply_reply BLOCKER_REASON ───────────────────────────────────────────────
def test_apply_reply_blocker_reason_writes_blocker_desc():
    svc = _service()
    db = _FakeSession({
        "from tasks where id": [(1,)],        # own check trong _write_blocker_reason
        "update task_blockers set": [],       # UPDATE description (không RETURNING)
        "update tasks set": [(5,)],           # append issues RETURNING id
    })
    fu = {"follow_up_id": 9, "task_id": 5, "kind": "BLOCKER_REASON"}
    res = asyncio.run(svc.apply_reply(db, fu, "chờ team Gapo cấp token", "10", {}))
    assert "đang kẹt" in res["message"].lower()
    assert db.find("update task_blockers set")   # ghi lý do vào blocker
    assert db.committed is True


# ── find_pending ──────────────────────────────────────────────────────────────
def test_find_pending_single():
    svc = _service()
    db = _FakeSession({"from agent_follow_ups": [(9, 5, "RESULT_ISSUES")]})
    res = asyncio.run(svc.find_pending(db, "10", "thread-1"))
    assert res == {"follow_up_id": 9, "task_id": 5, "kind": "RESULT_ISSUES"}


def test_find_pending_ambiguous_returns_none():
    svc = _service()
    db = _FakeSession({"from agent_follow_ups": [(9, 5, "RESULT_ISSUES"), (10, 6, "BLOCKER_REASON")]})
    assert asyncio.run(svc.find_pending(db, "10", "thread-1")) is None


def test_find_pending_no_thread():
    svc = _service()
    assert asyncio.run(svc.find_pending(_FakeSession({}), "10", None)) is None


def test_should_ask_outcome_only_done():
    svc = _service()
    done = TaskFacts(task_id=5, is_assignee=True, status="IN_PROGRESS")
    assert svc.should_ask_outcome(done, "DONE") is True
    assert svc.should_ask_outcome(done, "IN_PROGRESS") is False
