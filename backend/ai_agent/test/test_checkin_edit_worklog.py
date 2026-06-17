"""Test luồng SỬA worklog vừa lưu trong check-in.

Test logic thuần (không cần DB / LLM thật): stub `repo`, `parser`, `gapo`,
và `intent_guard`. Tập trung:
- Bấm "Sửa" ở state CONFIRMING -> chuyển AWAITING_EDIT, lưu đúng worklog_id.
- Bấm "Sửa" khi KHÔNG ở CONFIRMING -> từ chối.
- Nhập lại nội dung ở AWAITING_EDIT -> UPDATE worklog (không INSERT mới),
  recompute side-effects với parsed_json rỗng (không đổi status task).
"""
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import ai_agent.checkin.service as svc
from ai_agent.checkin.service import CheckinFlowService
from ai_agent.checkin.constants import CheckinState, P_EDIT, P_ADD_MORE, P_DONE


class _GuardStub:
    async def classify(self, text, *, state):
        return {"belongs_to_checkin": True, "intent": None}


class _ParserStub:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def parse(self, message, **kwargs):
        self.calls.append(message)
        return self.result


class _GapoStub:
    def __init__(self):
        self.menus = []

    async def send_menu(self, thread_id, title, actions):
        self.menus.append({"thread_id": thread_id, "title": title, "actions": actions})
        return True


def _make_service(parser=None, gapo=None):
    # Tránh ChatOpenAI thật trong __init__ bằng cách stub CheckinIntentGuard.
    orig = svc.CheckinIntentGuard
    svc.CheckinIntentGuard = lambda: _GuardStub()
    try:
        s = CheckinFlowService(gapo=gapo or _GapoStub(), worklog_parser=parser)
    finally:
        svc.CheckinIntentGuard = orig
    s.intent_guard = _GuardStub()
    return s


def _run(coro):
    return asyncio.run(coro)


# ── Bấm "Sửa" từ CONFIRMING ─────────────────────────────────────────────────

def test_edit_payload_from_confirming_enters_edit_state(monkeypatch):
    svc_obj = _make_service()
    captured = {}

    async def fake_set_editing(db, sid, worklog_id):
        captured["sid"] = sid
        captured["worklog_id"] = worklog_id

    monkeypatch.setattr(svc.repo, "set_session_editing", fake_set_editing)
    session = {"id": 1, "user_id": 9, "state": CheckinState.CONFIRMING,
               "pending_parsed": {"_worklog_id": 61, "hours": 3.5},
               "current_project_id": 14, "current_task_id": 5}

    out = _run(svc_obj._handle_payload(db=None, session=session, payload=P_EDIT))
    assert captured["worklog_id"] == 61
    assert "#61" in out


def test_edit_payload_outside_confirming_rejected():
    svc_obj = _make_service()
    session = {"id": 1, "user_id": 9, "state": CheckinState.AWAITING_TASK,
               "pending_parsed": None, "current_project_id": 14}
    out = _run(svc_obj._handle_payload(db=None, session=session, payload=P_EDIT))
    assert "vừa lưu" in out


def test_edit_payload_no_worklog_id_rejected():
    svc_obj = _make_service()
    session = {"id": 1, "user_id": 9, "state": CheckinState.CONFIRMING,
               "pending_parsed": {"hours": 3.5}, "current_project_id": 14}
    out = _run(svc_obj._handle_payload(db=None, session=session, payload=P_EDIT))
    assert "Không tìm thấy worklog" in out


# ── Nhập lại nội dung ở AWAITING_EDIT ───────────────────────────────────────

def test_edit_input_updates_worklog(monkeypatch):
    gapo = _GapoStub()
    parser = _ParserStub({"hours": 2.0, "description": "tách module pricing",
                          "work_date": "2026-06-17"})
    svc_obj = _make_service(parser=parser, gapo=gapo)

    calls = {}

    async def fake_get_worklog(db, wid):
        calls["get"] = wid
        return {"id": wid, "work_date": __import__("datetime").date(2026, 6, 17),
                "description": "old", "hours": 3.5,
                "task_id": 5, "project_id": 14, "user_id": 9}

    async def fake_update_worklog(db, **kw):
        calls["update"] = kw

    async def fake_side_effects(db, **kw):
        calls["side_effects"] = kw

    async def fake_set_confirming(db, sid, parsed):
        calls["confirming"] = parsed

    async def fake_project_name(db, pid):
        return "MTL"

    async def fake_task_name(db, tid):
        return "Tách module"

    monkeypatch.setattr(svc.repo, "get_worklog", fake_get_worklog)
    monkeypatch.setattr(svc.repo, "update_worklog", fake_update_worklog)
    monkeypatch.setattr(svc.repo, "apply_worklog_side_effects", fake_side_effects)
    monkeypatch.setattr(svc.repo, "set_session_confirming", fake_set_confirming)
    monkeypatch.setattr(svc.repo, "get_project_name", fake_project_name)
    monkeypatch.setattr(svc.repo, "get_task_name", fake_task_name)

    session = {"id": 1, "user_id": 9, "state": CheckinState.AWAITING_EDIT,
               "pending_parsed": {"type": "edit", "worklog_id": 61},
               "thread_id": "t1", "current_project_id": 14, "current_task_id": 5}

    out = _run(svc_obj._handle_edit_input(db=None, session=session,
                                          message_text="tách module pricing 2h"))
    assert calls["get"] == 61
    assert calls["update"]["worklog_id"] == 61
    assert calls["update"]["hours"] == 2.0
    # KHÔNG đổi status task: side-effects nhận parsed_json rỗng.
    assert calls["side_effects"]["parsed_json"] == {}
    assert calls["confirming"]["_worklog_id"] == 61
    assert out == ""  # đã gửi qua send_menu
    assert "#61" in gapo.menus[-1]["title"]
    # Menu confirm vẫn có đủ 3 nút.
    payloads = [a["payload"] for a in gapo.menus[-1]["actions"]]
    assert P_ADD_MORE in payloads and P_EDIT in payloads and P_DONE in payloads


def test_edit_input_invalid_hours_rejected(monkeypatch):
    parser = _ParserStub({"hours": 99, "description": "x"})
    svc_obj = _make_service(parser=parser)

    async def fake_get_worklog(db, wid):
        return {"id": wid, "work_date": __import__("datetime").date(2026, 6, 17),
                "description": "old", "hours": 3.5,
                "task_id": 5, "project_id": 14, "user_id": 9}

    monkeypatch.setattr(svc.repo, "get_worklog", fake_get_worklog)
    session = {"id": 1, "user_id": 9, "state": CheckinState.AWAITING_EDIT,
               "pending_parsed": {"type": "edit", "worklog_id": 61}}
    out = _run(svc_obj._handle_edit_input(db=None, session=session,
                                          message_text="x 99h"))
    assert "không hợp lệ" in out.lower()
