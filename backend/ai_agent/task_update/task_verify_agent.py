"""Agent xác minh khi user báo đã hoàn thành/đã cập nhật một task.

Quy tắc cốt lõi: CHỈ XÁC MINH, KHÔNG tự đổi tasks.status. Nếu task chưa DONE,
nhắc user tự cập nhật. Agent không bao giờ UPDATE bảng tasks.

Cách xác định "user đang nói về task nào":
  1. PRIMARY  — follow-up PENDING mới nhất (agent_follow_ups) của user+thread trong TTL.
  2. FALLBACK — bản ghi deadline_notification mới nhất (agent_audit_log) của thread.
  3. Nếu mơ hồ/không thấy -> hỏi lại user task nào.
"""
import json
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from ai_agent.coversation.conversation import ConversationAgent

logger = logging.getLogger(__name__)

FOLLOW_UP_TTL_HOURS = 24

# Map enum TaskStatus -> nhãn tiếng Việt thân thiện
_STATUS_LABEL = {
    "TODO": "Cần làm",
    "IN_PROGRESS": "Đang làm",
    "CANCELLED": "Đã huỷ",
    "DONE": "Hoàn thành",
}


class TaskVerifyAgent:
    def __init__(self, conversation_agent: ConversationAgent | None = None):
        # Chỉ mượn ConversationAgent cho tiện ích lấy tên (first name) — không gọi LLM.
        self._name_helper = conversation_agent or ConversationAgent()

    def _first_name(self, user_profile: dict | None) -> str:
        full = (user_profile or {}).get("full_name", "") or ""
        return self._name_helper._first_name(full)

    def _name_part(self, user_profile: dict | None) -> str:
        name = self._first_name(user_profile)
        return f" {name}" if name else ""

    async def verify(
        self,
        message: str,
        user_id: str,
        memory_context: str = "",
        thread_id: str | None = None,
        user_profile: dict | None = None,
        db: AsyncSession | None = None,
    ) -> dict:
        """Xác minh claim hoàn thành. Trả dict {type, message, resolved, status, task_id}."""
        if db is not None:
            return await self._verify_with_db(message, user_id, thread_id, user_profile, db)
        async with AsyncSessionLocal() as session:
            return await self._verify_with_db(message, user_id, thread_id, user_profile, session)

    async def _verify_with_db(self, message, user_id, thread_id, user_profile, db) -> dict:
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return self._ask_which_task(user_profile)

        name_part = self._name_part(user_profile)

        # PRIMARY: follow-up PENDING mới nhất trong TTL
        follow_up_id, task_id = await self._resolve_from_followup(db, uid, thread_id)

        # FALLBACK: audit log deadline_notification
        if task_id is None:
            task_id = await self._resolve_from_audit(db, thread_id)

        # Không xác định được -> hỏi user
        if task_id is None:
            return self._ask_which_task(user_profile)

        # Kiểm tra status (chỉ task của chính user)
        row = (await db.execute(text("""
            SELECT id, name, status::text AS status
            FROM tasks
            WHERE id = :tid AND assignee_id = :uid
        """), {"tid": task_id, "uid": uid})).fetchone()

        if row is None:
            # Không phải assignee / task không tồn tại -> không ghi gì, không chạm tasks
            return {
                "type": "task_update", "resolved": False, "task_id": task_id, "status": None,
                "message": (
                    f"Mình chưa tìm thấy task này được giao cho{name_part} trong hệ thống. "
                    "Bạn kiểm tra lại giúp mình nhé."
                ),
            }

        task_name, status = row[1], row[2]
        label = _STATUS_LABEL.get(status, status)

        if status == "DONE":
            msg = (
                f"Tuyệt vời{name_part}! Mình kiểm tra rồi, task '{task_name}' đã ở trạng thái "
                "Hoàn thành. Cảm ơn bạn đã cập nhật nhé!"
            )
        else:
            msg = (
                f"Mình vừa kiểm tra giúp{name_part}, nhưng task '{task_name}' trên hệ thống vẫn "
                f"đang ở trạng thái '{label}', chưa phải Hoàn thành. Bạn vào cập nhật trạng thái "
                "task giúp mình nhé, mình không tự đổi được."
            )

        # Side effect HỢP LỆ: đánh dấu follow-up đã trả lời (KHÔNG đụng tasks)
        if follow_up_id is not None:
            await db.execute(text("""
                UPDATE agent_follow_ups
                SET status = CAST('REPLIED' AS "FollowUpStatus"),
                    reply_text = :reply, replied_at = NOW(), updated_at = NOW()
                WHERE id = :fid
            """), {"fid": follow_up_id, "reply": message})
            await db.commit()

        return {"type": "task_update", "resolved": True, "task_id": task_id,
                "status": status, "message": msg}

    async def _resolve_from_followup(self, db, uid, thread_id):
        """Trả (follow_up_id, task_id) nếu có ĐÚNG 1 follow-up PENDING; ngược lại (None, None)."""
        if not thread_id:
            return None, None
        rows = (await db.execute(text("""
            SELECT id, task_id
            FROM agent_follow_ups
            WHERE user_id = :uid AND thread_id = :thread_id
              AND status = CAST('PENDING' AS "FollowUpStatus")
              AND created_at >= NOW() - (CAST(:ttl AS int) * INTERVAL '1 hour')
            ORDER BY created_at DESC
        """), {"uid": uid, "thread_id": str(thread_id), "ttl": FOLLOW_UP_TTL_HOURS})).fetchall()
        if len(rows) == 1:
            return rows[0][0], rows[0][1]
        # 0 row -> fallback; >1 -> mơ hồ, để fallback/hỏi (giữ đơn giản)
        return None, None

    async def _resolve_from_audit(self, db, thread_id):
        """Lấy task_id từ deadline_notification gần nhất nếu batch chỉ có 1 task."""
        if not thread_id:
            return None
        row = (await db.execute(text("""
            SELECT args_json
            FROM agent_audit_log
            WHERE tool = 'deadline_notification' AND error_message IS NULL
              AND args_json ->> 'thread_id' = :thread_id
              AND created_at >= NOW() - (CAST(:ttl AS int) * INTERVAL '1 hour')
            ORDER BY created_at DESC
            LIMIT 1
        """), {"thread_id": str(thread_id), "ttl": FOLLOW_UP_TTL_HOURS})).fetchone()
        if not row:
            return None
        args = row[0]
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return None
        task_ids = (args or {}).get("task_ids") or []
        return task_ids[0] if len(task_ids) == 1 else None

    def _ask_which_task(self, user_profile):
        name_part = self._name_part(user_profile)
        return {
            "type": "task_update", "resolved": False, "task_id": None, "status": None,
            "message": (
                f"Cảm ơn{name_part} đã báo! Bạn vừa cập nhật task nào vậy? "
                "Cho mình biết tên task để mình kiểm tra giúp nhé."
            ),
        }
