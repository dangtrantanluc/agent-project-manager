"""In-app notification persistence.

The agent already notifies users over Gapo. These helpers mirror those
notifications into the `notifications` table so they also surface in the web UI
(bell + notifications page). Call `create_notification` right next to each
`gapo.send_message(...)` so both channels stay in sync.
"""
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def create_notification(
    db: AsyncSession,
    *,
    user_id: int,
    type: str,
    title: str,
    body: Optional[str] = None,
    link: Optional[str] = None,
    commit: bool = True,
) -> Optional[int]:
    """Insert one in-app notification for a user.

    Best-effort: failures are logged and swallowed so a UI-notification write
    can never break the Gapo delivery path that calls it.
    """
    try:
        row = (await db.execute(
            text("""
                INSERT INTO notifications (user_id, type, title, body, link, created_at)
                VALUES (:user_id, :type, :title, :body, :link, NOW())
                RETURNING id
            """),
            {
                "user_id": user_id,
                "type": type,
                "title": title,
                "body": body,
                "link": link,
            },
        )).fetchone()
        if commit:
            await db.commit()
        return row[0] if row else None
    except Exception as e:  # noqa: BLE001 — never let UI write break delivery
        logger.error(f"[Notifications] create_notification failed user={user_id}: {e}")
        return None
