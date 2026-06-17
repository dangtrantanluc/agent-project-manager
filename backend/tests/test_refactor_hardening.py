"""Test cho các thay đổi hardening (bước 1-11).

Không cần DB/LLM/Redis thật — dùng fake/monkeypatch. Async test gọi asyncio.run
trực tiếp (dự án không cấu hình pytest-asyncio).
"""
import asyncio

import pytest

# ───────────────────────── Bước 11: intent_rules (pure) ─────────────────────
from ai_agent.router import intent_rules


@pytest.mark.parametrize("msg,expected", [
    ("làm xong task X rồi", "task_update"),
    ("lập kế hoạch chia task", "planning"),
    ("báo cáo tuần này", "report"),
    ("có bao nhiêu task quá hạn", "text2sql"),
    ("chào bạn", "conversation"),
])
def test_keyword_agent(msg, expected):
    assert intent_rules.keyword_agent(msg) == expected


def test_resolve_agents_task_code_forces_update():
    # Mã task "[2.4]" luôn ép task_update bất kể LLM chọn gì.
    assert intent_rules.resolve_agents("cập nhật [2.4]", ["report"]) == ["task_update"]


def test_resolve_agents_done_forces_update():
    assert intent_rules.resolve_agents("tôi update rồi", ["notification"]) == ["task_update"]


def test_resolve_agents_create_with_cho():
    assert intent_rules.resolve_agents("giao task X cho Nam", ["conversation"]) == ["create_task"]


def test_resolve_agents_drops_redundant_conversation():
    assert intent_rules.resolve_agents("hi", ["text2sql", "conversation"]) == ["text2sql"]


def test_resolve_agents_outbound():
    assert intent_rules.resolve_agents("nhắn Nam nộp báo cáo", ["conversation"]) == ["notification"]


# ───────────────────────── Bước 5: llm_factory ──────────────────────────────
def test_make_llm_uses_env_and_tags_purpose(monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "model-default")
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("BASE_URL", "http://x/v1")
    from ai_agent.shared.llm_factory import make_llm

    llm = make_llm(purpose="unit-test", timeout=12)
    assert llm.model_name == "model-default"
    assert llm.metadata.get("purpose") == "unit-test"


def test_make_llm_router_prefers_router_env(monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "model-default")
    monkeypatch.setenv("MODEL_NAME_ROUTER", "model-router")
    monkeypatch.setenv("API_KEY", "k")
    monkeypatch.setenv("BASE_URL", "http://x/v1")
    from ai_agent.shared.llm_factory import make_llm

    llm = make_llm(purpose="router", router=True)
    assert llm.model_name == "model-router"


# ───────────────────────── Bước 2: rate_limit ───────────────────────────────
class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key, ttl):
        return True


def test_rate_limit_blocks_after_limit(monkeypatch):
    from app.core import rate_limit
    from fastapi import HTTPException

    fake = _FakeRedis()

    async def _fake_get_redis():
        return fake

    monkeypatch.setattr("core.redis.get_redis", _fake_get_redis)

    async def run():
        # limit=2/window: 2 lần đầu OK, lần 3 ném 429.
        await rate_limit.check_rate_limit("t", "u1", 2, 60)
        await rate_limit.check_rate_limit("t", "u1", 2, 60)
        with pytest.raises(HTTPException) as e:
            await rate_limit.check_rate_limit("t", "u1", 2, 60)
        assert e.value.status_code == 429

    asyncio.run(run())


def test_rate_limit_fail_open_when_redis_down(monkeypatch):
    from app.core import rate_limit

    async def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr("core.redis.get_redis", _boom)

    async def run():
        # Redis lỗi → KHÔNG ném (fail-open).
        await rate_limit.check_rate_limit("t", "u1", 1, 60)

    asyncio.run(run())


# ───────────────────────── Bước 6: code_gen.reserve + bulk resolve ──────────
class _FakeResult:
    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar(self):
        return self._scalar

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    """db.execute trả lần lượt các kết quả đã xếp sẵn."""
    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    async def execute(self, *a, **k):
        r = self._results[self.calls]
        self.calls += 1
        return r


def test_reserve_task_codes_returns_contiguous_range():
    from app.core.code_gen import reserve_task_codes

    # 1st execute (bump counter) → end_val=8; 2nd (prefix) → entity_prefix "MTL".
    db = _FakeDB([_FakeResult(scalar=8), _FakeResult(rows=[("MTL", "MTL-LOGISTICS")])])
    out = asyncio.run(reserve_task_codes(1, 3, db))
    assert out == [(5, "MTL-T0005"), (6, "MTL-T0006"), (7, "MTL-T0007")]
    assert db.calls == 2  # đúng 2 query cho 3 task (chống N+1)


def test_reserve_task_codes_zero():
    from app.core.code_gen import reserve_task_codes
    db = _FakeDB([])
    assert asyncio.run(reserve_task_codes(1, 0, db)) == []


def test_resolve_assignees_bulk_substring_match():
    from app.modules.tasks.import_service import _resolve_assignees_bulk

    db = _FakeDB([_FakeResult(rows=[(10, "Nguyễn Văn Nam"), (11, "Trần Thị Lan")])])
    out = asyncio.run(_resolve_assignees_bulk(["nam", "lan", "khong-co"], db))
    assert out["nam"] == 10
    assert out["lan"] == 11
    assert "khong-co" not in out
    assert db.calls == 1  # 1 query cho nhiều tên


# ───────────────────────── Bước 7: Pydantic schemas ─────────────────────────
def test_task_create_in_requires_name_and_coerces():
    from app.modules.tasks.schemas import TaskCreateIn

    m = TaskCreateIn(name="A", projectId="5", junk="bỏ qua")  # type: ignore[arg-type]
    assert m.projectId == 5  # coerce str->int
    d = m.model_dump()
    assert "junk" not in d  # extra ignored

    with pytest.raises(Exception):
        TaskCreateIn(projectId=1)  # thiếu name


def test_task_update_exclude_unset_keeps_patch_semantics():
    from app.modules.tasks.schemas import TaskUpdateIn

    m = TaskUpdateIn(status="DONE")
    dumped = m.model_dump(exclude_unset=True)
    assert dumped == {"status": "DONE"}  # chỉ field được gửi


# ───────────────────── Prompt: khớp dự án MỀM (fix bug "dự án MTL") ──────────
def test_schema_prompt_uses_soft_project_match():
    from ai_agent.prompt.prompt import SCHEMA_COMPACT
    # Phải dạy LLM khớp project bằng ILIKE code/name, KHÔNG exact code=.
    assert "project_ref" in SCHEMA_COMPACT
    assert "p.code ILIKE" in SCHEMA_COMPACT
    assert "p.name ILIKE" in SCHEMA_COMPACT


# ───────────────────────── Bước 4: scheduler lock keys ──────────────────────
def test_scheduler_lock_keys_distinct():
    from ai_agent.checkin import constants as c
    keys = [
        c.LOCK_CHECKIN, c.LOCK_REMINDER, c.LOCK_MISSING,
        c.LOCK_EXPIRE_STALE, c.LOCK_RISK_SCAN, c.LOCK_DEADLINE,
    ]
    assert len(set(keys)) == len(keys)  # không trùng → không starvation chéo job
