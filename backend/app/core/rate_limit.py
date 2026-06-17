"""Rate limiting dựa trên Redis (fixed-window counter).

Triết lý fail-open: nếu Redis lỗi thì KHÔNG chặn user thật (chỉ mất lớp bảo vệ
tạm thời), tránh biến sự cố Redis thành sự cố toàn hệ thống. Cửa sổ cố định
(fixed window) đủ tốt cho chống brute-force/lạm dụng; không cần chính xác tuyệt đối.
"""
import logging
import os
import time

from fastapi import Depends, HTTPException, Request, status

logger = logging.getLogger(__name__)


async def check_rate_limit(scope: str, identity: str, limit: int, window: int) -> None:
    """Tăng counter cho (scope, identity) trong cửa sổ `window` giây.

    Ném 429 khi vượt `limit`. Redis lỗi → bỏ qua (fail-open).
    """
    if limit <= 0:
        return
    try:
        from core.redis import get_redis

        redis = await get_redis()
        bucket = f"rl:{scope}:{identity}:{int(time.time() // window)}"
        count = await redis.incr(bucket)
        if count == 1:
            await redis.expire(bucket, window)
        if count > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Quá nhiều yêu cầu, vui lòng thử lại sau.",
            )
    except HTTPException:
        raise
    except Exception:
        logger.warning("rate_limit: Redis lỗi, bỏ qua (fail-open)", exc_info=True)


def _client_ip(request: Request) -> str:
    # Sau reverse proxy: ưu tiên X-Forwarded-For (IP đầu tiên là client thật).
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit_ip(scope: str, limit: int, window: int):
    """Dependency factory: giới hạn theo IP. Dùng cho endpoint chưa đăng nhập."""

    async def _dep(request: Request) -> None:
        await check_rate_limit(scope, _client_ip(request), limit, window)

    return _dep


def rate_limit_user(scope: str, limit: int, window: int):
    """Dependency factory: giới hạn theo user đã đăng nhập."""
    from app.core.deps import get_current_user

    async def _dep(current_user: dict = Depends(get_current_user)) -> None:
        await check_rate_limit(scope, str(current_user["id"]), limit, window)

    return _dep


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# Cấu hình sẵn cho các điểm nóng (đọc từ env, có default an toàn).
LOGIN_LIMIT = _env_int("RATE_LIMIT_LOGIN", 5)
LOGIN_WINDOW = _env_int("RATE_LIMIT_LOGIN_WINDOW", 60)
AGENT_LIMIT = _env_int("RATE_LIMIT_AGENT", 20)
AGENT_WINDOW = _env_int("RATE_LIMIT_AGENT_WINDOW", 60)
