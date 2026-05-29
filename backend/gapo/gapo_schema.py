from typing import Any, Optional
from pydantic import BaseModel

class GapoMessageMetadata(BaseModel):
    mentions: list[Any] | None = None

class GapoMessage(BaseModel):
    id: str | int | None = None
    type: str | None = None
    text: str | None = ""
    payload: str | None = None
    metadata: dict[str, Any] | None = None

class GapoWebhookPayload(BaseModel):
    id: str | None = None
    event: str
    thread_id: int | None = None
    from_user_id: int | None = None
    to_bot_id: int | None = None
    message: Optional[GapoMessage] = None