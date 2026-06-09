import json
import logging

from fastapi import APIRouter, Request, HTTPException
from gapo.gapo_adapter import GapoAdapter

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook/gapo", tags=["Gapo"])
adapter = GapoAdapter()

@router.post("")
async def gapo_webhook(request: Request):
    # Đọc raw body để xác thực chữ ký HMAC (không thể dùng dict đã parse).
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        log.warning("gapo webhook payload không phải JSON hợp lệ")
        raise HTTPException(status_code=400, detail="invalid_json")

    try:
        result = await adapter.handle_event(
            payload,
            headers=dict(request.headers),
            raw_body=raw_body,
        )
        if isinstance(result, dict) and result.get("error") == "invalid_signature":
            raise HTTPException(status_code=401, detail="invalid_signature")
        log.info("gapo webhook processed result=%s", result)
        return result

    except HTTPException:
        raise
    except Exception as e:
        log.error("gapo webhook error: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))
