from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, is_restricted, project_access_exists_sql
from app.core.code_gen import next_worklog_code

router = APIRouter(prefix="/worklogs", tags=["worklogs"])

_SELECT = """
    SELECT w.id, w.work_date, w.hours, w.description,
           w.task_id, w.project_id, w.user_id,
           w.created_at, w.updated_at,
           t.name  AS task_name,
           p.name  AS project_name,
           u.full_name AS user_full_name
    FROM worklogs w
    LEFT JOIN tasks   t ON t.id = w.task_id
    LEFT JOIN projects p ON p.id = w.project_id
    LEFT JOIN users   u ON u.id = w.user_id
"""


def _parse_date(value):
    """asyncpg binds DATE columns from `date` objects, not strings."""
    if isinstance(value, date) or value is None:
        return value
    return date.fromisoformat(str(value)[:10])


def _row(r) -> dict:
    return {
        "id": r[0],
        "workDate": r[1].isoformat() if r[1] else None,
        "hours": float(r[2]),
        "description": r[3],
        "taskId": r[4],
        "projectId": r[5],
        "userId": r[6],
        "createdAt": r[7].isoformat() if r[7] else None,
        "updatedAt": r[8].isoformat() if r[8] else None,
        "task": {"id": r[4], "name": r[9]} if r[4] is not None else None,
        "project": {"id": r[5], "name": r[10]},
        "user": {"id": r[6], "fullName": r[11]},
    }


@router.get("")
async def list_worklogs(
    project_id: Optional[int] = Query(default=None, alias="projectId"),
    task_id: Optional[int] = Query(default=None, alias="taskId"),
    user_id: Optional[int] = Query(default=None, alias="userId"),
    work_date_from: Optional[str] = Query(default=None, alias="workDateFrom"),
    work_date_to: Optional[str] = Query(default=None, alias="workDateTo"),
    mine: Optional[bool] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE TRUE"
    params: dict = {}

    # MEMBER/VIEWER chỉ thấy worklog thuộc project mình tham gia (hoặc của chính mình).
    if is_restricted(current_user):
        where += f" AND (w.user_id = :access_uid OR {project_access_exists_sql('w.project_id')})"
        params["access_uid"] = current_user["id"]

    if mine:
        where += " AND w.user_id = :uid"
        params["uid"] = current_user["id"]
    elif user_id:
        where += " AND w.user_id = :uid"
        params["uid"] = user_id

    if project_id:
        where += " AND w.project_id = :pid"
        params["pid"] = project_id

    if task_id:
        where += " AND w.task_id = :tid"
        params["tid"] = task_id

    if work_date_from:
        where += " AND w.work_date >= :df"
        params["df"] = work_date_from

    if work_date_to:
        where += " AND w.work_date <= :dt"
        params["dt"] = work_date_to

    params["skip"] = skip
    params["limit"] = limit

    rows = (await db.execute(
        text(f"{_SELECT} {where} ORDER BY w.work_date DESC, w.id DESC LIMIT :limit OFFSET :skip"),
        params,
    )).fetchall()
    return [_row(r) for r in rows]


@router.post("", status_code=201)
async def create_worklog(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not body.get("workDate"):
        raise HTTPException(status_code=422, detail="workDate là bắt buộc")
    if body.get("hours") is None:
        raise HTTPException(status_code=422, detail="hours là bắt buộc")
    if not body.get("projectId"):
        raise HTTPException(status_code=422, detail="projectId là bắt buộc")

    # Verify project exists; worklog inherits the project's company.
    proj = (await db.execute(
        text("SELECT id, company_id FROM projects WHERE id = :pid"),
        {"pid": body["projectId"]},
    )).fetchone()
    if not proj:
        raise HTTPException(status_code=404, detail="Dự án không tồn tại")

    # Chỉ MANAGER/ADMIN mới được log giờ thay cho người khác; còn lại ép về chính mình.
    is_privileged = current_user.get("role") in ("MANAGER", "ADMIN") or current_user.get("isSuperAdmin")
    target_user_id = body.get("userId") or current_user["id"]
    if target_user_id != current_user["id"] and not is_privileged:
        raise HTTPException(status_code=403, detail="Không có quyền tạo worklog cho người khác")

    seq, code = await next_worklog_code(body["projectId"], db)
    row = (await db.execute(
        text("""
            INSERT INTO worklogs (
                work_date, description, hours, task_id, project_id,
                user_id, company_id, seq, code, updated_at
            ) VALUES (
                :work_date, :description, :hours, :task_id, :project_id,
                :user_id, :company_id, :seq, :code, NOW()
            )
            RETURNING id, work_date, hours, description,
                      task_id, project_id, user_id,
                      created_at, updated_at
        """),
        {
            "work_date": _parse_date(body["workDate"]),
            "description": body.get("description"),
            "hours": body["hours"],
            "task_id": body.get("taskId"),
            "project_id": body["projectId"],
            "user_id": target_user_id,
            "company_id": proj[1],
            "seq": seq, "code": code,
        },
    )).fetchone()
    await db.commit()

    # Reload with joins for full response shape
    full = (await db.execute(
        text(f"{_SELECT} WHERE w.id = :wid"),
        {"wid": row[0]},
    )).fetchone()
    return _row(full)


@router.patch("/{worklog_id}")
async def update_worklog(
    worklog_id: int,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        text("SELECT id, user_id FROM worklogs WHERE id = :wid"),
        {"wid": worklog_id},
    )).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Worklog không tồn tại")

    is_admin = current_user.get("role") in ("MANAGER", "ADMIN") or current_user.get("isSuperAdmin")
    if existing[1] != current_user["id"] and not is_admin:
        raise HTTPException(status_code=403, detail="Không có quyền sửa worklog này")

    field_map = {
        "workDate": "work_date",
        "description": "description",
        "hours": "hours",
        "taskId": "task_id",
    }
    sets, params = ["updated_at = NOW()"], {"wid": worklog_id}
    for js, col in field_map.items():
        if js in body:
            sets.append(f"{col} = :{js}")
            params[js] = _parse_date(body[js]) if js == "workDate" else body[js]

    if len(sets) == 1:
        # Nothing to update, return current record
        full = (await db.execute(
            text(f"{_SELECT} WHERE w.id = :wid"),
            {"wid": worklog_id},
        )).fetchone()
        return _row(full)

    await db.execute(
        text(f"UPDATE worklogs SET {', '.join(sets)} WHERE id = :wid"),
        params,
    )
    await db.commit()

    full = (await db.execute(
        text(f"{_SELECT} WHERE w.id = :wid"),
        {"wid": worklog_id},
    )).fetchone()
    return _row(full)


@router.delete("/{worklog_id}", status_code=204)
async def delete_worklog(
    worklog_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        text("SELECT id, user_id FROM worklogs WHERE id = :wid"),
        {"wid": worklog_id},
    )).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Worklog không tồn tại")

    is_admin = current_user.get("role") in ("MANAGER", "ADMIN") or current_user.get("isSuperAdmin")
    if existing[1] != current_user["id"] and not is_admin:
        raise HTTPException(status_code=403, detail="Không có quyền xóa worklog này")

    await db.execute(text("DELETE FROM worklogs WHERE id = :wid"), {"wid": worklog_id})
    await db.commit()
