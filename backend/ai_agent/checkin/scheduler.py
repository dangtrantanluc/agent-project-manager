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
    deadline_pm_hour = int(os.getenv("DEADLINE_NOTIFY_AFTERNOON_HOUR", "14"))
    deadline_pm_minute = int(os.getenv("DEADLINE_NOTIFY_AFTERNOON_MINUTE", "0"))
    _scheduler.add_job(
        run_checkin_slot,
        CronTrigger(day_of_week="mon-fri", hour=11, minute=50, timezone=_VN_TZ),
        id="checkin_lunch", replace_existing=True, args=[CheckinSlot.LUNCH],
    )
    _scheduler.add_job(
        run_reminder_slot,
        CronTrigger(day_of_week="mon-fri", hour=12, minute=30, timezone=_VN_TZ),
        id="reminder_lunch", replace_existing=True, args=[CheckinSlot.LUNCH],
    )
    _scheduler.add_job(
        run_checkin_slot,
        CronTrigger(day_of_week="mon-fri", hour=17, minute=50, timezone=_VN_TZ),
        id="checkin_end_day", replace_existing=True, args=[CheckinSlot.END_DAY],
    )
    _scheduler.add_job(
        run_reminder_slot,
        CronTrigger(day_of_week="mon-fri", hour=18, minute=30, timezone=_VN_TZ),
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
        kwargs={"slot": "morning"},
    )
    _scheduler.add_job(
        run_deadline_notifications,
        CronTrigger(hour=deadline_pm_hour, minute=deadline_pm_minute, timezone=_VN_TZ),
        id="deadline_notifications_afternoon", replace_existing=True,
        kwargs={"slot": "afternoon"},
    )
    risk_hour = int(os.getenv("RISK_SCAN_HOUR", "8"))
    risk_minute = int(os.getenv("RISK_SCAN_MINUTE", "30"))
    _scheduler.add_job(
        run_risk_scan,
        CronTrigger(day_of_week="mon-fri", hour=risk_hour, minute=risk_minute, timezone=_VN_TZ),
        id="risk_scan", replace_existing=True,
    )
    _scheduler.add_job(
        run_expire_stale,
        CronTrigger(minute=5, timezone=_VN_TZ),  # mỗi giờ, phút thứ 5
        id="expire_stale", replace_existing=True,
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
        from ai_agent.notification.inapp_repository import create_notification
        from gapo.gapo_client import GapoClient

        gapo = GapoClient()
        label = _SLOT_LABEL.get(slot, slot)

        async with AsyncSessionLocal() as db:
            sessions = await repo.list_sessions_awaiting_reminder(db, slot)
            logger.info(f"[Scheduler] run_reminder_slot={slot}, sessions={len(sessions)}")

            for s in sessions:
                try:
                    msg = (
                        f"Nhắc nhở: Bạn chưa hoàn thành check-in {label}!\n"
                        f"Gõ /checkin hoặc tiếp tục chọn dự án."
                    )
                    await gapo.send_message(s["thread_id"], msg)
                    await create_notification(
                        db,
                        user_id=s["user_id"],
                        type="checkin_reminder",
                        title=f"Nhắc nhở check-in {label}",
                        body="Bạn chưa hoàn thành check-in. Vào để hoàn tất.",
                        link="/worklogs",
                    )
                    await repo.increment_reminder(db, s["id"])
                except Exception as e:
                    logger.error(f"[Scheduler] Reminder error session={s['id']}: {e}")

    await _with_advisory_lock(_run())


async def run_missing_summary() -> None:
    async def _run():
        from collections import defaultdict
        from database import AsyncSessionLocal
        from ai_agent.checkin import repository as repo
        from ai_agent.notification.inapp_repository import create_notification
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
                    f"Báo cáo thiếu check-in\n"
                    f"Slot: {slot_label}\n"
                    f"Ngày: {today}\n"
                    f"Số lượng: {len(sessions)} người\n\n"
                    f"Danh sách:\n{names}"
                )

                for admin in admins:
                    try:
                        await gapo.send_message(admin["thread_id"], msg)
                        await create_notification(
                            db,
                            user_id=admin["user_id"],
                            type="checkin_missing_summary",
                            title=f"Báo cáo thiếu check-in — {slot_label}",
                            body=f"{len(sessions)} người chưa check-in ngày {today}.",
                            link="/settings/agent-audit",
                        )
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


async def run_expire_stale() -> None:
    """Đánh dấu EXPIRED cho cảnh báo rủi ro & follow-up PENDING đã quá TTL.

    Bộ lọc theo thời gian ở find_pending_for / _resolve_from_followup đã loại các
    bản ghi quá hạn khỏi việc khớp; job này dọn TRẠNG THÁI để giữ dữ liệu sạch,
    partial index nhỏ gọn, và đếm "đang chờ" chính xác.
    """
    async def _run():
        from database import AsyncSessionLocal
        from sqlalchemy import text
        from app.services.risk_alert_service import PENDING_TTL_HOURS
        from ai_agent.task_update.task_verify_service import FOLLOW_UP_TTL_HOURS

        async with AsyncSessionLocal() as db:
            risk = (await db.execute(text("""
                UPDATE risk_alerts
                SET status = 'EXPIRED', updated_at = NOW()
                WHERE status = 'PENDING_PM_CONFIRMATION'
                  AND created_at < NOW() - (CAST(:ttl AS int) * INTERVAL '1 hour')
            """), {"ttl": PENDING_TTL_HOURS})).rowcount
            followups = (await db.execute(text("""
                UPDATE agent_follow_ups
                SET status = CAST('EXPIRED' AS "FollowUpStatus"), updated_at = NOW()
                WHERE status = CAST('PENDING' AS "FollowUpStatus")
                  AND created_at < NOW() - (CAST(:ttl AS int) * INTERVAL '1 hour')
            """), {"ttl": FOLLOW_UP_TTL_HOURS})).rowcount
            await db.commit()
        logger.info("[Scheduler] run_expire_stale risk_alerts=%s follow_ups=%s", risk, followups)

    await _with_advisory_lock(_run())


async def run_risk_scan(today: date | None = None) -> None:
    """Quét dự án at-risk và gửi cảnh báo PENDING cho PM (sơ đồ Luồng 4).

    Cảnh báo ở trạng thái chờ PM xác nhận — human-in-the-loop. PM trả lời trong DM,
    message_router (state-gate) bắt câu trả lời để duyệt/bỏ qua.
    """
    async def _run():
        from database import AsyncSessionLocal
        from app.services.risk_alert_service import RiskAlertService

        target_day = today or datetime.now(_VN_TZ).date()
        service = RiskAlertService()
        async with AsyncSessionLocal() as db:
            stats = await service.scan_and_alert(db, today_iso=target_day.isoformat())
        logger.info("[Scheduler] run_risk_scan today=%s %s", target_day, stats)

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
            priority,
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
            "priority": priority,
            "reminder_type": reminder_type,
        })

    return dict(due_by_recipient), skipped


def _deadline_quick_actions(tasks: list[dict]) -> tuple[str, list[dict]]:
    """(title, actions) cho quick-reply sau digest deadline.

    1 task  -> menu trạng thái thẳng (1 chạm là xong).
    Nhiều   -> mỗi nút 1 task (TASKPICK|id) -> bấm task ra menu trạng thái.
    """
    def _short(name: str, n: int = 44) -> str:
        name = name or "task"
        return name if len(name) <= n else name[:n] + "…"

    if len(tasks) == 1:
        tid = tasks[0]["task_id"]
        return ("Cập nhật nhanh task này:", [
            {"label": "✅ Đã xong", "payload": f"TASKUPD|{tid}|100"},
            {"label": "🔄 50%", "payload": f"TASKUPD|{tid}|50"},
            {"label": "🔄 75%", "payload": f"TASKUPD|{tid}|75"},
            {"label": "⛔ Đang kẹt (blocker)", "payload": f"TASKBLOCK|{tid}"},
            {"label": "⏰ Gia hạn 3 ngày", "payload": f"TASKEXTEND|{tid}|3"},
            {"label": "😴 Hoãn nhắc 1 ngày", "payload": f"TASKSNOOZE|{tid}"},
        ])
    # Gapo render ~9-10 nút -> cap 6 task + nút "➡️ Xem thêm" (mở pager qua các trang).
    _MAX = 6
    actions = [{"label": _short(t["task_name"]), "payload": f"TASKPICK|{t['task_id']}"}
               for t in tasks[:_MAX]]
    if len(tasks) > _MAX:
        actions.append({"label": "➡️ Xem thêm", "payload": "TASKPAGE|2"})
    return ("Bấm task để cập nhật nhanh:", actions)


async def run_deadline_notifications(today: date | None = None, slot: str = "morning") -> None:
    """Gửi nhắc deadline.

    slot="morning" (9h): nhắc cả task đến hạn hôm nay (due_today) và task sắp
    đến hạn (~2 ngày, upcoming).
    slot="afternoon" (14h): chỉ nhắc lại task đến hạn HÔM NAY mà CHƯA hoàn thành.
    Task đã DONE tự động bị loại ở mệnh đề WHERE nên "hoàn thành rồi thì thôi".
    """
    async def _run():
        from database import AsyncSessionLocal
        from sqlalchemy import text
        from ai_agent.notification.notification_agent import NotificationAgent
        from ai_agent.notification.inapp_repository import create_notification
        from gapo.gapo_client import GapoClient

        target_day = today or datetime.now(_VN_TZ).date()
        gapo = GapoClient()
        notification_agent = NotificationAgent()

        async with AsyncSessionLocal() as db:
            rows = (await db.execute(text("""
                SELECT t.id, t.name, t.deadline, t.assignee_id,
                       p.name AS project_name, g.gapo_thread_id,
                       u.full_name AS assignee_name, t.status::text AS status,
                       t.priority::text AS priority
                FROM tasks t
                JOIN projects p ON p.id = t.project_id
                JOIN users u ON u.id = t.assignee_id
                JOIN gapo_user_maps g ON g.user_id = t.assignee_id
                WHERE t.deadline IS NOT NULL
                  AND t.assignee_id IS NOT NULL
                  AND t.status::text <> 'DONE'
                  -- Bỏ qua task user đã bấm "😴 Hoãn nhắc 1 ngày".
                  AND (t.snooze_reminder_until IS NULL OR t.snooze_reminder_until < CURRENT_DATE)
                ORDER BY t.deadline ASC, t.id ASC
            """))).fetchall()

            due_by_recipient, skipped = _group_due_deadline_tasks(rows, target_day)

            # Buổi chiều chỉ nhắc lại task đến hạn hôm nay (due_today) chưa xong.
            # Bỏ qua task "upcoming" vì chúng đã được nhắc buổi sáng.
            if slot == "afternoon":
                filtered: dict = {}
                for recipient, tasks in due_by_recipient.items():
                    due_today = [t for t in tasks if t["reminder_type"] == "due_today"]
                    if due_today:
                        filtered[recipient] = due_today
                    else:
                        skipped += len(tasks)
                due_by_recipient = filtered

            sent_batches = 0
            sent_tasks = 0
            for (assignee_id, thread_id), tasks in due_by_recipient.items():
                reminder_types = sorted({task["reminder_type"] for task in tasks})
                reminder_key = "+".join(reminder_types)
                correlation_id = f"deadline_batch:{assignee_id}:{target_day.isoformat()}:{slot}:{reminder_key}"
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
                    "slot": slot,
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
                    await create_notification(
                        db,
                        user_id=assignee_id,
                        type="task_deadline",
                        title=(
                            f"{len(tasks)} công việc sắp đến hạn"
                            if len(tasks) > 1 else "Công việc sắp đến hạn"
                        ),
                        body=tasks[0]["task_name"] if len(tasks) == 1 else None,
                        link="/tasks",
                        commit=False,
                    )
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
                    # Tạo follow-up PENDING cho từng task -> agent xác minh khi user báo
                    # "đã xong". task_id NOT NULL nên bắt buộc 1 row/1 task (không gộp batch).
                    for task in tasks:
                        per_task_corr = (
                            f"deadline:{task['task_id']}:"
                            f"{target_day.isoformat()}:{slot}:{task['reminder_type']}"
                        )
                        await db.execute(text("""
                            INSERT INTO agent_follow_ups
                                (task_id, user_id, channel, thread_id, question,
                                 status, correlation_id, asked_at, updated_at)
                            VALUES
                                (:task_id, :user_id, CAST(:channel AS "ChannelKind"),
                                 :thread_id, :question,
                                 CAST('PENDING' AS "FollowUpStatus"),
                                 :correlation_id, NOW(), NOW())
                        """), {
                            "task_id": task["task_id"],
                            "user_id": assignee_id,
                            "channel": "gapo",
                            "thread_id": str(thread_id),
                            "question": msg,
                            "correlation_id": per_task_corr,
                        })
                    await db.commit()
                    # Gửi NÚT BẤM nhanh sau digest: bấm là cập nhật, khỏi gõ.
                    # 1 task -> menu trạng thái thẳng (Đã xong/50%/75%/Kẹt/Gia hạn/Hoãn).
                    # Nhiều task -> picker (mỗi nút 1 task, payload TASKPICK|id).
                    try:
                        await gapo.send_menu(thread_id, *_deadline_quick_actions(tasks))
                    except Exception:
                        logger.warning("[Scheduler] gửi quick-reply deadline lỗi (bỏ qua)", exc_info=True)
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
                "[Scheduler] run_deadline_notifications today=%s slot=%s sent_batches=%d sent_tasks=%d skipped=%d",
                target_day,
                slot,
                sent_batches,
                sent_tasks,
                skipped,
            )

    await _with_advisory_lock(_run())
