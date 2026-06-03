import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from ai_agent.checkin.constants import CheckinSlot, ADVISORY_LOCK_KEY

_VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")
_scheduler = AsyncIOScheduler(timezone=_VN_TZ)
logger = logging.getLogger(__name__)

_SLOT_LABEL = {
    CheckinSlot.LUNCH:   "buoi sang (11:50)",
    CheckinSlot.END_DAY: "cuoi ngay (17:50)",
}


def start_checkin_scheduler() -> None:
    if _scheduler.running:
        return
    deadline_hour = int(os.getenv("DEADLINE_NOTIFY_HOUR", "9"))
    deadline_minute = int(os.getenv("DEADLINE_NOTIFY_MINUTE", "0"))
    _scheduler.add_job(
        run_checkin_slot, CronTrigger(hour=11, minute=50, timezone=_VN_TZ),
        id="checkin_lunch", replace_existing=True, args=[CheckinSlot.LUNCH],
    )
    _scheduler.add_job(
        run_reminder_slot, CronTrigger(hour=12, minute=30, timezone=_VN_TZ),
        id="reminder_lunch", replace_existing=True, args=[CheckinSlot.LUNCH],
    )
    _scheduler.add_job(
        run_checkin_slot, CronTrigger(hour=17, minute=50, timezone=_VN_TZ),
        id="checkin_end_day", replace_existing=True, args=[CheckinSlot.END_DAY],
    )
    _scheduler.add_job(
        run_reminder_slot, CronTrigger(hour=18, minute=30, timezone=_VN_TZ),
        id="reminder_end_day", replace_existing=True, args=[CheckinSlot.END_DAY],
    )
    _scheduler.add_job(
        run_missing_summary, CronTrigger(hour=19, minute=0, timezone=_VN_TZ),
        id="missing_summary", replace_existing=True,
    )
    _scheduler.add_job(
        run_deadline_notifications,
        CronTrigger(hour=deadline_hour, minute=deadline_minute, timezone=_VN_TZ),
        id="deadline_notifications", replace_existing=True,
    )
    _scheduler.start()
    logger.info("[Scheduler] Check-in scheduler started")


def stop_checkin_scheduler() -> None:
    if not _scheduler.running:
        return
    _scheduler.shutdown(wait=False)
    logger.info("[Scheduler] Check-in scheduler stopped")


async def _with_advisory_lock(coro):
    from database import AsyncSessionLocal
    from sqlalchemy import text

    async with AsyncSessionLocal() as db:
        locked = (await db.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY}
        )).scalar()
        if not locked:
            logger.info("[Scheduler] Advisory lock busy, skipping run")
            return
        try:
            await coro
        finally:
            await db.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY}
            )


async def run_checkin_slot(slot: str) -> None:
    async def _run():
        from database import AsyncSessionLocal
        from langchain_openai import ChatOpenAI
        from ai_agent.checkin import repository as repo
        from ai_agent.checkin.service import CheckinFlowService
        from gapo.gapo_client import GapoClient
        from ai_agent.checkin.worklog_parser.service import WorklogParserService

        llm = ChatOpenAI(
            model=os.getenv("MODEL_NAME"),
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL"),
        )
        gapo = GapoClient()
        parser = WorklogParserService(llm=llm)
        svc = CheckinFlowService(gapo=gapo, worklog_parser=parser)

        async with AsyncSessionLocal() as db:
            await repo.expire_old_sessions(db)
            users = await repo.get_mapped_active_users(db)
            logger.info(f"[Scheduler] run_checkin_slot={slot}, users={len(users)}")

            for user in users:
                try:
                    await svc.start_for_user(db, user=user, slot=slot)
                    await repo.insert_audit(
                        db,
                        tool="checkin_scheduler",
                        args={"slot": slot, "user_id": user["user_id"]},
                        result={"status": "sent"},
                    )
                except Exception as e:
                    logger.error(f"[Scheduler] Error user={user['user_id']}: {e}")
                    await repo.insert_audit(
                        db,
                        tool="checkin_scheduler",
                        args={"slot": slot, "user_id": user["user_id"]},
                        error=str(e),
                    )

    await _with_advisory_lock(_run())


async def run_reminder_slot(slot: str) -> None:
    async def _run():
        from database import AsyncSessionLocal
        from ai_agent.checkin import repository as repo
        from gapo.gapo_client import GapoClient

        gapo = GapoClient()
        label = _SLOT_LABEL.get(slot, slot)

        async with AsyncSessionLocal() as db:
            sessions = await repo.list_sessions_awaiting_reminder(db, slot)
            logger.info(f"[Scheduler] run_reminder_slot={slot}, sessions={len(sessions)}")

            for s in sessions:
                try:
                    msg = (
                        f"Nhac nho: Ban chua hoan thanh check-in {label}!\n"
                        f"Go /checkin hoac tiep tuc chon du an."
                    )
                    await gapo.send_message(s["thread_id"], msg)
                    await repo.increment_reminder(db, s["id"])
                except Exception as e:
                    logger.error(f"[Scheduler] Reminder error session={s['id']}: {e}")

    await _with_advisory_lock(_run())


async def run_missing_summary() -> None:
    async def _run():
        from collections import defaultdict
        from database import AsyncSessionLocal
        from ai_agent.checkin import repository as repo
        from gapo.gapo_client import GapoClient

        today = datetime.now(_VN_TZ).strftime("%Y-%m-%d")
        gapo = GapoClient()

        async with AsyncSessionLocal() as db:
            missed = await repo.mark_missed_sessions(db)
            logger.info(f"[Scheduler] run_missing_summary: {len(missed)} missed sessions")
            if not missed:
                return

            # Single-company deployment: group only by slot.
            by_slot: dict[str, list] = defaultdict(list)
            for m in missed:
                by_slot[m["slot"]].append(m)

            notified_admins = 0
            for slot, sessions in by_slot.items():
                admins = await repo.get_admins(db)
                if not admins:
                    logger.warning(
                        f"[Scheduler] No admins to notify for slot={slot}"
                    )
                    continue

                slot_label = _SLOT_LABEL.get(slot, slot)
                names = "\n".join(
                    "- " + (s.get("full_name") or f"User #{s['user_id']}")
                    for s in sessions
                )
                msg = (
                    f"Bao cao thieu check-in\n"
                    f"Slot: {slot_label}\n"
                    f"Ngay: {today}\n"
                    f"So luong: {len(sessions)} nguoi\n\n"
                    f"Danh sach:\n{names}"
                )

                for admin in admins:
                    try:
                        await gapo.send_message(admin["thread_id"], msg)
                        notified_admins += 1
                    except Exception as e:
                        logger.error(
                            f"[Scheduler] Failed to notify admin={admin.get('user_id')} "
                            f"slot={slot}: {e}"
                        )

            await repo.insert_audit(
                db,
                tool="checkin_missing_summary",
                args={"missed_count": len(missed), "sessions": [m["id"] for m in missed]},
                result={"notified_admins": notified_admins},
            )

    await _with_advisory_lock(_run())


def _deadline_notify_date(deadline: date) -> date:
    notify_date = deadline - timedelta(days=2)
    if notify_date.weekday() == 5:  # Saturday -> Friday
        return notify_date - timedelta(days=1)
    if notify_date.weekday() == 6:  # Sunday -> Friday
        return notify_date - timedelta(days=2)
    return notify_date


def _deadline_reminder_type(deadline: date, target_day: date) -> str | None:
    if deadline == target_day:
        return "due_today"
    if _deadline_notify_date(deadline) == target_day:
        return "upcoming"
    return None


def _group_due_deadline_tasks(rows, target_day: date) -> tuple[dict[tuple[int, str], list[dict]], int]:
    from collections import defaultdict

    due_by_recipient: dict[tuple[int, str], list[dict]] = defaultdict(list)
    skipped = 0
    for row in rows:
        (
            task_id,
            task_name,
            deadline,
            assignee_id,
            project_name,
            thread_id,
            assignee_name,
            status,
        ) = row
        reminder_type = _deadline_reminder_type(deadline, target_day)
        if reminder_type is None:
            skipped += 1
            continue

        due_by_recipient[(assignee_id, str(thread_id))].append({
            "task_id": task_id,
            "task_name": task_name,
            "deadline": deadline,
            "assignee_id": assignee_id,
            "assignee_name": assignee_name,
            "project_name": project_name,
            "thread_id": str(thread_id),
            "status": status,
            "reminder_type": reminder_type,
        })

    return dict(due_by_recipient), skipped


async def run_deadline_notifications(today: date | None = None) -> None:
    async def _run():
        from database import AsyncSessionLocal
        from sqlalchemy import text
        from ai_agent.notification.notification_agent import NotificationAgent
        from gapo.gapo_client import GapoClient

        target_day = today or datetime.now(_VN_TZ).date()
        gapo = GapoClient()
        notification_agent = NotificationAgent()

        async with AsyncSessionLocal() as db:
            rows = (await db.execute(text("""
                SELECT t.id, t.name, t.deadline, t.assignee_id,
                       p.name AS project_name, g.gapo_thread_id,
                       u.full_name AS assignee_name, t.status::text AS status
                FROM tasks t
                JOIN projects p ON p.id = t.project_id
                JOIN users u ON u.id = t.assignee_id
                JOIN gapo_user_maps g ON g.user_id = t.assignee_id
                WHERE t.deadline IS NOT NULL
                  AND t.assignee_id IS NOT NULL
                  AND t.status::text <> 'DONE'
                ORDER BY t.deadline ASC, t.id ASC
            """))).fetchall()

            due_by_recipient, skipped = _group_due_deadline_tasks(rows, target_day)

            sent_batches = 0
            sent_tasks = 0
            for (assignee_id, thread_id), tasks in due_by_recipient.items():
                reminder_types = sorted({task["reminder_type"] for task in tasks})
                reminder_key = "+".join(reminder_types)
                correlation_id = f"deadline_batch:{assignee_id}:{target_day.isoformat()}:{reminder_key}"
                already_sent = (await db.execute(text("""
                    SELECT 1
                    FROM agent_audit_log
                    WHERE tool = 'deadline_notification'
                      AND correlation_id = :correlation_id
                      AND error_message IS NULL
                    LIMIT 1
                """), {"correlation_id": correlation_id})).fetchone()
                if already_sent:
                    skipped += len(tasks)
                    continue

                task_ids = [task["task_id"] for task in tasks]
                assignee_name = tasks[0].get("assignee_name")
                msg = await notification_agent.prepare_deadline_digest(
                    recipient_name=assignee_name,
                    notify_date=target_day,
                    tasks=tasks,
                )
                args_json = {
                    "assignee_id": assignee_id,
                    "assignee_name": assignee_name,
                    "thread_id": thread_id,
                    "notify_date": target_day.isoformat(),
                    "task_ids": task_ids,
                    "tasks": [
                        {
                            "task_id": task["task_id"],
                            "task_name": task["task_name"],
                            "project_name": task["project_name"],
                            "deadline": task["deadline"].isoformat(),
                            "status": task["status"],
                            "reminder_type": task["reminder_type"],
                        }
                        for task in tasks
                    ],
                    "generated_by": "notification_agent",
                }

                try:
                    result = await gapo.send_message(thread_id, msg)
                    await db.execute(text("""
                        INSERT INTO agent_audit_log
                            (tool, args_json, result_json, source, correlation_id, created_at)
                        VALUES
                            ('deadline_notification', CAST(:args AS jsonb), CAST(:result AS jsonb),
                             CAST('cron' AS "AgentAuditSource"), :correlation_id, NOW())
                    """), {
                        "args": json.dumps(args_json),
                        "result": json.dumps({
                            "send_result": result,
                            "message": msg,
                            "task_ids": task_ids,
                            "per_task_correlations": [
                                f"deadline:{task['task_id']}:{target_day.isoformat()}:{task['reminder_type']}"
                                for task in tasks
                            ],
                        }),
                        "correlation_id": correlation_id,
                    })
                    await db.commit()
                    sent_batches += 1
                    sent_tasks += len(tasks)
                except Exception as e:
                    await db.execute(text("""
                        INSERT INTO agent_audit_log
                            (tool, args_json, error_message, source, correlation_id, created_at)
                        VALUES
                            ('deadline_notification', CAST(:args AS jsonb), :error,
                             CAST('cron' AS "AgentAuditSource"), :correlation_id, NOW())
                    """), {
                        "args": json.dumps(args_json),
                        "error": str(e),
                        "correlation_id": correlation_id,
                    })
                    await db.commit()
                    logger.error(
                        "[Scheduler] Deadline notification failed assignee=%s tasks=%s: %s",
                        assignee_id,
                        task_ids,
                        e,
                    )

            logger.info(
                "[Scheduler] run_deadline_notifications today=%s sent_batches=%d sent_tasks=%d skipped=%d",
                target_day,
                sent_batches,
                sent_tasks,
                skipped,
            )

    await _with_advisory_lock(_run())
