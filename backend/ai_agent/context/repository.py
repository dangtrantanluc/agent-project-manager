import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from ai_agent.context.models import ConversationState

_TTL_INTERVAL = "30 minutes"


async def load_conv_state(
    company_id: int,
    user_id: int,
    thread_id: str,
    db: AsyncSession,
) -> ConversationState:
    """Return live ConversationState or empty state if none/expired."""
    result = await db.execute(
        text("""
            SELECT state FROM conversation_states
            WHERE company_id = :cid
              AND user_id = :uid
              AND thread_id = :tid
              AND expires_at > NOW()
            LIMIT 1
        """),
        {"cid": company_id, "uid": user_id, "tid": thread_id},
    )
    row = result.fetchone()
    if not row:
        return ConversationState()
    # asyncpg returns JSONB as Python dict
    return ConversationState.model_validate(row[0])


async def save_conv_state(
    company_id: int,
    user_id: int,
    thread_id: str,
    state: ConversationState,
    db: AsyncSession,
) -> None:
    """UPSERT conversation state with 30-minute TTL extension."""
    await db.execute(
        text(f"""
            INSERT INTO conversation_states
                (company_id, user_id, thread_id, state, expires_at, created_at, updated_at)
            VALUES
                (:cid, :uid, :tid,
                 CAST(:state AS jsonb),
                 NOW() + INTERVAL '{_TTL_INTERVAL}',
                 NOW(), NOW())
            ON CONFLICT (company_id, user_id, thread_id)
            DO UPDATE SET
                state      = CAST(:state AS jsonb),
                expires_at = NOW() + INTERVAL '{_TTL_INTERVAL}',
                updated_at = NOW()
        """),
        {
            "cid": company_id,
            "uid": user_id,
            "tid": thread_id,
            "state": json.dumps(state.model_dump()),
        },
    )
    await db.commit()
