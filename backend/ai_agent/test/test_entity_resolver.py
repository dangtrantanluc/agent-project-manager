"""Test resolve_one: khung 3 nhánh dùng chung cho mọi luồng ghi qua chat."""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import asyncio

from ai_agent.shared.entity_resolver import resolve_one, is_privileged, resolve_tasks


def test_resolve_one_empty_returns_not_found():
    item, err = resolve_one([], "Lực", "người", "full_name")
    assert item is None
    assert "chưa tìm thấy" in err and "Lực" in err


def test_resolve_one_multiple_returns_ambiguous_with_names():
    items = [{"full_name": "Lực A"}, {"full_name": "Lực B"}]
    item, err = resolve_one(items, "Lực", "người", "full_name")
    assert item is None
    assert "nhiều người" in err and "Lực A" in err and "Lực B" in err


def test_resolve_one_single_returns_item():
    items = [{"id": 5, "name": "MTL"}]
    item, err = resolve_one(items, "MTL", "dự án", "name")
    assert err is None
    assert item == {"id": 5, "name": "MTL"}


def test_is_privileged():
    assert is_privileged("MANAGER")
    assert is_privileged("admin")  # case-insensitive
    assert is_privileged("SUPER_ADMIN")
    assert not is_privileged("MEMBER")
    assert not is_privileged(None)
    assert not is_privileged("")


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows_by_call):
        self.rows_by_call = list(rows_by_call)
        self.calls = []

    async def execute(self, stmt, params):
        self.calls.append((str(stmt), params))
        return _FakeResult(self.rows_by_call.pop(0))


def test_resolve_tasks_prefers_code_match():
    db = _FakeDB([[(12, "API docs", "3.2", 7, 9)]])
    out = asyncio.run(resolve_tasks(db, "[3.2]", 10))
    assert out == [{"id": 12, "name": "API docs", "code": "3.2", "project_id": 7, "assignee_id": 9}]
    assert db.calls[0][1]["code"] == "3.2"


def test_resolve_tasks_falls_back_to_name():
    db = _FakeDB([[(1, "Fix login", "1.1", 2, 3), (2, "Fix logout", "1.2", 2, 4)]])
    out = asyncio.run(resolve_tasks(db, "Fix", 10))
    assert len(out) == 2
    assert db.calls[0][1]["tok0"] == "%fix%"


def test_resolve_tasks_matches_tokens_out_of_order():
    # "mẫu mail" phải khớp "Mẫu Email & WhatsApp" qua AND nhiều LIKE theo từ
    # (bỏ stopword "task"), không đòi substring liền mạch.
    db = _FakeDB([[(26, "Mẫu Email & WhatsApp", "MTL-T0026", 5, 8)]])
    out = asyncio.run(resolve_tasks(db, "task mẫu mail", 10))
    assert len(out) == 1 and out[0]["id"] == 26
    params = db.calls[0][1]
    assert params["tok0"] == "%mẫu%" and params["tok1"] == "%mail%"
    assert "task" not in str(db.calls[0][0]).lower() or "tok2" not in params
