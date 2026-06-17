"""Test logic thuần 3 write-action mới: phân quyền, hỏi lại khi thiếu info, và
luồng confirm (need_confirm + payload nút bấm). Ca cần DB thật (DELETE/UPDATE) phủ
ở eval/HTTP end-to-end; ở đây test nhánh không chạm DB."""
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.change_assignee_service import ChangeAssigneeService, ChangeAssigneeExtraction
from app.services.delete_task_service import DeleteTaskService, DeleteTaskExtraction
from app.services.remove_member_service import RemoveMemberService, RemoveMemberExtraction
from ai_agent.shared.action_base import ActionContext


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


def _ctx(role="MANAGER", **kw):
    return ActionContext(message=kw.get("message", "x"), sender_user_id=kw.get("sender", "10"),
                         user_profile={"role": role})


# ── Phân quyền (gate ở base.run) ─────────────────────────────────────────────
def test_change_assignee_forbidden_for_member():
    svc = ChangeAssigneeService(llm=_FakeLLM(ChangeAssigneeExtraction(task_ref="[3.2]", new_assignee="Thảo")))
    res = asyncio.run(svc.run(_ctx(role="MEMBER")))
    assert res.status == "forbidden"


def test_delete_forbidden_for_member():
    svc = DeleteTaskService(llm=_FakeLLM(DeleteTaskExtraction(task_ref="[3.2]")))
    res = asyncio.run(svc.run(_ctx(role="MEMBER")))
    assert res.status == "forbidden"


def test_remove_member_forbidden_for_member():
    svc = RemoveMemberService(llm=_FakeLLM(RemoveMemberExtraction(member="Nam", project="MTL")))
    res = asyncio.run(svc.run(_ctx(role="VIEWER")))
    assert res.status == "forbidden"


# ── Thiếu thông tin -> hỏi lại (không chạm DB) ───────────────────────────────
def test_change_assignee_need_info():
    svc = ChangeAssigneeService(llm=_FakeLLM(ChangeAssigneeExtraction()))
    res = asyncio.run(svc.run(_ctx(role="MANAGER")))
    assert res.status == "need_info"


def test_delete_need_info():
    svc = DeleteTaskService(llm=_FakeLLM(DeleteTaskExtraction(task_ref="")))
    res = asyncio.run(svc.run(_ctx(role="ADMIN")))
    assert res.status == "need_info"


def test_remove_member_need_info():
    svc = RemoveMemberService(llm=_FakeLLM(RemoveMemberExtraction(member="Nam", project="")))
    res = asyncio.run(svc.run(_ctx(role="MANAGER")))
    assert res.status == "need_info"


# ── needs_confirm là cờ khai báo, không nhánh if độc quyền ───────────────────
def test_delete_and_remove_declare_needs_confirm():
    assert DeleteTaskService.needs_confirm is True
    assert RemoveMemberService.needs_confirm is True
    assert ChangeAssigneeService.needs_confirm is False
