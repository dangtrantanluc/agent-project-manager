"""Service xác minh khi user báo đã hoàn thành/đã cập nhật một task.

Lưu ý đặt tên: đây là một SERVICE tất định (SQL + if/else), KHÔNG phải "agent"
theo nghĩa LLM tự quyết — phần LLM chỉ diễn giải facts đã đọc từ DB. Tên cũ
``TaskVerifyAgent`` gây hiểu nhầm nên đổi thành ``TaskVerifyService``.

Quy tắc cốt lõi: CHỈ XÁC MINH, KHÔNG tự đổi tasks.status. Nếu task chưa DONE,
nhắc user tự cập nhật. Service không bao giờ UPDATE bảng tasks.

Cách xác định "user đang nói về task nào":
  1. PRIMARY  — follow-up PENDING mới nhất (agent_follow_ups) của user+thread trong TTL.
  2. FALLBACK — bản ghi deadline_notification mới nhất (agent_audit_log) của thread.
  3. Nếu mơ hồ/không thấy -> hỏi lại user task nào.

Verify-then-narrate: _gather_facts() đọc sự thật từ DB (trả ``TaskFacts``), rồi
_narrate() để LLM diễn giải facts đó bằng câu tiếng Việt tự nhiên — LLM bị RÀNG
BUỘC không được mâu thuẫn dữ kiện (vd cấm khen "đã xong" khi task chưa DONE).
Khi LLM lỗi/chưa cấu hình -> dùng câu template tất định (_fallback_message).
"""
import json
import logging
import os
import re
from dataclasses import dataclass

from langchain_openai import ChatOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from ai_agent.coversation.conversation import ConversationAgent

logger = logging.getLogger(__name__)

FOLLOW_UP_TTL_HOURS = 24

# Mã task kiểu "[2.4]", "[1.10]"… thường nằm đầu tên task -> dùng để khớp khi user
# gõ thẳng tên/mã task trong chat (không qua follow-up nhắc deadline).
_TASK_CODE_RE = re.compile(r"\[\d+(?:\.\d+)*\]")

# Map enum TaskStatus -> nhãn tiếng Việt thân thiện
_STATUS_LABEL = {
    "TODO": "Cần làm",
    "IN_PROGRESS": "Đang làm",
    "CANCELLED": "Đã huỷ",
    "DONE": "Hoàn thành",
}


def _status_label(status: str | None) -> str:
    """Nhãn tiếng Việt cho trạng thái task (giữ nguyên nếu lạ)."""
    return _STATUS_LABEL.get(status, status or "không tìm thấy")


@dataclass
class TaskFacts:
    """Sự thật đọc từ DB cho một claim hoàn thành. Thuần dữ liệu, không câu chữ.

    Ba trạng thái có thể có:
      - không xác định được task  -> task_id is None
      - xác định được nhưng không phải assignee -> task_id set, is_assignee=False
      - xác minh đầy đủ           -> is_resolved (task_id set + is_assignee)
    """

    task_id: int | None = None
    follow_up_id: int | None = None
    task_name: str | None = None
    status: str | None = None
    is_assignee: bool = False

    @property
    def is_done(self) -> bool:
        return self.status == "DONE"

    @property
    def is_resolved(self) -> bool:
        """Xác minh thành công: tìm được task VÀ là task của chính user."""
        return self.task_id is not None and self.is_assignee

    @property
    def label(self) -> str:
        return _status_label(self.status)


class TaskVerifyService:
    def __init__(self, conversation_agent: ConversationAgent | None = None,
                 llm: ChatOpenAI | None = None):
        # Mượn ConversationAgent cho tiện ích lấy tên (first name).
        self._name_helper = conversation_agent or ConversationAgent()
        # LLM dùng để diễn giải facts thành câu tự nhiên. None -> fallback tất định.
        self.llm = llm or self._build_llm()

    @staticmethod
    def _build_llm() -> ChatOpenAI | None:
        """Tạo LLM từ env; trả None (dùng fallback tất định) nếu chưa cấu hình."""
        model, api_key, base_url = (
            os.getenv("MODEL_NAME"), os.getenv("API_KEY"), os.getenv("BASE_URL"),
        )
        if model and api_key and base_url:
            from ai_agent.shared.llm_factory import make_llm
            return make_llm(
                purpose="task_verify", timeout=60, reasoning_effort="none",
                model=model, api_key=api_key, base_url=base_url,
            )
        logger.warning("TaskVerifyService LLM chưa cấu hình; dùng câu trả lời tất định.")
        return None

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
            return self._reply(self._ask_which_task_message(user_profile), facts=TaskFacts())

        facts = await self._gather_facts(uid, thread_id, db, message)

        # Side-effect HỢP LỆ: chỉ đánh dấu follow-up đã trả lời khi xác minh đầy đủ
        # (đúng assignee) và resolve được qua follow-up. KHÔNG bao giờ đụng bảng tasks.
        if facts.is_resolved and facts.follow_up_id is not None:
            await self._mark_followup_replied(db, facts.follow_up_id, message)
            await db.commit()

        narrated = self._narrate(facts, user_profile)
        dep_note = await self._dependency_note(db, facts)
        if dep_note:
            narrated = f"{narrated}\n\n{dep_note}"
        return self._reply(narrated, facts=facts)

    async def _dependency_note(self, db, facts: TaskFacts) -> str:
        """Cảnh báo mềm phụ thuộc cho luồng verify (không % ): nếu task resolve được.

        - status DONE: báo task khác đã sẵn sàng (newly_unblocked).
        - vẫn còn task chặn chưa xong: nhắc nhẹ.
        """
        if facts.task_id is None:
            return ""
        from app.services.dependency_service import (
            unfinished_blockers, newly_unblocked, format_blocker_warning, format_unblocked_note,
        )
        parts: list[str] = []
        if (facts.status or "").upper() == "DONE":
            unblocked = await newly_unblocked(db, facts.task_id)
            if unblocked:
                parts.append(format_unblocked_note(unblocked))
        blockers = await unfinished_blockers(db, facts.task_id)
        if blockers:
            parts.append(format_blocker_warning(blockers))
        return "\n".join(parts)

    @staticmethod
    def _reply(message: str, *, facts: TaskFacts) -> dict:
        """Đóng gói dict trả về thống nhất (giữ contract cũ của verify())."""
        return {
            "type": "task_update",
            "resolved": facts.is_resolved,
            "task_id": facts.task_id,
            "status": facts.status,
            "message": message,
        }

    async def _gather_facts(self, uid, thread_id, db, message: str = "") -> TaskFacts:
        """Đọc sự thật từ DB. task_id=None nếu không xác định được task nào.

        Thứ tự resolve "task nào": follow-up PENDING -> audit deadline -> MÃ/TÊN task
        gõ trong tin nhắn (vd "[2.4] Gửi báo giá..."). Bước cuối cho phép user cập
        nhật task họ tự nêu tên, không cần đã được nhắc deadline trước đó.
        """
        follow_up_id, task_id = await self._resolve_from_followup(db, uid, thread_id)
        if task_id is None:
            task_id = await self._resolve_from_audit(db, thread_id)
        if task_id is None and message:
            task_id = await self._resolve_from_message(db, uid, message)
        if task_id is None:
            return TaskFacts()

        # Chỉ lấy task của chính user (assignee).
        row = (await db.execute(text("""
            SELECT id, name, status::text AS status
            FROM tasks
            WHERE id = :tid AND assignee_id = :uid
        """), {"tid": task_id, "uid": uid})).fetchone()

        if row is None:
            # Xác định được task_id nhưng KHÔNG phải assignee. follow_up_id để None
            # để không mark REPLIED follow-up của task người khác.
            return TaskFacts(task_id=task_id, is_assignee=False)

        return TaskFacts(
            task_id=task_id, follow_up_id=follow_up_id,
            task_name=row[1], status=row[2], is_assignee=True,
        )

    async def _mark_followup_replied(self, db, follow_up_id, reply_text) -> None:
        await db.execute(text("""
            UPDATE agent_follow_ups
            SET status = CAST('REPLIED' AS "FollowUpStatus"),
                reply_text = :reply, replied_at = NOW(), updated_at = NOW()
            WHERE id = :fid
        """), {"fid": follow_up_id, "reply": reply_text})

    # ── Diễn giải facts -> câu trả lời ────────────────────────────────────────
    def _narrate(self, facts: TaskFacts, user_profile: dict | None) -> str:
        """LLM diễn giải facts (neo vào dữ kiện). Lỗi/None -> fallback tất định.

        Chỉ gọi LLM khi xác minh đầy đủ (is_resolved). Các ca cố định (không tìm
        thấy task / không phải assignee) trả thẳng template, không cần LLM.
        """
        fallback = self._fallback_message(facts, user_profile)
        if self.llm is None or not facts.is_resolved:
            return fallback
        try:
            resp = self.llm.invoke(self._narrate_prompt(facts, user_profile))
            return (resp.content or "").strip() or fallback
        except Exception:
            logger.exception("TaskVerify narrate lỗi, dùng fallback")
            return fallback

    def _narrate_prompt(self, facts: TaskFacts, user_profile: dict | None) -> str:
        name = self._first_name(user_profile) or "bạn"
        task_name = facts.task_name or "chưa xác định"
        label = facts.label
        # LƯU Ý: không đặt ví dụ chứa {} trong f-string của prompt.
        return (
            "Bạn là trợ lý PM. KẾT QUẢ KIỂM TRA HỆ THỐNG (sự thật, KHÔNG được mâu thuẫn):\n"
            f"- Task: {task_name}\n"
            f"- Trạng thái thực tế: {label}\n"
            f"- Đã hoàn thành (DONE)?: {facts.is_done}\n\n"
            f'Người dùng (tên "{name}") vừa nói họ đã cập nhật/hoàn thành task.\n\n'
            'Soạn ĐÚNG 1 câu trả lời tiếng Việt thân thiện, xưng "mình", gọi user theo tên trên.\n'
            "QUY TẮC BẮT BUỘC:\n"
            "- Nếu 'Đã hoàn thành' = False: TUYỆT ĐỐI KHÔNG khen đã xong. Phải nói rõ task "
            f"VẪN đang ở trạng thái '{label}', CHƯA Hoàn thành, và nhờ user tự vào cập nhật "
            "trạng thái (mình không tự đổi được).\n"
            "- Nếu 'Đã hoàn thành' = True: cảm ơn và xác nhận task đã Hoàn thành.\n"
            "- KHÔNG bịa thêm thông tin ngoài dữ kiện trên (không nhắc deadline/ngày nếu "
            "không có trong dữ kiện)."
        )

    def _fallback_message(self, facts: TaskFacts, user_profile: dict | None) -> str:
        """Câu trả lời tất định (dùng khi LLM lỗi/None hoặc ca câu hỏi cố định)."""
        name_part = self._name_part(user_profile)

        # Xác định được task_id nhưng không phải assignee -> báo không tìm thấy.
        if facts.task_id is not None and not facts.is_assignee:
            return (
                f"Mình chưa tìm thấy task này được giao cho{name_part} trong hệ thống. "
                "Bạn kiểm tra lại giúp mình nhé."
            )

        # Không xác định được task nào -> hỏi lại.
        if facts.task_id is None:
            return self._ask_which_task_message(user_profile)

        if facts.is_done:
            return (
                f"Tuyệt vời{name_part}! Mình kiểm tra rồi, task '{facts.task_name}' đã ở trạng "
                "thái Hoàn thành. Cảm ơn bạn đã cập nhật nhé!"
            )
        return (
            f"Mình vừa kiểm tra giúp{name_part}, nhưng task '{facts.task_name}' trên hệ thống "
            f"vẫn đang ở trạng thái '{facts.label}', chưa phải Hoàn thành. Bạn vào cập nhật "
            "trạng thái task giúp mình nhé, mình không tự đổi được."
        )

    # ── Phân giải "task nào" ──────────────────────────────────────────────────
    async def _resolve_from_followup(self, db, uid, thread_id):
        """Trả (follow_up_id, task_id) nếu có ĐÚNG 1 follow-up PENDING; ngược lại (None, None)."""
        if not thread_id:
            return None, None
        rows = (await db.execute(text("""
            SELECT id, task_id
            FROM agent_follow_ups
            WHERE user_id = :uid AND thread_id = :thread_id
              AND status = CAST('PENDING' AS "FollowUpStatus")
              -- Bỏ follow-up outcome (kết quả/khó khăn) — chúng do TaskOutcomeService
              -- xử lý ở seam riêng; verify chỉ resolve nhắc deadline/generic.
              AND kind NOT IN (CAST('RESULT_ISSUES' AS "FollowUpKind"),
                               CAST('BLOCKER_REASON' AS "FollowUpKind"))
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

    async def _resolve_from_message(self, db, uid, message):
        """Resolve task theo MÃ/TÊN gõ trong tin nhắn, trong các task của user.

        1) Có mã "[x.y]" -> khớp tasks.name ILIKE '%[x.y]%' (của user). Đúng 1 -> dùng.
        2) Không có mã -> so tên task (của task chưa xong) là chuỗi con của tin nhắn,
           chọn tên DÀI NHẤT (cụ thể nhất). Mơ hồ/không thấy -> None.
        """
        codes = _TASK_CODE_RE.findall(message or "")
        if codes:
            rows = (await db.execute(text("""
                SELECT id FROM tasks
                WHERE assignee_id = :uid AND name ILIKE ANY(:pats)
            """), {"uid": uid, "pats": [f"%{c}%" for c in codes]})).fetchall()
            return rows[0][0] if len(rows) == 1 else None

        low = (message or "").lower()
        rows = (await db.execute(text("""
            SELECT id, name FROM tasks
            WHERE assignee_id = :uid AND status::text NOT IN ('DONE','CANCELLED')
        """), {"uid": uid})).fetchall()
        matches = [(r[0], r[1]) for r in rows if r[1] and r[1].lower() in low]
        if not matches:
            return None
        matches.sort(key=lambda m: len(m[1]), reverse=True)
        return matches[0][0]

    def _ask_which_task_message(self, user_profile) -> str:
        name_part = self._name_part(user_profile)
        return (
            f"Cảm ơn{name_part} đã báo! Bạn vừa cập nhật task nào vậy? "
            "Cho mình biết tên task để mình kiểm tra giúp nhé."
        )
