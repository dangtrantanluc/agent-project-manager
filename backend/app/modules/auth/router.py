from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.modules.auth.schemas import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    UserDTO,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_dto(row) -> UserDTO:
    return UserDTO(
        id=row[0], email=row[1], fullName=row[2], avatarUrl=row[3],
        role=row[4], companyName=row[5], lang=row[6],
        timezone=row[7], isSuperAdmin=row[8],
    )


def _make_access_token(row) -> str:
    return create_access_token({
        "sub": str(row[0]),
        "email": row[1],
        "role": row[2],
        "companyName": row[3],
        "isSuperAdmin": row[4],
    })


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = (await db.execute(
        text("SELECT id FROM users WHERE email = :email LIMIT 1"),
        {"email": req.email},
    )).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Email đã được sử dụng")

    company_name = (req.companyName or "").strip()
    if not company_name:
        raise HTTPException(status_code=400, detail="Cần cung cấp companyName")
    role = "ADMIN"

    company_row = (await db.execute(
        text("""
            INSERT INTO companies (name, code, currency_id, updated_at)
            VALUES (:name, :code, 1, NOW())
            ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, updated_at = NOW()
            RETURNING id, name
        """),
        {"name": company_name, "code": company_name.lower().replace(" ", "-")[:50]},
    )).fetchone()

    user_row = (await db.execute(
        text("""
            INSERT INTO users (email, password_hash, full_name, company_id, role, is_super_admin, updated_at)
            VALUES (:email, :hash, :name, :company_id, CAST(:role AS "Role"), true, NOW())
            RETURNING id, email, full_name, avatar_url, role,
                      :company_name AS company_name, lang, timezone, is_super_admin
        """),
        {
            "email": req.email,
            "hash": hash_password(req.password),
            "name": req.fullName,
            "company_id": company_row[0],
            "company_name": company_row[1],
            "role": role,
        },
    )).fetchone()

    token_row = (await db.execute(
        text("""
            SELECT u.id, u.email, u.role, c.name, u.is_super_admin
            FROM users u LEFT JOIN companies c ON c.id = u.company_id
            WHERE u.id = :uid
        """),
        {"uid": user_row[0]},
    )).fetchone()
    await db.commit()

    return AuthResponse(user=_user_dto(user_row), accessToken=_make_access_token(token_row))


@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(
        text("""
            SELECT u.id, u.email, u.full_name, u.avatar_url, u.role, c.name AS company_name,
                   u.lang, u.timezone, u.is_super_admin, u.password_hash, u.active
            FROM users u
            LEFT JOIN companies c ON c.id = u.company_id
            WHERE u.email = :email LIMIT 1
        """),
        {"email": req.email},
    )).fetchone()

    if not row or not row[10]:
        raise HTTPException(status_code=401, detail="Email hoặc mật khẩu không đúng")
    if not verify_password(req.password, row[9]):
        raise HTTPException(status_code=401, detail="Email hoặc mật khẩu không đúng")

    await db.execute(
        text("UPDATE users SET last_login_at = NOW() WHERE id = :uid"),
        {"uid": row[0]},
    )
    await db.commit()

    token_row = (row[0], row[1], row[4], row[5], row[8])
    return AuthResponse(user=_user_dto(row), accessToken=_make_access_token(token_row))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(current_user: dict = Depends(get_current_user)):
    pass
