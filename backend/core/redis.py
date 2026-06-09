import asyncio
import os
import logging
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_redis_client: aioredis.Redis | None = None
_redis_lock = asyncio.Lock()


async def get_redis() -> aioredis.Redis:
    global _redis_client
    # Double-checked locking: tránh nhiều coroutine cùng tạo client khi khởi động
    # đồng thời (mỗi client mở pool kết nối riêng → rò rỉ kết nối).
    if _redis_client is None:
        async with _redis_lock:
            if _redis_client is None:
                _redis_client = aioredis.Redis(
                    host=os.getenv("REDIS_HOST", "localhost"),
                    port=int(os.getenv("REDIS_PORT", 6379)),
                    decode_responses=True,
                )
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    async with _redis_lock:
        if _redis_client is not None:
            await _redis_client.aclose()
            _redis_client = None
            logger.info("Redis connection closed")
