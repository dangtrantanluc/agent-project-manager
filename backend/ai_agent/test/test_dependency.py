"""Test phần thuần (không DB) của tính năng phụ thuộc công việc.

- risk_detector: tín hiệu dependency_blocked vào điểm + reasons.
- dependency_service: format cảnh báo/unblock.
Phần SQL (would_create_cycle, unfinished_blockers, newly_unblocked) test qua DB
thật trong eval; ở đây chỉ phủ logic thuần.
"""
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.risk_detector import _score_and_level, _build_reasons, _W_DEPENDENCY_BLOCKED
from app.services.dependency_service import format_blocker_warning, format_unblocked_note


def test_dependency_blocked_adds_to_score():
    # 2 task chờ phụ thuộc -> cộng 2 * weight vào điểm.
    base, _ = _score_and_level(0, 0, 0, 0)
    with_dep, _ = _score_and_level(0, 0, 0, 0, dependency_blocked=2)
    assert with_dep - base == 2 * _W_DEPENDENCY_BLOCKED


def test_dependency_blocked_in_reasons():
    reasons = _build_reasons(0, 0, 0, 0, dependency_blocked=3)
    assert any("chờ task phụ thuộc" in r for r in reasons)
    assert any("3 task" in r for r in reasons)


def test_no_dependency_no_reason():
    reasons = _build_reasons(1, 0, 0, 0)  # chỉ overdue
    assert not any("phụ thuộc" in r for r in reasons)


def test_format_blocker_warning():
    msg = format_blocker_warning([{"code": "MTL-T001", "name": "Thiết kế DB", "status": "TODO"}])
    assert "MTL-T001" in msg and "Thiết kế DB" in msg and "phụ thuộc" in msg


def test_format_unblocked_note():
    msg = format_unblocked_note([{"code": "MTL-T002", "name": "Viết API"}])
    assert "MTL-T002" in msg and "sẵn sàng" in msg


def test_format_handles_null_code():
    msg = format_blocker_warning([{"code": None, "name": "Task X", "status": "TODO"}])
    assert "Task X" in msg  # không vỡ khi code None
