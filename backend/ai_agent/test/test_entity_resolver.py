"""Test resolve_one: khung 3 nhánh dùng chung cho mọi luồng ghi qua chat."""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ai_agent.shared.entity_resolver import resolve_one, is_privileged


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
