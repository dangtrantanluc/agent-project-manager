from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_role
from app.core.security import hash_password

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Users ──────────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_admin_users(
    q: Optional[str] = Query(default=None),
    role: Optional[str] = Query(default=None),
    active: Optional[bool] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200, alias="pageSize"),
    current_user: dict = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE TRUE"
    params: dict = {}
    if role:
        where += " AND role = :role"; params["role"] = role
    if active is not None:
        where += " AND active = :active"; params["active"] = active
    if q:
        where += " AND (full_name ILIKE :q OR email ILIKE :q)"; params["q"] = f"%{q}%"

    total = (await db.execute(
        text(f"SELECT COUNT(*) FROM users {where}"), params
    )).scalar()

    params["offset"] = (page - 1) * page_size
    params["limit"] = page_size
    rows = (await db.execute(
        text(f"""
            SELECT id, email, full_name, role, active, avatar_url, lang, last_login_at, created_at
            FROM users {where}
            ORDER BY full_name
            LIMIT :limit OFFSET :offset
        """),
        params,
    )).fetchall()

    data = [
        {
            "id": r[0], "email": r[1], "fullName": r[2], "role": r[3],
            "active": r[4], "avatarUrl": r[5], "lang": r[6],
            "lastLoginAt": r[7].isoformat() if r[7] else None,
            "createdAt": r[8].isoformat(),
        }
        for r in rows
    ]
    return {"data": data, "meta": {"total": total, "page": page, "pageSize": page_size}}


@router.post("/users", status_code=201)
async def create_admin_user(
    body: dict,
    current_user: dict = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        text("SELECT id FROM users WHERE email = :email"), {"email": body["email"]}
    )).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Email đã được sử dụng")

    row = (await db.execute(
        text("""
            INSERT INTO users (email, full_name, role, password_hash, company_name, updated_at)
            VALUES (:email, :full_name, :role, :pw_hash, :company_name, NOW())
            RETURNING id, email, full_name, role, active
        """),
        {
            "email": body["email"], "full_name": body["fullName"],
            "role": body.get("role", "MEMBER"),
            "pw_hash": hash_password(body["password"]),
            "company_name": body.get("companyName") or current_user.get("companyName"),
        },
    )).fetchone()
    await db.commit()
    return {"data": {"id": row[0], "email": row[1], "fullName": row[2], "role": row[3], "active": row[4]}}


@router.patch("/users/{user_id}")
async def update_admin_user(
    user_id: int,
    body: dict,
    current_user: dict = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    existing = (await db.execute(
        text("SELECT id FROM users WHERE id = :uid"),
        {"uid": user_id},
    )).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Người dùng không tồn tại")
    if body.get("active") is False and user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="Không thể tự vô hiệu hóa tài khoản")

    field_map = {"fullName": "full_name", "role": "role", "active": "active",
                 "department": "department", "position": "position"}
    sets, params = ["updated_at = NOW()"], {"uid": user_id}
    for js, col in field_map.items():
        if js in body:
            sets.append(f"{col} = :{js}"); params[js] = body[js]
    if "password" in body:
        sets.append("password_hash = :pw_hash"); params["pw_hash"] = hash_password(body["password"])

    row = (await db.execute(
        text(f"""
            UPDATE users SET {', '.join(sets)} WHERE id = :uid
            RETURNING id, email, full_name, role, active
        """),
        params,
    )).fetchone()
    await db.commit()
    return {"data": {"id": row[0], "email": row[1], "fullName": row[2], "role": row[3], "active": row[4]}}


# ── Company ────────────────────────────────────────────────────────────────────

@router.get("/company")
async def get_company(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("""
            SELECT company_name, COUNT(*) AS user_count
            FROM users
            GROUP BY company_name
            ORDER BY user_count DESC
            LIMIT 1
        """),
        {},
    )).fetchone()
    projects_count = (await db.execute(text("SELECT COUNT(*) FROM projects"))).scalar()
    return {"data": {
        "name": row[0] if row else current_user.get("companyName"),
        "_count": {"users": row[1] if row else 0, "projects": projects_count or 0},
    }}


@router.patch("/company")
async def update_company(
    body: dict,
    current_user: dict = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    name = (body.get("name") or body.get("companyName") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Cần cung cấp tên công ty")

    row = (await db.execute(
        text("""
            UPDATE users
            SET company_name = :name, updated_at = NOW()
            RETURNING company_name
        """),
        {"name": name},
    )).fetchone()
    await db.commit()
    return {"data": {
        "name": row[0],
    }}


# ── Currencies ─────────────────────────────────────────────────────────────────

@router.get("/currencies")
async def list_currencies(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        text("SELECT id, code, symbol, rate FROM currencies ORDER BY code")
    )).fetchall()
    return {"data": [{"id": r[0], "code": r[1], "symbol": r[2], "rate": str(r[3])} for r in rows]}


@router.post("/currencies", status_code=201)
async def create_currency(
    body: dict,
    current_user: dict = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("""
            INSERT INTO currencies (code, symbol, rate)
            VALUES (:code, :symbol, COALESCE(:rate, 1.0))
            RETURNING id, code, symbol, rate
        """),
        {"code": body["code"], "symbol": body["symbol"], "rate": body.get("rate")},
    )).fetchone()
    await db.commit()
    return {"data": {"id": row[0], "code": row[1], "symbol": row[2], "rate": str(row[3])}}


@router.patch("/currencies/{currency_id}")
async def update_currency(
    currency_id: int,
    body: dict,
    current_user: dict = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    field_map = {"code": "code", "symbol": "symbol", "rate": "rate"}
    sets, params = [], {"cid": currency_id}
    for js, col in field_map.items():
        if js in body:
            sets.append(f"{col} = :{js}"); params[js] = body[js]
    if not sets:
        row = (await db.execute(
            text("SELECT id, code, symbol, rate FROM currencies WHERE id = :cid"), {"cid": currency_id}
        )).fetchone()
    else:
        row = (await db.execute(
            text(f"UPDATE currencies SET {', '.join(sets)} WHERE id = :cid RETURNING id, code, symbol, rate"),
            params,
        )).fetchone()
        await db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Currency không tồn tại")
    return {"data": {"id": row[0], "code": row[1], "symbol": row[2], "rate": str(row[3])}}


@router.delete("/currencies/{currency_id}", status_code=204)
async def delete_currency(
    currency_id: int,
    current_user: dict = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(text("DELETE FROM currencies WHERE id = :cid"), {"cid": currency_id})
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Currency không tồn tại")
    await db.commit()
