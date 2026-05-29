import logging
from datetime import date, datetime
import pytz
from sqlalchemy.ext.asyncio import AsyncSession

from ai_agent.checkin import repository as repo
from ai_agent.checkin.constants import (
    CheckinState, CheckinSlot,
    P_PROJECT, P_TASK, P_SKIP_TASK, P_CANCEL, P_ADD_MORE, P_DONE,
    CHECKIN_PREFIX, CHECKIN_TRIGGER,
)
from gapo.gapo_client import GapoClient
from ai_agent.checkin.worklog_parser.service import WorklogParserService

_VN_TZ = pytz.timezone("Asia/Ho_Chi_Minh")
logger = logging.getLogger(__name__)


class CheckinFlowService:
    def __init__(self, gapo: GapoClient, worklog_parser: WorklogParserService):
        self.gapo = gapo
        self.parser = worklog_parser

    # ── Public entry points ────────────────────────────────────────────────────

    async def start_for_user(self, db: AsyncSession, *, user: dict, slot: str) -> None:
        """Called from scheduler. user dict: user_id, thread_id, gapo_user_id."""
        work_date = datetime.now(_VN_TZ).date()
        expires_at = repo._calc_expires_at(slot)
        session = await repo.upsert_session(
            db,
            user_id=user["user_id"],
            gapo_user_id=user["gapo_user_id"], thread_id=user["thread_id"],
            work_date=work_date, slot=slot, expires_at=expires_at,
        )
        sent = await self._send_project_menu(db, session)
        if not sent:
            logger.error(
                "[Checkin] send_project_menu failed for user=%d slot=%s "
                "— session %d remains, user can type /checkin to recover.",
                user["user_id"], slot, session["id"],
            )
            await repo.insert_audit(
                db, tool="gapo_send_menu",
                args={"user_id": user["user_id"], "slot": slot, "session_id": session["id"]},
                error="send_project_menu failed after retries",
            )

    async def start_manual(
        self, db: AsyncSession, *,
        user_id: int, gapo_user_id: str, thread_id: str,
    ) -> str:
        await repo.cancel_all_active_sessions(db, user_id)
        work_date = datetime.now(_VN_TZ).date()
        expires_at = repo._calc_expires_at(CheckinSlot.MANUAL)
        session = await repo.upsert_session(
            db,
            user_id=user_id,
            gapo_user_id=gapo_user_id, thread_id=thread_id,
            work_date=work_date, slot=CheckinSlot.MANUAL, expires_at=expires_at,
        )
        await self._send_project_menu(db, session)
        return ""

    async def handle_message(
        self, db: AsyncSession, *,
        message_text: str,
        gapo_user_id: str,
        conversation_id: str,
        user_id: int,
    ) -> str | None:
        """
        Returns reply string if message handled by checkin flow.
        Returns None if unrelated — caller routes to intent router.
        Empty string "" means already sent via gapo.send_menu/send_message.
        """
        await repo.expire_old_sessions(db)

        # "checkin", "/checkin", "check-in" etc. → always start/restart from project menu
        if CHECKIN_TRIGGER.match(message_text.strip()):
            await self.start_manual(
                db, user_id=user_id,
                gapo_user_id=gapo_user_id, thread_id=conversation_id,
            )
            return ""

        if message_text.startswith(CHECKIN_PREFIX):
            session = await repo.get_active_session(db, user_id)
            if session:
                return await self._handle_payload(db, session, message_text)
            return "Session check-in đã hết hạn. Go /checkin để bắt đầu lại."

        session = await repo.get_active_session(db, user_id)
        if session:
            return await self._continue_flow(db, session, message_text)

        return None

    # ── Payload handler (button presses from Gapo menu) ───────────────────────

    async def _handle_payload(self, db: AsyncSession, session: dict, payload: str) -> str:
        uid = session["user_id"]
        sid = session["id"]

        if payload == P_CANCEL:
            await repo.cancel_all_active_sessions(db, uid)
            return "Đã hủy check-in."

        if payload == P_DONE:
            await repo.complete_session(db, sid, session.get("pending_parsed") or {})
            await repo.cancel_all_active_sessions(db, uid)
            return "Check-in hoàn tất! Cảm ơn bạn."

        if payload == P_ADD_MORE:
            project_id = session["current_project_id"]
            if session["state"] == CheckinState.CONFIRMING:
                # Keep project, clear task, go back to task selection
                if not project_id:
                    await self._send_project_menu(db, session)
                    return ""
                await repo.goto_add_more(db, sid, project_id)
                session["current_project_id"] = project_id
                session["current_task_id"] = None
                return await self._send_task_menu(db, session)
            # add_more from other states (edge case)
            if not project_id:
                await self._send_project_menu(db, session)
                return ""
            return await self._send_task_menu(db, session)

        if payload.startswith(P_PROJECT) and session["state"] == CheckinState.AWAITING_PROJECT:
            try:
                project_id = int(payload[len(P_PROJECT):])
            except ValueError:
                return "Payload không hợp lệ."
            ok = await repo.validate_project_access(
                db, user_id=uid, project_id=project_id
            )
            if not ok:
                return "Bạn không có quyền truy cập dự án này."
            await repo.set_session_state(db, sid, CheckinState.AWAITING_TASK, project_id=project_id)
            session["current_project_id"] = project_id
            return await self._send_task_menu(db, session)

        if payload.startswith(P_TASK) and session["state"] == CheckinState.AWAITING_TASK:
            try:
                task_id = int(payload[len(P_TASK):])
            except ValueError:
                return "Payload không hợp lệ."
            ok = await repo.validate_task_in_project(
                db, task_id=task_id,
                project_id=session["current_project_id"],
            )
            if not ok:
                return "Task không thuộc dự án đã chọn."
            task_name = await repo.get_task_name(db, task_id)
            await repo.set_session_state(db, sid, CheckinState.AWAITING_UPDATE, task_id=task_id)
            return (
                f"Task: *{task_name}*\n\n"
                    "Bạn đã làm gì hôm nay? Nhập mô tả + số giờ.\n"
                    "Ví du: *fix bug login 2h*"
            )

        if payload == P_SKIP_TASK and session["state"] == CheckinState.AWAITING_TASK:
            await repo.clear_task_from_session(db, sid)
            project_name = await repo.get_project_name(db, session["current_project_id"])
            return (
                f"Du an: *{project_name}* (khong chon task)\n\n"
                "Bạn đã làm gì hôm nay?\nVí dụ: *review code 1.5h*"
            )

        return "Hành động không hợp lệ hoặc session đã thay đổi trạng thái."

    # ── Free-text continuation ─────────────────────────────────────────────────

    async def _continue_flow(self, db: AsyncSession, session: dict, message_text: str) -> str:
        state = session["state"]
        stripped = message_text.strip()

        # AWAITING_UPDATE: parse and store worklog
        if state == CheckinState.AWAITING_UPDATE:
            return await self._handle_worklog_input(db, session, message_text)

        # CONFIRMING: user sent free text instead of pressing a button
        if state == CheckinState.CONFIRMING:
            return await self._remind_confirming(db, session)

        # AWAITING_PROJECT / AWAITING_TASK: check for numeric or text-search input
        if state in (CheckinState.AWAITING_PROJECT, CheckinState.AWAITING_TASK):
            lowered = stripped.lower()
            if lowered in {"hủy", "huy", "cancel", "thoát", "thoat"}:
                return await self._handle_payload(db, session, P_CANCEL)
            if state == CheckinState.AWAITING_TASK and lowered in {"bỏ qua", "bo qua", "skip"}:
                return await self._handle_payload(db, session, P_SKIP_TASK)
            if stripped.isdigit():
                return await self._handle_numeric_input(db, session, int(stripped))
            if stripped:
                return await self._handle_text_search(db, session, stripped)

        return await self._remind_current_state(db, session)

    async def _handle_numeric_input(self, db: AsyncSession, session: dict, index: int) -> str:
        """Resolve a numbered menu selection (fallback when quick_reply unavailable)."""
        pending = session.get("pending_parsed")
        if not isinstance(pending, dict) or pending.get("type") != "menu":
            return "Vui lòng chọn menu hoặc gõ /checkin để bắt đầu lại."
        items = pending.get("items", [])
        item = next((i for i in items if i.get("index") == index), None)
        if not item:
            return f"Số {index} không hợp lệ. Vui lòng chọn lại."
        return await self._handle_payload(db, session, item["payload"])

    async def _handle_text_search(self, db: AsyncSession, session: dict, query: str) -> str:
        """Search project or task by keyword and re-send filtered menu."""
        state = session["state"]

        if state == CheckinState.AWAITING_PROJECT:
            projects = await repo.list_project_candidates(
                db, user_id=session["user_id"], q=query
            )
            if not projects:
                return f"Không tìm thấy dự án nào với từ khóa '{query}'. Thử lại hoặc gõ /checkin."
            numbered = "\n".join(f"{i + 1}. {p['name']}" for i, p in enumerate(projects))
            title = (
                f"Kết quả '{query}':\n\n"
                f"{numbered}\n\n"
                'Hoặc tìm tiếp, hoặc "hủy".'
            )
            actions = [
                {"label": p["name"][:20], "payload": f"{P_PROJECT}{p['id']}"}
                for p in projects
            ]
            actions.append({"label": "Hủy", "payload": P_CANCEL})
            await repo.set_state_with_menu_mapping(
                db, session["id"], CheckinState.AWAITING_PROJECT, "project",
                [{"index": i + 1, "id": p["id"], "label": p["name"], "payload": f"{P_PROJECT}{p['id']}"}
                 for i, p in enumerate(projects)],
            )
            await self.gapo.send_menu(session["thread_id"], title, actions)
            return ""

        if state == CheckinState.AWAITING_TASK:
            tasks = await repo.list_task_candidates(
                db,
                user_id=session["user_id"],
                project_id=session["current_project_id"],
                q=query,
            )
            if not tasks:
                return f"Không tìm thấy task nào với từ khóa '{query}'. Thử lại hoặc gõ /checkin."
            project_name = await repo.get_project_name(db, session["current_project_id"])
            numbered = "\n".join(f"{i + 1}. {t['name']}" for i, t in enumerate(tasks))
            title = (
                f"{project_name}\nKết quả '{query}':\n\n"
                f"{numbered}\n\n"
                'Hoặc tìm tiếp, hoặc "bỏ qua" task.'
            )
            actions = [
                {"label": t["name"][:20], "payload": f"{P_TASK}{t['id']}"}
                for t in tasks
            ]
            actions.append({"label": "Bỏ qua task", "payload": P_SKIP_TASK})
            actions.append({"label": "Hủy", "payload": P_CANCEL})
            await repo.set_state_with_menu_mapping(
                db, session["id"], CheckinState.AWAITING_TASK, "task",
                [{"index": i + 1, "id": t["id"], "label": t["name"], "payload": f"{P_TASK}{t['id']}"}
                 for i, t in enumerate(tasks)],
            )
            await self.gapo.send_menu(session["thread_id"], title, actions)
            return ""

        return await self._remind_current_state(db, session)

    # ── Worklog input ──────────────────────────────────────────────────────────

    async def _handle_worklog_input(self, db: AsyncSession, session: dict, message_text: str) -> str:
        # 1. Load clarify context BEFORE update_session_pending overwrites pending_parsed
        _pending = session.get("pending_parsed") or {}
        _is_clarify = isinstance(_pending, dict) and _pending.get("type") == "clarify"
        prev_question: str | None = _pending.get("clarify_question") if _is_clarify else None
        prev_partial: dict | None = _pending.get("partial_draft") if _is_clarify else None
        clarify_count: int = int(_pending.get("clarify_count", 0)) if _is_clarify else 0

        # 2. Save raw pending_text (parse may fail)
        await repo.update_session_pending(db, session["id"], message_text)

        # 3. Idempotency: prevent duplicate worklog from same message
        dup_id = await repo.check_duplicate_worklog(
            db, session_id=session["id"], raw_message=message_text
        )
        if dup_id:
            return (
                f"Worklog này đã tồn tại (#{dup_id}).\n"
                "Nhập nội dung khác hoặc chọn 'Xong'."
            )

        # 4. LLM parse (with clarify context if this is a follow-up turn)
        parsed = await self.parser.parse(
            message_text, prev_question=prev_question, prev_partial=prev_partial
        )

        # 5. Clarification loop (max 3 attempts then cancel)
        if parsed.get("needs_clarification"):
            new_count = clarify_count + 1
            if new_count >= 3:
                await repo.cancel_session(db, session["id"])
                return (
                    "Mình chưa parse được worklog sau 3 lần thử. "
                    "Đã hủy check-in. Gõ /checkin để bắt đầu lại."
                )
            clarify_state = {
                "type": "clarify",
                "clarify_question": parsed.get("clarification_question"),
                "clarify_count": new_count,
                "partial_draft": {
                    k: parsed.get(k)
                    for k in ("description", "work_date", "status")
                    if parsed.get(k)
                },
            }
            await repo.update_session_pending(db, session["id"], message_text, clarify_state)
            q = parsed.get("clarification_question") or "Bạn nói rõ thêm giúp mình nhé."
            return f"{q}\n\n(Gõ \"hủy\" nếu muốn dừng.)"

        if "error" in parsed:
            return f"{parsed['error']}"

        # 6. Validate hours
        try:
            hours = float(parsed["hours"])
        except (TypeError, ValueError):
            return "Không đọc được số giờ. Vui lòng nhập lại, ví dụ: '2h fix bug'."
        if hours <= 0 or hours > 24:
            return "Số giờ không hợp lệ (phải từ 0.5 đến 24). Vui lòng nhập lại."

        # 7. Parse work_date
        work_date_str: str = parsed.get("work_date") or str(session["work_date"])
        try:
            work_date = date.fromisoformat(work_date_str)
        except ValueError:
            work_date = session["work_date"]
            work_date_str = str(work_date)

        description: str | None = parsed.get("description")

        # 8. Insert worklog
        worklog_id = await repo.insert_worklog(
            db,
            work_date=work_date,
            description=description,
            hours=hours,
            task_id=session["current_task_id"],
            project_id=session["current_project_id"],
            user_id=session["user_id"],
            raw_message=message_text,
            parsed_json=parsed,
            checkin_session_id=session["id"],
            slot=session["slot"],
        )
        await repo.apply_worklog_side_effects(
            db,
            project_id=session["current_project_id"],
            task_id=session["current_task_id"],
            user_id=session["user_id"],
            work_date=work_date,
            parsed_json=parsed,
        )

        # 9. Move to CONFIRMING (do NOT complete yet — user may want add_more)
        await repo.set_session_confirming(db, session["id"], parsed)

        # 10. Build confirm message
        project_name = await repo.get_project_name(db, session["current_project_id"])
        task_name = (
            await repo.get_task_name(db, session["current_task_id"])
            if session["current_task_id"] else "Khong co task"
        )
        summary = (
            f"Da luu worklog #{worklog_id}\n"
            f"{project_name} / {task_name}\n"
            f"{hours}h — {work_date_str}"
        )
        if description:
            summary += f"\n{description}"

        actions = [
            {"label": "Thêm worklog khác", "payload": P_ADD_MORE},
            {"label": "Xong", "payload": P_DONE},
        ]
        sent = await self.gapo.send_menu(session["thread_id"], summary, actions)
        if not sent:
            logger.error(
                "[Checkin] confirm menu failed thread=%s worklog=%d",
                session["thread_id"], worklog_id,
            )
        return ""

    # ── State reminders ────────────────────────────────────────────────────────

    async def _remind_confirming(self, db: AsyncSession, session: dict) -> str:
        """Re-send add_more/done menu when user sends free text during CONFIRMING."""
        project_name = await repo.get_project_name(db, session["current_project_id"])
        title = f"Da luu worklog cho {project_name}.\nBan muon:"
        actions = [
            {"label": "Thêm worklog khác", "payload": P_ADD_MORE},
            {"label": "Xong", "payload": P_DONE},
        ]
        await self.gapo.send_menu(session["thread_id"], title, actions)
        return ""

    async def _remind_current_state(self, db: AsyncSession, session: dict) -> str:
        state = session["state"]
        if state == CheckinState.AWAITING_PROJECT:
            await self._send_project_menu(db, session)
            return ""
        if state == CheckinState.AWAITING_TASK:
            return await self._send_task_menu(db, session)
        if state == CheckinState.CONFIRMING:
            return await self._remind_confirming(db, session)
        return "Go /checkin de bat dau check-in moi."

    # ── Menu senders ───────────────────────────────────────────────────────────

    async def _send_project_menu(self, db: AsyncSession, session: dict) -> bool:
        projects = await repo.list_project_candidates(
            db, user_id=session["user_id"]
        )

        if not projects:
            await repo.set_session_state(db, session["id"], CheckinState.AWAITING_PROJECT)
            await self.gapo.send_message(
                session["thread_id"],
                "Không tìm thấy dự án nào bạn đang tham gia.\n"
                "Liên hệ PM để được thêm vào dự án.",
            )
            return True

        items = [
            {"index": i + 1, "id": p["id"], "label": p["name"], "payload": f"{P_PROJECT}{p['id']}"}
            for i, p in enumerate(projects)
        ]
        # Atomically set state + save menu mapping for numbered-fallback
        await repo.set_state_with_menu_mapping(
            db, session["id"], CheckinState.AWAITING_PROJECT, "project", items
        )

        slot_label = {"lunch": "buổi sáng", "end_day": "ca ngày"}.get(
            session.get("slot", ""), ""
        )
        intro = f"Check-in{' ' + slot_label if slot_label else ''}! Hôm nay bạn làm project nào?"
        numbered = "\n".join(f"{i + 1}. {p['name']}" for i, p in enumerate(projects))
        title = (
            f"{intro}\n\n"
            f"Gần đây:\n{numbered}\n\n"
            'Hoặc gõ số, tên project để tìm, hoặc "hủy" để dừng.'
        )
        actions = [{"label": p["name"][:20], "payload": f"{P_PROJECT}{p['id']}"} for p in projects]
        actions.append({"label": "Hủy", "payload": P_CANCEL})
        sent = await self.gapo.send_menu(session["thread_id"], title, actions)
        return sent

    async def _send_task_menu(self, db: AsyncSession, session: dict) -> str:
        tasks = await repo.list_task_candidates(
            db,
            user_id=session["user_id"],
            project_id=session["current_project_id"],
        )
        project_name = await repo.get_project_name(db, session["current_project_id"])

        items = [
            {"index": i + 1, "id": t["id"], "label": t["name"], "payload": f"{P_TASK}{t['id']}"}
            for i, t in enumerate(tasks)
        ]
        # Save mapping for numbered fallback (don't change state — already AWAITING_TASK)
        await repo.set_state_with_menu_mapping(
            db, session["id"], CheckinState.AWAITING_TASK, "task", items
        )

        if tasks:
            numbered = "\n".join(f"{i + 1}. {t['name']}" for i, t in enumerate(tasks))
            title = (
                f"{project_name}\nChọn task bạn đã làm:\n\n"
                f"{numbered}\n\n"
                'Hoặc gõ số, tên task để tìm.\n'
                'Gõ "bỏ qua" nếu không cần chọn task.'
            )
        else:
            title = f"{project_name}\nKhông có task nào. Bạn đã làm gì hôm nay?"
        actions = [{"label": t["name"][:20], "payload": f"{P_TASK}{t['id']}"} for t in tasks]
        actions.append({"label": "Bỏ qua task", "payload": P_SKIP_TASK})
        actions.append({"label": "Hủy", "payload": P_CANCEL})
        await self.gapo.send_menu(session["thread_id"], title, actions)
        return ""
