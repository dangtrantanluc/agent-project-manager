"""Test luồng thoát check-in khi user phát intent khác giữa chừng + Bug 'huỷ'.

Test phần logic _continue_flow thuần (không cần DB / LLM thật): stub `repo` và
`intent_guard`. Tập trung vào:
- Bug 1: 'huỷ' (dấu ngã) / 'Hủy' (dấu hỏi) đều thoát check-in.
- Escape ở state chọn project/task -> trả None (nhường router), hủy session.
- State nhập worklog -> hỏi xác nhận; 'có' -> None; câu khác -> lưu worklog.
"""
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import ai_agent.checkin.service as svc
from ai_agent.checkin.service import CheckinFlowService, _strip_accents
from ai_agent.checkin.constants import CheckinState, P_CANCEL, P_SKIP_TASK


class _GuardStub:
    """Giả CheckinIntentGuard: trả verdict cố định."""
    def __init__(self, belongs: bool, intent=None):
        self.verdict = {"belongs_to_checkin": belongs, "intent": intent}
        self.calls = []

    async def classify(self, text, *, state):
        self.calls.append((text, state))
        return self.verdict


def _make_service(guard):
    s = CheckinFlowService(gapo=object(), worklog_parser=object())
    s.intent_guard = guard
    return s


def _run(coro):
    return asyncio.run(coro)


# ── Bug 1: chuẩn hoá dấu ────────────────────────────────────────────────────

def test_strip_accents_huy_variants():
    assert _strip_accents("Huỷ") == "huy"
    assert _strip_accents("hủy") == "huy"
    assert _strip_accents("HUỶ") == "huy"
    assert _strip_accents("Bỏ Qua") == "bo qua"
    assert _strip_accents("Đồng ý") == "dong y"


def test_cancel_word_with_tilde_triggers_cancel(monkeypatch):
    """'huỷ' (dấu ngã) phải thoát check-in — bug gốc không khớp."""
    svc_obj = _make_service(_GuardStub(belongs=True))
    captured = {}

    async def fake_handle_payload(db, session, payload):
        captured["payload"] = payload
        return "Đã hủy check-in."

    svc_obj._handle_payload = fake_handle_payload
    session = {"id": 1, "user_id": 9, "state": CheckinState.AWAITING_TASK,
               "pending_parsed": None, "current_project_id": 14}

    out = _run(svc_obj._continue_flow(db=None, session=session, message_text="huỷ"))
    assert captured["payload"] == P_CANCEL
    assert out == "Đã hủy check-in."


# ── Escape ở state chọn project/task -> None ────────────────────────────────

def test_other_intent_in_selection_escapes_to_router(monkeypatch):
    guard = _GuardStub(belongs=False, intent="create_task")
    svc_obj = _make_service(guard)
    cancelled = {}

    async def fake_cancel_all(db, uid):
        cancelled["uid"] = uid

    monkeypatch.setattr(svc.repo, "cancel_all_active_sessions", fake_cancel_all)
    session = {"id": 1, "user_id": 9, "state": CheckinState.AWAITING_TASK,
               "pending_parsed": None, "current_project_id": 14}

    out = _run(svc_obj._continue_flow(db=None, session=session,
                                      message_text="tạo task fix login"))
    assert out is None  # nhường router
    assert cancelled["uid"] == 9


def test_checkin_input_in_selection_does_text_search(monkeypatch):
    guard = _GuardStub(belongs=True)
    svc_obj = _make_service(guard)

    async def fake_search(db, session, q):
        return f"search:{q}"

    svc_obj._handle_text_search = fake_search
    session = {"id": 1, "user_id": 9, "state": CheckinState.AWAITING_TASK,
               "pending_parsed": None, "current_project_id": 14}

    out = _run(svc_obj._continue_flow(db=None, session=session, message_text="login"))
    assert out == "search:login"


# ── State nhập worklog -> hỏi xác nhận ──────────────────────────────────────

def test_other_intent_in_worklog_asks_confirmation(monkeypatch):
    guard = _GuardStub(belongs=False, intent="create_task")
    svc_obj = _make_service(guard)
    saved = {}

    async def fake_update_pending(db, sid, text, parsed=None):
        saved["parsed"] = parsed

    monkeypatch.setattr(svc.repo, "update_session_pending", fake_update_pending)
    session = {"id": 1, "user_id": 9, "state": CheckinState.AWAITING_UPDATE,
               "pending_parsed": None, "current_project_id": 14, "current_task_id": 5}

    out = _run(svc_obj._continue_flow(db=None, session=session,
                                      message_text="tạo task mới"))
    assert out is not None and "Thoát" in out
    assert saved["parsed"]["type"] == "escape_confirm"
    assert saved["parsed"]["intent"] == "create_task"


def test_escape_confirm_yes_escapes(monkeypatch):
    svc_obj = _make_service(_GuardStub(belongs=True))
    cancelled = {}

    async def fake_cancel_all(db, uid):
        cancelled["uid"] = uid

    monkeypatch.setattr(svc.repo, "cancel_all_active_sessions", fake_cancel_all)
    session = {"id": 1, "user_id": 9, "state": CheckinState.AWAITING_UPDATE,
               "pending_parsed": {"type": "escape_confirm", "intent": "create_task"},
               "current_project_id": 14, "current_task_id": 5}

    out = _run(svc_obj._continue_flow(db=None, session=session, message_text="có"))
    assert out is None
    assert cancelled["uid"] == 9


def test_escape_confirm_no_saves_worklog(monkeypatch):
    svc_obj = _make_service(_GuardStub(belongs=True))
    cleared = {}
    worklog = {}

    async def fake_update_pending(db, sid, text, parsed=None):
        cleared["parsed"] = parsed

    async def fake_worklog(db, session, text):
        worklog["text"] = text
        return "đã lưu worklog"

    monkeypatch.setattr(svc.repo, "update_session_pending", fake_update_pending)
    svc_obj._handle_worklog_input = fake_worklog
    session = {"id": 1, "user_id": 9, "state": CheckinState.AWAITING_UPDATE,
               "pending_parsed": {"type": "escape_confirm", "intent": "create_task"},
               "current_project_id": 14, "current_task_id": 5}

    out = _run(svc_obj._continue_flow(db=None, session=session,
                                      message_text="fix bug login 2h"))
    assert out == "đã lưu worklog"
    assert worklog["text"] == "fix bug login 2h"
    assert cleared["parsed"] is None  # cờ escape đã xoá
