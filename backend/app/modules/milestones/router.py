from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_role
from app.core.code_gen import next_milestone_code

router = APIRouter(tags=["milestones"])


def _row(r) -> dict:
    return {
        "id": r[0], "name": r[1], "status": r[2],
        "dueDate": r[3].isoformat() if r[3] else None,
        "description": r[4], "taskCount": r[5], "doneCount": r[6], "completionPct": r[7],
        "projectId": r[8],
        "createdAt": r[9].isoformat(), "updatedAt": r[10].isoformat(),
        "code": (r[11] if len(r) > 11 else None),
    }


@router.get("/projects/{project_id}/milestones")
@router.get("/milestones/by-project/{project_id}")
async def list_milestones(
    project_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        text("""
            SELECT m.id, m.name, m.status, m.due_date, m.description,
                   m.task_count, m.done_count, m.completion_pct, m.project_id,
                   m.created_at, m.updated_at, m.code
            FROM milestones m
            JOIN projects p ON p.id = m.project_id
            WHERE m.project_id = :pid
            ORDER BY m.due_date NULLS LAST
        """),
        {"pid": project_id},
    )).fetchall()
    return {"data": [_row(r) for r in rows]}


@router.post("/projects/{project_id}/milestones", status_code=201)
@router.post("/milestones/by-project/{project_id}", status_code=201)
async def create_milestone(
    project_id: int,
    body: dict,
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    proj = (await db.execute(
        text("SELECT id FROM projects WHERE id = :pid"),
        {"pid": project_id},
    )).fetchone()
    if not proj:
        raise HTTPException(status_code=404, detail="Dự án không tồn tại")

    seq, code = await next_milestone_code(project_id, db)
    row = (await db.execute(
        text("""
            INSERT INTO milestones (name, status, due_date, description, project_id, seq, code, updated_at)
            VALUES (:name, :status, :due_date, :description, :pid, :seq, :code, NOW())
            RETURNING id, name, status, due_date, description,
                      task_count, done_count, completion_pct, project_id, created_at, updated_at, code
        """),
        {
            "name": body["name"], "status": body.get("status"),
            "due_date": body.get("dueDate"), "description": body.get("description"),
            "pid": project_id, "seq": seq, "code": code,
        },
    )).fetchone()
    await db.execute(
        text("UPDATE projects SET milestone_count = milestone_count + 1, updated_at = NOW() WHERE id = :pid"),
        {"pid": project_id},
    )
    await db.commit()
    return {"data": _row(row)}


@router.patch("/milestones/{milestone_id}")
async def update_milestone(
    milestone_id: int,
    body: dict,
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        text("""
            SELECT m.id FROM milestones m
            JOIN projects p ON p.id = m.project_id
            WHERE m.id = :mid
        """),
        {"mid": milestone_id},
    )).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Milestone không tồn tại")

    field_map = {"name": "name", "status": "status", "dueDate": "due_date", "description": "description"}
    sets, params = ["updated_at = NOW()"], {"mid": milestone_id}
    for js, col in field_map.items():
        if js in body:
            sets.append(f"{col} = :{js}"); params[js] = body[js]

    row = (await db.execute(
        text(f"""
            UPDATE milestones SET {', '.join(sets)} WHERE id = :mid
            RETURNING id, name, status, due_date, description,
                      task_count, done_count, completion_pct, project_id, created_at, updated_at, code
        """),
        params,
    )).fetchone()
    await db.commit()
    return {"data": _row(row)}


@router.delete("/milestones/{milestone_id}", status_code=204)
async def delete_milestone(
    milestone_id: int,
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("""
            SELECT m.project_id FROM milestones m
            JOIN projects p ON p.id = m.project_id
            WHERE m.id = :mid
        """),
        {"mid": milestone_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Milestone không tồn tại")

    await db.execute(text("DELETE FROM milestones WHERE id = :mid"), {"mid": milestone_id})
    await db.execute(
        text("UPDATE projects SET milestone_count = GREATEST(milestone_count - 1, 0), updated_at = NOW() WHERE id = :pid"),
        {"pid": row[0]},
    )
    await db.commit()
