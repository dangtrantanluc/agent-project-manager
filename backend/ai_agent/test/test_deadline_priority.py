"""Test ưu tiên + cắt bớt task trong tin nhắc deadline (tránh tin quá dài)."""
import sys
from datetime import date
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ai_agent.notification.notification_agent import _prioritize_tasks


def _t(name, prio, rtype, dl):
    return {"task_name": name, "priority": prio, "reminder_type": rtype, "deadline": dl}


def test_due_today_and_priority_order():
    tasks = [
        _t("low_upcoming", "LOW", "upcoming", date(2026, 6, 14)),
        _t("urgent_today", "URGENT", "due_today", date(2026, 6, 12)),
        _t("high_today", "HIGH", "due_today", date(2026, 6, 12)),
    ]
    display, extra = _prioritize_tasks(tasks, 5)
    assert extra == 0
    # due_today trước upcoming; trong due_today thì URGENT trước HIGH.
    assert [t["task_name"] for t in display] == ["urgent_today", "high_today", "low_upcoming"]


def test_caps_and_counts_extra():
    tasks = [_t(f"t{i}", "MEDIUM", "due_today", date(2026, 6, 12)) for i in range(8)]
    display, extra = _prioritize_tasks(tasks, 5)
    assert len(display) == 5
    assert extra == 3


def test_unknown_priority_goes_last():
    tasks = [
        _t("weird", "", "due_today", date(2026, 6, 12)),
        _t("high", "HIGH", "due_today", date(2026, 6, 12)),
    ]
    display, _ = _prioritize_tasks(tasks, 5)
    assert display[0]["task_name"] == "high"
