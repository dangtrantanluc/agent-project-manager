from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_agent_user, get_current_user, get_db, require_role, is_restricted, project_access_exists_sql

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _parse_date(value: object) -> Optional[date]:
    """Chuyển chuỗi ISO ('YYYY-MM-DD' hoặc datetime đầy đủ) thành date object.
    asyncpg yêu cầu bind date object cho cột DATE, không nhận chuỗi (DataError).
    Trả None cho giá trị rỗng để clear cột."""
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()

_VALID_TRANSITIONS = {
    "TODO": {"IN_PROGRESS", "CANCELLED"},
    "IN_PROGRESS": {"DONE", "TODO", "CANCELLED"},
    "DONE": {"IN_PROGRESS"},
    "CANCELLED": set(),
}

def _normalize_task_status(raw: object) -> str:
    status = str(raw or "").strip().upper()
    if status in {"PLAN", "PLANNED"}:
        return "TODO"
    if status in {"REVIEW", "IN_REVIEW"}:
        return "DONE"
    return status

_SELECT_TASK = """
    SELECT t.id, t.name, t.status, t.priority, t.deadline, t.end_at,
           t.description, t.result, t.issues,
           t.total_hours,
           t.project_id, t.assignee_id, t.milestone_id, t.currency_id,
           t.created_at, t.updated_at,
           u.full_name AS assignee_full_name, u.avatar_url AS assignee_avatar_url,
           m.name AS milestone_name
    FROM tasks t
    LEFT JOIN users u ON u.id = t.assignee_id
    LEFT JOIN milestones m ON m.id = t.milestone_id
"""


def _is_privileged(current_user: dict) -> bool:
    return current_user.get("role") in ("MANAGER", "ADMIN") or current_user.get("isSuperAdmin")


async def _ensure_can_modify_task(db: AsyncSession, current_user: dict, assignee_id) -> None:
    """MANAGER/ADMIN sửa được mọi task; MEMBER/VIEWER chỉ sửa task được assign cho mình."""
    if _is_privileged(current_user):
        return
    if assignee_id is not None and assignee_id == current_user["id"]:
        return
    raise HTTPException(status_code=403, detail="Không có quyền thao tác task này")


def _row_to_dict(r) -> dict:
    return {
        "id": r[0], "name": r[1], "status": r[2], "priority": r[3],
        "deadline": r[4].isoformat() if r[4] else None,
        "endAt": r[5].isoformat() if r[5] else None,
        "description": r[6], "result": r[7], "issues": r[8],
        "totalHours": r[9],
        "projectId": r[10], "assigneeId": r[11],
        "milestoneId": r[12], "currencyId": r[13],
        "createdAt": r[14].isoformat(), "updatedAt": r[15].isoformat(),
        # assignee nested object is only present on rows from _SELECT_TASK
        # (which LEFT JOINs users). RETURNING-based rows omit it.
        "assignee": (
            {"id": r[11], "fullName": r[16], "avatarUrl": r[17]}
            if len(r) > 16 and r[11] is not None else None
        ),
        "milestone": (
            {"id": r[12], "name": r[18]}
            if len(r) > 18 and r[12] is not None else None
        ),
    }


async def _fetch_task_dict(task_id: int, db: AsyncSession) -> dict:
    """Re-fetch a task via _SELECT_TASK so the response includes the nested
    assignee object (RETURNING rows from INSERT/UPDATE don't join users)."""
    row = (await db.execute(
        text(f"{_SELECT_TASK} WHERE t.id = :tid"), {"tid": task_id},
    )).fetchone()
    return _row_to_dict(row)


async def _recompute_milestone(milestone_id: int, db: AsyncSession):
    await db.execute(
        text("""
            UPDATE milestones SET
                done_count = (
                    SELECT COUNT(*) FROM tasks
                    WHERE milestone_id = :mid AND status = 'DONE'::"TaskStatus"
                ),
                completion_pct = (
                    SELECT CASE WHEN COUNT(*) = 0 THEN 0
                    ELSE ROUND(COUNT(*) FILTER (WHERE status = 'DONE'::"TaskStatus") * 100.0 / COUNT(*))
                    END FROM tasks WHERE milestone_id = :mid
                ),
                updated_at = NOW()
            WHERE id = :mid
        """),
        {"mid": milestone_id},
    )


@router.get("")
async def list_tasks(
    project_id: Optional[int] = Query(default=None, alias="projectId"),
    status: Optional[str] = Query(default=None),
    assignee_id: Optional[int] = Query(default=None, alias="assigneeId"),
    milestone_id: Optional[int] = Query(default=None, alias="milestoneId"),
    q: Optional[str] = Query(default=None),
    page_size: int = Query(default=100, ge=1, le=500, alias="pageSize"),
    sort: Optional[str] = Query(default=None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE TRUE"
    params: dict = {}
    # MEMBER/VIEWER chỉ thấy task thuộc project mình tham gia.
    if is_restricted(current_user):
        where += f" AND {project_access_exists_sql('t.project_id')}"
        params["access_uid"] = current_user["id"]
    if project_id:
        where += " AND t.project_id = :pid"; params["pid"] = project_id
    if status:
        status = _normalize_task_status(status)
        where += ' AND t.status = CAST(:status AS "TaskStatus")'; params["status"] = status
    if assignee_id:
        where += " AND t.assignee_id = :aid"; params["aid"] = assignee_id
    if milestone_id:
        where += " AND t.milestone_id = :mid"; params["mid"] = milestone_id
    if q:
        where += " AND t.name ILIKE :q"; params["q"] = f"%{q}%"

    order_by = "t.deadline NULLS LAST, t.priority DESC"
    if sort == "updatedAt:desc":
        order_by = "t.updated_at DESC"
    elif sort == "updatedAt:asc":
        order_by = "t.updated_at ASC"
    params["limit"] = page_size
    rows = (await db.execute(
        text(f"{_SELECT_TASK} {where} ORDER BY {order_by} LIMIT :limit"),
        params,
    )).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.post("", status_code=201)
@router.post("/by-project/{project_id}", status_code=201)
async def create_task(
    body: dict,
    project_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _is_privileged(current_user):
        raise HTTPException(status_code=403, detail="Chỉ quản lý mới được tạo task")

    target_project_id = project_id or body["projectId"]
    project_row = (await db.execute(
        text("SELECT company_id FROM projects WHERE id = :pid"),
        {"pid": target_project_id},
    )).fetchone()
    if not project_row:
        raise HTTPException(status_code=404, detail="Project không tồn tại")

    row = (await db.execute(
        text("""
            INSERT INTO tasks (
                name, status, priority, deadline, end_at, description,
                project_id, assignee_id, milestone_id, currency_id, company_id, updated_at
            ) VALUES (
                :name, COALESCE(:status, 'TODO')::"TaskStatus",
                COALESCE(:priority, 'MEDIUM')::"Priority",
                :deadline, :end_at, :description,
                :project_id, :assignee_id, :milestone_id, :currency_id, :company_id, NOW()
            )
            RETURNING id, name, status, priority, deadline, end_at,
                      description, result, issues, total_hours,
                      project_id, assignee_id, milestone_id, currency_id,
                      created_at, updated_at
        """),
        {
            "name": body["name"], "status": _normalize_task_status(body.get("status")) if body.get("status") else None, "priority": body.get("priority"),
            "deadline": _parse_date(body.get("deadline")), "end_at": _parse_date(body.get("endAt")),
            "description": body.get("description"),
            "project_id": target_project_id,
            "assignee_id": body.get("assigneeId"),
            "milestone_id": body.get("milestoneId"),
            "currency_id": body.get("currencyId"),
            "company_id": project_row[0],
        },
    )).fetchone()

    if row[12]:  # milestone_id
        await _recompute_milestone(row[12], db)
        await db.execute(
            text("UPDATE milestones SET task_count = task_count + 1 WHERE id = :mid"),
            {"mid": row[12]},
        )

    await db.commit()
    return await _fetch_task_dict(row[0], db)


@router.get("/overdue")
async def overdue_tasks(
    project_id: Optional[int] = Query(default=None, alias="projectId"),
    days: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE t.deadline < CURRENT_DATE AND t.status <> 'DONE'::\"TaskStatus\""
    params: dict = {"limit": limit}
    if project_id:
        where += " AND t.project_id = :pid"; params["pid"] = project_id
    if days:
        where += " AND t.deadline >= CURRENT_DATE - (:days * INTERVAL '1 day')"; params["days"] = days

    rows = (await db.execute(
        text(f"{_SELECT_TASK} {where} ORDER BY t.deadline LIMIT :limit"),
        params,
    )).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.get("/stale")
async def stale_tasks(
    project_id: Optional[int] = Query(default=None, alias="projectId"),
    days_since_update: int = Query(default=7, alias="daysSinceUpdate"),
    limit: int = Query(default=50, ge=1, le=500),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE t.status NOT IN ('DONE'::\"TaskStatus\") AND t.updated_at < NOW() - INTERVAL '1 day' * :days"
    params: dict = {"days": days_since_update, "limit": limit}
    if project_id:
        where += " AND t.project_id = :pid"; params["pid"] = project_id

    rows = (await db.execute(
        text(f"{_SELECT_TASK} {where} ORDER BY t.updated_at LIMIT :limit"),
        params,
    )).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.get("/hygiene")
async def tasks_hygiene(
    project_id: Optional[int] = Query(default=None, alias="projectId"),
    stale_days: int = Query(default=14, alias="staleDays"),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    params: dict = {"stale_days": stale_days}
    base = "WHERE t.status <> 'DONE'::\"TaskStatus\""
    if project_id:
        base += " AND t.project_id = :pid"; params["pid"] = project_id

    no_assignee = (await db.execute(
        text(f"SELECT COUNT(*) FROM tasks t {base} AND t.assignee_id IS NULL"), params
    )).scalar()
    no_deadline = (await db.execute(
        text(f"SELECT COUNT(*) FROM tasks t {base} AND t.deadline IS NULL"), params
    )).scalar()
    overdue = (await db.execute(
        text(f"SELECT COUNT(*) FROM tasks t {base} AND t.deadline < CURRENT_DATE"), params
    )).scalar()
    stale = (await db.execute(
        text(f"SELECT COUNT(*) FROM tasks t {base} AND t.updated_at < NOW() - INTERVAL '1 day' * :stale_days"), params
    )).scalar()

    return {"noAssignee": no_assignee, "noDeadline": no_deadline, "overdue": overdue, "stale": stale}


@router.get("/{task_id}")
async def get_task(
    task_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE t.id = :tid"
    params: dict = {"tid": task_id}
    if is_restricted(current_user):
        where += f" AND {project_access_exists_sql('t.project_id')}"
        params["access_uid"] = current_user["id"]
    row = (await db.execute(
        text(f"{_SELECT_TASK} {where}"),
        params,
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task không tồn tại")
    return _row_to_dict(row)


@router.patch("/{task_id}")
async def update_task(
    task_id: int,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        text("SELECT id, milestone_id, assignee_id FROM tasks WHERE id = :tid"),
        {"tid": task_id},
    )).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Task không tồn tại")
    await _ensure_can_modify_task(db, current_user, existing[2])
    # MEMBER không được tự đổi người phụ trách (assignee) — chỉ MANAGER/ADMIN.
    if "assigneeId" in body and not _is_privileged(current_user):
        raise HTTPException(status_code=403, detail="Không có quyền đổi người phụ trách")

    field_map = {
        "name": "name", "description": "description", "result": "result", "issues": "issues",
        "deadline": "deadline", "endAt": "end_at",
        "assigneeId": "assignee_id", "milestoneId": "milestone_id", "currencyId": "currency_id",
    }
    _date_fields = {"deadline", "endAt"}
    sets, params = ["updated_at = NOW()"], {"tid": task_id}
    for js, col in field_map.items():
        if js in body:
            sets.append(f"{col} = :{js}")
            params[js] = _parse_date(body[js]) if js in _date_fields else body[js]
    if "status" in body:
        sets.append('status = CAST(:status AS "TaskStatus")'); params["status"] = _normalize_task_status(body["status"])
    if "priority" in body:
        sets.append('priority = CAST(:priority AS "Priority")'); params["priority"] = body["priority"]

    row = (await db.execute(
        text(f"""
            UPDATE tasks SET {', '.join(sets)} WHERE id = :tid
            RETURNING id, name, status, priority, deadline, end_at,
                      description, result, issues, total_hours,
                      project_id, assignee_id, milestone_id, currency_id,
                      created_at, updated_at
        """),
        params,
    )).fetchone()

    if row[12]:
        await _recompute_milestone(row[12], db)

    await db.commit()
    return await _fetch_task_dict(row[0], db)


@router.delete("/{task_id}", status_code=204)
async def delete_task(
    task_id: int,
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("SELECT milestone_id FROM tasks WHERE id = :tid"),
        {"tid": task_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task không tồn tại")

    await db.execute(text("DELETE FROM tasks WHERE id = :tid"), {"tid": task_id})

    if row[0]:
        await db.execute(
            text("UPDATE milestones SET task_count = GREATEST(task_count - 1, 0) WHERE id = :mid"),
            {"mid": row[0]},
        )
        await _recompute_milestone(row[0], db)

    await db.commit()


@router.post("/{task_id}/transition")
async def transition_task(
    task_id: int,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("SELECT status, milestone_id, assignee_id FROM tasks WHERE id = :tid"),
        {"tid": task_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task không tồn tại")
    await _ensure_can_modify_task(db, current_user, row[2])

    new_status = _normalize_task_status(body.get("status", ""))
    allowed = _VALID_TRANSITIONS.get(row[0], set())
    if new_status not in allowed:
        raise HTTPException(status_code=400, detail=f"Không thể chuyển từ {row[0]} sang {new_status}")

    updated = (await db.execute(
        text("""
            UPDATE tasks SET status = CAST(:status AS "TaskStatus"), updated_at = NOW()
            WHERE id = :tid
            RETURNING id, name, status, priority, deadline, end_at,
                      description, result, issues, total_hours,
                      project_id, assignee_id, milestone_id, currency_id,
                      created_at, updated_at
        """),
        {"tid": task_id, "status": new_status},
    )).fetchone()

    if row[1]:
        await _recompute_milestone(row[1], db)

    await db.commit()
    return await _fetch_task_dict(updated[0], db)


@router.get("/{task_id}/blockers")
async def list_blockers(
    task_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        text("""
            SELECT b.id, b.task_id, b.severity, b.description, b.resolved_at, b.created_at
            FROM task_blockers b
            JOIN tasks t ON t.id = b.task_id
            WHERE b.task_id = :tid
            ORDER BY b.created_at DESC
        """),
        {"tid": task_id},
    )).fetchall()
    return [
        {
            "id": r[0], "taskId": r[1], "severity": r[2], "description": r[3],
            "resolvedAt": r[4].isoformat() if r[4] else None,
            "createdAt": r[5].isoformat(),
        }
        for r in rows
    ]


@router.post("/{task_id}/blockers", status_code=201)
@router.post("/{task_id}/blocker", status_code=201)
async def create_blocker(
    task_id: int,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = (await db.execute(
        text("SELECT id, assignee_id FROM tasks WHERE id = :tid"),
        {"tid": task_id},
    )).fetchone()
    if not task:
        raise HTTPException(status_code=404, detail="Task không tồn tại")
    await _ensure_can_modify_task(db, current_user, task[1])

    row = (await db.execute(
        text("""
            INSERT INTO task_blockers (task_id, severity, description)
            VALUES (:tid, COALESCE(:severity, 'MED')::"BlockerSeverity", :desc)
            RETURNING id, task_id, severity, description, resolved_at, created_at
        """),
        {"tid": task_id, "severity": body.get("severity"), "desc": body["description"]},
    )).fetchone()
    await db.commit()
    return {
        "id": row[0], "taskId": row[1], "severity": row[2], "description": row[3],
        "resolvedAt": row[4], "createdAt": row[5].isoformat(),
    }


# ── Agent endpoints ────────────────────────────────────────────────────────────

@router.get("/overdue")
async def overdue_tasks(
    project_id: Optional[int] = Query(default=None, alias="projectId"),
    days: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE t.deadline < CURRENT_DATE AND t.status <> 'DONE'::\"TaskStatus\""
    params: dict = {"limit": limit}
    if project_id:
        where += " AND t.project_id = :pid"; params["pid"] = project_id
    if days:
        where += " AND t.deadline >= CURRENT_DATE - (:days * INTERVAL '1 day')"; params["days"] = days

    rows = (await db.execute(
        text(f"{_SELECT_TASK} {where} ORDER BY t.deadline LIMIT :limit"),
        params,
    )).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.get("/stale")
async def stale_tasks(
    project_id: Optional[int] = Query(default=None, alias="projectId"),
    days_since_update: int = Query(default=7, alias="daysSinceUpdate"),
    limit: int = Query(default=50, ge=1, le=500),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE t.status NOT IN ('DONE'::\"TaskStatus\") AND t.updated_at < NOW() - INTERVAL '1 day' * :days"
    params: dict = {"days": days_since_update, "limit": limit}
    if project_id:
        where += " AND t.project_id = :pid"; params["pid"] = project_id

    rows = (await db.execute(
        text(f"{_SELECT_TASK} {where} ORDER BY t.updated_at LIMIT :limit"),
        params,
    )).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.get("/hygiene")
async def tasks_hygiene(
    project_id: Optional[int] = Query(default=None, alias="projectId"),
    stale_days: int = Query(default=14, alias="staleDays"),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    params: dict = {"stale_days": stale_days}
    base = "WHERE t.status <> 'DONE'::\"TaskStatus\""
    if project_id:
        base += " AND t.project_id = :pid"; params["pid"] = project_id

    no_assignee = (await db.execute(
        text(f"SELECT COUNT(*) FROM tasks t {base} AND t.assignee_id IS NULL"), params
    )).scalar()
    no_deadline = (await db.execute(
        text(f"SELECT COUNT(*) FROM tasks t {base} AND t.deadline IS NULL"), params
    )).scalar()
    overdue = (await db.execute(
        text(f"SELECT COUNT(*) FROM tasks t {base} AND t.deadline < CURRENT_DATE"), params
    )).scalar()
    stale = (await db.execute(
        text(f"SELECT COUNT(*) FROM tasks t {base} AND t.updated_at < NOW() - INTERVAL '1 day' * :stale_days"), params
    )).scalar()

    return {"noAssignee": no_assignee, "noDeadline": no_deadline, "overdue": overdue, "stale": stale}
