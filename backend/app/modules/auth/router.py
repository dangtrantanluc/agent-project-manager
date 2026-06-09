from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core.security import (
    create_access_token,
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


@router.post("/register", status_code=status.HTTP_403_FORBIDDEN)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Hệ thống nội bộ một công ty: không cho tự đăng ký. Mọi tài khoản nhân viên
    # do ADMIN tạo qua POST /admin/users. Giữ endpoint để client cũ nhận lỗi rõ ràng.
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Đăng ký đã bị vô hiệu hóa. Vui lòng liên hệ quản trị viên để được cấp tài khoản.",
    )


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
