"""Test TaskCreateService: giao việc qua chat — phân quyền + hỏi lại khi thiếu info.

Các ca cần DB (tạo task thật) được phủ ở eval end-to-end; ở đây test phần logic
thuần không cần DB: phân quyền, thiếu thông tin, parse deadline.
"""
import asyncio
import sys
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.task_create_service import (
    TaskCreateService, TaskCreateExtraction, _parse_deadline,
)


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
    return TaskCreateService(llm=_FakeLLM(extraction))


def test_forbidden_for_non_manager():
    out = asyncio.run(_svc(TaskCreateExtraction(task_name="x", assignee="y")).create_from_chat(
        message="giao task x cho y", sender_user_id="10", user_profile={"role": "MEMBER"},
    ))
    assert out.status == "forbidden"
    assert "quản lý" in out.message.lower()


def test_need_info_when_task_or_assignee_missing():
    out = asyncio.run(_svc(TaskCreateExtraction(task_name="", assignee="")).create_from_chat(
        message="giao việc giúp tôi", sender_user_id="10", user_profile={"role": "MANAGER"},
    ))
    assert out.status == "need_info"


def test_parse_deadline():
    assert _parse_deadline("2026-06-20") == date(2026, 6, 20)
    assert _parse_deadline("2026-06-20T00:00:00") == date(2026, 6, 20)
    assert _parse_deadline("") is None
    assert _parse_deadline("không phải ngày") is None
