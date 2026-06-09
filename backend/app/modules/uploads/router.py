import os
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db
from app.core import storage

router = APIRouter(prefix="/uploads", tags=["uploads"])

_ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_MAX_BYTES = 2 * 1024 * 1024


def _mime_to_ext(mime: str) -> str:
    return {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}.get(mime, "bin")


async def _store_avatar(data: bytes, filename: str, content_type: str) -> str:
    """Lưu ảnh lên MinIO nếu được cấu hình, ngược lại fallback về disk local.
    Trả về URL công khai để hiển thị."""
    if storage.is_enabled():
        # SDK MinIO đồng bộ -> chạy trong threadpool để không chặn event loop.
        # object_name không cần prefix bucket (đã là bucket "avatars").
        return await run_in_threadpool(
            storage.put_object, data, filename, content_type
        )

    upload_dir = Path(os.getenv("UPLOAD_DIR", "./uploads/avatars"))
    upload_dir.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(upload_dir / filename, "wb") as f:
        await f.write(data)
    public_base = os.getenv("UPLOADS_PUBLIC_BASE", "http://localhost:8000/uploads/avatars")
    return f"{public_base}/{filename}"


@router.post("/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if file.content_type not in _ALLOWED_MIME:
        raise HTTPException(status_code=400, detail="Chỉ chấp nhận PNG, JPEG, WEBP, GIF")

    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="File quá lớn (tối đa 2MB)")

    ext = _mime_to_ext(file.content_type)
    filename = f"{uuid.uuid4()}.{ext}"

    try:
        url = await _store_avatar(data, filename, file.content_type)
    except Exception as e:  # lỗi kết nối/cấu hình storage
        raise HTTPException(status_code=502, detail=f"Lưu trữ ảnh thất bại: {e}")

    await db.execute(
        text("UPDATE users SET avatar_url = :url, updated_at = NOW() WHERE id = :uid"),
        {"url": url, "uid": current_user["id"]},
    )
    await db.commit()
    return {"avatarUrl": url}
