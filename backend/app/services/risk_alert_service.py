"""Cảnh báo rủi ro có PM phê duyệt — human-in-the-loop (sơ đồ Luồng 4, ⑰⑱⑲⑳).

Luồng:
  1. scan_and_alert(): quét at-risk (risk_detector) -> soạn cảnh báo + đề xuất ->
     gửi DM cho PM (owner/account_manager) -> lưu risk_alerts (PENDING_PM_CONFIRMATION).
  2. PM trả lời trong DM -> message_router gọi find_pending_for() (STATE-GATE) ->
     classify_decision() phân APPROVE/DISMISS -> handle_decision() chốt trạng thái,
     (tuỳ chọn) broadcast cảnh báo vào group dự án.

Thiết kế phân loại xác nhận: LLM là chính, rule là lưới an toàn — và CHỈ chạy SAU
khi state-gate xác nhận có cảnh báo đang chờ (không thêm danh mục vào router toàn cục,
tránh lỗi định tuyến mở). Xem [[project_router_multiagent]].
"""
import json
import logging
import os
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from gapo.gapo_client import GapoClient
from ai_agent.notification.inapp_repository import create_notification
from app.services.risk_detector import detect_at_risk_projects, ProjectRisk

logger = logging.getLogger(__name__)

PENDING_TTL_HOURS = 48

# Sentinel để phân biệt "không truyền llm" (mặc định -> tự build từ env) với
# "truyền llm=None" (ép tắt LLM -> dùng rule/template, dùng trong test).
_LLM_UNSET = object()

# Đề xuất hành động tất định theo từng loại tín hiệu rủi ro.
_ACTION_HINTS = [
    ("overdue", "Rà soát & gia hạn hoặc giao lại các task quá hạn."),
    ("due_soon_low", "Ưu tiên đẩy nhanh các task sắp đến hạn còn tiến độ thấp."),
    ("stale", "Đốc thúc cập nhật trạng thái các task lâu không động đến."),
    ("unassigned", "Phân công người phụ trách cho các task chưa có owner."),
]

# Nhãn ngắn cho từng loại rủi ro của task (hiển thị cạnh tên task).
_TASK_REASON_LABEL = {
    "blocked": "đang bị blocker",
    "overdue": "quá hạn",
    "due_soon_low": "sắp đến hạn, tiến độ thấp",
    "stale": "lâu không cập nhật",
    "unassigned": "chưa có người phụ trách",
}

# Mẫu hành động cá nhân hoá theo loại rủi ro của TỪNG task (điền tên task + người).
def _task_action(reason: str, name: str, assignee: str | None) -> str:
    who = assignee or "team"
    return {
        "blocked":      f"Gỡ blocker cho '{name}' (hỏi {who} vướng gì, hỗ trợ ngay).",
        "overdue":      f"Chốt deadline mới hoặc giao lại '{name}' (đang trễ — {who}).",
        "due_soon_low": f"Đốc thúc {who} đẩy nhanh '{name}' (sắp đến hạn, tiến độ thấp).",
        "unassigned":   f"Phân công người phụ trách cho '{name}'.",
        "stale":        f"Yêu cầu {who} cập nhật tiến độ '{name}' (lâu không động).",
    }.get(reason, f"Rà soát '{name}'.")

_APPROVE_WORDS = (
    "ok", "oke", "okay", "duyệt", "duyet", "đồng ý", "dong y", "gửi", "gui",
    "xác nhận", "xac nhan", "yes", "ừ", "u", "uh", "đồng ý gửi", "chốt", "chot",
)
_DISMISS_WORDS = (
    "không", "khong", "bỏ qua", "bo qua", "khoan", "để sau", "de sau", "thôi",
    "thoi", "huỷ", "huy", "hủy", "no", "khỏi", "khoi", "đừng", "dung gui",
)


@dataclass
class PendingAlert:
    id: int
    project_id: int
    project_name: str
    draft_message: str
    pm_user_id: int


class RiskAlertService:
    def __init__(self, gapo: GapoClient | None = None, llm=_LLM_UNSET):
        self.gapo = gapo or GapoClient()
        # LLM dùng để (a) soạn cảnh báo đẹp hơn, (b) phân loại xác nhận.
        # Không truyền -> tự build từ env; truyền None -> tắt LLM (rule/template).
        self.llm = self._build_llm() if llm is _LLM_UNSET else llm

    @staticmethod
    def _build_llm():
        model, api_key, base_url = (
            os.getenv("MODEL_NAME"), os.getenv("API_KEY"), os.getenv("BASE_URL"),
        )
        if model and api_key and base_url:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(model=model, timeout=30, api_key=api_key,
                              base_url=base_url, reasoning_effort="none")
        return None

    # ── 1. QUÉT & GỬI CẢNH BÁO ────────────────────────────────────────────────
    async def scan_and_alert(self, db: AsyncSession, today_iso: str,
                             project_id: int | None = None) -> dict:
        """Quét at-risk và gửi cảnh báo PENDING cho PM. Trả thống kê {sent, skipped}.

        project_id != None -> chỉ quét đúng 1 project (near-real-time).
        """
        risks = await detect_at_risk_projects(db, project_id=project_id)
        sent = skipped = 0
        for risk in risks:
            pm_id = risk.pm_user_id
            if not pm_id:
                skipped += 1
                continue
            correlation_id = f"risk:{risk.project_id}:{today_iso}"
            exists = (await db.execute(text("""
                SELECT 1 FROM risk_alerts WHERE correlation_id = :cid LIMIT 1
            """), {"cid": correlation_id})).fetchone()
            if exists:
                skipped += 1
                continue

            thread_id, gapo_user_id = await self._resolve_pm_channel(db, pm_id)
            draft = self.build_draft_message(risk)

            await db.execute(text("""
                INSERT INTO risk_alerts
                    (project_id, pm_user_id, risk_score, risk_level, reasons,
                     draft_message, status, thread_id, correlation_id, created_at, updated_at)
                VALUES
                    (:pid, :pm, :score, :level, CAST(:reasons AS jsonb),
                     :draft, 'PENDING_PM_CONFIRMATION', :thread, :cid, NOW(), NOW())
            """), {
                "pid": risk.project_id, "pm": pm_id, "score": risk.score,
                "level": risk.level, "reasons": json.dumps(risk.reasons, ensure_ascii=False),
                "draft": draft, "thread": str(thread_id) if thread_id else None,
                "cid": correlation_id,
            })
            await create_notification(
                db, user_id=pm_id, type="risk_alert",
                title=f"Cảnh báo rủi ro: {risk.project_name}",
                body=f"Mức {risk.level} — cần bạn xác nhận", link="/projects", commit=False,
            )
            await db.execute(text("""
                INSERT INTO agent_audit_log (tool, args_json, source, correlation_id, created_at)
                VALUES ('risk_alert', CAST(:args AS jsonb), CAST('cron' AS "AgentAuditSource"),
                        :cid, NOW())
            """), {
                "args": json.dumps({"project_id": risk.project_id, "pm_user_id": pm_id,
                                    "score": risk.score, "level": risk.level}),
                "cid": correlation_id,
            })
            await db.commit()

            # Gửi DM cho PM — ưu tiên receiver_id (DM chủ động, Gapo tự định tuyến
            # thread 1-1 đúng người; POST vào thread_id cũ có thể 200 nhưng không giao).
            # GỬI THẤT BẠI -> đánh EXPIRED ngay: alert "ma" (PENDING mà PM chưa từng
            # thấy) sẽ khiến state-gate chặn hội thoại của PM vô cớ.
            try:
                if gapo_user_id:
                    await self.gapo.send_to_user(receiver_id=gapo_user_id, text=draft)
                elif thread_id:
                    await self.gapo.send_message(thread_id=str(thread_id), text=draft)
                else:
                    raise RuntimeError("PM chưa liên kết Gapo (không có receiver/thread)")
                sent += 1
            except Exception:
                logger.exception("Gửi DM cảnh báo cho PM=%s thất bại — expire alert", pm_id)
                await db.execute(text("""
                    UPDATE risk_alerts
                    SET status = 'EXPIRED', decision_note = 'dm_send_failed', updated_at = NOW()
                    WHERE correlation_id = :cid
                """), {"cid": correlation_id})
                await db.commit()
                skipped += 1

        logger.info("[Risk] scan_and_alert sent=%d skipped=%d", sent, skipped)
        return {"sent": sent, "skipped": skipped}

    async def _resolve_pm_channel(self, db, pm_id):
        row = (await db.execute(text("""
            SELECT gapo_thread_id, gapo_user_id FROM gapo_user_maps WHERE user_id = :uid
        """), {"uid": pm_id})).fetchone()
        if not row:
            return None, None
        return row[0], row[1]

    def build_draft_message(self, risk: ProjectRisk) -> str:
        """Soạn nội dung cảnh báo + đề xuất. Dùng template tất định (LLM tuỳ chọn)."""
        # Đề xuất CÁ NHÂN HOÁ theo từng task cụ thể (đích danh + người); nếu không
        # có task chi tiết thì rơi về gợi ý tổng quát theo loại tín hiệu.
        if risk.top_tasks:
            actions = [_task_action(t.reason, t.name, t.assignee) for t in risk.top_tasks]
            if risk.extra_tasks:
                actions.append(f"Rà soát {risk.extra_tasks} task rủi ro còn lại.")
        else:
            counts = {"overdue": risk.overdue, "due_soon_low": risk.due_soon_low,
                      "stale": risk.stale, "unassigned": risk.unassigned}
            actions = [hint for key, hint in _ACTION_HINTS if counts.get(key)]

        # Liệt kê TASK CỤ THỂ (đích danh) thay vì chỉ nêu con số tổng quát.
        task_lines = []
        for t in risk.top_tasks:
            label = _TASK_REASON_LABEL.get(t.reason, t.reason or "")
            meta = []
            if t.deadline:
                meta.append(f"hạn {t.deadline}")
            meta.append(t.assignee or "chưa giao")
            task_lines.append(f"- {t.name} ({label} — {', '.join(meta)})")
        if risk.extra_tasks:
            task_lines.append(f"- …và {risk.extra_tasks} task rủi ro khác")

        lines = [
            f"⚠️ **Cảnh báo rủi ro dự án: {risk.project_name}**",
            f"Mức độ: {risk.level} (điểm rủi ro {risk.score})",
            "",
            "Lý do:",
            *[f"- {r}" for r in risk.reasons],
        ]
        if task_lines:
            lines += ["", "Task cần chú ý:", *task_lines]
        lines += [
            "",
            "Đề xuất hành động:",
            *[f"- {a}" for a in actions],
            "",
            'Bạn xác nhận ghi nhận/gửi cảnh báo này chứ? Trả lời "OK/duyệt" để xác nhận, '
            '"bỏ qua" để huỷ.',
        ]
        template = "\n".join(lines)
        if self.llm is None:
            return template
        try:
            prompt = (
                "Bạn là trợ lý PM. Viết lại cảnh báo rủi ro dưới đây cho mạch lạc, "
                "thân thiện, GIỮ NGUYÊN số liệu và các đề xuất, kết thúc bằng câu hỏi "
                "xác nhận. KHÔNG bịa thêm số liệu.\n\n" + template
            )
            resp = self.llm.invoke(prompt)
            return (resp.content or "").strip() or template
        except Exception:
            logger.exception("[Risk] LLM soạn cảnh báo lỗi, dùng template")
            return template

    # ── 2. STATE-GATE: có cảnh báo đang chờ PM này không? ─────────────────────
    async def find_pending_list(self, db: AsyncSession, user_id: str, thread_id: str | None) -> list[PendingAlert]:
        """TẤT CẢ cảnh báo PENDING của PM trong thread (mới nhất trước), còn TTL.

        Trả list để quyết định của PM áp cho TOÀN BỘ (PM sở hữu nhiều project
        at-risk -> nhiều alert cùng thread; duyệt từng cái một sẽ khiến tin nhắn
        kế tiếp lại bị gate bắt — và PM không biết mình đang duyệt cái nào).
        """
        if not thread_id:
            return []
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return []
        rows = (await db.execute(text("""
            SELECT ra.id, ra.project_id, p.name, ra.draft_message, ra.pm_user_id
            FROM risk_alerts ra
            JOIN projects p ON p.id = ra.project_id
            WHERE ra.pm_user_id = :uid AND ra.thread_id = :thread
              AND ra.status = 'PENDING_PM_CONFIRMATION'
              AND ra.created_at >= NOW() - (CAST(:ttl AS int) * INTERVAL '1 hour')
            ORDER BY ra.created_at DESC
        """), {"uid": uid, "thread": str(thread_id), "ttl": PENDING_TTL_HOURS})).fetchall()
        return [PendingAlert(id=r[0], project_id=r[1], project_name=r[2],
                             draft_message=r[3], pm_user_id=r[4]) for r in rows]

    async def find_pending_for(self, db: AsyncSession, user_id: str, thread_id: str | None) -> PendingAlert | None:
        """Cảnh báo PENDING mới nhất (giữ cho tương thích cũ/test)."""
        alerts = await self.find_pending_list(db, user_id, thread_id)
        return alerts[0] if alerts else None

    # ── Phân loại APPROVE / DISMISS / UNCLEAR ─────────────────────────────────
    def classify_decision(self, message: str) -> str:
        """LLM chính, rule lưới. Trả 'approve' | 'dismiss' | 'unclear'."""
        if self.llm is not None:
            try:
                return self._llm_decision(message)
            except Exception:
                logger.exception("[Risk] LLM classify lỗi, dùng rule")
        return self._rule_decision(message)

    def _rule_decision(self, message: str) -> str:
        lowered = (message or "").lower().strip()
        # Ưu tiên DISMISS khi có phủ định rõ ("không gửi") để không bị "gửi" lừa.
        if any(w in lowered for w in _DISMISS_WORDS):
            return "dismiss"
        if any(w in lowered for w in _APPROVE_WORDS):
            return "approve"
        return "unclear"

    def _llm_decision(self, message: str) -> str:
        prompt = (
            "PM vừa nhận một cảnh báo rủi ro và đang trả lời. Phân loại câu trả lời "
            "thành ĐÚNG MỘT từ: approve (đồng ý/duyệt/gửi), dismiss (bỏ qua/không gửi/để sau), "
            "hoặc unclear (không rõ). CHỈ in ra một từ đó.\n\n"
            f'Câu trả lời: "{message}"\nKết quả:'
        )
        resp = self.llm.invoke(prompt)
        out = (resp.content or "").strip().lower()
        for label in ("approve", "dismiss", "unclear"):
            if label in out:
                return label
        return self._rule_decision(message)

    # ── 3. CHỐT QUYẾT ĐỊNH ────────────────────────────────────────────────────
    async def apply_decision(
        self, db: AsyncSession, alerts: list[PendingAlert], decision: str, note: str,
    ) -> str:
        """Áp quyết định approve/dismiss cho TOÀN BỘ alerts. Trả câu phản hồi cho PM.

        Chống race: UPDATE có guard ``status='PENDING_PM_CONFIRMATION'`` và chỉ
        ghi audit / broadcast cho alert mà CHÍNH transaction này chuyển trạng thái
        (rowcount=1). Hai tin nhắn đồng thời -> tin thứ 2 update 0 dòng -> không
        duyệt/đăng group lần hai.
        """
        new_status = "APPROVED" if decision == "approve" else "DISMISSED"
        applied: list[PendingAlert] = []
        for alert in alerts:
            res = await db.execute(text("""
                UPDATE risk_alerts
                SET status = :st, decided_at = NOW(), decision_note = :note, updated_at = NOW()
                WHERE id = :id AND status = 'PENDING_PM_CONFIRMATION'
            """), {"st": new_status, "note": note, "id": alert.id})
            if res.rowcount != 1:
                continue  # alert đã được xử lý bởi request khác -> bỏ qua
            applied.append(alert)
            await db.execute(text("""
                INSERT INTO agent_audit_log (tool, args_json, source, created_at)
                VALUES ('risk_alert_decision', CAST(:args AS jsonb), CAST('chat' AS "AgentAuditSource"), NOW())
            """), {"args": json.dumps({"alert_id": alert.id, "project_id": alert.project_id,
                                       "decision": decision})})
        await db.commit()

        # Nếu không có alert nào do request này chốt (đã bị xử lý song song trước đó).
        if not applied:
            return "Cảnh báo rủi ro này đã được xử lý rồi. Cảm ơn bạn nhé!"

        names = ", ".join(f"'{a.project_name}'" for a in applied)
        if decision == "dismiss":
            return f"Đã bỏ qua cảnh báo rủi ro cho dự án {names}. Khi cần bạn cứ nhắn mình nhé."

        # APPROVE: (tuỳ chọn) broadcast vào group dự án nếu đã liên kết.
        broadcasted = 0
        for alert in applied:
            if await self._maybe_broadcast(db, alert):
                broadcasted += 1
        suffix = f" và đã đăng vào group dự án ({broadcasted})" if broadcasted else ""
        return f"Đã xác nhận cảnh báo rủi ro dự án {names}{suffix}. Cảm ơn bạn đã duyệt!"

    async def handle_decision(self, db: AsyncSession, alert: PendingAlert, message: str) -> str:
        """Phân loại + chốt MỘT cảnh báo (giữ tương thích cũ/test)."""
        decision = self.classify_decision(message)
        if decision == "unclear":
            return (
                f"Mình chưa rõ ý bạn về cảnh báo dự án '{alert.project_name}'. "
                'Trả lời "OK/duyệt" để xác nhận gửi, hoặc "bỏ qua" để huỷ giúp mình nhé.'
            )
        return await self.apply_decision(db, [alert], decision, message)

    # ── 4. QUÉT NEAR-REAL-TIME cho 1 project (gọi nền khi task thay đổi) ───────
    @staticmethod
    async def trigger_for_project(project_id: int) -> None:
        """Quét rủi ro NGAY cho 1 project (best-effort, chạy nền sau khi task đổi).

        An toàn để gọi trên mọi lần sửa task: dedup 'risk:{project}:{ngày}' đảm bảo
        tối đa 1 cảnh báo/project/ngày, nên không spam PM. Bật/tắt qua env
        RISK_REALTIME_ENABLED. Lỗi được nuốt để không ảnh hưởng request sửa task.
        """
        if os.getenv("RISK_REALTIME_ENABLED", "true").lower() not in {"1", "true", "yes", "on"}:
            return
        try:
            import pytz
            from datetime import datetime
            today = datetime.now(pytz.timezone("Asia/Ho_Chi_Minh")).date().isoformat()
            async with AsyncSessionLocal() as db:
                stats = await RiskAlertService().scan_and_alert(db, today_iso=today, project_id=project_id)
            if stats.get("sent"):
                logger.info("[Risk] realtime project=%s %s", project_id, stats)
        except Exception:
            logger.exception("[Risk] trigger_for_project lỗi project=%s", project_id)

    async def _maybe_broadcast(self, db, alert: PendingAlert) -> bool:
        row = (await db.execute(text("""
            SELECT gapo_thread_id FROM projects WHERE id = :pid
        """), {"pid": alert.project_id})).fetchone()
        group_thread = row[0] if row else None
        if not group_thread:
            return False
        try:
            await self.gapo.send_message(thread_id=str(group_thread), text=alert.draft_message)
            return True
        except Exception:
            logger.exception("[Risk] broadcast group cho project=%s lỗi", alert.project_id)
            return False
