from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_role

router = APIRouter(prefix="/scopes", tags=["scopes"])


def _row(r) -> dict:
    return {
        "id": r[0], "sequence": r[1], "name": r[2], "notes": r[3],
        "estimatedHours": float(r[4]) if r[4] is not None else None,
        "projectId": r[5], "taskId": r[6], "assigneeId": r[7], "currencyId": r[8],
        "createdAt": r[9].isoformat(), "updatedAt": r[10].isoformat(),
    }


_SELECT = """
    SELECT id, sequence, name, notes,
           estimated_hours,
           project_id, task_id, assignee_id, currency_id,
           created_at, updated_at
    FROM scopes
"""


@router.get("/by-project/{project_id}")
async def list_scopes(
    project_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    proj = (await db.execute(
        text("SELECT id FROM projects WHERE id = :pid"),
        {"pid": project_id},
    )).fetchone()
    if not proj:
        raise HTTPException(status_code=404, detail="Dự án không tồn tại")

    rows = (await db.execute(
        text(f"{_SELECT} WHERE project_id = :pid ORDER BY sequence ASC, id ASC"),
        {"pid": project_id},
    )).fetchall()
    return {"data": [_row(r) for r in rows]}


@router.post("/by-project/{project_id}", status_code=201)
async def create_scope(
    project_id: int,
    body: dict,
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    proj = (await db.execute(
        text("SELECT id, currency_id FROM projects WHERE id = :pid"),
        {"pid": project_id},
    )).fetchone()
    if not proj:
        raise HTTPException(status_code=404, detail="Dự án không tồn tại")

    sequence = body.get("sequence")
    if sequence is None:
        last = (await db.execute(
            text("SELECT COALESCE(MAX(sequence), 0) FROM scopes WHERE project_id = :pid"),
            {"pid": project_id},
        )).scalar()
        sequence = (last or 0) + 10

    currency_id = body.get("currencyId") or proj[1]
    row = (await db.execute(
        text("""
            INSERT INTO scopes
                (sequence, name, notes, estimated_hours,
                 project_id, task_id, assignee_id, currency_id, updated_at)
            VALUES
                (:sequence, :name, :notes, :estimated_hours,
                 :pid, :task_id, :assignee_id, :currency_id, NOW())
            RETURNING id, sequence, name, notes,
                      estimated_hours,
                      project_id, task_id, assignee_id, currency_id,
                      created_at, updated_at
        """),
        {
            "sequence": sequence, "name": body["name"], "notes": body.get("notes"),
            "estimated_hours": body.get("estimatedHours"),
            "pid": project_id, "task_id": body.get("taskId"),
            "assignee_id": body.get("assigneeId"), "currency_id": currency_id,
        },
    )).fetchone()
    await db.execute(
        text("UPDATE projects SET scope_count = scope_count + 1, updated_at = NOW() WHERE id = :pid"),
        {"pid": project_id},
    )
    await db.commit()
    return {"data": _row(row)}


@router.patch("/{scope_id}")
async def update_scope(
    scope_id: int,
    body: dict,
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        text("""
            SELECT s.id FROM scopes s
            JOIN projects p ON p.id = s.project_id
            WHERE s.id = :sid
        """),
        {"sid": scope_id},
    )).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Scope không tồn tại")

    field_map = {
        "name": "name", "notes": "notes", "sequence": "sequence",
        "estimatedHours": "estimated_hours", "taskId": "task_id",
        "assigneeId": "assignee_id", "currencyId": "currency_id",
    }
    sets, params = ["updated_at = NOW()"], {"sid": scope_id}
    for js, col in field_map.items():
        if js in body:
            sets.append(f"{col} = :{js}"); params[js] = body[js]

    row = (await db.execute(
        text(f"""
            UPDATE scopes SET {', '.join(sets)} WHERE id = :sid
            RETURNING id, sequence, name, notes,
                      estimated_hours,
                      project_id, task_id, assignee_id, currency_id,
                      created_at, updated_at
        """),
        params,
    )).fetchone()
    await db.commit()
    return {"data": _row(row)}


@router.delete("/{scope_id}", status_code=204)
async def delete_scope(
    scope_id: int,
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("""
            SELECT s.project_id FROM scopes s
            JOIN projects p ON p.id = s.project_id
            WHERE s.id = :sid
        """),
        {"sid": scope_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Scope không tồn tại")

    await db.execute(text("DELETE FROM scopes WHERE id = :sid"), {"sid": scope_id})
    await db.execute(
        text("UPDATE projects SET scope_count = GREATEST(scope_count - 1, 0), updated_at = NOW() WHERE id = :pid"),
        {"pid": row[0]},
    )
    await db.commit()


@router.post("/by-project/{project_id}/reorder", status_code=204)
async def reorder_scopes(
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

    ordered_ids = body.get("orderedIds", [])
    for idx, scope_id in enumerate(ordered_ids):
        await db.execute(
            text("UPDATE scopes SET sequence = :seq WHERE id = :sid AND project_id = :pid"),
            {"seq": (idx + 1) * 10, "sid": scope_id, "pid": project_id},
        )
    await db.commit()
