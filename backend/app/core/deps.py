import os
from typing import Any, Optional

from fastapi import Depends, HTTPException, Header, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from app.core.security import decode_token

_bearer = HTTPBearer(auto_error=False)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    x_agent_token: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    expected_agent_token = os.getenv("AGENT_API_TOKEN", "")
    if x_agent_token and expected_agent_token and x_agent_token == expected_agent_token:
        return await _load_agent_user(db)

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Yêu cầu xác thực",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token không hợp lệ")

    row = (await db.execute(
        text("""
            SELECT u.id, u.email, u.full_name, u.avatar_url, u.role,
                   u.company_id, c.name AS company_name,
                   u.lang, u.timezone, u.is_super_admin, u.active
            FROM users u
            LEFT JOIN companies c ON c.id = u.company_id
            WHERE u.id = :uid LIMIT 1
        """),
        {"uid": int(user_id)},
    )).fetchone()

    if not row or not row[10]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tài khoản không tồn tại hoặc bị vô hiệu")

    return {
        "id": row[0], "email": row[1], "fullName": row[2], "avatarUrl": row[3],
        "role": row[4], "companyId": row[5], "companyName": row[6],
        "lang": row[7], "timezone": row[8], "isSuperAdmin": row[9],
    }


async def get_agent_user(
    x_agent_token: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Service-to-service auth via X-Agent-Token header."""
    expected = os.getenv("AGENT_API_TOKEN", "")
    if not expected or x_agent_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Agent token không hợp lệ")

    return await _load_agent_user(db)


async def _load_agent_user(db: AsyncSession) -> dict[str, Any]:
    email = os.getenv("AGENT_USER_EMAIL", "pm-agent@bluebolt.local")
    row = (await db.execute(
        text("""
            SELECT u.id, u.email, u.full_name, u.avatar_url, u.role,
                   u.company_id, c.name AS company_name,
                   u.lang, u.timezone, u.is_super_admin
            FROM users u
            LEFT JOIN companies c ON c.id = u.company_id
            WHERE u.email = :email AND u.active = true LIMIT 1
        """),
        {"email": email},
    )).fetchone()

    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Agent user không tìm thấy")

    return {
        "id": row[0], "email": row[1], "fullName": row[2], "avatarUrl": row[3],
        "role": row[4], "companyId": row[5], "companyName": row[6],
        "lang": row[7], "timezone": row[8], "isSuperAdmin": row[9],
    }


_FULL_ACCESS_ROLES = {"ADMIN", "MANAGER"}

# SQL fragment: project `p` mà :access_uid được tham gia. Dùng để giới hạn dữ liệu
# (tasks/worklogs/backlogs/...) cho MEMBER/VIEWER. Tham chiếu alias bảng truyền vào
# để có thể dùng trong nhiều ngữ cảnh (vd lọc theo t.project_id hay w.project_id).
def project_access_exists_sql(project_id_expr: str) -> str:
    """Trả về điều kiện EXISTS(...) kiểm tra :access_uid có quyền xem project_id_expr."""
    return f"""EXISTS (
        SELECT 1 FROM projects _ap
        WHERE _ap.id = {project_id_expr}
          AND (
            _ap.owner_id = :access_uid
            OR _ap.account_manager_id = :access_uid
            OR EXISTS (SELECT 1 FROM members _m WHERE _m.project_id = _ap.id AND _m.user_id = :access_uid)
            OR EXISTS (SELECT 1 FROM tasks _t WHERE _t.project_id = _ap.id AND _t.assignee_id = :access_uid)
            OR EXISTS (SELECT 1 FROM worklogs _w WHERE _w.project_id = _ap.id AND _w.user_id = :access_uid)
            OR EXISTS (SELECT 1 FROM backlogs _b WHERE _b.project_id = _ap.id AND _b.user_id = :access_uid)
          )
    )"""


def is_restricted(current_user: dict) -> bool:
    """True nếu user chỉ được thấy dữ liệu thuộc project mình tham gia."""
    if current_user.get("isSuperAdmin"):
        return False
    return current_user.get("role") not in _FULL_ACCESS_ROLES


_ROLE_ORDER = {"VIEWER": 0, "MEMBER": 1, "MANAGER": 2, "ADMIN": 3}


def require_role(*roles: str):
    """Dependency factory. Usage: Depends(require_role('MANAGER', 'ADMIN'))"""
    allowed = set(roles)

    async def _check(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("isSuperAdmin"):
            return current_user
        if current_user["role"] not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Yêu cầu quyền: {', '.join(roles)}",
            )
        return current_user

    return _check
