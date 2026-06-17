"""Tests mỏng cho các ActionAgent mới: validate nhánh không DB và confirm menu."""
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ai_agent.shared.action_base import ActionContext
from app.services.change_assignee_service import ChangeAssigneeExtraction, ChangeAssigneeService
from app.services.delete_task_service import DeleteTaskExtraction, DeleteTaskService
from app.services.remove_member_service import RemoveMemberExtraction, RemoveMemberService


class _StructLLM:
    def __init__(self, val):
        self.val = val

    async def ainvoke(self, messages):
        return self.val


class _FakeLLM:
    def __init__(self, val):
        self.val = val

    def with_structured_output(self, schema, method=None):
        return _StructLLM(self.val)


class _Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class _DB:
    async def execute(self, *args, **kwargs):
        return _Result((44,))


class _SessionLocal:
    async def __aenter__(self):
        return _DB()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _ctx(message="msg"):
    return ActionContext(
        message=message,
        sender_user_id="10",
        user_profile={"role": "MANAGER", "full_name": "PM"},
    )


def test_change_assignee_need_info():
    svc = ChangeAssigneeService(llm=_FakeLLM(ChangeAssigneeExtraction()))
    out = asyncio.run(svc.run(_ctx("chuyển giúp tôi")))
    assert out.status == "need_info"


def test_delete_task_confirm_menu(monkeypatch):
    async def _resolve_tasks(db, ref, sender_id):
        return [{"id": 12, "name": "API docs", "code": "3.2", "project_id": 7, "assignee_id": 9}]

    monkeypatch.setattr("app.services.delete_task_service.AsyncSessionLocal", _SessionLocal)
    monkeypatch.setattr("app.services.delete_task_service.resolve_tasks", _resolve_tasks)

    svc = DeleteTaskService(llm=_FakeLLM(DeleteTaskExtraction(task_ref="[3.2]")))
    out = asyncio.run(svc.run(_ctx("xoá task [3.2]")))
    assert out.status == "need_confirm"
    assert out.entity_id == 12
    assert out.menu[0]["payload"] == "ACTDEL|task|12"


def test_remove_member_confirm_menu(monkeypatch):
    async def _resolve_users(db, name, sender_id):
        return [{"user_id": 20, "full_name": "Nam"}]

    async def _resolve_projects(db, name, sender_id):
        return [{"id": 7, "name": "Logistics", "company_id": 1}]

    monkeypatch.setattr("app.services.remove_member_service.AsyncSessionLocal", _SessionLocal)
    monkeypatch.setattr("app.services.remove_member_service.resolve_users", _resolve_users)
    monkeypatch.setattr("app.services.remove_member_service.resolve_projects", _resolve_projects)

    svc = RemoveMemberService(llm=_FakeLLM(RemoveMemberExtraction(member="Nam", project="Logistics")))
    out = asyncio.run(svc.run(_ctx("gỡ Nam khỏi dự án Logistics")))
    assert out.status == "need_confirm"
    assert out.entity_id == 44
    assert out.menu[0]["payload"] == "ACTDEL|member|44"
