"""MinIO object storage cho upload (avatar...).

Client được khởi tạo lười (lazy) ở lần dùng đầu tiên. Nếu thiếu cấu hình
(MINIO_ENDPOINT trống) thì `is_enabled()` trả False để router fallback về
lưu file local — tránh vỡ các môi trường chưa chạy MinIO.
"""
import os
import io
import threading

try:
    from minio import Minio
    from minio.error import S3Error
except ImportError:  # SDK chưa cài (vd môi trường test tối giản)
    Minio = None
    S3Error = Exception

_client = None
_bucket_ready = False
_lock = threading.Lock()


def is_enabled() -> bool:
    return bool(Minio and os.getenv("MINIO_ENDPOINT"))


def _get_client():
    """Trả về client MinIO, tạo bucket public-read nếu chưa có (idempotent)."""
    global _client, _bucket_ready
    if _client is None:
        with _lock:
            if _client is None:
                _client = Minio(
                    os.getenv("MINIO_ENDPOINT", "minio:9000"),
                    access_key=os.getenv("MINIO_ACCESS_KEY", "admin"),
                    secret_key=os.getenv("MINIO_SECRET_KEY", "password123"),
                    secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
                )
    if not _bucket_ready:
        with _lock:
            if not _bucket_ready:
                bucket = os.getenv("MINIO_BUCKET", "avatars")
                if not _client.bucket_exists(bucket):
                    _client.make_bucket(bucket)
                _bucket_ready = True
    return _client


def put_object(data: bytes, object_name: str, content_type: str) -> str:
    """Upload bytes lên bucket và trả về URL công khai.

    Bucket được giả định là public-read (init bởi service minio-init), nên URL
    dạng {MINIO_PUBLIC_URL}/{bucket}/{object_name} tải được trực tiếp.
    """
    client = _get_client()
    bucket = os.getenv("MINIO_BUCKET", "avatars")
    client.put_object(
        bucket,
        object_name,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    public_base = os.getenv("MINIO_PUBLIC_URL", "http://localhost:9000").rstrip("/")
    return f"{public_base}/{bucket}/{object_name}"
