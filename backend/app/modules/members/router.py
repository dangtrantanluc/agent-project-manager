from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_role

router = APIRouter(prefix="/members", tags=["members"])


def _member_row(r) -> dict:
    return {
        "id": r[0], "projectId": r[1], "userId": r[2], "role": r[3],
        "joinedAt": r[4].isoformat(), "createdAt": r[5].isoformat(), "updatedAt": r[6].isoformat(),
        "user": {
            "id": r[2],
            "fullName": r[7] if len(r) > 7 else None,
            "email": r[8] if len(r) > 8 else None,
            "avatarUrl": r[9] if len(r) > 9 else None,
            "role": r[10] if len(r) > 10 else None,
        } if len(r) > 7 else None,
        "rates": [],
    }


async def _get_member(member_id: int, db: AsyncSession) -> dict:
    row = (await db.execute(
        text("""
            SELECT m.id, m.project_id, m.user_id, m.role, m.joined_at, m.created_at, m.updated_at,
                   u.full_name, u.email, u.avatar_url, u.role
            FROM members m
            JOIN users u ON u.id = m.user_id
            WHERE m.id = :mid
        """),
        {"mid": member_id},
    )).fetchone()
    data = _member_row(row)
    data["rates"] = []
    return data


@router.get("/by-project/{project_id}")
async def list_members(
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
        text("""
            SELECT m.id, m.project_id, m.user_id, m.role, m.joined_at, m.created_at, m.updated_at,
                   u.full_name, u.email, u.avatar_url, u.role
            FROM members m
            JOIN users u ON u.id = m.user_id
            WHERE m.project_id = :pid
            ORDER BY m.joined_at ASC
        """),
        {"pid": project_id},
    )).fetchall()
    # rows đã JOIN đủ thông tin user -> map thẳng, tránh N+1 (trước đây gọi
    # _get_member() cho từng dòng = thêm 1 query/member).
    return {"data": [_member_row(r) for r in rows]}


@router.post("/by-project/{project_id}", status_code=201)
async def create_member(
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

    row = (await db.execute(
        text("""
            INSERT INTO members (project_id, user_id, role, updated_at)
            VALUES (:pid, :uid, :role, NOW())
            ON CONFLICT (project_id, user_id) DO NOTHING
            RETURNING id, project_id, user_id, role, joined_at, created_at, updated_at
        """),
        {"pid": project_id, "uid": body["userId"], "role": body.get("role")},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=409, detail="Thành viên đã tồn tại trong dự án")

    await db.execute(
        text("UPDATE projects SET member_count = member_count + 1, updated_at = NOW() WHERE id = :pid"),
        {"pid": project_id},
    )
    await db.commit()
    return {"data": await _get_member(row[0], db)}


@router.patch("/{member_id}")
async def update_member(
    member_id: int,
    body: dict,
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        text("""
            SELECT m.id FROM members m
            JOIN projects p ON p.id = m.project_id
            WHERE m.id = :mid
        """),
        {"mid": member_id},
    )).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Thành viên không tồn tại")

    row = (await db.execute(
        text("""
            UPDATE members SET role = :role, updated_at = NOW() WHERE id = :mid
            RETURNING id, project_id, user_id, role, joined_at, created_at, updated_at
        """),
        {"mid": member_id, "role": body.get("role")},
    )).fetchone()
    await db.commit()
    return {"data": await _get_member(row[0], db)}


@router.delete("/{member_id}", status_code=204)
async def delete_member(
    member_id: int,
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("""
            SELECT m.project_id FROM members m
            JOIN projects p ON p.id = m.project_id
            WHERE m.id = :mid
        """),
        {"mid": member_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Thành viên không tồn tại")

    await db.execute(text("DELETE FROM members WHERE id = :mid"), {"mid": member_id})
    await db.execute(
        text("UPDATE projects SET member_count = GREATEST(member_count - 1, 0), updated_at = NOW() WHERE id = :pid"),
        {"pid": row[0]},
    )
    await db.commit()


@router.get("/{member_id}/rates")
async def list_rates(
    member_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    raise HTTPException(status_code=410, detail="Member rates đã bị loại bỏ khỏi schema.")


@router.post("/{member_id}/rates", status_code=201)
async def create_rate(
    member_id: int,
    body: dict,
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    raise HTTPException(status_code=410, detail="Member rates đã bị loại bỏ khỏi schema.")
