import json
import logging
import os

from openai import AsyncOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MAX_TURNS = 5

MEMORY_SUMMARY_SYSTEM_PROMPT = """
Bạn là bộ tóm tắt memory cho PM chatbot quản lý dự án.

Nhiệm vụ:
Tóm tắt ngắn gọn cuộc hội thoại để dùng làm ngữ cảnh cho các lượt chat tiếp theo.

Mục tiêu của summary:
- Giúp bot hiểu các câu hỏi follow-up như: "dự án đó", "task này", "người đó", "deadline kia".
- Giữ lại thông tin quan trọng về project, task, user, deadline, số giờ, blocker, báo cáo.
- Loại bỏ lời chào, cảm ơn, câu xã giao không quan trọng.

Thông tin cần giữ:
- Tên project được nhắc tới.
- Tên task/milestone được nhắc tới.
- Tên người/member/assignee nếu có.
- Deadline, ngày tháng, tuần/tháng được hỏi.
- Số giờ worklog nếu có.
- Blocker/rủi ro nếu có.
- Intent gần nhất: hỏi report, log work, check deadline, hỏi task.
- Kết quả quan trọng bot đã trả lời.

Thông tin cần bỏ:
- Lời chào.
- Cảm ơn.
- Text lặp lại không có giá trị.
- Chi tiết quá dài của bảng kết quả.
- Markdown không cần thiết.

Quy tắc:
- Viết bằng tiếng Việt.
- Tối đa 3 câu.
- Không bịa thêm thông tin.
- Không suy luận ngoài nội dung hội thoại.
- Nếu không có thông tin quan trọng, trả về chuỗi rỗng.
- Không dùng markdown.
- Không dùng bullet.
- Không giải thích.

Format:
Một đoạn text ngắn duy nhất.
"""


async def _has_column(db: AsyncSession, table_name: str, column_name: str) -> bool:
    result = await db.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = :table_name
                  AND column_name = :column_name
            )
        """),
        {"table_name": table_name, "column_name": column_name},
    )
    return bool(result.scalar())


async def _resolve_company_id(
    db: AsyncSession,
    company_id: int | None = None,
    user_id: int | str | None = None,
) -> int | None:
    if company_id is not None:
        return int(company_id)

    if user_id is not None and await _has_column(db, "users", "company_id"):
        result = await db.execute(
            text("SELECT company_id FROM users WHERE id = :uid LIMIT 1"),
            {"uid": int(user_id)},
        )
        user_company_id = result.scalar()
        if user_company_id is not None:
            return int(user_company_id)

    if await _has_column(db, "companies", "id"):
        result = await db.execute(
            text("SELECT id FROM companies ORDER BY id LIMIT 1")
        )
        default_company_id = result.scalar()
        if default_company_id is not None:
            return int(default_company_id)

    return None

async def load_memory(conversation_id: str, db: AsyncSession) -> tuple[str, list[dict]]:
    """Returns (summary_text, recent_turns_list) — oldest first."""
    summary_result = await db.execute(
        text("""
            SELECT summary
            FROM agent_memory
            WHERE conversation_id = :cid
              AND NULLIF(BTRIM(summary), '') IS NOT NULL
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        """),
        {"cid": conversation_id},
    )
    latest_summary = summary_result.scalar() or ""

    turns_result = await db.execute(
        text("""
            SELECT user_text, reply_text
            FROM agent_memory
            WHERE conversation_id = :cid
            ORDER BY created_at DESC, id DESC
            LIMIT :n
        """),
        {"cid": conversation_id, "n": MAX_TURNS},
    )
    rows = turns_result.fetchall()
    if not rows:
        return "", []

    logger.info(
        "Loaded memory for conversation %s: has_summary=%s, turns=%s",
        conversation_id,
        bool(latest_summary),
        len(rows),
    )
    recent_turns = [{"user": r[0], "bot": r[1]} for r in reversed(rows)]
    return latest_summary, recent_turns


async def save_memory(
    conversation_id: str,
    user_text: str,
    reply_text: str,
    tools_used: list[str],
    correlation_id: str,
    db: AsyncSession,
    company_id: int | None = None,
    user_id: int | str | None = None,
    **_kwargs,  # absorb deprecated llm= callers
) -> None:
    has_company_id = await _has_column(db, "agent_memory", "company_id")
    insert_columns = "conversation_id, source, user_text, reply_text, summary, tools_used, correlation_id"
    insert_values = ":conv_id, 'chat', :user_text, :reply_text, '', CAST(:tools AS jsonb), :corr_id"
    params = {
        "conv_id": conversation_id,
        "user_text": user_text,
        "reply_text": reply_text,
        "tools": json.dumps(tools_used),
        "corr_id": correlation_id,
    }

    if has_company_id:
        resolved_company_id = await _resolve_company_id(db, company_id=company_id, user_id=user_id)
        if resolved_company_id is None:
            raise ValueError("agent_memory.company_id is required but no company_id could be resolved")
        insert_columns = f"company_id, {insert_columns}"
        insert_values = f":company_id, {insert_values}"
        params["company_id"] = resolved_company_id

    insert_result = await db.execute(
        text(f"""
            INSERT INTO agent_memory
                ({insert_columns})
            VALUES
                ({insert_values})
            RETURNING id
        """),
        params,
    )
    memory_id = insert_result.scalar_one()
    await db.commit()

    count_result = await db.execute(
        text("SELECT COUNT(*) FROM agent_memory WHERE conversation_id = :cid"),
        {"cid": conversation_id},
    )
    turn_count = count_result.scalar() or 0

    if turn_count % 4 != 0:
        return

    try:
        prev_summary, recent = await load_memory(conversation_id, db)
        ctx = f"Tóm tắt trước: {prev_summary}\n" if prev_summary else ""
        for turn in recent:
            ctx += f"User: {turn['user']}\nBot: {turn['bot']}\n"

        client = AsyncOpenAI(
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL"),
        )
        resp = await client.chat.completions.create(
            model=os.getenv("MODEL_NAME", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": MEMORY_SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": ctx.strip()},
            ],
            temperature=0,
        )
        if isinstance(resp, str):
            summary = resp.strip()
        else:
            summary = (resp.choices[0].message.content if resp.choices else "") or ""
            summary = summary.strip()
    except Exception:
        logger.exception("Failed to create memory summary for conversation %s", conversation_id)
        return

    await db.execute(
        text("UPDATE agent_memory SET summary = :summary WHERE id = :id"),
        {"id": memory_id, "summary": summary},
    )
    await db.commit()
