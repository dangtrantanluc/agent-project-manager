"""Test khung ActionAgentBase: gate quyền + gate LLM (1 lần cho mọi tool con)."""
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from pydantic import BaseModel

from ai_agent.shared.action_base import ActionAgentBase, ActionContext, ActionResult


class _DummyExtraction(BaseModel):
    foo: str = ""


class _DummyAction(ActionAgentBase):
    name = "dummy"
    intent_desc = "- dummy: test"
    extraction_model = _DummyExtraction
    system_prompt = "test"

    def __init__(self):
        # KHÔNG gọi super().__init__ để tránh dựng LLM thật; ép _llm theo từng test.
        self._llm = None

    async def _handle(self, extraction, ctx):
        return ActionResult("done", "đã xử lý")


def _ctx(role):
    return ActionContext(message="x", sender_user_id="10", user_profile={"role": role})


def test_forbidden_when_not_privileged():
    act = _DummyAction()
    res = asyncio.run(act.run(_ctx("MEMBER")))
    assert res.status == "forbidden"


def test_error_when_llm_unavailable():
    act = _DummyAction()  # _llm=None
    res = asyncio.run(act.run(_ctx("MANAGER")))
    assert res.status == "error"


def test_handle_runs_when_privileged_and_llm_ok():
    act = _DummyAction()

    class _FakeLLM:
        async def ainvoke(self, _msgs):
            return _DummyExtraction(foo="bar")

    act._llm = _FakeLLM()
    res = asyncio.run(act.run(_ctx("ADMIN")))
    assert res.status == "done" and res.message == "đã xử lý"


def test_intent_desc_readable_without_instance():
    # Router đọc intent_desc qua class, KHÔNG khởi tạo (tránh kéo make_llm).
    assert _DummyAction.intent_desc == "- dummy: test"
