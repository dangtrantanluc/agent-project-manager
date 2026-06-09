from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _iso(dt):
    return dt.isoformat() if dt else None


@router.get("")
async def list_notifications(
    unread: Optional[bool] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: Optional[int] = Query(default=None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE user_id = :uid"
    params: dict = {"uid": current_user["id"], "limit": limit}
    if unread is True:
        where += " AND read_at IS NULL"
    if cursor is not None:
        where += " AND id < :cursor"
        params["cursor"] = cursor

    rows = (await db.execute(
        text(f"""
            SELECT id, type, title, body, link, read_at, created_at
            FROM notifications
            {where}
            ORDER BY id DESC
            LIMIT :limit
        """),
        params,
    )).fetchall()

    data = [
        {
            "id": r[0], "type": r[1], "title": r[2], "body": r[3], "link": r[4],
            "readAt": _iso(r[5]), "createdAt": _iso(r[6]),
        }
        for r in rows
    ]
    next_cursor = data[-1]["id"] if len(data) == limit else None
    return {"data": data, "meta": {"nextCursor": next_cursor}}


@router.get("/unread-count")
async def unread_count(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    count = (await db.execute(
        text("SELECT COUNT(*) FROM notifications WHERE user_id = :uid AND read_at IS NULL"),
        {"uid": current_user["id"]},
    )).scalar()
    return {"data": {"count": count or 0}}


@router.patch("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("""
            UPDATE notifications
            SET read_at = COALESCE(read_at, NOW())
            WHERE id = :id AND user_id = :uid
            RETURNING id
        """),
        {"id": notification_id, "uid": current_user["id"]},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Thông báo không tồn tại")
    await db.commit()
    return {"data": {"id": row[0]}}


@router.post("/read-all")
async def mark_all_read(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text("""
            UPDATE notifications
            SET read_at = NOW()
            WHERE user_id = :uid AND read_at IS NULL
        """),
        {"uid": current_user["id"]},
    )
    await db.commit()
    return {"data": {"updated": result.rowcount}}
