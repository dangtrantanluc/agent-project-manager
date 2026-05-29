import os
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db

router = APIRouter(prefix="/uploads", tags=["uploads"])

_ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_MAX_BYTES = 2 * 1024 * 1024


def _mime_to_ext(mime: str) -> str:
    return {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}.get(mime, "bin")


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
    upload_dir = Path(os.getenv("UPLOAD_DIR", "./uploads/avatars"))
    upload_dir.mkdir(parents=True, exist_ok=True)

    async with aiofiles.open(upload_dir / filename, "wb") as f:
        await f.write(data)

    public_base = os.getenv("UPLOADS_PUBLIC_BASE", "http://localhost:8000/uploads/avatars")
    url = f"{public_base}/{filename}"

    await db.execute(
        text("UPDATE users SET avatar_url = :url, updated_at = NOW() WHERE id = :uid"),
        {"url": url, "uid": current_user["id"]},
    )
    await db.commit()
    return {"avatarUrl": url}
