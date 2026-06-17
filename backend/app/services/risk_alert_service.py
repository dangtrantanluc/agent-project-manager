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
            from ai_agent.shared.llm_factory import make_llm
            return make_llm(purpose="risk_alert", timeout=30, reasoning_effort="none",
                            model=model, api_key=api_key, base_url=base_url)
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

            thread_id, gapo_user_id, pm_name = await self._resolve_pm_channel(db, pm_id)
            draft = self.build_draft_message(risk, pm_name=pm_name)

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

    async def scan_and_alert_for_user(
        self, db: AsyncSession, *, user_id: int, today_iso: str
    ) -> dict:
        """Quét at-risk các dự án mà USER liên quan (owner/AM/member) rồi gửi cảnh báo.

        Dùng cho lệnh /risk thủ công: chỉ quét trong phạm vi quyền của user (không
        lộ dự án ngoài quyền). Mỗi project chạy qua scan_and_alert (dedup theo ngày).
        Trả {scanned, sent, skipped}.
        """
        project_ids = [r[0] for r in (await db.execute(text("""
            SELECT p.id FROM projects p
            WHERE p.status::text NOT IN ('DONE','CANCELLED')
              AND (
                  p.owner_id = :uid
                  OR p.account_manager_id = :uid
                  OR EXISTS (SELECT 1 FROM members m WHERE m.project_id = p.id AND m.user_id = :uid)
                  OR EXISTS (SELECT 1 FROM tasks t WHERE t.project_id = p.id AND t.assignee_id = :uid)
              )
        """), {"uid": user_id})).fetchall()]

        total = {"scanned": len(project_ids), "sent": 0, "skipped": 0}
        for pid in project_ids:
            stats = await self.scan_and_alert(db, today_iso=today_iso, project_id=pid)
            total["sent"] += stats.get("sent", 0)
            total["skipped"] += stats.get("skipped", 0)
        return total

    async def _resolve_pm_channel(self, db, pm_id):
        """Trả (thread_id, gapo_user_id, full_name) của PM để định tuyến DM + chào tên."""
        row = (await db.execute(text("""
            SELECT g.gapo_thread_id, g.gapo_user_id, u.full_name
            FROM users u
            LEFT JOIN gapo_user_maps g ON g.user_id = u.id
            WHERE u.id = :uid
        """), {"uid": pm_id})).fetchone()
        if not row:
            return None, None, None
        return row[0], row[1], row[2]

    # Số task nêu đích danh trong cảnh báo (giữ NGẮN; phần còn lại gộp "…và N khác").
    _MAX_LISTED_TASKS = 3

    def build_draft_message(self, risk: ProjectRisk, pm_name: str | None = None) -> str:
        """Soạn cảnh báo NGẮN GỌN đủ ý: chào + mức + vài task gấp + nút thắt + 1-2 hành động.

        Cố ý KHÔNG liệt kê task hai lần (một ở 'task chú ý', một ở 'đề xuất'): đề
        xuất gộp THEO LOẠI rủi ro, không mỗi task một dòng. Dùng template tất định
        (LLM tuỳ chọn, chỉ để mượt câu — bị ép giữ ngắn). pm_name để chào đích danh.
        """
        listed = risk.top_tasks[: self._MAX_LISTED_TASKS]
        # extra = task không liệt kê chi tiết (phần bị cắt khỏi top_tasks + extra_tasks gốc).
        extra = risk.extra_tasks + max(0, len(risk.top_tasks) - len(listed))

        # Top task: chỉ tên + hạn (bỏ nhãn lý do dài dòng — đã gói trong dòng "Lý do").
        task_lines = []
        for t in listed:
            suffix = f" (hạn {t.deadline})" if t.deadline else ""
            task_lines.append(f"- {t.name}{suffix}")
        if extra:
            task_lines.append(f"- …và {extra} task khác")

        # Người chịu phần lớn rủi ro: chỉ nêu khi mọi task đích danh cùng 1 người.
        owners = {t.assignee for t in listed if t.assignee}
        owner_note = f" Phần lớn do {next(iter(owners))} phụ trách." if len(owners) == 1 else ""

        # Đề xuất GỘP THEO LOẠI (1 dòng/loại có mặt), KHÔNG mỗi task một dòng.
        counts = {"overdue": risk.overdue, "due_soon_low": risk.due_soon_low,
                  "stale": risk.stale, "unassigned": risk.unassigned}
        actions = [hint for key, hint in _ACTION_HINTS if counts.get(key)]

        # Dòng chào đích danh PM (fallback "Chào bạn," khi chưa có tên).
        greeting = f"Chào {pm_name.strip()}," if pm_name and pm_name.strip() else "Chào bạn,"
        lines = [
            greeting,
            "",
            f"⚠️ Rủi ro {risk.level} — {risk.project_name} ({risk.score}đ)",
            "",
            # Lý do gộp 1 dòng (· ngăn cách) thay cho bullet rời từng số liệu.
            " · ".join(risk.reasons) + "." + owner_note,
        ]
        if task_lines:
            lines += ["", "Task gấp nhất:", *task_lines]
        # Nút thắt phụ thuộc: task chặn nhiều task nhất -> ưu tiên gỡ trước (ý giá trị cao).
        if risk.bottleneck:
            b = risk.bottleneck
            code = f"{b['code']} " if b.get("code") else ""
            lines += ["", f"🔗 Ưu tiên gỡ {code}{b['name']} trước — đang chặn {b['blocks_count']} task khác."]
        if actions:
            lines += ["", "→ " + " ".join(actions)]
        template = "\n".join(lines)

        if self.llm is None:
            return template
        try:
            prompt = (
                "Bạn là trợ lý PM. Viết lại cảnh báo rủi ro dưới đây cho mượt nhưng "
                "PHẢI NGẮN GỌN (tối đa ~9 dòng). GIỮ dòng chào đầu tiên (1 dòng, ngắn). "
                "GIỮ NGUYÊN số liệu, tên task, tên người. KHÔNG bịa số liệu. KHÔNG "
                "thêm xã giao dài dòng. KHÔNG liệt kê lại task ở phần đề xuất. "
                "KHÔNG hỏi xác nhận.\n\n" + template
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
