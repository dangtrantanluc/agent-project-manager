import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ai_agent.router import message_router
from ai_agent.router.message_router import AgentMessageRouter
from gapo import gapo_adapter
from gapo.gapo_adapter import GapoAdapter


class _FakeIntentRouter:
    def selected_agents(self, message):
        return [message_router.Agent(
            name="conversation",
            description="conversation",
            threshold=0.2,
            confidence=0.5,
            selected=True,
        )]


class _FakeConversationAgent:
    def __init__(self):
        self.user_context = None
        self.timezone_name = None

    async def process_message_async(self, message, user_context=None, timezone_name=None):
        self.user_context = user_context
        self.timezone_name = timezone_name
        return {"message": "ok"}


def test_agent_router_loads_memory_context_when_db_and_conversation_id_are_present(monkeypatch):
    async def fake_load_memory(conversation_id, db):
        assert conversation_id == "thread-1"
        assert db == "db"
        return "summary cũ", [{"user": "dự án A sao rồi?", "bot": "Dự án A đang chạy."}]

    monkeypatch.setattr(message_router, "load_memory", fake_load_memory)

    router = object.__new__(AgentMessageRouter)
    router.intent_router = _FakeIntentRouter()
    router.conversation_agent = _FakeConversationAgent()

    reply = asyncio.run(router.handle_message(
        message="deadline của dự án đó?",
        user_id="9",
        thread_id="thread-1",
        db="db",
        conversation_id="thread-1",
        correlation_id="msg-1",
    ))

    assert reply.answer == "ok"
    assert reply.metadata["memory_loaded"] is True
    assert router.conversation_agent.timezone_name == "Asia/Ho_Chi_Minh"
    assert "timezone=Asia/Ho_Chi_Minh" in router.conversation_agent.user_context
    assert "Tóm tắt trước: summary cũ" in router.conversation_agent.user_context
    assert "User: dự án A sao rồi?" in router.conversation_agent.user_context


class _FakeSessionFactory:
    def __init__(self):
        self.sessions = []

    def __call__(self):
        session = _FakeSession()
        self.sessions.append(session)
        return session


class _FakeSession:
    def __init__(self):
        self.executed = []
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, query, params=None):
        self.executed.append((query, params))
        return None

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


class _FakeCheckin:
    async def handle_message(self, *args, **kwargs):
        return None


class _FakeRouter:
    def __init__(self):
        self.calls = []

    async def handle_message(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(answer="agent answer", agent="conversation")


class _FakeClient:
    bot_id = None

    def __init__(self):
        self.sent = []

    async def send_text(self, **kwargs):
        self.sent.append(kwargs)


def test_gapo_adapter_uses_thread_id_as_memory_conversation_id(monkeypatch):
    saved = []
    session_factory = _FakeSessionFactory()

    async def fake_save_memory(**kwargs):
        saved.append(kwargs)

    monkeypatch.setattr(gapo_adapter, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(gapo_adapter, "save_memory", fake_save_memory)

    adapter = object.__new__(GapoAdapter)
    adapter.client = _FakeClient()
    adapter.router = _FakeRouter()
    adapter.checkin = _FakeCheckin()
    adapter.llm = object()

    async def fake_lookup(gapo_user_id):
        return {"user_id": 9}

    adapter._lookup_gapo_user = fake_lookup

    payload = {
        "id": "event-1",
        "event": "message_created",
        "thread_id": 123,
        "from_user_id": 456,
        "to_bot_id": 789,
        "message": {"id": "msg-1", "type": "text", "text": "hello"},
    }

    result = asyncio.run(adapter.handle_event(payload))

    assert result["ok"] is True
    assert isinstance(result["response_time_ms"], int)
    assert adapter.router.calls[0]["conversation_id"] == "123"
    assert adapter.router.calls[0]["correlation_id"] == "msg-1"
    assert saved[0]["conversation_id"] == "123"
    assert saved[0]["correlation_id"] == "msg-1"
    assert saved[0]["reply_text"] == "agent answer"
    assert adapter.client.sent[0]["text"] == "agent answer"
    audit_session = session_factory.sessions[-1]
    assert audit_session.committed is True
    assert audit_session.executed[0][1]["tool"] == "gapo_response_time"
    assert audit_session.executed[0][1]["correlation_id"] == "msg-1"
    assert audit_session.executed[0][1]["duration_ms"] == result["response_time_ms"]
