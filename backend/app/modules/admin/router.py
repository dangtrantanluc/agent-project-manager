import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, require_role
from app.core.security import hash_password

router = APIRouter(prefix="/admin", tags=["admin"])

# Bảng chữ cái dễ đọc cho mã liên kết Gapo: bỏ 0/O/1/I/L để tránh nhầm khi đọc/gõ.
_LINK_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_LINK_CODE_LENGTH = 6


def _generate_link_code() -> str:
    return "".join(secrets.choice(_LINK_CODE_ALPHABET) for _ in range(_LINK_CODE_LENGTH))


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

    # users.company_id là FK tới companies (NOT NULL). User mới thuộc cùng công ty
    # với admin đang tạo; fallback sang công ty đầu tiên cho deployment 1 công ty.
    company_id = current_user.get("companyId")
    if not company_id:
        company_id = (await db.execute(
            text("SELECT id FROM companies ORDER BY id LIMIT 1")
        )).scalar()
    if not company_id:
        raise HTTPException(status_code=400, detail="Chưa có công ty nào trong hệ thống")

    row = (await db.execute(
        text("""
            INSERT INTO users (email, full_name, role, password_hash, company_id, updated_at)
            VALUES (:email, :full_name, CAST(:role AS "Role"), :pw_hash, :company_id, NOW())
            RETURNING id, email, full_name, role, active
        """),
        {
            "email": body["email"], "full_name": body["fullName"],
            "role": body.get("role", "MEMBER"),
            "pw_hash": hash_password(body["password"]),
            "company_id": company_id,
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
            # role là enum "Role" → cần CAST tường minh cho asyncpg.
            if col == "role":
                sets.append('role = CAST(:role AS "Role")')
            else:
                sets.append(f"{col} = :{js}")
            params[js] = body[js]
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


# ── Gapo linking ─────────────────────────────────────────────────────────────--
#
# Self-service linking: admin issues a short-lived code per user; the employee
# messages the bot "/link <code>" and the webhook writes gapo_user_maps with the
# real gapo_user_id + thread_id. These endpoints never touch those raw ids — they
# only manage the code lifecycle and let admins view / revoke completed links.


@router.get("/gapo-maps")
async def list_gapo_maps(
    q: Optional[str] = Query(default=None),
    current_user: dict = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """List users with their Gapo link status and any active link code."""
    where = "WHERE TRUE"
    params: dict = {}
    if q:
        where += " AND (u.full_name ILIKE :q OR u.email ILIKE :q)"
        params["q"] = f"%{q}%"

    rows = (await db.execute(
        text(f"""
            SELECT u.id, u.email, u.full_name, u.active,
                   g.gapo_user_id, g.gapo_thread_id, g.gapo_full_name, g.created_at,
                   c.code, c.expires_at
            FROM users u
            LEFT JOIN gapo_user_maps g ON g.user_id = u.id
            LEFT JOIN gapo_link_codes c
                   ON c.user_id = u.id AND c.used_at IS NULL AND c.expires_at > NOW()
            {where}
            ORDER BY u.full_name
        """),
        params,
    )).fetchall()

    data = [
        {
            "userId": r[0], "email": r[1], "fullName": r[2], "active": r[3],
            "linked": r[4] is not None,
            "gapoUserId": str(r[4]) if r[4] is not None else None,
            "gapoThreadId": str(r[5]) if r[5] is not None else None,
            "gapoFullName": r[6],
            "linkedAt": r[7].isoformat() if r[7] else None,
            "activeCode": r[8],
            "codeExpiresAt": r[9].isoformat() if r[9] else None,
        }
        for r in rows
    ]
    return {"data": data}


@router.post("/gapo-maps/{user_id}/link-code", status_code=201)
async def create_gapo_link_code(
    user_id: int,
    relink: bool = Query(default=False),
    current_user: dict = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Issue a fresh single-use link code for a user.

    Invalidates any prior unused code for that user. Refuses if the user is
    already linked unless relink=true (used when an employee changes Gapo account).
    """
    user = (await db.execute(
        text("SELECT id FROM users WHERE id = :uid"), {"uid": user_id}
    )).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Người dùng không tồn tại")

    already_linked = (await db.execute(
        text("SELECT 1 FROM gapo_user_maps WHERE user_id = :uid"), {"uid": user_id}
    )).fetchone()
    if already_linked and not relink:
        raise HTTPException(
            status_code=409,
            detail="Người dùng đã được liên kết Gapo. Dùng relink=true để cấp lại mã.",
        )

    ttl_hours = int(os.getenv("GAPO_LINK_CODE_TTL_HOURS", "24"))
    expires_at = datetime.utcnow() + timedelta(hours=ttl_hours)

    # Drop the user's prior unused code so the partial-unique index stays satisfied.
    await db.execute(
        text("DELETE FROM gapo_link_codes WHERE user_id = :uid AND used_at IS NULL"),
        {"uid": user_id},
    )

    # Retry on the (astronomically unlikely) UNIQUE(code) collision.
    row = None
    for _ in range(5):
        code = _generate_link_code()
        exists = (await db.execute(
            text("SELECT 1 FROM gapo_link_codes WHERE code = :code"), {"code": code}
        )).fetchone()
        if exists:
            continue
        row = (await db.execute(
            text("""
                INSERT INTO gapo_link_codes (code, user_id, expires_at, created_by)
                VALUES (:code, :uid, :expires_at, :created_by)
                RETURNING code, expires_at
            """),
            {
                "code": code, "uid": user_id, "expires_at": expires_at,
                "created_by": current_user["id"],
            },
        )).fetchone()
        break
    if row is None:
        raise HTTPException(status_code=500, detail="Không tạo được mã, vui lòng thử lại")

    await db.commit()
    return {"data": {
        "code": row[0],
        "expiresAt": row[1].isoformat(),
        "ttlHours": ttl_hours,
    }}


@router.delete("/gapo-maps/{user_id}", status_code=204)
async def unlink_gapo_map(
    user_id: int,
    current_user: dict = Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    """Remove a user's Gapo mapping (e.g. when they switch Gapo accounts)."""
    result = await db.execute(
        text("DELETE FROM gapo_user_maps WHERE user_id = :uid"), {"uid": user_id}
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Người dùng chưa được liên kết Gapo")
    await db.commit()


# ── Company ────────────────────────────────────────────────────────────────────

@router.get("/company")
async def get_company(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    company_id = current_user.get("companyId")
    row = (await db.execute(
        text("""
            SELECT c.id, c.name, COUNT(u.id) AS user_count
            FROM companies c
            LEFT JOIN users u ON u.company_id = c.id
            WHERE (CAST(:cid AS integer) IS NULL OR c.id = CAST(:cid AS integer))
            GROUP BY c.id, c.name
            ORDER BY user_count DESC
            LIMIT 1
        """),
        {"cid": company_id},
    )).fetchone()
    projects_count = (await db.execute(text("SELECT COUNT(*) FROM projects"))).scalar()
    return {"data": {
        "id": row[0] if row else None,
        "name": row[1] if row else current_user.get("companyName"),
        "_count": {"users": row[2] if row else 0, "projects": projects_count or 0},
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

    company_id = current_user.get("companyId")
    if not company_id:
        company_id = (await db.execute(
            text("SELECT id FROM companies ORDER BY id LIMIT 1")
        )).scalar()

    row = (await db.execute(
        text("""
            UPDATE companies
            SET name = :name, updated_at = NOW()
            WHERE id = :cid
            RETURNING name
        """),
        {"name": name, "cid": company_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Không tìm thấy công ty")
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
