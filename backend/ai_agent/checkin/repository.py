from datetime import date, datetime, timedelta
import json
import pytz
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_agent.checkin.constants import (
    CheckinState, SLOT_EXPIRE_TIME, MANUAL_EXPIRE_DELTA,
    REMINDER_COOLDOWN_MINUTES, MAX_REMINDERS_PER_SLOT,
)

_VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")
_column_cache: dict[tuple[str, str], bool] = {}


def _now_vn() -> datetime:
    return datetime.now(_VN_TZ)


def _calc_expires_at(slot: str) -> datetime:
    now = _now_vn()
    expire_time = SLOT_EXPIRE_TIME.get(slot)
    if expire_time:
        h, m = map(int, expire_time.split(":"))
        local_expires = now.replace(hour=h, minute=m, second=0, microsecond=0)
    else:
        local_expires = now + MANUAL_EXPIRE_DELTA
    # asyncpg treats naive datetimes as UTC for timestamptz columns
    return local_expires.astimezone(pytz.utc).replace(tzinfo=None)


def _parse_json_col(value) -> dict | None:
    """Safely parse a json column value that may come as str or dict."""
    if value is None:
        return None


async def _has_column(db: AsyncSession, table_name: str, column_name: str) -> bool:
    key = (table_name, column_name)
    if key in _column_cache:
        return _column_cache[key]
    exists = (await db.execute(text("""
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table_name
              AND column_name = :column_name
        )
    """), {"table_name": table_name, "column_name": column_name})).scalar()
    _column_cache[key] = bool(exists)
    return _column_cache[key]
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except Exception:
        return None


# ── User / session bootstrap ──────────────────────────────────────────────────

async def get_mapped_active_users(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(text("""
        SELECT u.id, u.full_name,
               g.gapo_user_id, g.gapo_thread_id
        FROM users u
        JOIN gapo_user_maps g ON g.user_id = u.id
        WHERE u.active = true
          AND g.gapo_thread_id IS NOT NULL
    """))).fetchall()
    return [
        {
            "user_id": r[0], "full_name": r[1],
            "gapo_user_id": str(r[2]), "thread_id": str(r[3]),
        }
        for r in rows
    ]


async def upsert_session(
    db: AsyncSession, *,
    user_id: int,
    gapo_user_id: str,
    thread_id: str,
    work_date: date,
    slot: str,
    expires_at: datetime,
) -> dict:
    p = {
        "uid": user_id, "gid": gapo_user_id,
        "tid": thread_id, "work_date": work_date, "slot": slot,
        "expires_at": expires_at,
    }
    existing = (await db.execute(text("""
        SELECT id FROM checkin_sessions
        WHERE user_id = :uid AND work_date = :work_date AND slot = :slot
          AND state::text NOT IN ('COMPLETED','CANCELLED','EXPIRED','MISSED')
        LIMIT 1
    """), p)).fetchone()

    if existing:
        row = (await db.execute(text("""
            UPDATE checkin_sessions
            SET state = CAST('IDLE' AS "CheckinState"),
                thread_id = :tid,
                expires_at = :expires_at, reminder_count = 0,
                pending_parsed = NULL, pending_text = NULL,
                updated_at = NOW()
            WHERE id = :sid
            RETURNING id, user_id, state, work_date, slot, thread_id
        """), {"sid": existing[0], "tid": p["tid"], "expires_at": expires_at})).fetchone()
    else:
        has_company_id = await _has_column(db, "checkin_sessions", "company_id")
        company_col = "company_id, " if has_company_id else ""
        company_val = (
            "COALESCE((SELECT company_id FROM users WHERE id = :uid), "
            "(SELECT id FROM companies ORDER BY id LIMIT 1)), "
            if has_company_id else ""
        )
        row = (await db.execute(text("""
            INSERT INTO checkin_sessions
                (user_id, {company_col}gapo_user_id, thread_id,
                 work_date, slot, state, expires_at,
                 reminder_count, created_at, updated_at)
            VALUES
                (:uid, {company_val}:gid, :tid,
                 :work_date, :slot, CAST('IDLE' AS "CheckinState"), :expires_at,
                 0, NOW(), NOW())
            RETURNING id, user_id, state, work_date, slot, thread_id
        """.format(company_col=company_col, company_val=company_val)), p)).fetchone()

    await db.commit()
    return {
        "id": row[0], "user_id": row[1],
        "state": row[2], "work_date": row[3], "slot": row[4], "thread_id": row[5],
        "current_project_id": None, "current_task_id": None,
        "pending_parsed": None, "pending_text": None,
    }


async def get_active_session(db: AsyncSession, user_id: int) -> dict | None:
    row = (await db.execute(text("""
        SELECT id, user_id, thread_id,
               current_project_id, current_task_id,
               state, work_date, slot, expires_at,
               pending_parsed, pending_text
        FROM checkin_sessions
        WHERE user_id = :uid
          AND state::text NOT IN ('COMPLETED','CANCELLED','EXPIRED','MISSED')
          AND expires_at > NOW()
        ORDER BY created_at DESC
        LIMIT 1
    """), {"uid": user_id})).fetchone()
    if not row:
        return None
    return {
        "id": row[0], "user_id": row[1],
        "thread_id": row[2], "current_project_id": row[3],
        "current_task_id": row[4], "state": row[5],
        "work_date": row[6], "slot": row[7], "expires_at": row[8],
        "pending_parsed": _parse_json_col(row[9]),
        "pending_text": row[10],
    }


# ── State transitions ─────────────────────────────────────────────────────────

async def cancel_all_active_sessions(db: AsyncSession, user_id: int) -> None:
    """Cancel any lingering non-terminal sessions before starting a fresh one."""
    await db.execute(text("""
        UPDATE checkin_sessions
        SET state = CAST('CANCELLED' AS "CheckinState"), updated_at = NOW()
        WHERE user_id = :uid
          AND state::text NOT IN ('COMPLETED','CANCELLED','EXPIRED','MISSED')
    """), {"uid": user_id})
    await db.commit()


async def expire_old_sessions(db: AsyncSession) -> int:
    result = await db.execute(text("""
        UPDATE checkin_sessions
        SET state = CAST('EXPIRED' AS "CheckinState"), updated_at = NOW()
        WHERE expires_at < NOW()
          AND state::text NOT IN ('COMPLETED','CANCELLED','EXPIRED','MISSED')
    """))
    await db.commit()
    return result.rowcount


async def set_session_state(
    db: AsyncSession, session_id: int, state: str,
    project_id: int | None = None,
    task_id: int | None = None,
) -> None:
    sets = ['state = CAST(:state AS "CheckinState")', "updated_at = NOW()"]
    params: dict = {"sid": session_id, "state": state}
    if project_id is not None:
        sets.append("current_project_id = :project_id")
        params["project_id"] = project_id
    if task_id is not None:
        sets.append("current_task_id = :task_id")
        params["task_id"] = task_id
    await db.execute(
        text(f"UPDATE checkin_sessions SET {', '.join(sets)} WHERE id = :sid"),
        params,
    )
    await db.commit()


async def set_state_with_menu_mapping(
    db: AsyncSession, session_id: int, state: str, menu_type: str, items: list[dict]
) -> None:
    """Atomically set state and save menu mapping for numbered-fallback resolution."""
    mapping = json.dumps({"type": "menu", "menu_type": menu_type, "items": items})
    await db.execute(text("""
        UPDATE checkin_sessions
        SET state          = CAST(:state AS "CheckinState"),
            pending_parsed = CAST(:mapping AS json),
            updated_at     = NOW()
        WHERE id = :sid
    """), {"sid": session_id, "state": state, "mapping": mapping})
    await db.commit()


async def clear_task_from_session(db: AsyncSession, session_id: int) -> None:
    await db.execute(text("""
        UPDATE checkin_sessions
        SET current_task_id = NULL,
            state = CAST('AWAITING_UPDATE' AS "CheckinState"),
            updated_at = NOW()
        WHERE id = :sid
    """), {"sid": session_id})
    await db.commit()


async def goto_add_more(db: AsyncSession, session_id: int, project_id: int) -> None:
    """After confirming a worklog, keep project but reset task → AWAITING_TASK."""
    await db.execute(text("""
        UPDATE checkin_sessions
        SET state              = CAST('AWAITING_TASK' AS "CheckinState"),
            current_task_id    = NULL,
            current_project_id = :pid,
            pending_parsed     = NULL,
            updated_at         = NOW()
        WHERE id = :sid
    """), {"sid": session_id, "pid": project_id})
    await db.commit()


async def update_session_pending(
    db: AsyncSession, session_id: int, pending_text: str, pending_parsed: dict | None = None
) -> None:
    await db.execute(text("""
        UPDATE checkin_sessions
        SET pending_text   = :pending_text,
            pending_parsed = CAST(:pending_parsed AS json),
            updated_at     = NOW()
        WHERE id = :sid
    """), {
        "sid": session_id,
        "pending_text": pending_text,
        "pending_parsed": json.dumps(pending_parsed) if pending_parsed is not None else None,
    })
    await db.commit()


async def set_session_confirming(db: AsyncSession, session_id: int, parsed_json: dict) -> None:
    """After worklog inserted: wait for user to choose add_more or done."""
    await db.execute(text("""
        UPDATE checkin_sessions
        SET state          = CAST('AWAITING_TASK_CONFIRM' AS "CheckinState"),
            pending_parsed = CAST(:parsed AS json),
            pending_text   = NULL,
            updated_at     = NOW()
        WHERE id = :sid
    """), {"sid": session_id, "parsed": json.dumps(parsed_json)})
    await db.commit()


async def complete_session(db: AsyncSession, session_id: int, parsed_json: dict) -> None:
    await db.execute(text("""
        UPDATE checkin_sessions
        SET state          = CAST('COMPLETED' AS "CheckinState"),
            pending_parsed = CAST(:parsed AS json),
            completed_at   = NOW(),
            updated_at     = NOW()
        WHERE id = :sid
    """), {"sid": session_id, "parsed": json.dumps(parsed_json) if parsed_json else None})
    await db.commit()


async def cancel_session(db: AsyncSession, session_id: int) -> None:
    await db.execute(text("""
        UPDATE checkin_sessions
        SET state = CAST('CANCELLED' AS "CheckinState"), updated_at = NOW()
        WHERE id = :sid
    """), {"sid": session_id})
    await db.commit()


async def mark_missed_sessions(db: AsyncSession) -> list[dict]:
    today = _now_vn().date()
    rows = (await db.execute(text("""
        UPDATE checkin_sessions cs
        SET state    = CAST('MISSED' AS "CheckinState"),
            missed_at = NOW(),
            updated_at = NOW()
        FROM users u
        WHERE cs.work_date < :today
          AND cs.state::text = 'EXPIRED'
          AND u.id = cs.user_id
        RETURNING cs.id, cs.user_id, cs.slot, cs.work_date,
                  u.full_name
    """), {"today": today})).fetchall()
    await db.commit()
    return [
        {
            "id": r[0], "user_id": r[1],
            "slot": r[2], "work_date": r[3], "full_name": r[4],
        }
        for r in rows
    ]


# ── Reminders ─────────────────────────────────────────────────────────────────

async def increment_reminder(db: AsyncSession, session_id: int) -> None:
    await db.execute(text("""
        UPDATE checkin_sessions
        SET reminder_count   = reminder_count + 1,
            last_reminded_at = NOW(),
            updated_at       = NOW()
        WHERE id = :sid
    """), {"sid": session_id})
    await db.commit()


async def list_sessions_awaiting_reminder(
    db: AsyncSession,
    slot: str,
    max_reminders: int = MAX_REMINDERS_PER_SLOT,
    cooldown_minutes: int = REMINDER_COOLDOWN_MINUTES,
) -> list[dict]:
    rows = (await db.execute(text("""
        SELECT id, user_id, thread_id, state, slot, reminder_count
        FROM checkin_sessions
        WHERE slot = :slot
          AND state::text NOT IN ('COMPLETED','CANCELLED','EXPIRED','MISSED')
          AND expires_at > NOW()
          AND reminder_count < :max_r
          AND (
            last_reminded_at IS NULL
            OR last_reminded_at < NOW() - (:cooldown_min || ' minutes')::INTERVAL
          )
        ORDER BY created_at
    """), {
        "slot": slot,
        "max_r": max_reminders,
        "cooldown_min": str(cooldown_minutes),
    })).fetchall()
    return [
        {"id": r[0], "user_id": r[1], "thread_id": r[2],
         "state": r[3], "slot": r[4], "reminder_count": r[5]}
        for r in rows
    ]


# ── Project / task candidates ─────────────────────────────────────────────────

async def list_project_candidates(
    db: AsyncSession, *, user_id: int, limit: int = 8, q: str | None = None
) -> list[dict]:
    params: dict = {"uid": user_id, "lim": limit}
    q_clause = ""
    if q:
        q_clause = "AND p.name ILIKE :q"
        params["q"] = f"%{q}%"
    rows = (await db.execute(text(f"""
        SELECT p.id, p.name, p.status
        FROM projects p
        WHERE p.status::text <> 'DONE'
          {q_clause}
          AND (
            EXISTS (SELECT 1 FROM members m WHERE m.project_id = p.id AND m.user_id = :uid)
            OR
            EXISTS (
                SELECT 1 FROM tasks t
                WHERE t.project_id = p.id AND t.assignee_id = :uid
                  AND t.status::text <> 'DONE'
            )
          )
        GROUP BY p.id
        ORDER BY
          CASE p.status::text WHEN 'IN_PROGRESS' THEN 0 ELSE 1 END,
          MAX(p.updated_at) DESC
        LIMIT :lim
    """), params)).fetchall()
    return [{"id": r[0], "name": r[1], "status": r[2]} for r in rows]


async def list_task_candidates(
    db: AsyncSession, *, user_id: int, project_id: int,
    limit: int = 8, q: str | None = None
) -> list[dict]:
    params: dict = {"pid": project_id, "uid": user_id, "lim": limit}
    q_clause = ""
    if q:
        q_clause = "AND name ILIKE :q"
        params["q"] = f"%{q}%"
    rows = (await db.execute(text(f"""
        SELECT id, name, status, deadline, assignee_id
        FROM tasks
        WHERE project_id = :pid
          AND status::text <> 'DONE'
          {q_clause}
        ORDER BY
          CASE WHEN assignee_id = :uid THEN 0 ELSE 1 END,
          deadline ASC NULLS LAST,
          updated_at DESC
        LIMIT :lim
    """), params)).fetchall()
    return [
        {"id": r[0], "name": r[1], "status": r[2],
         "deadline": r[3].isoformat() if r[3] else None, "assignee_id": r[4]}
        for r in rows
    ]


async def validate_project_access(
    db: AsyncSession, *, user_id: int, project_id: int
) -> bool:
    row = (await db.execute(text("""
        SELECT 1 FROM projects p
        WHERE p.id = :pid
          AND (
            EXISTS (SELECT 1 FROM members m WHERE m.project_id = p.id AND m.user_id = :uid)
            OR
            EXISTS (SELECT 1 FROM tasks t WHERE t.project_id = p.id AND t.assignee_id = :uid)
          )
        LIMIT 1
    """), {"pid": project_id, "uid": user_id})).fetchone()
    return row is not None


async def validate_task_in_project(
    db: AsyncSession, *, task_id: int, project_id: int
) -> bool:
    row = (await db.execute(text("""
        SELECT 1 FROM tasks
        WHERE id = :tid AND project_id = :pid
        LIMIT 1
    """), {"tid": task_id, "pid": project_id})).fetchone()
    return row is not None


async def get_project_name(db: AsyncSession, project_id: int) -> str:
    row = (await db.execute(
        text("SELECT name FROM projects WHERE id = :pid LIMIT 1"),
        {"pid": project_id},
    )).fetchone()
    return row[0] if row else f"#{project_id}"


async def get_task_name(db: AsyncSession, task_id: int) -> str:
    row = (await db.execute(
        text("SELECT name FROM tasks WHERE id = :tid LIMIT 1"),
        {"tid": task_id},
    )).fetchone()
    return row[0] if row else f"#{task_id}"


# ── Worklog ───────────────────────────────────────────────────────────────────

async def check_duplicate_worklog(
    db: AsyncSession, *, session_id: int, raw_message: str
) -> int | None:
    """Returns existing worklog_id if exact same message already logged in this session."""
    row = (await db.execute(text("""
        SELECT id FROM worklogs
        WHERE checkin_session_id = :sid AND raw_message = :raw
        LIMIT 1
    """), {"sid": session_id, "raw": raw_message})).fetchone()
    return row[0] if row else None


async def insert_worklog(
    db: AsyncSession, *,
    work_date: date,
    description: str | None,
    hours: float,
    task_id: int | None,
    project_id: int,
    user_id: int,
    raw_message: str,
    parsed_json: dict,
    checkin_session_id: int,
    slot: str,
) -> int:
    has_company_id = await _has_column(db, "worklogs", "company_id")
    company_col = "company_id, " if has_company_id else ""
    company_val = (
        "COALESCE((SELECT company_id FROM projects WHERE id = :project_id), "
        "(SELECT id FROM companies ORDER BY id LIMIT 1)), "
        if has_company_id else ""
    )
    row = (await db.execute(text("""
        INSERT INTO worklogs
            (work_date, description, hours, task_id, project_id,
             {company_col}user_id, source, raw_message, parsed_json,
             checkin_session_id, slot, created_at, updated_at)
        VALUES
            (:work_date, :description, :hours, :task_id, :project_id,
             {company_val}:user_id, 'GAPO_CHECKIN', :raw_message, CAST(:parsed_json AS jsonb),
             :session_id, :slot, NOW(), NOW())
        RETURNING id
    """.format(company_col=company_col, company_val=company_val)), {
        "work_date": work_date, "description": description, "hours": hours,
        "task_id": task_id, "project_id": project_id, "user_id": user_id, "raw_message": raw_message,
        "parsed_json": json.dumps(parsed_json),
        "session_id": checkin_session_id, "slot": slot,
    })).fetchone()
    await db.commit()
    return row[0]


async def apply_worklog_side_effects(
    db: AsyncSession, *,
    project_id: int,
    task_id: int | None,
    user_id: int,
    work_date: date,
    parsed_json: dict,
) -> None:
    status = str(parsed_json.get("status") or "").lower()
    blocker = parsed_json.get("blocker")

    if task_id and status in {"done", "DONE"}:
        await db.execute(text("""
            UPDATE tasks
            SET status = CAST('DONE' AS "TaskStatus"),
                end_at = COALESCE(end_at, :work_date),
                updated_at = NOW()
            WHERE id = :tid
        """), {"tid": task_id, "work_date": work_date})
    elif task_id and status in {"blocked", "BLOCKED"}:
        await db.execute(text("""
            UPDATE tasks
            SET status = CAST('IN_PROGRESS' AS "TaskStatus"),
                issues = COALESCE(:blocker, issues),
                updated_at = NOW()
            WHERE id = :tid
        """), {"tid": task_id, "blocker": blocker})
        if blocker:
            await db.execute(text("""
                INSERT INTO task_blockers (task_id, severity, description)
                VALUES (:tid, CAST('MED' AS "BlockerSeverity"), :description)
            """), {"tid": task_id, "description": blocker})
    elif task_id and status in {"in_progress", "IN_PROGRESS"}:
        await db.execute(text("""
            UPDATE tasks
            SET status = CASE
                    WHEN status = CAST('TODO' AS "TaskStatus") THEN CAST('IN_PROGRESS' AS "TaskStatus")
                    ELSE status
                END,
                updated_at = NOW()
            WHERE id = :tid
        """), {"tid": task_id})

    if task_id:
        await db.execute(text("""
            UPDATE tasks t
            SET total_hours = COALESCE((
                    SELECT SUM(w.hours)::double precision FROM worklogs w WHERE w.task_id = :tid
                ), 0),
                updated_at = NOW()
            WHERE t.id = :tid
        """), {"tid": task_id})

    await db.execute(text("""
        UPDATE projects p
        SET total_hours = COALESCE((
                SELECT SUM(w.hours)::double precision FROM worklogs w WHERE w.project_id = :pid
            ), 0),
            worklog_count = COALESCE((
                SELECT COUNT(*) FROM worklogs w WHERE w.project_id = :pid
            ), 0),
            updated_at = NOW()
        WHERE p.id = :pid
    """), {"pid": project_id})

    await db.commit()


# ── Admin / missing summary ───────────────────────────────────────────────────

async def get_admins(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(text("""
        SELECT u.id, u.full_name, g.gapo_thread_id
        FROM users u
        JOIN gapo_user_maps g ON g.user_id = u.id
        WHERE u.active = true
          AND (u.role::text = 'ADMIN' OR u.is_admin = true)
          AND g.gapo_thread_id IS NOT NULL
        LIMIT 10
    """))).fetchall()
    return [
        {"user_id": r[0], "full_name": r[1], "thread_id": str(r[2])}
        for r in rows
    ]


# ── Audit ─────────────────────────────────────────────────────────────────────

async def insert_audit(
    db: AsyncSession, *,
    tool: str,
    args: dict,
    result: dict | None = None,
    error: str | None = None,
    correlation_id: str | None = None,
) -> None:
    await db.execute(text("""
        INSERT INTO agent_audit_log
            (tool, args_json, result_json, error_message, source, correlation_id, created_at)
        VALUES
            (:tool, CAST(:args AS jsonb), CAST(:result AS jsonb), :error,
             CAST('other' AS "AgentAuditSource"), :corr, NOW())
    """), {
        "tool": tool,
        "args": json.dumps(args),
        "result": json.dumps(result) if result else None,
        "error": error,
        "corr": correlation_id,
    })
    await db.commit()
