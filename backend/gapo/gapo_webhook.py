from fastapi import APIRouter, Request, HTTPException
from gapo.gapo_adapter import GapoAdapter
import logging

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook/gapo", tags=["Gapo"])
adapter = GapoAdapter()

@router.post("")
async def gapo_webhook(request: Request):
    try:
        payload = await request.json()
        result = await adapter.handle_event(payload, headers=dict(request.headers))
        log.info("gapo webhook processed result=%s", result)
        return result

    except Exception as e:
        log.error("gapo webhook error: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))
