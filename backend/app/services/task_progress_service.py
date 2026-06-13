"""Cập nhật tiến độ % của task khi thành viên báo qua chat (vd "đã xong 80%").

Bổ sung cho TaskVerifyService — KHÔNG thay thế và KHÔNG sửa core của nó:
  - TaskVerifyService: user nói "xong rồi/done" (nhị phân) -> CHỈ xác minh, không đổi.
  - TaskProgressService: user nói kèm SỐ PHẦN TRĂM -> CẬP NHẬT tasks.progress (+ status
    suy ra) và ghi audit_log (sơ đồ Luồng 3, bước ⑬⑭).

Tái dùng phần "user đang nói về task nào" của TaskVerifyService (_gather_facts) để
logic resolve task nhất quán, không nhân đôi. Chỉ chạm bảng tasks khi đã xác minh
đúng assignee (giống ràng buộc an toàn của verify).

Quy ước status từ %:
  - progress == 100        -> DONE
  - 0  < progress < 100    -> IN_PROGRESS
  - progress == 0          -> giữ nguyên status hiện tại
Task đã CANCELLED thì không tự kích hoạt lại (tôn trọng _VALID_TRANSITIONS của router).
"""
import json
import logging
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from ai_agent.task_update.task_verify_service import TaskVerifyService, TaskFacts

logger = logging.getLogger(__name__)

# Bắt "80%", "80 %", "80 phần trăm". Lấy số 0..100.
_PERCENT_RE = re.compile(r"(\d{1,3})\s*(?:%|phần\s*trăm|phan\s*tram)", re.IGNORECASE)

# Từ khẳng định ĐÃ HOÀN THÀNH (không kèm số) -> coi như 100%.
_COMPLETION_WORDS = ("hoàn thành", "hoàn tất", "đã xong", "xong rồi", "làm xong",
                     "done", "hoan thanh", "xong roi")
# Phủ định -> KHÔNG phải hoàn thành ("chưa xong", "không hoàn thành").
_NEGATION_WORDS = ("chưa", "không", "chua", "khong", "chẳng")


# Tách từ (gồm chữ có dấu tiếng Việt qua \w + UNICODE) để khớp mờ tên task.
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
# Từ lệnh/đệm không mang ý nghĩa nhận diện task -> bỏ khi khớp mờ.
_STOPWORDS = {
    "update", "updae", "cập", "nhật", "capnhat", "task", "việc", "done", "xong",
    "hoàn", "thành", "cho", "tôi", "mình", "em", "anh", "chị", "nha", "nhé", "nhe",
    "di", "đi", "giúp", "giup", "bạn", "ban", "này", "nè", "ne", "rồi", "roi",
    "sang", "trạng", "thái", "status", "là", "the", "qua",
}


# ── Phiên /update (Redis, TTL ngắn, tự hết hạn) ────────────────────────────────
# Chỉ là CỜ "user đang trong luồng /update" để: (a) cho gõ thẳng từ khoá = tìm task,
# (b) có thứ để 'Huỷ'. Mọi dữ liệu task vẫn nhúng trong payload (stateless). Redis
# lỗi -> coi như không có phiên (an toàn: /update + nút bấm vẫn chạy).
_SESSION_TTL = 180  # giây (3 phút không thao tác -> tự thoát phiên /update)
TASKCANCEL_PAYLOAD = "TASKCANCEL"


def _session_key(user_id) -> str:
    return f"taskupd_sess:{user_id}"


async def open_session(user_id) -> None:
    try:
        from core.redis import get_redis
        await (await get_redis()).set(_session_key(user_id), "1", ex=_SESSION_TTL)
    except Exception:
        logger.warning("Redis unavailable, bỏ qua mở phiên /update", exc_info=True)


async def touch_session(user_id) -> None:
    """Gia hạn TTL khi còn tương tác (giống open)."""
    await open_session(user_id)


async def close_session(user_id) -> None:
    try:
        from core.redis import get_redis
        await (await get_redis()).delete(_session_key(user_id))
    except Exception:
        logger.warning("Redis unavailable, bỏ qua đóng phiên /update", exc_info=True)


async def is_in_session(user_id) -> bool:
    try:
        from core.redis import get_redis
        return bool(await (await get_redis()).get(_session_key(user_id)))
    except Exception:
        return False  # Redis lỗi -> không coi là đang trong phiên


def is_completion(message: str) -> bool:
    """Câu khẳng định đã hoàn thành (không phủ định, không kèm %)."""
    low = (message or "").lower()
    if any(n in low for n in _NEGATION_WORDS):
        return False
    return any(w in low for w in _COMPLETION_WORDS)


def extract_percent(message: str) -> int | None:
    """Trích phần trăm hợp lệ (0..100) từ tin nhắn; None nếu không có/không hợp lệ."""
    m = _PERCENT_RE.search(message or "")
    if not m:
        return None
    val = int(m.group(1))
    return val if 0 <= val <= 100 else None


def has_percent(message: str) -> bool:
    return extract_percent(message) is not None


def _status_from_percent(percent: int, current_status: str | None) -> str | None:
    """Status mới suy từ %; None nghĩa là giữ nguyên status hiện tại."""
    if percent >= 100:
        return "DONE"
    if percent > 0:
        return "IN_PROGRESS"
    return None  # 0% -> không đổi status


class TaskProgressService:
    def __init__(self, verify_service: TaskVerifyService | None = None):
        # Mượn verify service để resolve "task nào" + helper tên + ca fallback.
        self._verify = verify_service or TaskVerifyService()

    async def update(
        self,
        message: str,
        user_id: str,
        memory_context: str = "",
        thread_id: str | None = None,
        user_profile: dict | None = None,
        db: AsyncSession | None = None,
    ) -> dict:
        """Cập nhật tiến độ task theo % trong tin nhắn. Trả dict cùng contract verify()."""
        if db is not None:
            return await self._update_with_db(message, user_id, thread_id, user_profile, db)
        async with AsyncSessionLocal() as session:
            return await self._update_with_db(message, user_id, thread_id, user_profile, session)

    async def _update_with_db(self, message, user_id, thread_id, user_profile, db) -> dict:
        percent = extract_percent(message)
        # Câu khẳng định hoàn thành (không kèm số) -> coi như 100%.
        if percent is None and is_completion(message):
            percent = 100
        # Chặn % "giả": "tôi không chắc 100% là kịp deadline" có 100% nhưng KHÔNG
        # phải báo hoàn thành. Câu phủ định + percent>=100 -> không tự set DONE,
        # để verify xử lý (đọc DB, trả lời theo sự thật). Percent <100 kèm phủ định
        # ("chưa xong, mới 30%") vẫn là báo tiến độ hợp lệ -> giữ.
        if percent is not None and percent >= 100:
            low = (message or "").lower()
            if any(n in low for n in _NEGATION_WORDS):
                percent = None
        # Không có % và không phải câu hoàn thành -> để verify xử lý (giữ hành vi cũ:
        # vd "tôi update rồi" -> hỏi lại / kiểm tra, không tự đổi).
        if percent is None:
            return await self._verify.verify(
                message=message, user_id=user_id, thread_id=thread_id,
                user_profile=user_profile, db=db,
            )

        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return self._verify._reply(
                self._verify._ask_which_task_message(user_profile), facts=TaskFacts())

        facts = await self._verify._gather_facts(uid, thread_id, db, message)

        # Resolve được qua follow-up/audit/mã -> cập nhật luôn.
        if facts.is_resolved:
            return await self._finish_update(db, facts, uid, percent, user_profile, message)

        # Tìm được task nhưng KHÔNG phải của user -> báo không tìm thấy.
        if facts.task_id is not None:
            return self._verify._reply(self._verify._narrate(facts, user_profile), facts=facts)

        # CHƯA rõ task -> KHỚP MỜ (token overlap) trong task của user. User không
        # phải nhớ mã hay gõ đúng tên: "gửi báo giá qua mail" vẫn ra "[2.4] Gửi báo
        # giá qua email/WhatsApp".
        candidates = await self._resolve_candidates(db, uid, message)
        if len(candidates) == 1:
            resolved = await self._facts_for_task(db, uid, candidates[0][0])
            if resolved.is_resolved:
                return await self._finish_update(db, resolved, uid, percent, user_profile, message)
        if len(candidates) >= 2:
            # Mơ hồ -> đưa NÚT BẤM chọn task (không bắt user gõ lại). Payload mang
            # sẵn task_id + % để khi bấm là cập nhật ngay (không cần lưu state).
            return self._choose_task_reply(candidates, percent, user_profile)

        # Không khớp task nào -> hỏi lại.
        return self._verify._reply(self._verify._narrate(facts, user_profile), facts=facts)

    async def _finish_update(self, db, facts: TaskFacts, uid: int, percent: int,
                             user_profile, message: str) -> dict:
        """CANCELLED-guard + UPDATE + mark follow-up + commit + câu xác nhận."""
        if facts.status == "CANCELLED":
            name_part = self._verify._name_part(user_profile)
            return self._verify._reply(
                f"Task '{facts.task_name}' đang ở trạng thái Đã huỷ nên mình không cập "
                f"nhật tiến độ được{name_part}. Bạn kiểm tra lại giúp mình nhé.",
                facts=facts,
            )
        new_status = _status_from_percent(percent, facts.status)
        await self._apply_update(db, facts, uid, percent, new_status)
        if facts.follow_up_id is not None:
            await self._verify._mark_followup_replied(db, facts.follow_up_id, message)
        await db.commit()
        final_status = new_status or facts.status
        return {
            "type": "task_update",
            "resolved": True,
            "task_id": facts.task_id,
            "status": final_status,
            "progress": percent,
            "message": self._confirm_message(facts.task_name, percent, final_status, user_profile),
        }

    async def _apply_update(self, db, facts: TaskFacts, uid: int, percent: int, new_status: str | None) -> None:
        """UPDATE tasks (progress + status nếu có) + recompute milestone + audit_log."""
        # Đọc progress cũ để audit có cả giá trị "trước" (truy vết thay đổi đầy đủ).
        old_row = (await db.execute(text(
            "SELECT progress FROM tasks WHERE id = :tid"), {"tid": facts.task_id})).fetchone()
        old_progress = old_row[0] if old_row else None

        if new_status is not None:
            row = (await db.execute(text("""
                UPDATE tasks
                SET progress = :p, status = CAST(:st AS "TaskStatus"), updated_at = NOW()
                WHERE id = :tid AND assignee_id = :uid
                RETURNING milestone_id
            """), {"p": percent, "st": new_status, "tid": facts.task_id, "uid": uid})).fetchone()
        else:
            row = (await db.execute(text("""
                UPDATE tasks
                SET progress = :p, updated_at = NOW()
                WHERE id = :tid AND assignee_id = :uid
                RETURNING milestone_id
            """), {"p": percent, "tid": facts.task_id, "uid": uid})).fetchone()

        milestone_id = row[0] if row else None
        if milestone_id:
            await self._recompute_milestone(db, milestone_id)

        await db.execute(text("""
            INSERT INTO agent_audit_log (tool, args_json, result_json, source, created_at)
            VALUES ('task_progress_update', CAST(:args AS jsonb), CAST(:result AS jsonb),
                    CAST('chat' AS "AgentAuditSource"), NOW())
        """), {
            "args": json.dumps({
                "task_id": facts.task_id, "user_id": uid,
                "old_status": facts.status, "old_progress": old_progress,
            }),
            "result": json.dumps({
                "new_progress": percent, "new_status": new_status or facts.status,
            }),
        })

    # ── Khớp mờ task theo mô tả tự nhiên (không cần nhớ mã/gõ đủ tên) ──────────
    async def _facts_for_task(self, db, uid: int, task_id: int) -> TaskFacts:
        """Dựng TaskFacts cho 1 task_id cụ thể (đúng assignee mới resolved)."""
        row = (await db.execute(text("""
            SELECT id, name, status::text AS status
            FROM tasks WHERE id = :tid AND assignee_id = :uid
        """), {"tid": task_id, "uid": uid})).fetchone()
        if row is None:
            return TaskFacts(task_id=task_id, is_assignee=False)
        return TaskFacts(task_id=row[0], task_name=row[1], status=row[2], is_assignee=True)

    async def _resolve_candidates(self, db, uid: int, message: str) -> list[tuple[int, str]]:
        """Task của user khớp mô tả trong tin nhắn, xếp theo độ trùng từ khoá giảm dần.

        Bỏ qua từ lệnh/đệm ("update","task","done","cho","tôi"...). Một task là ứng
        viên khi trùng >=2 từ có nghĩa với tên (hoặc trùng 1 từ nếu tên chỉ có 1 từ
        nghĩa). Ưu tiên task chưa xong; chỉ xét task của chính user.
        """
        msg_tokens = {t for t in _TOKEN_RE.findall((message or "").lower()) if t not in _STOPWORDS and len(t) >= 2}
        if not msg_tokens:
            return []
        rows = (await db.execute(text("""
            SELECT id, name FROM tasks
            WHERE assignee_id = :uid AND status::text NOT IN ('DONE','CANCELLED')
        """), {"uid": uid})).fetchall()
        scored = []
        for tid, name in rows:
            name_tokens = {t for t in _TOKEN_RE.findall((name or "").lower())
                           if t not in _STOPWORDS and len(t) >= 2}
            if not name_tokens:
                continue
            overlap = len(name_tokens & msg_tokens)
            need = 1 if len(name_tokens) == 1 else 2
            if overlap >= need:
                scored.append((overlap, len(name or ""), tid, name))
        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        return [(tid, name) for _, _, tid, name in scored[:5]]

    def _choose_task_reply(self, candidates: list[tuple[int, str]], percent: int, user_profile) -> dict:
        """Trả reply kèm 'menu' nút bấm; payload mang task_id + % để bấm là cập nhật."""
        name_part = self._verify._name_part(user_profile)
        verb = "hoàn thành" if percent >= 100 else f"cập nhật {percent}%"
        menu = [{"label": (name[:45] + "…") if len(name) > 46 else name,
                 "payload": f"TASKUPD|{tid}|{percent}"} for tid, name in candidates]
        return {
            "type": "choose_task", "resolved": False,
            "message": f"Bạn{name_part} muốn {verb} task nào? Bấm chọn giúp mình:",
            "menu": menu,
        }

    async def apply_payload(self, message: str, user_id: str, db: AsyncSession | None = None) -> dict:
        """Xử lý payload nút bấm 'TASKUPD|<task_id>|<percent>' -> cập nhật task đó."""
        try:
            _, sid, spct = message.split("|", 2)
            task_id, percent = int(sid), int(spct)
            uid = int(user_id)
        except (ValueError, TypeError):
            return self._verify._reply("Mình chưa hiểu lựa chọn này, bạn thử lại nhé.", facts=TaskFacts())
        if db is not None:
            return await self._apply_payload_with_db(db, uid, task_id, percent)
        async with AsyncSessionLocal() as session:
            return await self._apply_payload_with_db(session, uid, task_id, percent)

    async def _apply_payload_with_db(self, db, uid: int, task_id: int, percent: int) -> dict:
        facts = await self._facts_for_task(db, uid, task_id)
        if not facts.is_resolved:
            return self._verify._reply(
                "Mình chưa thấy task này được giao cho bạn, kiểm tra lại giúp mình nhé.", facts=facts)
        return await self._finish_update(db, facts, uid, percent, None, "")

    # ── Lệnh /update: chọn task -> chọn trạng thái (quick-reply, stateless) ────
    # Gapo quick-reply chỉ render tốt ~9-10 nút -> mỗi TRANG 6 task + nút điều hướng
    # (⬅️ Trước / ➡️ Xem thêm) + Huỷ = tối đa 9 nút. Phân trang để xem HẾT task.
    _PAGE_SIZE = 6

    async def menu_my_tasks(self, user_id: str, query: str | None = None,
                            page: int = 1, db: AsyncSession | None = None) -> dict:
        """Menu DANH SÁCH task của user (phân trang) để bấm chọn (payload TASKPICK|id).

        query -> lọc theo từ khoá (mỗi từ ILIKE, hợp AND). page -> trang hiện tại;
        nút ➡️/⬅️ (payload TASKPAGE|<page>[|<query>]) để duyệt hết task qua các trang.
        """
        if db is not None:
            return await self._menu_my_tasks_with_db(db, user_id, query, page)
        async with AsyncSessionLocal() as session:
            return await self._menu_my_tasks_with_db(session, user_id, query, page)

    async def _menu_my_tasks_with_db(self, db, user_id: str, query: str | None, page: int) -> dict:
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return {"type": "task_menu", "message": "Không xác định được tài khoản của bạn."}
        page = max(1, page)

        where = "assignee_id = :uid"
        params: dict = {"uid": uid}
        terms = [t for t in _TOKEN_RE.findall((query or "").lower()) if len(t) >= 2]
        for i, term in enumerate(terms):
            where += f" AND name ILIKE :q{i}"
            params[f"q{i}"] = f"%{term}%"

        total = (await db.execute(
            text(f"SELECT COUNT(*) FROM tasks WHERE {where}"), params)).scalar() or 0
        if total == 0:
            if terms:
                return {"type": "task_menu",
                        "message": f"Không tìm thấy task nào khớp \"{query.strip()}\". "
                                   "Gõ /update để xem tất cả, hoặc thử từ khoá khác."}
            return {"type": "task_menu", "message": "Bạn chưa có task nào được giao."}

        pages = (total + self._PAGE_SIZE - 1) // self._PAGE_SIZE
        page = min(page, pages)
        params.update({"lim": self._PAGE_SIZE, "off": (page - 1) * self._PAGE_SIZE})
        rows = (await db.execute(text(f"""
            SELECT id, name, status::text FROM tasks
            WHERE {where}
            ORDER BY (status::text = 'DONE') ASC, (status::text = 'CANCELLED') ASC,
                     deadline ASC NULLS LAST, id ASC
            LIMIT :lim OFFSET :off
        """), params)).fetchall()

        menu = [{"label": self._task_label(name, st), "payload": f"TASKPICK|{tid}"}
                for tid, name, st in rows]
        # Nút điều hướng trang — giữ query trong payload để lọc xuyên trang.
        qsuffix = f"|{query.strip()}" if terms else ""
        if page > 1:
            menu.append({"label": "⬅️ Trước", "payload": f"TASKPAGE|{page - 1}{qsuffix}"})
        if page < pages:
            menu.append({"label": "➡️ Xem thêm", "payload": f"TASKPAGE|{page + 1}{qsuffix}"})
        menu.append({"label": "⛔ Huỷ", "payload": TASKCANCEL_PAYLOAD})

        if terms:
            head = f"Task khớp \"{query.strip()}\" ({total} task)"
        else:
            head = f"Task của bạn ({total} task)"
        head += f" — trang {page}/{pages}. Bấm task để cập nhật"
        head += " (gõ tên task để tìm nhanh):" if not terms else ":"
        return {"type": "task_menu", "message": head, "menu": menu}

    @staticmethod
    def _task_label(name: str, status: str) -> str:
        tag = {"DONE": " (xong)", "IN_PROGRESS": " (đang làm)",
               "CANCELLED": " (huỷ)"}.get(status, "")
        base = (name or "task")[:40]
        return f"{base}{tag}"

    async def menu_status(self, user_id: str, task_id: int, db: AsyncSession | None = None) -> dict:
        """Trả menu TRẠNG THÁI cho 1 task đã chọn (Hoàn thành/25/50/75%/Blocker)."""
        if db is not None:
            return await self._menu_status_with_db(db, user_id, task_id)
        async with AsyncSessionLocal() as session:
            return await self._menu_status_with_db(session, user_id, task_id)

    async def _menu_status_with_db(self, db, user_id: str, task_id: int) -> dict:
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return {"message": "Không xác định được tài khoản của bạn."}
        facts = await self._facts_for_task(db, uid, task_id)
        if not facts.is_resolved:
            return {"message": "Task này không phải của bạn hoặc không tồn tại."}
        menu = [
            {"label": "✅ Hoàn thành", "payload": f"TASKUPD|{task_id}|100"},
            {"label": "🔄 50%", "payload": f"TASKUPD|{task_id}|50"},
            {"label": "🔄 75%", "payload": f"TASKUPD|{task_id}|75"},
            {"label": "⛔ Đang kẹt (blocker)", "payload": f"TASKBLOCK|{task_id}"},
            {"label": "⏰ Gia hạn 3 ngày", "payload": f"TASKEXTEND|{task_id}|3"},
            {"label": "😴 Hoãn nhắc 1 ngày", "payload": f"TASKSNOOZE|{task_id}"},
            {"label": "✖ Huỷ", "payload": TASKCANCEL_PAYLOAD},
        ]
        return {"message": f"Cập nhật task '{facts.task_name}' — chọn trạng thái:", "menu": menu}

    async def extend_deadline(self, user_id: str, task_id: int, days: int,
                              db: AsyncSession | None = None) -> dict:
        """Gia hạn deadline task thêm `days` ngày (tính từ max(deadline, hôm nay))."""
        if db is not None:
            return await self._extend_with_db(db, user_id, task_id, days)
        async with AsyncSessionLocal() as session:
            return await self._extend_with_db(session, user_id, task_id, days)

    async def _extend_with_db(self, db, user_id: str, task_id: int, days: int) -> dict:
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return {"message": "Không xác định được tài khoản của bạn."}
        days = max(1, min(int(days), 30))
        row = (await db.execute(text("""
            UPDATE tasks
            SET deadline = GREATEST(COALESCE(deadline, CURRENT_DATE), CURRENT_DATE)
                           + (:days * INTERVAL '1 day'),
                updated_at = NOW()
            WHERE id = :tid AND assignee_id = :uid
            RETURNING name, deadline
        """), {"days": days, "tid": task_id, "uid": uid})).fetchone()
        if row is None:
            return {"message": "Task này không phải của bạn hoặc không tồn tại."}
        await db.commit()
        return {"message": f"Đã gia hạn task '{row[0]}' thêm {days} ngày, deadline mới: "
                           f"{row[1].date().isoformat() if hasattr(row[1], 'date') else row[1]}."}

    async def snooze_reminder(self, user_id: str, task_id: int,
                              db: AsyncSession | None = None) -> dict:
        """Hoãn NHẮC deadline task này 1 ngày (không đổi deadline thật)."""
        if db is not None:
            return await self._snooze_with_db(db, user_id, task_id)
        async with AsyncSessionLocal() as session:
            return await self._snooze_with_db(session, user_id, task_id)

    async def _snooze_with_db(self, db, user_id: str, task_id: int) -> dict:
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return {"message": "Không xác định được tài khoản của bạn."}
        row = (await db.execute(text("""
            UPDATE tasks SET snooze_reminder_until = CURRENT_DATE + 1, updated_at = NOW()
            WHERE id = :tid AND assignee_id = :uid
            RETURNING name
        """), {"tid": task_id, "uid": uid})).fetchone()
        if row is None:
            return {"message": "Task này không phải của bạn hoặc không tồn tại."}
        await db.commit()
        return {"message": f"Đã hoãn nhắc task '{row[0]}' 1 ngày. Mai mình sẽ không nhắc task này nữa nhé."}

    async def apply_blocker(self, user_id: str, task_id: int, db: AsyncSession | None = None) -> dict:
        """Tạo blocker (chưa giải quyết) cho task -> đẩy điểm rủi ro project lên."""
        if db is not None:
            return await self._apply_blocker_with_db(db, user_id, task_id)
        async with AsyncSessionLocal() as session:
            return await self._apply_blocker_with_db(session, user_id, task_id)

    async def _apply_blocker_with_db(self, db, user_id: str, task_id: int) -> dict:
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return {"message": "Không xác định được tài khoản của bạn."}
        row = (await db.execute(text("""
            SELECT name, project_id FROM tasks WHERE id = :tid AND assignee_id = :uid
        """), {"tid": task_id, "uid": uid})).fetchone()
        if row is None:
            return {"message": "Task này không phải của bạn hoặc không tồn tại."}
        await db.execute(text("""
            INSERT INTO task_blockers (task_id, severity, description)
            VALUES (:tid, 'MED'::"BlockerSeverity", :desc)
        """), {"tid": task_id, "desc": "Báo blocker nhanh qua /update"})
        await db.commit()
        # Blocker -> rủi ro project tăng: quét lại near-real-time (best-effort).
        try:
            from app.services.risk_alert_service import RiskAlertService
            await RiskAlertService.trigger_for_project(row[1])
        except Exception:
            logger.exception("trigger risk sau blocker lỗi task=%s", task_id)
        return {"message": f"Đã ghi nhận blocker cho task '{row[0]}'. Bạn nhắn thêm chi tiết "
                           "nếu cần, và cập nhật lại khi gỡ được nhé."}

    @staticmethod
    async def _recompute_milestone(db, milestone_id: int) -> None:
        """Đồng bộ thống kê milestone (giống tasks/router._recompute_milestone)."""
        await db.execute(text("""
            UPDATE milestones SET
                done_count = (
                    SELECT COUNT(*) FROM tasks
                    WHERE milestone_id = :mid AND status = 'DONE'::"TaskStatus"
                ),
                completion_pct = (
                    SELECT CASE WHEN COUNT(*) = 0 THEN 0
                    ELSE ROUND(COUNT(*) FILTER (WHERE status = 'DONE'::"TaskStatus") * 100.0 / COUNT(*))
                    END FROM tasks WHERE milestone_id = :mid
                ),
                updated_at = NOW()
            WHERE id = :mid
        """), {"mid": milestone_id})

    def _confirm_message(self, task_name, percent, status, user_profile) -> str:
        name_part = self._verify._name_part(user_profile)
        if percent >= 100:
            return (
                f"Tuyệt vời{name_part}! Mình đã ghi nhận task '{task_name}' hoàn thành 100% "
                "và chuyển sang trạng thái Hoàn thành. Cảm ơn bạn nhé!"
            )
        return (
            f"Đã ghi nhận{name_part}: task '{task_name}' hiện ở mức {percent}% "
            "(Đang làm). Cảm ơn bạn đã cập nhật tiến độ!"
        )
