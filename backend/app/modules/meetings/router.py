from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db

router = APIRouter(prefix="/meetings", tags=["meetings"])


def _meeting_row(r) -> dict:
    return {
        "id": r[0], "projectId": r[1], "title": r[2],
        "heldAt": r[3].isoformat() if r[3] else None,
        "summary": r[4], "decisions": r[5], "participants": r[6],
        "createdById": r[7],
        "createdAt": r[8].isoformat(), "updatedAt": r[9].isoformat(),
    }


def _item_row(r) -> dict:
    return {
        "id": r[0], "meetingId": r[1], "title": r[2], "description": r[3],
        "ownerName": r[4], "ownerUserId": r[5],
        "dueDate": r[6].isoformat() if r[6] else None,
        "priority": r[7], "status": r[8], "createdTaskId": r[9],
        "createdAt": r[10].isoformat(), "updatedAt": r[11].isoformat(),
    }


async def _resolve_owner_user_id(owner_name: Optional[str], db: AsyncSession) -> Optional[int]:
    if not owner_name:
        return None
    row = (await db.execute(
        text("""
            SELECT id FROM users
            WHERE active = TRUE
              AND (full_name ILIKE :name OR email ILIKE :name)
            LIMIT 1
        """),
        {"name": f"%{owner_name.strip()}%"},
    )).fetchone()
    return row[0] if row else None


@router.post("", status_code=201)
async def create_meeting(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project_id = body.get("projectId")
    if project_id:
        proj = (await db.execute(
            text("SELECT id FROM projects WHERE id = :pid"),
            {"pid": project_id},
        )).fetchone()
        if not proj:
            raise HTTPException(status_code=404, detail="Dự án không tồn tại")

    import json
    row = (await db.execute(
        text("""
            INSERT INTO meetings
                (project_id, title, held_at, transcript, summary,
                 decisions, participants, created_by_id, updated_at)
            VALUES
                (:pid, :title, COALESCE(:held_at::timestamptz, NOW()), :transcript, :summary,
                 CAST(:decisions AS jsonb), :participants, :created_by, NOW())
            RETURNING id, project_id, title, held_at, summary,
                      decisions, participants, created_by_id, created_at, updated_at
        """),
        {
            "pid": project_id,
            "title": body.get("title"), "held_at": body.get("heldAt"),
            "transcript": body["transcript"], "summary": body.get("summary"),
            "decisions": json.dumps(body.get("decisions", [])),
            "participants": body.get("participants", []),
            "created_by": current_user["id"],
        },
    )).fetchone()

    meeting_id = row[0]
    items = body.get("items", [])
    for item in items:
        owner_user_id = await _resolve_owner_user_id(item.get("ownerName"), db)
        await db.execute(
            text("""
                INSERT INTO meeting_action_items
                    (meeting_id, title, description, owner_name, owner_user_id, due_date, priority, updated_at)
                VALUES
                    (:mid, :title, :desc, :owner_name, :owner_uid, :due_date,
                     COALESCE(:priority, 'MEDIUM')::"Priority", NOW())
            """),
            {
                "mid": meeting_id, "title": item["title"], "desc": item.get("description"),
                "owner_name": item.get("ownerName"), "owner_uid": owner_user_id,
                "due_date": item.get("dueDate"), "priority": item.get("priority"),
            },
        )

    await db.commit()
    meeting = _meeting_row(row)
    meeting["itemCount"] = len(items)
    return meeting


@router.get("")
async def list_meetings(
    project_id: Optional[int] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE TRUE"
    params: dict = {"limit": limit}
    if project_id:
        where += " AND project_id = :pid"; params["pid"] = project_id

    rows = (await db.execute(
        text(f"""
            SELECT id, project_id, title, held_at, summary,
                   decisions, participants, created_by_id, created_at, updated_at
            FROM meetings {where}
            ORDER BY created_at DESC
            LIMIT :limit
        """),
        params,
    )).fetchall()
    return [_meeting_row(r) for r in rows]


@router.get("/{meeting_id}")
async def get_meeting(
    meeting_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("""
            SELECT id, project_id, title, held_at, summary,
                   decisions, participants, created_by_id, created_at, updated_at
            FROM meetings WHERE id = :mid
        """),
        {"mid": meeting_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Meeting không tồn tại")

    items = (await db.execute(
        text("""
            SELECT id, meeting_id, title, description, owner_name, owner_user_id,
                   due_date, priority, status, created_task_id, created_at, updated_at
            FROM meeting_action_items WHERE meeting_id = :mid
            ORDER BY id ASC
        """),
        {"mid": meeting_id},
    )).fetchall()

    result = _meeting_row(row)
    result["items"] = [_item_row(i) for i in items]
    return result


@router.post("/{meeting_id}/approve")
async def approve_meeting_items(
    meeting_id: int,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    meeting = (await db.execute(
        text("SELECT id, project_id FROM meetings WHERE id = :mid"),
        {"mid": meeting_id},
    )).fetchone()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting không tồn tại")

    item_ids = body.get("itemIds", [])
    default_project_id = body.get("defaultProjectId")
    target_project_id = meeting[1] or default_project_id
    if not target_project_id:
        raise HTTPException(status_code=400, detail="Meeting chưa gắn dự án; cung cấp defaultProjectId")

    proj = (await db.execute(
        text("SELECT id, currency_id FROM projects WHERE id = :pid"),
        {"pid": target_project_id},
    )).fetchone()
    if not proj:
        raise HTTPException(status_code=404, detail="Dự án không tồn tại")

    items = (await db.execute(
        text("""
            SELECT id, title, description, owner_user_id, due_date, priority
            FROM meeting_action_items
            WHERE meeting_id = :mid AND id = ANY(:ids) AND status = 'DRAFT'::"MeetingItemStatus"
        """),
        {"mid": meeting_id, "ids": item_ids},
    )).fetchall()

    created = []
    skipped = []
    for it in items:
        try:
            task_row = (await db.execute(
                text("""
                    INSERT INTO tasks
                        (project_id, currency_id, name, description,
                         priority, assignee_id, deadline, updated_at)
                    VALUES
                        (:pid, :currency_id, :name, :desc,
                         COALESCE(:priority, 'MEDIUM')::"Priority", :assignee_id, :deadline, NOW())
                    RETURNING id
                """),
                {
                    "pid": proj[0], "currency_id": proj[1],
                    "name": it[1], "desc": it[2],
                    "priority": it[5], "assignee_id": it[3], "deadline": it[4],
                },
            )).fetchone()
            await db.execute(
                text("""
                    UPDATE meeting_action_items
                    SET status = 'APPROVED'::"MeetingItemStatus", created_task_id = :tid, updated_at = NOW()
                    WHERE id = :iid
                """),
                {"tid": task_row[0], "iid": it[0]},
            )
            created.append({"itemId": it[0], "taskId": task_row[0]})
        except Exception as e:
            skipped.append({"itemId": it[0], "reason": str(e)})

    await db.commit()
    return {"meetingId": meeting_id, "projectId": proj[0], "created": created, "skipped": skipped}


@router.post("/{meeting_id}/reject")
async def reject_meeting_items(
    meeting_id: int,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    meeting = (await db.execute(
        text("SELECT id FROM meetings WHERE id = :mid"),
        {"mid": meeting_id},
    )).fetchone()
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting không tồn tại")

    item_ids = body.get("itemIds", [])
    result = await db.execute(
        text("""
            UPDATE meeting_action_items
            SET status = 'REJECTED'::"MeetingItemStatus", updated_at = NOW()
            WHERE meeting_id = :mid AND id = ANY(:ids) AND status = 'DRAFT'::"MeetingItemStatus"
        """),
        {"mid": meeting_id, "ids": item_ids},
    )
    await db.commit()
    return {"data": {"rejected": result.rowcount}}
