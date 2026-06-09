from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_role, is_restricted, project_access_exists_sql

router = APIRouter(prefix="/backlogs", tags=["backlogs"])

_SELECT = """
    SELECT b.id, b.status, b.source, b.work_date, b.description, b.hours,
           b.task_id, b.project_id, b.user_id, b.currency_id,
           b.approver_id, b.approved_at, b.rejected_reason,
           b.created_at, b.updated_at
    FROM backlogs b
"""


def _row(r) -> dict:
    return {
        "id": r[0], "status": r[1], "source": r[2],
        "workDate": r[3].isoformat() if r[3] else None,
        "description": r[4], "hours": float(r[5]),
        "taskId": r[6], "projectId": r[7],
        "userId": r[8], "currencyId": r[9],
        "approverId": r[10],
        "approvedAt": r[11].isoformat() if r[11] else None,
        "rejectedReason": r[12],
        "createdAt": r[13].isoformat(), "updatedAt": r[14].isoformat(),
    }


async def _recompute_totals(project_id: int, task_id: Optional[int], db: AsyncSession):
    await db.execute(
        text("""
            UPDATE projects SET
                total_hours = (
                    SELECT COALESCE(SUM(hours), 0) FROM backlogs
                    WHERE project_id = :pid AND status = 'APPROVED'::"BacklogStatus"
                ),
                updated_at = NOW()
            WHERE id = :pid
        """),
        {"pid": project_id},
    )
    if task_id:
        await db.execute(
            text("""
                UPDATE tasks SET
                    total_hours = (
                        SELECT COALESCE(SUM(hours), 0) FROM backlogs
                        WHERE task_id = :tid AND status = 'APPROVED'::"BacklogStatus"
                    ),
                    updated_at = NOW()
                WHERE id = :tid
            """),
            {"tid": task_id},
        )


@router.get("")
async def list_backlogs(
    project_id: Optional[int] = Query(default=None),
    task_id: Optional[int] = Query(default=None),
    user_id: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None, alias="workDateFrom"),
    date_to: Optional[str] = Query(default=None, alias="workDateTo"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE TRUE"
    params: dict = {}
    # MEMBER/VIEWER chỉ thấy backlog thuộc project mình tham gia (hoặc của chính mình).
    if is_restricted(current_user):
        where += f" AND (b.user_id = :access_uid OR {project_access_exists_sql('b.project_id')})"
        params["access_uid"] = current_user["id"]
    if project_id:
        where += " AND b.project_id = :pid"; params["pid"] = project_id
    if task_id:
        where += " AND b.task_id = :tid"; params["tid"] = task_id
    if user_id:
        where += " AND b.user_id = :uid"; params["uid"] = user_id
    if status:
        where += ' AND b.status = CAST(:status AS "BacklogStatus")'; params["status"] = status
    if date_from:
        where += " AND b.work_date >= :df"; params["df"] = date_from
    if date_to:
        where += " AND b.work_date <= :dt"; params["dt"] = date_to

    rows = (await db.execute(
        text(f"{_SELECT} {where} ORDER BY b.work_date DESC"),
        params,
    )).fetchall()
    data = [_row(r) for r in rows]
    return {"data": data, "meta": {"page": 1, "pageSize": len(data), "total": len(data)}}


@router.post("", status_code=201)
@router.post("/by-project/{project_id}", status_code=201)
async def create_backlog(
    body: dict,
    project_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target_project_id = project_id or body["projectId"]

    # Chỉ MANAGER/ADMIN mới được tạo backlog thay cho người khác; còn lại ép về chính mình.
    is_privileged = current_user.get("role") in ("MANAGER", "ADMIN") or current_user.get("isSuperAdmin")
    target_user_id = body.get("userId") or current_user["id"]
    if target_user_id != current_user["id"] and not is_privileged:
        raise HTTPException(status_code=403, detail="Không có quyền tạo backlog cho người khác")

    row = (await db.execute(
        text("""
            INSERT INTO backlogs (
                work_date, description, hours, task_id, project_id,
                user_id, currency_id, updated_at
            ) VALUES (
                :work_date, :description, :hours, :task_id, :project_id,
                :user_id, :currency_id, NOW()
            )
            RETURNING id, status, source, work_date, description, hours,
                      task_id, project_id, user_id, currency_id,
                      approver_id, approved_at, rejected_reason, created_at, updated_at
        """),
        {
            "work_date": body["workDate"], "description": body.get("description"),
            "hours": body["hours"], "task_id": body.get("taskId"),
            "project_id": target_project_id,
            "user_id": body.get("userId", current_user["id"]),
            "currency_id": body.get("currencyId"),
        },
    )).fetchone()
    await db.commit()
    return {"data": _row(row)}


@router.post("/by-task/{task_id}", status_code=201)
async def create_task_backlog(
    task_id: int,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = (await db.execute(
        text("SELECT project_id FROM tasks WHERE id = :tid"),
        {"tid": task_id},
    )).fetchone()
    if not task:
        raise HTTPException(status_code=404, detail="Task không tồn tại")
    body = {**body, "taskId": task_id, "projectId": task[0]}
    return await create_backlog(body=body, project_id=task[0], current_user=current_user, db=db)


@router.patch("/{backlog_id}")
async def update_backlog(
    backlog_id: int,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        text("SELECT id, status, project_id, task_id, user_id FROM backlogs WHERE id = :bid"),
        {"bid": backlog_id},
    )).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Backlog không tồn tại")
    is_privileged = current_user.get("role") in ("MANAGER", "ADMIN") or current_user.get("isSuperAdmin")
    if existing[4] != current_user["id"] and not is_privileged:
        raise HTTPException(status_code=403, detail="Không có quyền sửa backlog này")
    if existing[1] == "APPROVED":
        raise HTTPException(status_code=400, detail="Không thể sửa backlog đã duyệt")

    field_map = {"workDate": "work_date", "description": "description",
                 "hours": "hours", "taskId": "task_id", "currencyId": "currency_id"}
    sets, params = ["updated_at = NOW()"], {"bid": backlog_id}
    for js, col in field_map.items():
        if js in body:
            sets.append(f"{col} = :{js}"); params[js] = body[js]

    row = (await db.execute(
        text(f"""
            UPDATE backlogs SET {', '.join(sets)} WHERE id = :bid
            RETURNING id, status, source, work_date, description, hours,
                      task_id, project_id, user_id, currency_id,
                      approver_id, approved_at, rejected_reason, created_at, updated_at
        """),
        params,
    )).fetchone()
    await db.commit()
    return {"data": _row(row)}


@router.delete("/{backlog_id}", status_code=204)
async def delete_backlog(
    backlog_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        text("SELECT project_id, task_id, status, user_id FROM backlogs WHERE id = :bid"),
        {"bid": backlog_id},
    )).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Backlog không tồn tại")
    is_privileged = current_user.get("role") in ("MANAGER", "ADMIN") or current_user.get("isSuperAdmin")
    if existing[3] != current_user["id"] and not is_privileged:
        raise HTTPException(status_code=403, detail="Không có quyền xóa backlog này")

    await db.execute(text("DELETE FROM backlogs WHERE id = :bid"), {"bid": backlog_id})
    if existing[2] == "APPROVED":
        await _recompute_totals(existing[0], existing[1], db)
    await db.commit()


@router.post("/{backlog_id}/approve")
async def approve_backlog(
    backlog_id: int,
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    bl = (await db.execute(
        text("""
            SELECT b.id, b.status, b.hours, b.project_id, b.task_id, b.user_id, b.work_date
            FROM backlogs b WHERE b.id = :bid
        """),
        {"bid": backlog_id},
    )).fetchone()
    if not bl:
        raise HTTPException(status_code=404, detail="Backlog không tồn tại")
    if bl[1] != "PENDING":
        raise HTTPException(status_code=400, detail=f"Backlog đang ở trạng thái {bl[1]}")

    row = (await db.execute(
        text("""
            UPDATE backlogs SET
                status = 'APPROVED'::"BacklogStatus",
                approver_id = :approver,
                approved_at = NOW(),
                updated_at = NOW()
            WHERE id = :bid
            RETURNING id, status, source, work_date, description, hours,
                      task_id, project_id, user_id, currency_id,
                      approver_id, approved_at, rejected_reason, created_at, updated_at
        """),
        {"approver": current_user["id"], "bid": backlog_id},
    )).fetchone()

    await _recompute_totals(bl[3], bl[4], db)
    await db.commit()
    return {"data": _row(row)}


@router.post("/{backlog_id}/reject")
async def reject_backlog(
    backlog_id: int,
    body: dict,
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    bl = (await db.execute(
        text("SELECT id, status FROM backlogs WHERE id = :bid"),
        {"bid": backlog_id},
    )).fetchone()
    if not bl:
        raise HTTPException(status_code=404, detail="Backlog không tồn tại")
    if bl[1] != "PENDING":
        raise HTTPException(status_code=400, detail=f"Backlog đang ở trạng thái {bl[1]}")

    row = (await db.execute(
        text("""
            UPDATE backlogs SET
                status = 'REJECTED'::"BacklogStatus",
                rejected_reason = :reason,
                approver_id = :approver,
                updated_at = NOW()
            WHERE id = :bid
            RETURNING id, status, source, work_date, description, hours,
                      task_id, project_id, user_id, currency_id,
                      approver_id, approved_at, rejected_reason, created_at, updated_at
        """),
        {"reason": body.get("reason"), "approver": current_user["id"], "bid": backlog_id},
    )).fetchone()
    await db.commit()
    return {"data": _row(row)}


@router.post("/{backlog_id}/reset")
async def reset_backlog(
    backlog_id: int,
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    bl = (await db.execute(
        text("SELECT id, status, project_id, task_id FROM backlogs WHERE id = :bid"),
        {"bid": backlog_id},
    )).fetchone()
    if not bl:
        raise HTTPException(status_code=404, detail="Backlog không tồn tại")

    was_approved = bl[1] == "APPROVED"
    row = (await db.execute(
        text("""
            UPDATE backlogs SET
                status = 'PENDING'::"BacklogStatus",
                approver_id = NULL, approved_at = NULL, rejected_reason = NULL,
                updated_at = NOW()
            WHERE id = :bid
            RETURNING id, status, source, work_date, description, hours,
                      task_id, project_id, user_id, currency_id,
                      approver_id, approved_at, rejected_reason, created_at, updated_at
        """),
        {"bid": backlog_id},
    )).fetchone()

    if was_approved:
        await _recompute_totals(bl[2], bl[3], db)
    await db.commit()
    return {"data": _row(row)}
