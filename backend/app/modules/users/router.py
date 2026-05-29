from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db

router = APIRouter(tags=["users"])


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return current_user


@router.patch("/me")
async def update_me(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = {"fullName": "full_name", "avatarUrl": "avatar_url", "lang": "lang", "timezone": "timezone"}
    sets, params = [], {"uid": current_user["id"]}
    for field, col in allowed.items():
        if field in body:
            sets.append(f"{col} = :{field}")
            params[field] = body[field]
    if not sets:
        return current_user

    row = (await db.execute(
        text(f"""
            UPDATE users SET {', '.join(sets)}, updated_at = NOW()
            WHERE id = :uid
            RETURNING id, email, full_name, avatar_url, role, company_name, lang, timezone, is_admin
        """),
        params,
    )).fetchone()
    await db.commit()
    return {
        "id": row[0], "email": row[1], "fullName": row[2], "avatarUrl": row[3],
        "role": row[4], "companyName": row[5], "lang": row[6],
        "timezone": row[7], "isSuperAdmin": row[8],
    }


@router.get("/users")
async def list_users(
    active: Optional[bool] = Query(default=True),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE TRUE"
    params: dict = {}
    if active is not None:
        where += " AND active = :active"
        params["active"] = active

    rows = (await db.execute(
        text(f"""
            SELECT id, email, full_name, role, avatar_url, company_name
            FROM users {where}
            ORDER BY full_name
        """),
        params,
    )).fetchall()
    return {
        "data": [
            {
                "id": r[0], "email": r[1], "fullName": r[2], "role": r[3],
                "avatarUrl": r[4], "companyName": r[5],
            }
            for r in rows
        ]
    }


@router.get("/company/users")
async def list_company_users(
    active: Optional[bool] = Query(default=None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE TRUE"
    params: dict = {}
    if active is not None:
        where += " AND active = :active"
        params["active"] = active

    rows = (await db.execute(
        text(f"""
            SELECT id, email, full_name, avatar_url, role, company_name,
                   lang, timezone, is_admin, active, department, position
            FROM users {where}
            ORDER BY full_name
        """),
        params,
    )).fetchall()

    return [
        {
            "id": r[0], "email": r[1], "fullName": r[2], "avatarUrl": r[3],
            "role": r[4], "companyName": r[5], "lang": r[6], "timezone": r[7],
            "isSuperAdmin": r[8], "active": r[9], "department": r[10], "position": r[11],
        }
        for r in rows
    ]
