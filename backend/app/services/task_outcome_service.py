"""Bắt KẾT QUẢ & KHÓ KHĂN của task khi cập nhật qua chat (sơ đồ outcome capture).

Bám điểm hội tụ chung của 2 luồng update (nhắc deadline + tin nhắn thường): sau khi
``TaskProgressService`` đã GHI task xong, service này hỏi/bắt thêm:

  - Task -> DONE                : hỏi "kết quả + khó khăn?"  -> ghi tasks.result / tasks.issues
  - Bấm "⛔ Đang kẹt (blocker)" : hỏi "vướng ở đâu?"        -> ghi task_blockers.description (+ tasks.issues)

Cơ chế hỏi-đáp tái dùng bảng ``agent_follow_ups`` (như luồng nhắc deadline), phân
biệt bằng cột ``kind`` để reply không bị verify/deadline nuốt nhầm:
  - kind=RESULT_ISSUES  -> apply_reply ghi result/issues
  - kind=BLOCKER_REASON -> apply_reply ghi lý do blocker

Nguyên tắc an toàn (giống verify/progress): chỉ ghi khi đúng assignee; LLM lỗi/None
-> fallback rule-based; mọi INSERT/UPDATE nằm trong CÙNG transaction với update gốc
(không tự commit ở các hàm tạo follow-up).
"""
import json
import logging
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_agent.task_update.task_verify_service import TaskVerifyService, TaskFacts

logger = logging.getLogger(__name__)

# Reply outcome phải tới trong TTL ngắn (khác TTL 24h của deadline) để tránh
# gắn nhầm câu nói rời rạc nhiều giờ sau vào task.
_OUTCOME_TTL_HOURS = 2

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
# "Bỏ qua" — chỉ coi là skip khi CẢ câu là từ phủ định (tránh nuốt
# "không có khó khăn, kết quả là X").
_SKIP_WORDS = {"bỏ", "qua", "bo", "không", "khong", "ko", "skip", "thôi", "thoi", "none", "no"}

# Cue cho biết câu update đã NÊU RÕ kết quả/khó khăn (để bắt inline, khỏi hỏi lại).
_INLINE_CUE_RE = re.compile(
    r"(kết\s*quả|ket\s*qua|khó\s*khăn|kho\s*khan|vướng|vuong|trở\s*ngại|tro\s*ngai|issue|bug|block)")

# Schema cho with_structured_output(method="function_calling").
OUTCOME_SCHEMA = {
    "title": "task_outcome",
    "description": "Kết quả đạt được và khó khăn gặp phải khi làm task.",
    "type": "object",
    "properties": {
        "result": {"type": ["string", "null"], "description": "Kết quả đạt được; null nếu không đề cập."},
        "issues": {"type": ["string", "null"], "description": "Khó khăn/vướng mắc; null nếu không có."},
        "has_difficulty": {"type": "boolean", "description": "Có nêu khó khăn không."},
    },
    "required": ["has_difficulty"],
}


class TaskOutcomeService:
    """Hỏi & ghi kết quả/khó khăn sau khi task được cập nhật. Mượn TaskVerifyService
    cho LLM + helper tên + _mark_followup_replied (không nhân đôi)."""

    def __init__(self, verify_service: TaskVerifyService | None = None):
        self._verify = verify_service or TaskVerifyService()
        self.llm = self._verify.llm  # None -> dùng fallback tất định

    # ── Quyết định có hỏi không ───────────────────────────────────────────────
    @staticmethod
    def should_ask_outcome(facts: TaskFacts, final_status: str) -> bool:
        """Hỏi kết quả/khó khăn khi task vừa chuyển sang DONE (và là task của user)."""
        return bool(facts.is_resolved) and final_status == "DONE"

    # ── Trích kết quả/khó khăn từ câu chữ ─────────────────────────────────────
    def extract_outcome(self, text_in: str) -> dict:
        """Trả {result, issues, has_difficulty}. LLM structured output; lỗi -> rule-based."""
        text_in = (text_in or "").strip()
        if self.llm is not None:
            try:
                structured = self.llm.with_structured_output(OUTCOME_SCHEMA, method="function_calling")
                data = structured.invoke(
                    "Trích KẾT QUẢ đạt được và KHÓ KHĂN gặp phải từ câu sau của thành viên. "
                    "Không đề cập phần nào thì để null.\n\nCâu: «" + text_in + "»"
                )
                if isinstance(data, dict):
                    return self._normalize(data.get("result"), data.get("issues"))
            except Exception:
                logger.exception("extract_outcome LLM lỗi, dùng fallback")
        return self._fallback_extract(text_in)

    @staticmethod
    def _normalize(result, issues) -> dict:
        result = (result or "").strip() or None
        issues = (issues or "").strip() or None
        return {"result": result, "issues": issues, "has_difficulty": issues is not None}

    @staticmethod
    def _fallback_extract(text_in: str) -> dict:
        """Tách thô theo mốc từ khoá khi không có LLM."""
        if not text_in:
            return {"result": None, "issues": None, "has_difficulty": False}
        low = text_in.lower()
        # Tìm mốc "khó khăn/vướng/issue/bug" -> phần sau là issues; phần trước là result.
        m = re.search(r"(khó\s*khăn|kho\s*khan|vướng|vuong|trở\s*ngại|tro\s*ngai|issue|bug|block)",
                      low)
        if m:
            result = text_in[:m.start()].strip(" ,.;:-") or None
            issues = text_in[m.start():].strip(" ,.;:-") or None
            # Bỏ mào đầu "kết quả:" nếu có cho gọn.
            if result:
                result = re.sub(r"^(kết\s*quả|ket\s*qua)\s*[:\-]?\s*", "", result, flags=re.IGNORECASE).strip() or None
            return {"result": result, "issues": issues, "has_difficulty": issues is not None}
        # Không có mốc khó khăn -> coi cả câu là kết quả.
        result = re.sub(r"^(kết\s*quả|ket\s*qua)\s*[:\-]?\s*", "", text_in, flags=re.IGNORECASE).strip() or None
        return {"result": result, "issues": None, "has_difficulty": False}

    def inline_extract_outcome(self, message: str) -> dict | None:
        """Nếu câu update gốc đã nêu RÕ kết quả/khó khăn -> trích ngay (khỏi hỏi lại).

        Chỉ kích khi có cue rõ ràng; câu báo hoàn thành thuần ("task X xong rồi")
        KHÔNG bị coi là kết quả -> để hỏi follow-up.
        """
        if not message or not _INLINE_CUE_RE.search(message.lower()):
            return None
        data = self.extract_outcome(message)
        return data if (data["result"] or data["issues"]) else None

    @staticmethod
    def is_skip(message: str) -> bool:
        tokens = _TOKEN_RE.findall((message or "").lower())
        return bool(tokens) and all(t in _SKIP_WORDS for t in tokens)

    # ── Câu hỏi follow-up ─────────────────────────────────────────────────────
    def build_question(self, user_profile, *, kind: str) -> str:
        name_part = self._verify._name_part(user_profile)
        if kind == "BLOCKER_REASON":
            return (f"Đã ghi nhận đang kẹt. Bạn{name_part} đang vướng/khó khăn ở đâu? "
                    "(nhắn 'bỏ qua' nếu chưa rõ)")
        return (f"📝 Bạn{name_part} ghi giúp kết quả đạt được và khó khăn (nếu có) cho task "
                "này nhé? (nhắn 'bỏ qua' nếu không cần)")

    # ── Tạo follow-up (KHÔNG commit — chung transaction với update gốc) ────────
    async def create_followup(
        self, db: AsyncSession, *, task_id: int, user_id: int,
        thread_id: str | None, channel: str, kind: str, question: str,
    ) -> int | None:
        if not thread_id:
            return None  # không có thread -> không bắt được reply, bỏ qua hỏi
        row = (await db.execute(text("""
            INSERT INTO agent_follow_ups (task_id, user_id, channel, thread_id, question, kind, status)
            VALUES (:tid, :uid, CAST(:ch AS "ChannelKind"), :thread, :q,
                    CAST(:kind AS "FollowUpKind"), CAST('PENDING' AS "FollowUpStatus"))
            RETURNING id
        """), {"tid": task_id, "uid": user_id, "ch": channel or "gapo",
               "thread": str(thread_id), "q": question, "kind": kind})).fetchone()
        return row[0] if row else None

    # ── Tìm follow-up outcome đang chờ (seam B của router) ─────────────────────
    async def find_pending(self, db: AsyncSession, user_id: str, thread_id: str | None) -> dict | None:
        """Trả {follow_up_id, task_id, kind} nếu có ĐÚNG 1 follow-up outcome PENDING."""
        if not thread_id:
            return None
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return None
        rows = (await db.execute(text("""
            SELECT id, task_id, kind::text
            FROM agent_follow_ups
            WHERE user_id = :uid AND thread_id = :thread
              AND status = CAST('PENDING' AS "FollowUpStatus")
              AND kind IN (CAST('RESULT_ISSUES' AS "FollowUpKind"),
                           CAST('BLOCKER_REASON' AS "FollowUpKind"))
              AND created_at >= NOW() - (CAST(:ttl AS int) * INTERVAL '1 hour')
            ORDER BY created_at DESC
        """), {"uid": uid, "thread": str(thread_id), "ttl": _OUTCOME_TTL_HOURS})).fetchall()
        if len(rows) == 1:
            return {"follow_up_id": rows[0][0], "task_id": rows[0][1], "kind": rows[0][2]}
        return None  # 0 hoặc >1 -> bỏ qua (tránh nhập nhằng)

    # ── Ghi DB ────────────────────────────────────────────────────────────────
    async def _write_result_issues(self, db, *, task_id: int, uid: int,
                                   result: str | None, issues: str | None) -> bool:
        """Append kèm ngày vào tasks.result/issues; chỉ khi đúng assignee. Trả True nếu ghi được."""
        if result is None and issues is None:
            return False
        # CAST(:r/:i AS text): asyncpg không suy được kiểu khi param vừa ở 'IS NULL'
        # vừa ở chuỗi nối (AmbiguousParameterError). Xem [[feedback_asyncpg_casts]].
        row = (await db.execute(text("""
            UPDATE tasks SET
                result = CASE WHEN CAST(:r AS text) IS NULL THEN result
                    ELSE COALESCE(result || E'\n', '') || '[' || to_char(CURRENT_DATE,'YYYY-MM-DD') || '] ' || CAST(:r AS text) END,
                issues = CASE WHEN CAST(:i AS text) IS NULL THEN issues
                    ELSE COALESCE(issues || E'\n', '') || '[' || to_char(CURRENT_DATE,'YYYY-MM-DD') || '] ' || CAST(:i AS text) END,
                updated_at = NOW()
            WHERE id = :tid AND assignee_id = :uid
            RETURNING id
        """), {"r": result, "i": issues, "tid": task_id, "uid": uid})).fetchone()
        return row is not None

    async def _write_blocker_reason(self, db, *, task_id: int, uid: int, reason: str) -> bool:
        """Ghi lý do vào blocker CHƯA gỡ mới nhất của task + append vào tasks.issues."""
        own = (await db.execute(text(
            "SELECT 1 FROM tasks WHERE id = :tid AND assignee_id = :uid"),
            {"tid": task_id, "uid": uid})).fetchone()
        if own is None:
            return False
        await db.execute(text("""
            UPDATE task_blockers SET description = :desc
            WHERE id = (SELECT id FROM task_blockers
                        WHERE task_id = :tid AND resolved_at IS NULL
                        ORDER BY created_at DESC LIMIT 1)
        """), {"desc": reason, "tid": task_id})
        await self._write_result_issues(db, task_id=task_id, uid=uid, result=None, issues=reason)
        return True

    async def _audit(self, db, *, task_id: int, uid: int, kind: str, data: dict) -> None:
        await db.execute(text("""
            INSERT INTO agent_audit_log (tool, args_json, result_json, source, created_at)
            VALUES ('task_outcome_update', CAST(:a AS jsonb), CAST(:r AS jsonb),
                    CAST('chat' AS "AgentAuditSource"), NOW())
        """), {
            "a": json.dumps({"task_id": task_id, "user_id": uid, "kind": kind}),
            "r": json.dumps({"result_added": bool(data.get("result")),
                             "issues_added": bool(data.get("issues"))}),
        })

    # ── Xử lý câu trả lời của user (seam B) ────────────────────────────────────
    async def apply_reply(self, db: AsyncSession, follow_up: dict, message: str,
                          user_id: str, user_profile) -> dict:
        """Ghi kết quả/khó khăn (hoặc lý do blocker) từ reply; đóng follow-up. Contract _reply."""
        fid, task_id, kind = follow_up["follow_up_id"], follow_up["task_id"], follow_up["kind"]
        name_part = self._verify._name_part(user_profile)
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return self._reply(task_id, "Không xác định được tài khoản của bạn.")

        # Bỏ qua -> đóng follow-up, không ghi tasks.
        if self.is_skip(message):
            await self._verify._mark_followup_replied(db, fid, "(bỏ qua)")
            await db.commit()
            return self._reply(task_id, f"Ok{name_part}, mình bỏ qua phần ghi chú nhé.")

        if kind == "BLOCKER_REASON":
            wrote = await self._write_blocker_reason(db, task_id=task_id, uid=uid, reason=message.strip())
            data = {"result": None, "issues": message.strip()}
            ok_msg = f"✅ Đã ghi lý do đang kẹt cho task. Khi gỡ được bạn cập nhật lại nhé{name_part}!"
        else:  # RESULT_ISSUES
            data = self.extract_outcome(message)
            wrote = await self._write_result_issues(
                db, task_id=task_id, uid=uid, result=data["result"], issues=data["issues"])
            parts = [p for p, v in (("kết quả", data["result"]), ("khó khăn", data["issues"])) if v]
            ok_msg = f"✅ Đã lưu {' & '.join(parts) or 'ghi chú'} cho task. Cảm ơn{name_part}!"

        if not wrote:
            return self._reply(task_id, "Mình chưa ghi được (task này không thuộc bạn hoặc đã đổi).")

        await self._verify._mark_followup_replied(db, fid, message)
        await self._audit(db, task_id=task_id, uid=uid, kind=kind, data=data)
        await db.commit()
        return self._reply(task_id, ok_msg)

    @staticmethod
    def _reply(task_id: int, message: str) -> dict:
        return {"type": "task_update", "resolved": True, "task_id": task_id,
                "status": None, "message": message}
