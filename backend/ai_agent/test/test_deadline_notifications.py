import asyncio
from datetime import date

from ai_agent.checkin.scheduler import (
    _deadline_notify_date,
    _deadline_reminder_type,
    _group_due_deadline_tasks,
)
from ai_agent.notification.notification_agent import NotificationAgent


def test_deadline_notify_date_keeps_weekday_minus_two_days():
    assert _deadline_notify_date(date(2026, 5, 29)) == date(2026, 5, 27)


def test_deadline_notify_date_moves_monday_deadline_to_previous_friday():
    assert _deadline_notify_date(date(2026, 6, 1)) == date(2026, 5, 29)


def test_deadline_notify_date_moves_tuesday_deadline_to_previous_friday():
    assert _deadline_notify_date(date(2026, 6, 2)) == date(2026, 5, 29)


def test_deadline_reminder_type_includes_two_days_before_and_deadline_day():
    assert _deadline_reminder_type(date(2026, 5, 29), date(2026, 5, 27)) == "upcoming"
    assert _deadline_reminder_type(date(2026, 5, 29), date(2026, 5, 29)) == "due_today"
    assert _deadline_reminder_type(date(2026, 5, 29), date(2026, 5, 28)) is None


def test_group_due_deadline_tasks_batches_by_assignee_and_thread():
    rows = [
        (1, "Task A", date(2026, 5, 29), 10, "Project X", 1000, "User A", "PLANNED"),
        (2, "Task B", date(2026, 5, 29), 10, "Project X", 1000, "User A", "IN_PROGRESS"),
        (3, "Task C", date(2026, 6, 2), 11, "Project Y", 2000, "User B", "PLANNED"),
        (4, "Task D", date(2026, 6, 9), 10, "Project X", 1000, "User A", "PLANNED"),
    ]

    grouped, skipped = _group_due_deadline_tasks(rows, date(2026, 5, 27))

    assert skipped == 2
    assert list(grouped.keys()) == [(10, "1000")]
    assert [task["task_id"] for task in grouped[(10, "1000")]] == [1, 2]
    assert {task["reminder_type"] for task in grouped[(10, "1000")]} == {"upcoming"}


def test_group_due_deadline_tasks_includes_deadline_day_reminder():
    rows = [
        (1, "Task A", date(2026, 5, 29), 10, "Project X", 1000, "User A", "PLANNED"),
        (2, "Task B", date(2026, 5, 30), 10, "Project X", 1000, "User A", "IN_PROGRESS"),
    ]

    grouped, skipped = _group_due_deadline_tasks(rows, date(2026, 5, 29))

    assert skipped == 1
    assert [task["task_id"] for task in grouped[(10, "1000")]] == [1]
    assert grouped[(10, "1000")][0]["reminder_type"] == "due_today"


def test_deadline_digest_single_task_uses_fallback_without_llm():
    agent = NotificationAgent(llm=FailingLLM())

    message = asyncio.run(agent.prepare_deadline_digest(
        recipient_name="User A",
        notify_date=date(2026, 5, 27),
        tasks=[{
            "task_id": 1,
            "task_name": "Kết nối AgentMessageRouter",
            "project_name": "Gapo Test CRM Rollout",
            "deadline": date(2026, 5, 29),
            "status": "IN_PROGRESS",
            "reminder_type": "upcoming",
        }],
    ))

    assert "Nhắc deadline" in message
    assert "Project: Gapo Test CRM Rollout" in message
    assert "Task: Kết nối AgentMessageRouter" in message
    assert "Deadline: 2026-05-29" in message
    assert "2 ngày" in message


def test_deadline_digest_single_task_due_today_uses_due_today_copy():
    agent = NotificationAgent(llm=FailingLLM())

    message = asyncio.run(agent.prepare_deadline_digest(
        recipient_name="User A",
        notify_date=date(2026, 5, 29),
        tasks=[{
            "task_id": 1,
            "task_name": "Kết nối AgentMessageRouter",
            "project_name": "Gapo Test CRM Rollout",
            "deadline": date(2026, 5, 29),
            "status": "IN_PROGRESS",
            "reminder_type": "due_today",
        }],
    ))

    assert "đến hạn hôm nay" in message
    assert "hoàn thành" in message


def test_deadline_digest_multiple_tasks_uses_one_numbered_message_without_llm():
    agent = NotificationAgent(llm=FailingLLM())

    message = asyncio.run(agent.prepare_deadline_digest(
        recipient_name="User A",
        notify_date=date(2026, 5, 29),
        tasks=[
            {
                "task_id": 1,
                "task_name": "Task A",
                "project_name": "Project X",
                "deadline": date(2026, 6, 2),
                "status": "PLANNED",
                "reminder_type": "upcoming",
            },
            {
                "task_id": 2,
                "task_name": "Task B",
                "project_name": "Project Y",
                "deadline": date(2026, 6, 2),
                "status": "IN_PROGRESS",
                "reminder_type": "upcoming",
            },
            {
                "task_id": 3,
                "task_name": "Task C",
                "project_name": "Project Z",
                "deadline": date(2026, 6, 2),
                "status": "IN_PROGRESS",
                "reminder_type": "upcoming",
            },
        ],
    ))

    assert "Bạn có 3 task còn khoảng 2 ngày đến hạn" in message
    assert "1. Task A" in message
    assert "2. Task B" in message
    assert "3. Task C" in message


def test_deadline_digest_falls_back_when_llm_fails():
    agent = NotificationAgent(llm=FailingLLM())

    message = asyncio.run(agent.prepare_deadline_digest(
        recipient_name="User A",
        notify_date=date(2026, 5, 27),
        tasks=[{
            "task_id": 1,
            "task_name": "Task A",
            "project_name": "Project X",
            "deadline": date(2026, 5, 29),
            "status": "PLANNED",
            "reminder_type": "upcoming",
        }],
    ))

    assert "Task A" in message
    assert "Project X" in message
    assert "2026-05-29" in message


class FailingLLM:
    async def ainvoke(self, messages):
        raise RuntimeError("LLM unavailable")
