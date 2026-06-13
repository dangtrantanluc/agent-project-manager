from typing import Any, Optional
from pydantic import BaseModel

class GapoMessageMetadata(BaseModel):
    mentions: list[Any] | None = None

class GapoThreadInfo(BaseModel):
    id: int | str | None = None
    name: str | None = None
    type: str | None = None      # "direct" = chat 1-1; khác đi là group
    pair_ids: str | None = None

class GapoUserInfo(BaseModel):
    id: str | int | None = None
    name: str | None = None

class GapoMessage(BaseModel):
    id: str | int | None = None
    type: str | None = None
    text: str | None = ""
    payload: str | None = None
    metadata: dict[str, Any] | None = None
    # thread.type cho biết tin đến từ chat 1-1 hay group; user là người gửi
    # (dùng để mention lại khi trả lời trong group).
    thread: GapoThreadInfo | None = None
    user: GapoUserInfo | None = None

class GapoWebhookPayload(BaseModel):
    id: str | None = None
    event: str
    thread_id: int | None = None
    from_user_id: int | None = None
    to_bot_id: int | None = None
    message: Optional[GapoMessage] = None
