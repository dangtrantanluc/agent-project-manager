import os
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt as _bcrypt
from jose import JWTError, jwt
from fastapi import HTTPException, status

_ALGORITHM = "HS256"


def _secret() -> str:
    s = os.getenv("JWT_SECRET", "dev-secret-change-me")
    return s


def _parse_ttl(ttl_str: str, default_seconds: int) -> int:
    """Parse '15m', '7d', '3600s' → seconds."""
    if not ttl_str:
        return default_seconds
    ttl_str = ttl_str.strip()
    if ttl_str.endswith("d"):
        return int(ttl_str[:-1]) * 86400
    if ttl_str.endswith("h"):
        return int(ttl_str[:-1]) * 3600
    if ttl_str.endswith("m"):
        return int(ttl_str[:-1]) * 60
    if ttl_str.endswith("s"):
        return int(ttl_str[:-1])
    return int(ttl_str)


def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt(rounds=10)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(data: dict[str, Any]) -> str:
    ttl = _parse_ttl(os.getenv("JWT_ACCESS_TTL", "15m"), 900)
    expire = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    payload = {**data, "exp": expire}
    return jwt.encode(payload, _secret(), algorithm=_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, _secret(), algorithms=[_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không hợp lệ hoặc đã hết hạn",
            headers={"WWW-Authenticate": "Bearer"},
        )


