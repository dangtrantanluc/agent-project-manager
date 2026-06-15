"""Test AddMemberService: thêm thành viên qua chat — phân quyền + hỏi lại khi
thiếu info. Ca cần DB (INSERT members thật) phủ ở eval/HTTP end-to-end; ở đây
test logic thuần: phân quyền, thiếu thông tin.
"""
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.add_member_service import AddMemberService, AddMemberExtraction


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


def _svc(extraction):
    return AddMemberService(llm=_FakeLLM(extraction))


def test_forbidden_for_non_manager():
    out = asyncio.run(_svc(AddMemberExtraction(member="Lực", project="MTL")).add_from_chat(
        message="thêm Lực vào MTL", sender_user_id="10", user_profile={"role": "MEMBER"},
    ))
    assert out.status == "forbidden"
    assert "quản lý" in out.message.lower()


def test_need_info_when_member_or_project_missing():
    out = asyncio.run(_svc(AddMemberExtraction(member="", project="")).add_from_chat(
        message="thêm người giúp tôi", sender_user_id="10", user_profile={"role": "MANAGER"},
    ))
    assert out.status == "need_info"


def test_need_info_when_only_member_given():
    out = asyncio.run(_svc(AddMemberExtraction(member="Lực", project="")).add_from_chat(
        message="thêm Lực", sender_user_id="10", user_profile={"role": "MANAGER"},
    ))
    assert out.status == "need_info"
