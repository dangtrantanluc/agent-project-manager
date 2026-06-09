import json
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_agent_user, get_db
from ai_agent.checkin import repository as checkin_repo
from ai_agent.router.message_router import AgentMessageRouter
from ai_agent.text_to_sql.text2sql import Text2SQLAgent

router = APIRouter(prefix="/agent", tags=["agent"])
_message_router: AgentMessageRouter | None = None
_sql_agent: Text2SQLAgent | None = None

def _get_message_router() -> AgentMessageRouter:
    global _message_router
    if _message_router is None:
        _message_router = AgentMessageRouter()
    return _message_router

def _get_sql_agent() -> Text2SQLAgent:
    global _sql_agent
    if _sql_agent is None:
        _sql_agent = Text2SQLAgent()
    return _sql_agent

def _iso(value):
    return value.isoformat() if value else None

def _json(value, default):
    return json.dumps(value if value is not None else default)

def _session_row(r) -> dict:
    return {
        "id": r[0], "userId": r[1], "gapoUserId": r[2], "threadId": r[3],
        "currentProjectId": r[4], "currentTaskId": r[5], "state": r[6],
        "expiresAt": _iso(r[7]), "lastMessageId": r[8], "pendingText": r[9],
        "pendingParsed": r[10], "completedAt": _iso(r[11]),
        "createdAt": _iso(r[12]), "updatedAt": _iso(r[13]),
    }

def _backlog_row(r) -> dict:
    return {
        "id": r[0], "status": r[1], "source": r[2], "workDate": _iso(r[3]),
        "description": r[4], "hours": float(r[5] or 0), "taskId": r[6],
        "projectId": r[7], "userId": r[8],
        "project": {"id": r[7], "name": r[9]} if r[7] else None,
        "task": {"id": r[6], "name": r[10]} if r[6] else None,
        "user": {"id": r[8], "fullName": r[11]} if r[8] else None,
        "createdAt": _iso(r[12]), "updatedAt": _iso(r[13]),
    }

def _worklog_checkin_row(r) -> dict:
    source = r[12] or "worklog"
    return {
        "id": r[0], "status": "APPROVED", "source": source, "workDate": _iso(r[1]),
        "description": r[2], "hours": float(r[3] or 0), "taskId": r[4],
        "projectId": r[5], "userId": r[6],
        "project": {"id": r[5], "name": r[7]} if r[5] else None,
        "task": {"id": r[4], "name": r[8]} if r[4] else None,
        "user": {"id": r[6], "fullName": r[9]} if r[6] else None,
        "createdAt": _iso(r[10]), "updatedAt": _iso(r[11]),
    }

async def _fetch_backlog(db: AsyncSession, backlog_id: int) -> dict:
    row = (await db.execute(
        text("""
            SELECT b.id, b.status, b.source, b.work_date, b.description, b.hours,
                   b.task_id, b.project_id, b.user_id,
                   p.name, t.name, u.full_name, b.created_at, b.updated_at
            FROM backlogs b
            LEFT JOIN projects p ON p.id = b.project_id
            LEFT JOIN tasks t ON t.id = b.task_id
            LEFT JOIN users u ON u.id = b.user_id
            WHERE b.id = :id
        """),
        {"id": backlog_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Backlog không tồn tại")
    return _backlog_row(row)

async def _fetch_checkin_worklog(db: AsyncSession, worklog_id: int) -> dict:
    row = (await db.execute(
        text("""
            SELECT w.id, w.work_date, w.description, w.hours,
                   w.task_id, w.project_id, w.user_id,
                   p.name, t.name, u.full_name, w.created_at, w.updated_at, w.source
            FROM worklogs w
            LEFT JOIN projects p ON p.id = w.project_id
            LEFT JOIN tasks t ON t.id = w.task_id
            LEFT JOIN users u ON u.id = w.user_id
            WHERE w.id = :id
        """),
        {"id": worklog_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Worklog không tồn tại")
    return _worklog_checkin_row(row)

@router.get("/user-by-channel")
async def user_by_channel(
    channel: str,
    external_id: str = Query(alias="externalId"),
    thread_id: Optional[str] = Query(default=None, alias="threadId"),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("""
            SELECT u.id, u.email, u.full_name, u.role, c.name AS company_name, u.is_admin,
                   ci.external_id, ci.thread_id, ci.external_name
            FROM channel_identities ci
            JOIN users u ON u.id = ci.user_id
            LEFT JOIN companies c ON c.id = u.company_id
            WHERE ci.channel = CAST(:channel AS "ChannelKind")
              AND ci.external_id = :external_id
              AND (CAST(:thread_id AS text) IS NULL OR ci.thread_id = CAST(:thread_id AS text) OR ci.thread_id IS NULL)
            ORDER BY ci.preferred DESC, ci.last_seen_at DESC
            LIMIT 1
        """),
        {"channel": channel, "external_id": external_id, "thread_id": thread_id},
    )).fetchone()
    if not row and channel == "gapo":
        row = (await db.execute(
            text("""
                SELECT u.id, u.email, u.full_name, u.role, c.name AS company_name, u.is_admin,
                       gum.gapo_user_id::text, gum.gapo_thread_id::text, gum.gapo_full_name
                FROM gapo_user_maps gum
                JOIN users u ON u.id = gum.user_id
                LEFT JOIN companies c ON c.id = u.company_id
                WHERE gum.gapo_user_id::text = :external_id
                LIMIT 1
            """),
            {"external_id": external_id},
        )).fetchone()
    if not row:
        return None
    return {
        "user": {
            "id": row[0], "email": row[1], "fullName": row[2], "role": row[3],
            "companyName": row[4], "isSuperAdmin": row[5],
            "externalId": row[6], "threadId": row[7], "externalName": row[8],
        }
    }

@router.get("/gapo-thread/{user_id}")
async def gapo_thread(
    user_id: int,
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("""
            SELECT ci.external_id, ci.thread_id, ci.external_name
            FROM channel_identities ci
            JOIN users u ON u.id = ci.user_id
            WHERE ci.user_id = :uid AND ci.channel = 'gapo'::"ChannelKind"
            ORDER BY ci.preferred DESC, ci.last_seen_at DESC
            LIMIT 1
        """),
        {"uid": user_id},
    )).fetchone()
    if not row:
        row = (await db.execute(
            text("""
                SELECT gum.gapo_user_id::text, gum.gapo_thread_id::text, gum.gapo_full_name
                FROM gapo_user_maps gum JOIN users u ON u.id = gum.user_id
                WHERE gum.user_id = :uid LIMIT 1
            """),
            {"uid": user_id},
        )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Gapo mapping không tồn tại")
    return {"gapoUserId": row[0], "gapoThreadId": row[1], "externalName": row[2]}

@router.get("/channel-identity/{user_id}")
async def list_channel_identity(
    user_id: int,
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        text("""
            SELECT ci.id, ci.user_id, ci.channel, ci.external_id, ci.external_name,
                   ci.thread_id, ci.preferred, ci.last_seen_at, ci.created_at, ci.updated_at
            FROM channel_identities ci JOIN users u ON u.id = ci.user_id
            WHERE ci.user_id = :uid
            ORDER BY ci.channel, ci.preferred DESC
        """),
        {"uid": user_id},
    )).fetchall()
    return [
        {
            "id": r[0], "userId": r[1], "channel": r[2], "externalId": r[3],
            "externalName": r[4], "threadId": r[5], "preferred": r[6],
            "lastSeenAt": _iso(r[7]), "createdAt": _iso(r[8]), "updatedAt": _iso(r[9]),
        }
        for r in rows
    ]

@router.post("/channel-identity")
async def upsert_channel_identity(
    body: dict,
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = body["userId"]
    user = (await db.execute(
        text("SELECT id FROM users WHERE id = :uid"),
        {"uid": user_id},
    )).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User không tồn tại")
    row = (await db.execute(
        text("""
            INSERT INTO channel_identities (
                user_id, channel, external_id, external_name, thread_id, preferred,
                last_seen_at, updated_at
            ) VALUES (
                :user_id, CAST(:channel AS "ChannelKind"), :external_id, :external_name,
                :thread_id, COALESCE(:preferred, false), NOW(), NOW()
            )
            ON CONFLICT (channel, external_id) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                external_name = EXCLUDED.external_name,
                thread_id = EXCLUDED.thread_id,
                preferred = EXCLUDED.preferred,
                last_seen_at = NOW(),
                updated_at = NOW()
            RETURNING id
        """),
        {
            "user_id": user_id, "channel": body.get("channel", "gapo"),
            "external_id": str(body["externalId"]), "external_name": body.get("externalName"),
            "thread_id": body.get("threadId"), "preferred": body.get("preferred"),
        },
    )).fetchone()
    await db.commit()
    return {"id": row[0]}

@router.post("/checkins/import", status_code=201)
async def import_checkin(
    body: dict,
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    project = (await db.execute(
        text("SELECT id FROM projects WHERE id = :pid"),
        {"pid": body["projectId"]},
    )).fetchone()
    if not project:
        raise HTTPException(status_code=404, detail="Dự án không tồn tại")
    has_company_id = await checkin_repo._has_column(db, "worklogs", "company_id")
    company_col = "company_id, " if has_company_id else ""
    company_val = (
        "COALESCE((SELECT company_id FROM projects WHERE id = :project_id), "
        "(SELECT id FROM companies ORDER BY id LIMIT 1)), "
        if has_company_id else ""
    )
    row = (await db.execute(
        text("""
            INSERT INTO worklogs (
                source, work_date, description, hours, task_id, project_id,
                {company_col}user_id, updated_at
            ) VALUES (
                'MANUAL_CHECKIN', :work_date, :description, :hours,
                :task_id, :project_id, {company_val}:user_id, NOW()
            )
            RETURNING id
        """.format(company_col=company_col, company_val=company_val)),
        {
            "work_date": body["workDate"], "description": body.get("description"),
            "hours": body["hours"], "task_id": body.get("taskId"),
            "project_id": body["projectId"], "user_id": body["userId"],
        },
    )).fetchone()
    await db.commit()
    await checkin_repo.apply_worklog_side_effects(
        db,
        project_id=body["projectId"],
        task_id=body.get("taskId"),
        user_id=body["userId"],
        work_date=date.fromisoformat(body["workDate"]),
        parsed_json={},
    )
    return await _fetch_checkin_worklog(db, row[0])

@router.patch("/checkins/{backlog_id}")
async def update_checkin(
    backlog_id: int,
    body: dict,
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    field_map = {"workDate": "work_date", "description": "description", "hours": "hours", "taskId": "task_id"}
    sets, params = ["updated_at = NOW()"], {"id": backlog_id}
    for js, col in field_map.items():
        if js in body:
            sets.append(f"{col} = :{js}")
            params[js] = body[js]
    await db.execute(
        text(f"UPDATE worklogs SET {', '.join(sets)} WHERE id = :id"),
        params,
    )
    await db.commit()
    updated = await _fetch_checkin_worklog(db, backlog_id)
    await checkin_repo.apply_worklog_side_effects(
        db,
        project_id=updated["projectId"],
        task_id=updated["taskId"],
        user_id=updated["userId"],
        work_date=date.fromisoformat(updated["workDate"]),
        parsed_json={},
    )
    return await _fetch_checkin_worklog(db, backlog_id)

@router.get("/checkins/projects")
async def checkin_projects(
    user_id: int = Query(alias="userId"),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        text("""
            SELECT DISTINCT p.id, p.name, p.status
            FROM projects p
            LEFT JOIN members m ON m.project_id = p.id
            LEFT JOIN tasks t ON t.project_id = p.id
            WHERE (p.owner_id = :uid OR m.user_id = :uid OR t.assignee_id = :uid)
              AND p.status IN ('PLANNED'::"ProjectStatus", 'IN_PROGRESS'::"ProjectStatus")
            ORDER BY p.name
            LIMIT 15
        """),
        {"uid": user_id},
    )).fetchall()
    return [{"id": r[0], "name": r[1], "status": r[2]} for r in rows]

@router.get("/checkins/status")
async def checkin_status(
    date_: Optional[str] = Query(default=None, alias="date"),
    project_id: Optional[int] = Query(default=None, alias="projectId"),
    user_id: Optional[int] = Query(default=None, alias="userId"),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE TRUE"
    params = {}
    if date_:
        where += " AND w.work_date = :work_date"; params["work_date"] = date_
    if project_id:
        where += " AND w.project_id = :pid"; params["pid"] = project_id
    if user_id:
        where += " AND w.user_id = :uid"; params["uid"] = user_id
    rows = (await db.execute(
        text(f"""
            SELECT w.id, w.work_date, w.description, w.hours,
                   w.task_id, w.project_id, w.user_id,
                   p.name, t.name, u.full_name, w.created_at, w.updated_at, w.source
            FROM worklogs w
            LEFT JOIN projects p ON p.id = w.project_id
            LEFT JOIN tasks t ON t.id = w.task_id
            LEFT JOIN users u ON u.id = w.user_id
            {where}
            ORDER BY w.work_date DESC, w.id DESC
        """),
        params,
    )).fetchall()
    return [_worklog_checkin_row(r) for r in rows]

@router.get("/checkins/missing")
async def missing_checkins(
    date_: Optional[str] = Query(default=None, alias="date"),
    project_id: Optional[int] = Query(default=None, alias="projectId"),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    target_date = date_ or date.today().isoformat()
    params = {"work_date": target_date}
    project_filter = ""
    if project_id:
        project_filter = "AND EXISTS (SELECT 1 FROM members m WHERE m.user_id = u.id AND m.project_id = :pid)"
        params["pid"] = project_id
    rows = (await db.execute(
        text(f"""
            SELECT u.id, u.full_name, gm.gapo_user_id::text, gm.gapo_thread_id::text,
                   cs.id AS active_session
            FROM users u
            LEFT JOIN gapo_user_maps gm ON gm.user_id = u.id
            LEFT JOIN checkin_sessions cs ON cs.user_id = u.id
                 AND cs.state <> 'COMPLETED'::"CheckinState" AND cs.expires_at > NOW()
            WHERE u.active = true
              {project_filter}
              AND NOT EXISTS (
                  SELECT 1 FROM worklogs w
                  WHERE w.user_id = u.id AND w.work_date = :work_date
              )
            ORDER BY u.full_name
        """),
        params,
    )).fetchall()
    return [
        {
            "id": r[0], "fullName": r[1], "gapoUserId": r[2],
            "gapoThreadId": r[3], "activeSession": {"id": r[4]} if r[4] else None,
        }
        for r in rows
    ]

@router.get("/checkins/project-daily-summary")
async def project_daily_summary(
    project_id: int = Query(alias="projectId"),
    date_: Optional[str] = Query(default=None, alias="date"),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    target_date = date_ or date.today().isoformat()
    rows = (await db.execute(
        text("""
            SELECT u.full_name, w.description, w.hours, w.source
            FROM worklogs w JOIN users u ON u.id = w.user_id
            WHERE w.project_id = :pid AND w.work_date = :work_date
            ORDER BY u.full_name
        """),
        {"pid": project_id, "work_date": target_date},
    )).fetchall()
    return {
        "projectId": project_id, "date": target_date,
        "totalHours": float(sum(r[2] or 0 for r in rows)),
        "items": [{"userFullName": r[0], "description": r[1], "hours": float(r[2] or 0), "status": r[3]} for r in rows],
    }

@router.post("/checkin-sessions/start", status_code=201)
async def start_checkin_session(
    body: dict,
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        text("DELETE FROM checkin_sessions WHERE user_id = :uid"),
        {"uid": body["userId"]},
    )
    has_company_id = await checkin_repo._has_column(db, "checkin_sessions", "company_id")
    company_col = "company_id, " if has_company_id else ""
    company_val = (
        "COALESCE((SELECT company_id FROM users WHERE id = :user_id), "
        "(SELECT id FROM companies ORDER BY id LIMIT 1)), "
        if has_company_id else ""
    )
    row = (await db.execute(
        text("""
            INSERT INTO checkin_sessions (
                user_id, {company_col}gapo_user_id, thread_id, work_date, slot, state, expires_at,
                last_message_id, updated_at
            ) VALUES (
                :user_id, {company_val}:gapo_user_id, :thread_id, :work_date, :slot, 'AWAITING_PROJECT'::"CheckinState",
                :expires_at, :last_message_id, NOW()
            )
            RETURNING id, user_id, gapo_user_id, thread_id, current_project_id,
                      current_task_id, state, expires_at, last_message_id,
                      pending_text, pending_parsed, completed_at, created_at, updated_at
        """.format(company_col=company_col, company_val=company_val)),
        {
            "user_id": body["userId"], "gapo_user_id": body["gapoUserId"],
            "thread_id": body["threadId"], "expires_at": body["expiresAt"],
            "work_date": body.get("workDate") or date.today().isoformat(),
            "slot": body.get("slot") or "manual",
            "last_message_id": body.get("lastMessageId"),
        },
    )).fetchone()
    await db.commit()
    return _session_row(row)

@router.get("/checkin-sessions/current")
async def current_checkin_session(
    user_id: int = Query(alias="userId"),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("""
            SELECT id, user_id, gapo_user_id, thread_id, current_project_id,
                   current_task_id, state, expires_at, last_message_id,
                   pending_text, pending_parsed, completed_at, created_at, updated_at
            FROM checkin_sessions
            WHERE user_id = :uid
            ORDER BY updated_at DESC
            LIMIT 1
        """),
        {"uid": user_id},
    )).fetchone()
    return _session_row(row) if row else None

@router.patch("/checkin-sessions/{session_id}")
async def patch_checkin_session(
    session_id: int,
    body: dict,
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    field_map = {
        "currentProjectId": "current_project_id", "currentTaskId": "current_task_id",
        "expiresAt": "expires_at", "lastMessageId": "last_message_id",
        "pendingText": "pending_text",
    }
    sets, params = ["updated_at = NOW()"], {"id": session_id}
    for js, col in field_map.items():
        if js in body:
            sets.append(f"{col} = :{js}")
            params[js] = body[js]
    if "state" in body:
        sets.append('state = CAST(:state AS "CheckinState")')
        params["state"] = body["state"]
    if "pendingParsed" in body:
        sets.append("pending_parsed = CAST(:pendingParsed AS jsonb)")
        params["pendingParsed"] = _json(body.get("pendingParsed"), {})
    row = (await db.execute(
        text(f"""
            UPDATE checkin_sessions SET {', '.join(sets)}
            WHERE id = :id
            RETURNING id, user_id, gapo_user_id, thread_id, current_project_id,
                      current_task_id, state, expires_at, last_message_id,
                      pending_text, pending_parsed, completed_at, created_at, updated_at
        """),
        params,
    )).fetchone()
    await db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Session không tồn tại")
    return _session_row(row)

@router.post("/checkin-sessions/{session_id}/complete")
async def complete_checkin_session(
    session_id: int,
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("""
            UPDATE checkin_sessions
            SET state = 'COMPLETED'::"CheckinState", completed_at = NOW(), updated_at = NOW()
            WHERE id = :id
            RETURNING id, user_id, gapo_user_id, thread_id, current_project_id,
                      current_task_id, state, expires_at, last_message_id,
                      pending_text, pending_parsed, completed_at, created_at, updated_at
        """),
        {"id": session_id},
    )).fetchone()
    await db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Session không tồn tại")
    return _session_row(row)

@router.post("/memory", status_code=201)
async def post_memory(
    body: dict,
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("""
            INSERT INTO agent_memory (
                conversation_id, source, user_text, reply_text,
                summary, tools_used, project_ids, task_ids, correlation_id
            ) VALUES (
                :conversation_id, CAST(:source AS "AgentAuditSource"),
                :user_text, :reply_text, :summary, CAST(:tools_used AS jsonb),
                :project_ids, :task_ids, :correlation_id
            )
            RETURNING id, created_at
        """),
        {
            "conversation_id": body.get("conversationId"),
            "source": body.get("source", "chat"), "user_text": body.get("userText", ""),
            "reply_text": body.get("replyText", ""), "summary": body.get("summary", "")[:4000],
            "tools_used": _json(body.get("toolsUsed"), []),
            "project_ids": body.get("projectIds"), "task_ids": body.get("taskIds"),
            "correlation_id": body.get("correlationId"),
        },
    )).fetchone()
    await db.commit()
    return {"id": row[0], "createdAt": _iso(row[1])}

@router.get("/memory/search")
async def search_memory(
    q: Optional[str] = None,
    project_id: Optional[int] = Query(default=None, alias="projectId"),
    task_id: Optional[int] = Query(default=None, alias="taskId"),
    conversation_id: Optional[str] = Query(default=None, alias="conversationId"),
    days_back: Optional[int] = Query(default=None, alias="daysBack"),
    limit: int = Query(default=10, ge=1, le=50),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE TRUE"
    params = {"limit": limit}
    if q:
        where += " AND (summary ILIKE :q OR user_text ILIKE :q)"; params["q"] = f"%{q}%"
    if project_id:
        where += " AND :project_id = ANY(project_ids)"; params["project_id"] = project_id
    if task_id:
        where += " AND :task_id = ANY(task_ids)"; params["task_id"] = task_id
    if conversation_id:
        where += " AND conversation_id = :conversation_id"; params["conversation_id"] = conversation_id
    if days_back:
        where += " AND created_at >= :cutoff"; params["cutoff"] = datetime.now(timezone.utc) - timedelta(days=days_back)
    rows = (await db.execute(
        text(f"""
            SELECT id, conversation_id, source, user_text, reply_text, summary,
                   tools_used, project_ids, task_ids, correlation_id, created_at
            FROM agent_memory {where}
            ORDER BY created_at DESC LIMIT :limit
        """),
        params,
    )).fetchall()
    return [
        {
            "id": r[0], "conversationId": r[1], "source": r[2], "userText": r[3],
            "replyText": r[4], "summary": r[5], "toolsUsed": r[6],
            "projectIds": r[7], "taskIds": r[8], "correlationId": r[9],
            "createdAt": _iso(r[10]),
        }
        for r in rows
    ]

@router.post("/follow-up", status_code=201)
async def post_follow_up(body: dict, agent_user: dict = Depends(get_agent_user), db: AsyncSession = Depends(get_db)):
    row = (await db.execute(
        text("""
            INSERT INTO agent_follow_ups (
                task_id, user_id, channel, thread_id, question, status,
                correlation_id, updated_at
            ) VALUES (
                :task_id, :user_id, CAST(:channel AS "ChannelKind"), :thread_id,
                :question, COALESCE(:status, 'PENDING')::"FollowUpStatus",
                :correlation_id, NOW()
            )
            RETURNING id
        """),
        {
            "task_id": body["taskId"], "user_id": body["userId"],
            "channel": body.get("channel", "gapo"), "thread_id": body.get("threadId"),
            "question": body["question"], "status": body.get("status"),
            "correlation_id": body.get("correlationId"),
        },
    )).fetchone()
    await db.commit()
    return {"id": row[0]}

@router.get("/follow-ups")
async def list_follow_ups(
    user_id: Optional[int] = Query(default=None, alias="userId"),
    task_id: Optional[int] = Query(default=None, alias="taskId"),
    status: Optional[str] = None,
    days_back: Optional[int] = Query(default=None, alias="daysBack"),
    limit: int = Query(default=50, ge=1, le=200),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE TRUE"
    params = {"limit": limit}
    if user_id:
        where += " AND f.user_id = :uid"; params["uid"] = user_id
    if task_id:
        where += " AND f.task_id = :tid"; params["tid"] = task_id
    if status:
        where += ' AND f.status = CAST(:status AS "FollowUpStatus")'; params["status"] = status
    if days_back:
        where += " AND f.created_at >= :cutoff"; params["cutoff"] = datetime.now(timezone.utc) - timedelta(days=days_back)
    rows = (await db.execute(
        text(f"""
            SELECT f.id, f.task_id, f.user_id, f.channel, f.thread_id, f.question,
                   f.status, f.asked_at, f.replied_at, f.reply_text, f.correlation_id
            FROM agent_follow_ups f JOIN users u ON u.id = f.user_id
            {where} ORDER BY f.created_at DESC LIMIT :limit
        """),
        params,
    )).fetchall()
    return [
        {
            "id": r[0], "taskId": r[1], "userId": r[2], "channel": r[3],
            "threadId": r[4], "question": r[5], "status": r[6],
            "askedAt": _iso(r[7]), "repliedAt": _iso(r[8]), "replyText": r[9],
            "correlationId": r[10],
        }
        for r in rows
    ]

@router.patch("/follow-up/{follow_up_id}")
async def patch_follow_up(
    follow_up_id: int,
    body: dict,
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("""
            UPDATE agent_follow_ups f
            SET status = CAST(:status AS "FollowUpStatus"),
                reply_text = :reply_text,
                replied_at = CASE WHEN :status = 'REPLIED' THEN NOW() ELSE replied_at END,
                updated_at = NOW()
            FROM users u
            WHERE f.id = :id AND u.id = f.user_id
            RETURNING f.id
        """),
        {"id": follow_up_id, "status": body["status"], "reply_text": body.get("replyText")},
    )).fetchone()
    await db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Follow-up không tồn tại")
    return {"id": row[0]}

@router.get("/users")
async def agent_users(agent_user: dict = Depends(get_agent_user), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        text("""
            SELECT u.id, u.email, u.full_name, u.role, u.avatar_url, c.name AS company_name,
                   u.department, u.position
            FROM users u
            LEFT JOIN companies c ON c.id = u.company_id
            WHERE u.active = true ORDER BY u.full_name
        """),
        {},
    )).fetchall()
    return [{"id": r[0], "email": r[1], "fullName": r[2], "role": r[3], "avatarUrl": r[4], "companyName": r[5], "department": r[6], "position": r[7]} for r in rows]

@router.get("/users-workload")
async def users_workload(
    department: Optional[str] = None,
    role: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE u.active = true"
    params = {"limit": limit}
    if department:
        where += " AND u.department ILIKE :department"; params["department"] = f"%{department}%"
    if role:
        where += ' AND u.role = CAST(:role AS "Role")'; params["role"] = role
    rows = (await db.execute(
        text(f"""
            SELECT u.id, u.full_name, u.role, COUNT(t.id) FILTER (WHERE t.status <> 'DONE'::"TaskStatus") AS open_tasks
            FROM users u LEFT JOIN tasks t ON t.assignee_id = u.id
            {where}
            GROUP BY u.id ORDER BY open_tasks DESC, u.full_name LIMIT :limit
        """),
        params,
    )).fetchall()
    return [{"id": r[0], "fullName": r[1], "role": r[2], "openTasks": r[3]} for r in rows]

@router.get("/digests/role-based")
async def role_based_digest(
    user_id: int = Query(alias="userId"),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    user = (await db.execute(
        text("SELECT id, full_name, role FROM users WHERE id = :uid"),
        {"uid": user_id},
    )).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User không tồn tại")
    stats = (await db.execute(
        text("""
            SELECT COUNT(*) FILTER (WHERE status <> 'DONE'::"TaskStatus"),
                   COUNT(*) FILTER (WHERE status <> 'DONE'::"TaskStatus" AND deadline < CURRENT_DATE),
                   (
                       SELECT COUNT(*) FROM task_blockers tb
                       JOIN tasks bt ON bt.id = tb.task_id
                       WHERE bt.assignee_id = :uid
                         AND tb.resolved_at IS NULL
                   )
            FROM tasks WHERE assignee_id = :uid
        """),
        {"uid": user_id},
    )).fetchone()
    return {
        "recipient": {"id": user[0], "fullName": user[1], "role": user[2]},
        "overview": {"openTasks": stats[0] or 0, "overdueTasks": stats[1] or 0, "blockedTasks": stats[2] or 0},
    }

@router.get("/report/schema")
async def report_schema(agent_user: dict = Depends(get_agent_user)):
    return {
        "schema": (
            "Tables: projects(id,name,status,owner_id,start_date,end_date,total_hours), "
            "tasks(id,name,status,priority,deadline,project_id,assignee_id,updated_at), "
            "users(id,full_name,email,role,department,position), "
            "members(project_id,user_id,role), backlogs(id,status,work_date,description,hours,task_id,project_id,user_id), "
            "agent_memory(conversation_id,summary,user_text,reply_text,created_at). "
            "The app is single-company; do not add company_id filters."
        )
    }

@router.post("/report/query")
async def report_query(body: dict, agent_user: dict = Depends(get_agent_user), db: AsyncSession = Depends(get_db)):
    sql = str(body.get("sql") or "").strip()
    # Dùng chung lớp an toàn của Text2SQLAgent (strip comment, chặn mutation,
    # multi-statement, placeholder chưa bind, và cột/hàm nhạy cảm như password_hash).
    # is_safe_sql yêu cầu kết thúc bằng ';' nên thêm vào nếu thiếu.
    agent = _get_sql_agent()
    sql_checked = sql if sql.rstrip().endswith(";") else sql + ";"
    if not agent.is_safe_sql(sql_checked):
        raise HTTPException(
            status_code=400,
            detail="Chỉ cho phép một câu SELECT an toàn (không mutation, không cột nhạy cảm).",
        )
    # Chạy qua pool read-only của agent (DB_AGENT_USER) thay vì session superuser,
    # để DB từ chối mọi thao tác ghi / cột bị thu hồi ngay cả khi regex bị qua mặt.
    data = await agent.execute_sql(agent._clean_sql(sql_checked))
    return {"rows": data, "rowCount": len(data)}

@router.post("/audit", status_code=201)
async def post_audit(body: dict, agent_user: dict = Depends(get_agent_user), db: AsyncSession = Depends(get_db)):
    row = (await db.execute(
        text("""
            INSERT INTO agent_audit_log (
                tool, args_json, result_json, error_message, duration_ms,
                correlation_id, source
            ) VALUES (
                :tool, CAST(:args_json AS jsonb), CAST(:result_json AS jsonb),
                :error_message, :duration_ms, :correlation_id,
                CAST(:source AS "AgentAuditSource")
            )
            RETURNING id, created_at
        """),
        {
            "tool": body["tool"], "args_json": _json(body.get("argsJson"), {}),
            "result_json": _json(body.get("resultJson"), None),
            "error_message": body.get("errorMessage"), "duration_ms": body.get("durationMs"),
            "correlation_id": body.get("correlationId"), "source": body.get("source", "chat"),
        },
    )).fetchone()
    await db.commit()
    return {"id": row[0], "createdAt": _iso(row[1])}

@router.post("/audit/cleanup")
async def cleanup_audit(body: dict, agent_user: dict = Depends(get_agent_user), db: AsyncSession = Depends(get_db)):
    days = int(body.get("days", 90))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    count = (await db.execute(
        text("SELECT COUNT(*) FROM agent_audit_log WHERE created_at < :cutoff"),
        {"cutoff": cutoff},
    )).scalar()
    if not body.get("dryRun"):
        await db.execute(text("DELETE FROM agent_audit_log WHERE created_at < :cutoff"), {"cutoff": cutoff})
        await db.commit()
    return {"deleted": 0 if body.get("dryRun") else count, "matched": count, "dryRun": bool(body.get("dryRun"))}

@router.get("/automations")
async def list_automations(
    active: Optional[bool] = None,
    owner_id: Optional[int] = Query(default=None, alias="ownerId"),
    limit: int = Query(default=200, ge=1, le=500),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE TRUE"
    params = {"limit": limit}
    if active is not None:
        where += " AND active = :active"; params["active"] = active
    if owner_id:
        where += " AND owner_id = :owner_id"; params["owner_id"] = owner_id
    rows = (await db.execute(
        text(f"""
            SELECT id, name, workflow, schedule, inputs, target, active, owner_id,
                   last_run_at, last_run_status, last_run_error, consecutive_fails
            FROM automations {where} ORDER BY id DESC LIMIT :limit
        """),
        params,
    )).fetchall()
    return [
        {
            "id": r[0], "name": r[1], "workflow": r[2], "schedule": r[3],
            "inputs": r[4], "target": r[5], "active": r[6], "ownerId": r[7],
            "lastRunAt": _iso(r[8]), "lastRunStatus": r[9],
            "lastRunError": r[10], "consecutiveFails": r[11],
        }
        for r in rows
    ]

@router.post("/automations", status_code=201)
async def create_automation(body: dict, agent_user: dict = Depends(get_agent_user), db: AsyncSession = Depends(get_db)):
    row = (await db.execute(
        text("""
            INSERT INTO automations (
                name, workflow, schedule, inputs, target, active, owner_id, updated_at
            ) VALUES (
                :name, :workflow, :schedule, CAST(:inputs AS jsonb), :target,
                COALESCE(:active, true), :owner_id, NOW()
            )
            RETURNING id
        """),
        {
            "name": body["name"], "workflow": body["workflow"], "schedule": body["schedule"],
            "inputs": _json(body.get("inputs"), {}), "target": body.get("target"),
            "active": body.get("active"), "owner_id": body.get("ownerId", agent_user["id"]),
        },
    )).fetchone()
    await db.commit()
    return {"id": row[0]}

@router.patch("/automations/{automation_id}")
async def patch_automation(automation_id: int, body: dict, agent_user: dict = Depends(get_agent_user), db: AsyncSession = Depends(get_db)):
    field_map = {"name": "name", "workflow": "workflow", "schedule": "schedule", "target": "target", "active": "active"}
    sets, params = ["updated_at = NOW()"], {"id": automation_id}
    for js, col in field_map.items():
        if js in body:
            sets.append(f"{col} = :{js}"); params[js] = body[js]
    if "inputs" in body:
        sets.append("inputs = CAST(:inputs AS jsonb)"); params["inputs"] = _json(body.get("inputs"), {})
    row = (await db.execute(
        text(f"UPDATE automations SET {', '.join(sets)} WHERE id = :id RETURNING id"),
        params,
    )).fetchone()
    await db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Automation không tồn tại")
    return {"id": row[0]}

@router.delete("/automations/{automation_id}", status_code=204)
async def delete_automation(automation_id: int, agent_user: dict = Depends(get_agent_user), db: AsyncSession = Depends(get_db)):
    await db.execute(
        text("DELETE FROM automations WHERE id = :id"),
        {"id": automation_id},
    )
    await db.commit()
