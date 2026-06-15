"""Cảnh báo rủi ro — THÔNG BÁO THUẦN cho PM (không cần duyệt).

Luồng:
  scan_and_alert(): quét at-risk (risk_detector) -> soạn cảnh báo + đề xuất ->
  GỬI THẲNG DM cho PM (owner/account_manager) -> lưu risk_alerts ('APPROVED' = đã
  gửi & ghi nhận). KHÔNG còn bước PM duyệt/bỏ qua, KHÔNG broadcast group, KHÔNG
  state-gate. Bản ghi giữ để dedup 1 cảnh báo/project/ngày + audit.
"""
import json
import logging
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from gapo.gapo_client import GapoClient
from ai_agent.notification.inapp_repository import create_notification
from app.services.risk_detector import detect_at_risk_projects, ProjectRisk

logger = logging.getLogger(__name__)

# Sentinel để phân biệt "không truyền llm" (mặc định -> tự build từ env) với
# "truyền llm=None" (ép tắt LLM -> dùng template, dùng trong test).
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

class RiskAlertService:
    def __init__(self, gapo: GapoClient | None = None, llm=_LLM_UNSET):
        self.gapo = gapo or GapoClient()
        # LLM dùng để soạn cảnh báo mạch lạc hơn (tuỳ chọn; không có vẫn chạy template).
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
        """Quét at-risk và GỬI THẲNG cảnh báo (thông báo thuần) cho PM. {sent, skipped}.

        KHÔNG còn bước PM duyệt/bỏ qua: gửi DM xong là ghi 'APPROVED' (= đã gửi &
        ghi nhận). Bản ghi vẫn giữ để dedup 1 cảnh báo/project/ngày + audit.
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
                     :draft, 'APPROVED', :thread, :cid, NOW(), NOW())
            """), {
                "pid": risk.project_id, "pm": pm_id, "score": risk.score,
                "level": risk.level, "reasons": json.dumps(risk.reasons, ensure_ascii=False),
                "draft": draft, "thread": str(thread_id) if thread_id else None,
                "cid": correlation_id,
            })
            await create_notification(
                db, user_id=pm_id, type="risk_alert",
                title=f"Cảnh báo rủi ro: {risk.project_name}",
                body=f"Mức {risk.level} — dự án đang có rủi ro, bạn rà soát giúp nhé", link="/projects", commit=False,
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
            # GỬI THẤT BẠI -> đánh EXPIRED: bản ghi 'APPROVED' (đã gửi) nhưng PM chưa
            # từng thấy là sai sự thật; EXPIRED đánh dấu "thông báo không tới được".
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
            "Bạn rà soát và xử lý sớm giúp nhé.",
        ]
        template = "\n".join(lines)
        if self.llm is None:
            return template
        try:
            prompt = (
                "Bạn là trợ lý PM. Viết lại cảnh báo rủi ro dưới đây cho mạch lạc, "
                "thân thiện, GIỮ NGUYÊN số liệu và các đề xuất. KHÔNG bịa thêm số "
                "liệu. KHÔNG hỏi xác nhận (đây là thông báo, không cần PM duyệt).\n\n" + template
            )
            resp = self.llm.invoke(prompt)
            return (resp.content or "").strip() or template
        except Exception:
            logger.exception("[Risk] LLM soạn cảnh báo lỗi, dùng template")
            return template

    # ── QUÉT NEAR-REAL-TIME cho 1 project (gọi nền khi task thay đổi) ─────────
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
