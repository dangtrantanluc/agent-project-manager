import json
import re
from typing import Optional
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_agent_user, get_current_user, get_db, require_role, is_restricted
from app.modules.tasks.ai_import_service import (
    AiImportConfirmBody,
    confirm_ai_import,
    enrich_with_planning_agent,
    parse_ai_import_xlsx,
    serialize_workbook_context,
)
from app.modules.tasks.import_service import ImportConfirmBody, bulk_create_tasks, parse_xlsx

router = APIRouter(prefix="/projects", tags=["projects"])

_VALID_TRANSITIONS = {
    "PLANNED": {"PENDING", "IN_PROGRESS", "CANCELLED"},
    "PENDING": {"IN_PROGRESS", "CANCELLED"},
    "IN_PROGRESS": {"PENDING", "DONE", "CANCELLED"},
    "DONE": set(),
    "CANCELLED": set(),
}

_SELECT_PROJECT = """
    SELECT p.id, p.name, p.code, p.status, p.priority, p.start_date, p.end_date,
           p.description, p.total_hours,
           p.task_count, p.member_count, p.worklog_count, p.scope_count, p.milestone_count,
           p.owner_id, p.customer_name, p.account_manager_id, p.currency_id,
           p.created_at, p.updated_at,
           o.full_name AS owner_name, o.avatar_url AS owner_avatar,
           am.full_name AS account_manager_name,
           COALESCE((
               SELECT json_agg(json_build_object('id', tg.id, 'name', tg.name, 'color', tg.color)
                               ORDER BY tg.name)
               FROM project_tags pt JOIN tags tg ON tg.id = pt.tag_id
               WHERE pt.project_id = p.id
           ), '[]'::json) AS tags,
           p.gapo_thread_id
    FROM projects p
    LEFT JOIN users o ON o.id = p.owner_id
    LEFT JOIN users am ON am.id = p.account_manager_id
"""


async def _read_xlsx_upload(request: Request, file: UploadFile | None) -> tuple[str, bytes]:
    if file is not None:
        filename = file.filename or "upload.xlsx"
        return filename, await file.read()

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Thiếu file upload. Hãy gửi multipart/form-data field tên 'file'.")

    if body.startswith(b"PK"):
        return "upload.xlsx", body

    parsed = _extract_file_from_raw_multipart(body)
    if parsed is not None:
        return parsed

    content_type = request.headers.get("content-type", "")
    raise HTTPException(
        status_code=400,
        detail=(
            "Không đọc được file upload. Content-Type hiện tại: "
            f"{content_type or 'trống'}. Hãy gửi FormData với field 'file'."
        ),
    )


def _extract_file_from_raw_multipart(body: bytes) -> tuple[str, bytes] | None:
    boundary = body.split(b"\r\n", 1)[0]
    if not boundary.startswith(b"--"):
        return None

    for part in body.split(boundary):
        if b"Content-Disposition:" not in part or b"filename=" not in part:
            continue
        header_blob, separator, content = part.partition(b"\r\n\r\n")
        if not separator:
            continue
        headers = header_blob.decode("utf-8", errors="ignore")
        match = re.search(r'filename="([^"]+)"', headers)
        filename = match.group(1) if match else "upload.xlsx"
        content = content.rstrip(b"\r\n-")
        return filename, content
    return None


def _row_to_dict(r) -> dict:
    return {
        "id": r[0], "name": r[1], "code": r[2], "status": r[3], "priority": r[4],
        "startDate": r[5].isoformat() if r[5] else None,
        "endDate": r[6].isoformat() if r[6] else None,
        "description": r[7],
        "totalHours": r[8],
        "taskCount": r[9], "memberCount": r[10], "worklogCount": r[11],
        "scopeCount": r[12], "milestoneCount": r[13],
        "ownerId": r[14], "customerName": r[15],
        "accountManagerId": r[16], "currencyId": r[17],
        "createdAt": r[18].isoformat(), "updatedAt": r[19].isoformat(),
        # Owner / account-manager names are only present when the row comes from
        # _SELECT_PROJECT (which LEFT JOINs users). RETURNING rows from
        # create/update/transition are shorter — guard with len() so they don't
        # IndexError; those callers re-read via _SELECT_PROJECT to hydrate names.
        "owner": (
            {"id": r[14], "fullName": r[20], "avatarUrl": r[21]}
            if len(r) > 21 and r[20] else None
        ),
        "accountManager": (
            {"id": r[16], "fullName": r[22]}
            if len(r) > 22 and r[22] else None
        ),
        "tags": (
            (json.loads(r[23]) if isinstance(r[23], str) else (r[23] or []))
            if len(r) > 23 else []
        ),
        "gapoThreadId": r[24] if len(r) > 24 else None,
    }


# Vai trò được xem toàn bộ project. MEMBER/VIEWER chỉ thấy project họ tham gia.
_FULL_PROJECT_ACCESS_ROLES = {"ADMIN", "MANAGER"}

# Điều kiện "user tham gia project p": là member, owner, account manager,
# được assign task, hoặc đã điền worklog/backlog vào project (vd người ngoài
# vào support fix bug rồi log giờ). Dùng EXISTS để không nhân bản dòng.
_PROJECT_ACCESS_CLAUSE = """
    p.owner_id = :access_uid
    OR p.account_manager_id = :access_uid
    OR EXISTS (SELECT 1 FROM members m WHERE m.project_id = p.id AND m.user_id = :access_uid)
    OR EXISTS (SELECT 1 FROM tasks t WHERE t.project_id = p.id AND t.assignee_id = :access_uid)
    OR EXISTS (SELECT 1 FROM worklogs w WHERE w.project_id = p.id AND w.user_id = :access_uid)
    OR EXISTS (SELECT 1 FROM backlogs b WHERE b.project_id = p.id AND b.user_id = :access_uid)
"""


def _restricted(current_user: dict) -> bool:
    """True nếu user chỉ được thấy project mình tham gia (không phải ADMIN/MANAGER)."""
    return is_restricted(current_user)


@router.get("")
async def list_projects(
    status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    tag_id: Optional[int] = Query(default=None, alias="tagId"),
    page_size: int = Query(default=50, ge=1, le=500, alias="pageSize"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE TRUE"
    params: dict = {"limit": page_size}
    if _restricted(current_user):
        where += f" AND ({_PROJECT_ACCESS_CLAUSE})"
        params["access_uid"] = current_user["id"]
    if status:
        where += " AND p.status::text = :status"
        params["status"] = status
    if tag_id:
        where += " AND EXISTS (SELECT 1 FROM project_tags pt WHERE pt.project_id = p.id AND pt.tag_id = :tag_id)"
        params["tag_id"] = tag_id
    if q:
        where += " AND (p.name ILIKE :q OR p.code ILIKE :q)"
        params["q"] = f"%{q}%"

    rows = (await db.execute(
        text(f'{_SELECT_PROJECT} {where} ORDER BY p.updated_at DESC LIMIT :limit'),
        params,
    )).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.get("/digest")
async def projects_digest(
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        text("""
            SELECT p.id, p.name, p.status, p.total_hours,
                   COUNT(t.id) AS task_count,
                   COUNT(t.id) FILTER (WHERE t.status = 'DONE'::"TaskStatus") AS done_count,
                   COUNT(t.id) FILTER (
                       WHERE t.status <> 'DONE'::"TaskStatus" AND t.deadline < CURRENT_DATE
                   ) AS overdue_count
            FROM projects p
            LEFT JOIN tasks t ON t.project_id = p.id
            GROUP BY p.id
            ORDER BY p.updated_at DESC
            LIMIT 50
        """),
        {},
    )).fetchall()
    return {
        "projects": [
            {
                "id": r[0], "name": r[1], "status": r[2],
                "totalHours": r[3],
                "taskCount": r[4], "doneCount": r[5], "overdueTaskCount": r[6],
            }
            for r in rows
        ]
    }


@router.get("/weekly-report")
async def weekly_report(
    days: int = Query(default=7, ge=1, le=90),
    project_id: Optional[int] = Query(default=None, alias="projectId"),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE TRUE"
    params: dict = {"days": days}
    if project_id:
        where += " AND p.id = :pid"; params["pid"] = project_id
    rows = (await db.execute(
        text(f"""
            SELECT p.id, p.name,
                   COUNT(t.id) FILTER (WHERE t.status = 'DONE'::"TaskStatus"
                       AND t.updated_at >= NOW() - (:days * INTERVAL '1 day')) AS done_tasks,
                   COUNT(tb.id) FILTER (WHERE tb.created_at >= NOW() - (:days * INTERVAL '1 day')) AS blockers,
                   COALESCE(SUM(b.hours) FILTER (
                       WHERE b.status = 'APPROVED'::"BacklogStatus"
                         AND b.work_date >= CURRENT_DATE - (:days * INTERVAL '1 day')
                   ), 0) AS approved_hours
            FROM projects p
            LEFT JOIN tasks t ON t.project_id = p.id
            LEFT JOIN task_blockers tb ON tb.task_id = t.id
            LEFT JOIN backlogs b ON b.project_id = p.id
            {where}
            GROUP BY p.id
            ORDER BY p.name
        """),
        params,
    )).fetchall()
    return {
        "days": days,
        "projects": [
            {
                "id": r[0], "name": r[1], "doneTasks": r[2],
                "newBlockers": r[3], "approvedHours": float(r[4] or 0),
            }
            for r in rows
        ],
    }


@router.post("", status_code=201)
async def create_project(
    body: dict,
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("""
            INSERT INTO projects (
                name, code, status, priority, start_date, end_date, description,
                owner_id, customer_name, account_manager_id, currency_id, company_id, updated_at
            ) VALUES (
                :name, :code, COALESCE(:status, 'PLANNED')::"ProjectStatus",
                COALESCE(:priority, 'MEDIUM')::"Priority",
                :start_date, :end_date, :description,
                :owner_id, :customer_name, :account_manager_id, :currency_id, :company_id, NOW()
            )
            RETURNING id, name, code, status, priority, start_date, end_date,
                      description, total_hours,
                      task_count, member_count, worklog_count, scope_count, milestone_count,
                      owner_id, customer_name, account_manager_id, currency_id,
                      created_at, updated_at
        """),
        {
            "name": body.get("name"), "code": body.get("code"),
            "status": body.get("status"), "priority": body.get("priority"),
            "start_date": body.get("startDate"), "end_date": body.get("endDate"),
            "description": body.get("description"),
            "owner_id": body.get("ownerId", current_user["id"]),
            "customer_name": body.get("customerName"),
            "account_manager_id": body.get("accountManagerId"),
            "currency_id": body.get("currencyId"),
            "company_id": current_user.get("companyId"),
        },
    )).fetchone()
    await db.commit()
    return _row_to_dict(row)


@router.get("/{project_id}")
async def get_project(
    project_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE p.id = :pid"
    params: dict = {"pid": project_id}
    if _restricted(current_user):
        where += f" AND ({_PROJECT_ACCESS_CLAUSE})"
        params["access_uid"] = current_user["id"]
    row = (await db.execute(
        text(f'{_SELECT_PROJECT} {where}'),
        params,
    )).fetchone()
    if not row:
        # 404 (không 403) để không lộ sự tồn tại của project ngoài quyền.
        raise HTTPException(status_code=404, detail="Dự án không tồn tại")
    return _row_to_dict(row)


@router.patch("/{project_id}")
async def update_project(
    project_id: int,
    body: dict,
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        text("SELECT id FROM projects WHERE id = :pid"),
        {"pid": project_id},
    )).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Dự án không tồn tại")

    field_map = {
        "name": "name", "code": "code", "description": "description",
        "startDate": "start_date", "endDate": "end_date",
        "ownerId": "owner_id", "customerName": "customer_name",
        "accountManagerId": "account_manager_id", "currencyId": "currency_id",
        # Thread group Gapo để broadcast cảnh báo rủi ro / tin giao việc cho cả nhóm.
        "gapoThreadId": "gapo_thread_id",
    }
    sets, params = ["updated_at = NOW()"], {"pid": project_id}
    for js, col in field_map.items():
        if js in body:
            sets.append(f"{col} = :{js}")
            params[js] = body[js]
    if "priority" in body:
        sets.append('priority = CAST(:priority AS "Priority")')
        params["priority"] = body["priority"]
    if "status" in body:
        sets.append('status = CAST(:status AS "ProjectStatus")')
        params["status"] = body["status"]

    await db.execute(
        text(f"UPDATE projects SET {', '.join(sets)} WHERE id = :pid"),
        params,
    )
    await db.commit()
    # Re-read through _SELECT_PROJECT so the response includes owner / account
    # manager names (RETURNING can't JOIN users).
    row = (await db.execute(
        text(f'{_SELECT_PROJECT} WHERE p.id = :pid'),
        {"pid": project_id},
    )).fetchone()
    return _row_to_dict(row)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: int,
    current_user: dict = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text("DELETE FROM projects WHERE id = :pid"),
        {"pid": project_id},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Dự án không tồn tại")
    await db.commit()


@router.post("/{project_id}/transition")
async def transition_project(
    project_id: int,
    body: dict,
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("SELECT status FROM projects WHERE id = :pid"),
        {"pid": project_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Dự án không tồn tại")

    new_status = body.get("status", "")
    allowed = _VALID_TRANSITIONS.get(row[0], set())
    if new_status not in allowed:
        raise HTTPException(status_code=400, detail=f"Không thể chuyển từ {row[0]} sang {new_status}")

    await db.execute(
        text("""
            UPDATE projects SET status = CAST(:status AS "ProjectStatus"), updated_at = NOW()
            WHERE id = :pid
        """),
        {"pid": project_id, "status": new_status},
    )
    await db.commit()
    updated = (await db.execute(
        text(f'{_SELECT_PROJECT} WHERE p.id = :pid'),
        {"pid": project_id},
    )).fetchone()
    return _row_to_dict(updated)


@router.get("/{project_id}/weekly-report")
async def project_weekly_report(
    project_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("SELECT id, name FROM projects WHERE id = :pid"),
        {"pid": project_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Dự án không tồn tại")

    tasks = (await db.execute(
        text("""
            SELECT id, name, status, priority, deadline, assignee_id
            FROM tasks WHERE project_id = :pid
            ORDER BY status, deadline NULLS LAST
        """),
        {"pid": project_id},
    )).fetchall()

    weekly_hours = (await db.execute(
        text("""
            SELECT COALESCE(SUM(hours), 0)
            FROM worklogs WHERE project_id = :pid
              AND work_date >= date_trunc('week', CURRENT_DATE)
        """),
        {"pid": project_id},
    )).scalar()

    return {
        "projectId": project_id,
        "projectName": row[1],
        "tasks": [
            {
                "id": t[0], "name": t[1], "status": t[2], "priority": t[3],
                "deadline": t[4].isoformat() if t[4] else None, "assigneeId": t[5],
            }
            for t in tasks
        ],
        "weeklyHours": float(weekly_hours or 0),
    }


# ── Agent endpoints ────────────────────────────────────────────────────────────

@router.get("/{project_id}/digest")
async def project_digest(
    project_id: int,
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("SELECT id, name, status, total_hours, task_count FROM projects WHERE id = :pid"),
        {"pid": project_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Dự án không tồn tại")

    overdue = (await db.execute(
        text("""
            SELECT COUNT(*) FROM tasks
            WHERE project_id = :pid AND status <> 'DONE'::"TaskStatus"
              AND deadline < CURRENT_DATE
        """),
        {"pid": project_id},
    )).scalar()

    return {
        "id": row[0], "name": row[1], "status": row[2],
        "totalHours": row[3], "taskCount": row[4],
        "overdueTaskCount": overdue,
    }


@router.get("/weekly-reports")
async def all_weekly_reports(
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        text("""
            SELECT p.id, p.name, p.status,
                   COUNT(t.id) FILTER (WHERE t.status = 'DONE'::"TaskStatus") AS done_this_week
            FROM projects p
            LEFT JOIN tasks t ON t.project_id = p.id AND t.updated_at >= date_trunc('week', NOW())
            WHERE p.status = 'IN_PROGRESS'::"ProjectStatus"
            GROUP BY p.id
            ORDER BY p.name
        """)
    )).fetchall()
    return [
        {"id": r[0], "name": r[1], "status": r[2], "doneThisWeek": r[3]}
        for r in rows
    ]


# ── Excel import ───────────────────────────────────────────────────────────────

@router.post("/{project_id}/import-tasks/preview", tags=["tasks"])
async def import_tasks_preview(
    project_id: int,
    request: Request,
    file: UploadFile | None = File(default=None),
    sheet: Optional[str] = Query(default=None),
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("SELECT id FROM projects WHERE id = :pid"),
        {"pid": project_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project không tồn tại")

    filename, content = await _read_xlsx_upload(request, file)
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ file .xlsx")

    try:
        result = parse_xlsx(content, sheet_name=sheet, filename=filename)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result.model_dump()


@router.post("/{project_id}/import-tasks/confirm", status_code=201, tags=["tasks"])
async def import_tasks_confirm(
    project_id: int,
    body: ImportConfirmBody,
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("SELECT id FROM projects WHERE id = :pid"),
        {"pid": project_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project không tồn tại")

    result = await bulk_create_tasks(
        project_id=project_id,
        rows=body.rows,
        user_id=current_user["id"],
        db=db,
    )
    return result


@router.post("/{project_id}/ai-import/preview", tags=["tasks"])
async def ai_import_preview(
    project_id: int,
    request: Request,
    file: UploadFile | None = File(default=None),
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("SELECT id FROM projects WHERE id = :pid"),
        {"pid": project_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project không tồn tại")

    filename, content = await _read_xlsx_upload(request, file)
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="V1 chỉ hỗ trợ file .xlsx")

    try:
        preview = parse_ai_import_xlsx(content, filename=filename)
        workbook_context = serialize_workbook_context(content)
        preview = await enrich_with_planning_agent(preview, workbook_context)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    return preview.model_dump()


@router.post("/{project_id}/ai-import/confirm", status_code=201, tags=["tasks"])
async def ai_import_confirm(
    project_id: int,
    body: AiImportConfirmBody,
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("SELECT id FROM projects WHERE id = :pid"),
        {"pid": project_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project không tồn tại")

    result = await confirm_ai_import(project_id=project_id, body=body, db=db)
    return result
