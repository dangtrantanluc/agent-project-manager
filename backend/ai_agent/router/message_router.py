import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import AsyncSessionLocal

from ai_agent.coversation.conversation import ConversationAgent
from ai_agent.memory.memory import load_memory
from ai_agent.planning.planning_agent import PlanningAgent, ProjectPlan
from ai_agent.report_generator.report_agent import ReportAgent
from ai_agent.router.router import PMMultiAgentRouter
from ai_agent.text_to_sql.text2sql import Text2SQLAgent
from ai_agent.notification.notification_agent import NotificationAgent
from ai_agent.task_update.task_verify_service import TaskVerifyService
from app.services.task_progress_service import (
    TaskProgressService, has_percent,
    open_session, close_session, touch_session, is_in_session, TASKCANCEL_PAYLOAD,
)
from app.services.outbound_message_service import OutboundMessageService
from app.services.risk_alert_service import RiskAlertService
from app.services.task_create_service import TaskCreateService
from app.services.add_member_service import AddMemberService

logger = logging.getLogger(__name__)
DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"

# Số dòng tối đa hiển thị khi liệt kê kết quả truy vấn thô (text2sql không tự
# diễn giải được); dư ra thì gộp thành dòng "... và N dòng khác".
MAX_DISPLAYED_ROWS = 10

# Câu user KHẲNG ĐỊNH đã hoàn thành/cập nhật một task đã được nhắc trước đó.
# Dùng cả ở _keyword_agent (fallback) lẫn _fallback_agent_for_message (ép verify).
# Luật/từ khoá định tuyến tất định đã chuyển sang intent_rules.py. Import lại để
# tương thích ngược (test/module khác có thể tham chiếu qua message_router).
from ai_agent.router.intent_rules import (
    TASK_UPDATE_KEYWORDS,
    CREATE_TASK_KEYWORDS,
    _OUTBOUND_RE,
    _TASK_CODE_RE,
    resolve_agents as _resolve_agents_rule,
    keyword_agent as _keyword_agent_rule,
)

# Tập HẸP hơn để HỎI LẠI khi không rõ người nhận: động từ gần như luôn nhắm tới
# một người cụ thể. Cố ý BỎ "nhắc" (quá rộng) để không cướp nhầm luồng soạn thông báo.
# (Chỉ dùng trong message_router nên giữ ở đây, không chuyển sang intent_rules.)
_ASKBACK_OUTBOUND_RE = re.compile(r"\b(?:push|nhắn|giục|đốc thúc|thúc)\b")

# Payload nút bấm cập nhật task.
TASKUPD_PAYLOAD_PREFIX = "TASKUPD|"

# Dấu hiệu câu hỏi THAM CHIẾU lại lượt trước (anaphora) -> chèn SQL lượt trước vào
# memory_context để LLM tái dùng điều kiện. List để rộng tay (xem _references_previous_turn).
_ANAPHORA_PATTERNS = (
    " đó", " đấy", " này", " kia", " ấy",
    "còn lại", "trong số", "trong đó", "số còn",
    "liệt kê", "chi tiết", "cụ thể", "gồm những", "là những",
    "vừa rồi", "vừa nói", "ở trên", "bên trên", "nói trên",
    "khác", "còn",
)


def _parse_payload_id(payload: str) -> int | None:
    """Lấy task_id từ payload dạng 'PREFIX|<id>'."""
    try:
        return int(payload.split("|", 2)[1])
    except (IndexError, ValueError):
        return None

@dataclass
class AgentReply:
    answer: str
    agent: str
    metadata: dict | None = None
    # SQL của lượt text2sql (nếu có) để gapo_adapter lưu vào memory cho follow-up.
    last_sql: str | None = None

def _parse_page_args(message: str):
    """TASKPAGE|<page>[|<query>] -> (query|None, page). Sai định dạng -> trang 1."""
    parts = message.split("|", 2)
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
    query = parts[2] if len(parts) > 2 and parts[2].strip() else None
    return (query, page)


def _parse_id_args(message: str):
    """TASKPICK|<id> / TASKBLOCK|<id> / TASKSNOOZE|<id> -> (id,). Thiếu id -> None."""
    tid = _parse_payload_id(message)
    return (tid,) if tid else None


def _parse_id_days_args(message: str):
    """TASKEXTEND|<id>|<days> -> (id, days). days mặc định 3. Thiếu id -> None."""
    tid = _parse_payload_id(message)
    if not tid:
        return None
    parts = message.split("|")
    days = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 3
    return (tid, days)


class AgentMessageRouter:
    # Bảng KHAI BÁO cho payload nút bấm task (xem _dispatch_task_payload). Mỗi dòng:
    #   prefix  -> tiền tố payload cần khớp
    #   method  -> tên method của task_progress_service, gọi dạng method(user_id,*args,db)
    #   parse   -> hàm bóc args từ payload (None nếu payload sai -> báo "không hợp lệ")
    #   session -> 'touch' (gia hạn phiên) | 'close' (đóng phiên) | None (giữ nguyên)
    #   reply   -> 'menu' (kèm nút bấm) | 'message' (lấy res['message']) | 'extract'
    # TASKUPD| KHÔNG ở đây vì apply_payload có thứ tự tham số khác (message trước user_id).
    _PAYLOAD_GATES = [
        {"prefix": "TASKPAGE|", "method": "menu_my_tasks", "parse": _parse_page_args,
         "session": "touch", "reply": "menu"},
        {"prefix": "TASKPICK|", "method": "menu_status", "parse": _parse_id_args,
         "session": "touch", "reply": "menu"},
        {"prefix": "TASKEXTEND|", "method": "extend_deadline", "parse": _parse_id_days_args,
         "session": "close", "reply": "message"},
        {"prefix": "TASKSNOOZE|", "method": "snooze_reminder", "parse": _parse_id_args,
         "session": "close", "reply": "message"},
        {"prefix": "TASKBLOCK|", "method": "apply_blocker", "parse": _parse_id_args,
         "session": "close", "reply": "message", "needs_ctx": True},
    ]

    def __init__(self):
        self.intent_router = PMMultiAgentRouter()
        self.conversation_agent = ConversationAgent()
        self.text2sql_agent = Text2SQLAgent()
        self.report_agent = ReportAgent()
        self.planning_agent = PlanningAgent()
        self.notification_agent = NotificationAgent()
        self.outbound_message_service = OutboundMessageService()
        self.task_verify_service = TaskVerifyService()
        # Cập nhật % dùng lại task_verify_service để resolve "task nào" (không nhân đôi logic).
        self.task_progress_service = TaskProgressService(verify_service=self.task_verify_service)
        # Bắt kết quả/khó khăn (reply cho follow-up RESULT_ISSUES/BLOCKER_REASON).
        from app.services.task_outcome_service import TaskOutcomeService
        self.task_outcome_service = TaskOutcomeService(verify_service=self.task_verify_service)
        self.risk_alert_service = RiskAlertService()
        self.task_create_service = TaskCreateService()
        self.add_member_service = AddMemberService()

    async def handle_message(
        self,
        message: str,
        user_id: str,
        channel: str = "gapo",
        thread_id: str | None = None,
        metadata: dict | None = None,
        db: AsyncSession | None = None,
        conversation_id: str | None = None,
        correlation_id: str | None = None,
    ) -> AgentReply:
        """Route one normalized chat message to an agent and return sendable text."""
        metadata = metadata or {}
        conversation_id = conversation_id or thread_id
        memory_context = ""
        t_total = time.perf_counter()

        try:
            # ── Luồng /update có PHIÊN (Redis, TTL ngắn) ─────────────────────────
            msg_stripped = message.strip()
            first_word = msg_stripped.split(maxsplit=1)[0].lower() if msg_stripped else ""

            # /update [<từ khoá>] -> MỞ phiên + menu task (trang 1).
            if first_word in ("/update", "/capnhat", "/task", "/tasks", "/mytask"):
                query = msg_stripped[len(first_word):].strip() or None
                await open_session(user_id)
                res = await self.task_progress_service.menu_my_tasks(user_id, query, db=db)
                return self._task_menu_reply(res, metadata)

            # /risk -> quét rủi ro NGAY các dự án user liên quan, gửi cảnh báo cho PM
            # (chạy thật như cron 8h30). Dùng để test thủ công không phải chờ cron.
            if first_word in ("/risk", "/ruiro"):
                return await self._handle_risk_command(user_id, db, metadata)

            # /deadline -> chạy NGAY luồng nhắc deadline cho chính người gõ
            # (giống cron 9h/14h). Dùng để test thủ công không phải chờ cron.
            if first_word in ("/deadline", "/nhachan", "/nhacdeadline"):
                return await self._handle_deadline_command(user_id, db, metadata)

            # Huỷ phiên.
            if msg_stripped == TASKCANCEL_PAYLOAD:
                await close_session(user_id)
                return AgentReply(answer="Đã huỷ. Cần cập nhật task, bạn gõ /update nhé.",
                                  agent="task_update", metadata=metadata)

            # Payload nút bấm task (TASKPAGE/TASKPICK/TASKEXTEND/TASKSNOOZE/TASKBLOCK)
            # -> phân phối qua bảng khai báo _PAYLOAD_GATES.
            dispatched = await self._dispatch_task_payload(message, user_id, db, metadata,
                                                           thread_id=thread_id, channel=channel)
            if dispatched is not None:
                return dispatched

            # Bấm trạng thái %/Done -> cập nhật + ĐÓNG phiên.
            if message.startswith(TASKUPD_PAYLOAD_PREFIX):
                res = await self.task_progress_service.apply_payload(
                    message, user_id, db, thread_id=thread_id, channel=channel)
                await close_session(user_id)
                return AgentReply(answer=self._extract_message(res), agent="task_update", metadata=metadata)

            # Trả lời câu hỏi KẾT QUẢ/KHÓ KHĂN (follow-up RESULT_ISSUES/BLOCKER_REASON)
            # -> ghi thẳng, KHÔNG route như update thường. Đặt TRƯỚC "đang trong phiên".
            if db is not None and msg_stripped and not msg_stripped.startswith(("/", "TASK")):
                fu = await self.task_outcome_service.find_pending(db, user_id, thread_id)
                if fu is not None:
                    res = await self.task_outcome_service.apply_reply(db, fu, msg_stripped, user_id, {})
                    return AgentReply(answer=self._extract_message(res),
                                      agent="task_update", metadata=metadata)

            # ĐANG TRONG PHIÊN + câu gõ thẳng (không phải payload) -> coi là TÌM task.
            if msg_stripped and await is_in_session(user_id):
                await touch_session(user_id)
                res = await self.task_progress_service.menu_my_tasks(user_id, msg_stripped, db=db)
                return self._task_menu_reply(res, metadata)

            # Cảnh báo rủi ro giờ là THÔNG BÁO THUẦN (gửi thẳng cho PM, không cần
            # duyệt) -> không còn state-gate bắt câu trả lời ở đây.

            user_profile: dict = {}
            t_route = time.perf_counter()
            if db is not None and conversation_id:
                selected_task = asyncio.create_task(self.intent_router.selected_agents(message))
                memory_context, user_profile = await asyncio.gather(
                    self._load_memory_context_new_session(conversation_id, message),
                    self._load_user_profile_new_session(user_id),
                )
                selected = await selected_task
                metadata = {
                    **metadata,
                    "conversation_id": conversation_id,
                    "correlation_id": correlation_id,
                    "memory_loaded": bool(memory_context),
                }
            else:
                selected = await self.intent_router.selected_agents(message)
            route_ms = (time.perf_counter() - t_route) * 1000

            agent_names = self._fallback_agent_for_message(message, selected)

            # task_update là intent ĐỘC QUYỀN -> xử lý riêng để đính 'menu' (nút chọn
            # task khi mơ hồ) vào reply; không đi qua vòng gộp _run_agent (trả str).
            if agent_names == ["task_update"]:
                res = await self.task_progress_service.update(
                    message=message, user_id=user_id, memory_context=memory_context,
                    thread_id=thread_id, user_profile=user_profile or {}, db=db,
                )
                md = {**metadata}
                if res.get("menu"):
                    md["menu"] = res["menu"]
                return AgentReply(
                    answer=self._extract_message(res),
                    agent="task_update", metadata=md,
                )

            logger.info(
                "routed agents=%s selected=%s route_ms=%.0f user_id=%s thread_id=%s",
                agent_names, selected, route_ms, user_id, thread_id,
            )

            t_exec = time.perf_counter()
            # sql_sink: text2sql ghi câu SQL nó vừa chạy vào đây để lưu memory cho
            # follow-up. Chạy song song nên dùng 1 dict chung (chỉ text2sql ghi; nếu
            # có >1 text2sql, lượt sau đè lượt trước — chấp nhận, lấy SQL gần nhất).
            sql_sink: dict = {}
            results = await asyncio.gather(
                *[
                    self._run_agent(
                        name,
                        message,
                        user_id,
                        channel,
                        thread_id,
                        metadata,
                        memory_context,
                        user_profile,
                        sql_sink,
                    )
                    for name in agent_names
                ],
                return_exceptions=True,
            )
            exec_ms = (time.perf_counter() - t_exec) * 1000
            total_ms = (time.perf_counter() - t_total) * 1000

            answer, ran_agents = self._combine_results(agent_names, results)

            logger.info(
                "request_done agents=%s ran=%s exec_ms=%.0f total_ms=%.0f user_id=%s thread_id=%s",
                agent_names, ran_agents, exec_ms, total_ms, user_id, thread_id,
            )

            if not ran_agents:
                # Tất cả agent đều lỗi → trả thông điệp xin lỗi.
                return AgentReply(
                    answer="Xin lỗi, mình đang gặp lỗi khi xử lý tin nhắn này. Bạn thử lại giúp mình nhé.",
                    agent="error",
                    metadata={"selected_agents": list(selected), **metadata},
                )

            return AgentReply(
                answer=answer,
                # agent là chuỗi str (vd "text2sql+report") để JSON-serializable
                # ở gapo_adapter (audit_context, tools_used).
                agent="+".join(ran_agents),
                metadata={"selected_agents": list(selected), **metadata},
                last_sql=sql_sink.get("last_sql"),
            )
        except Exception:
            total_ms = (time.perf_counter() - t_total) * 1000
            logger.exception(
                "request_failed total_ms=%.0f user_id=%s thread_id=%s",
                total_ms, user_id, thread_id,
            )
            return AgentReply(
                answer="Xin lỗi, mình đang gặp lỗi khi xử lý tin nhắn này. Bạn thử lại giúp mình nhé.",
                agent="error",
                metadata=metadata,
            )

    def _task_menu_reply(self, res: dict, metadata: dict) -> "AgentReply":
        """Đóng gói reply có (tuỳ chọn) 'menu' nút bấm cho luồng /update."""
        md = {**metadata}
        if res.get("menu"):
            md["menu"] = res["menu"]
        return AgentReply(answer=res.get("message", ""), agent="task_update", metadata=md)

    async def _dispatch_task_payload(
        self, message: str, user_id: str, db, metadata: dict,
        thread_id: str | None = None, channel: str = "gapo",
    ) -> "AgentReply | None":
        """Phân phối payload nút bấm task qua BẢNG KHAI BÁO (thay vì chuỗi if-gate).

        Mỗi entry: prefix -> cách parse args, method service, có giữ/đóng phiên,
        và kiểu reply (menu nút bấm hay text). Trả AgentReply nếu khớp prefix; None
        để handle_message tiếp tục routing thường. Thêm nút bấm mới = thêm 1 dòng
        vào _PAYLOAD_GATES, không phải viết thêm if.
        """
        for gate in self._PAYLOAD_GATES:
            if not message.startswith(gate["prefix"]):
                continue
            # session: 'touch' (gia hạn), 'close' (kết thúc), hoặc None (giữ nguyên).
            if gate["session"] == "touch":
                await touch_session(user_id)
            args = gate["parse"](message)
            if args is None:
                res = {"message": "Lựa chọn không hợp lệ."}
            else:
                method = getattr(self.task_progress_service, gate["method"])
                # needs_ctx: method nhận thêm thread_id/channel (vd apply_blocker tạo follow-up).
                kwargs = {"thread_id": thread_id, "channel": channel} if gate.get("needs_ctx") else {}
                res = await method(user_id, *args, db, **kwargs)
            if gate["session"] == "close":
                await close_session(user_id)
            if gate["reply"] == "menu":
                return self._task_menu_reply(res, metadata)
            text_out = self._extract_message(res) if gate["reply"] == "extract" else res.get("message", "")
            return AgentReply(answer=text_out, agent="task_update", metadata=metadata)
        return None

    def _fallback_agent_for_message(self, message: str, selected: list[str]) -> list[str]:
        """Wrapper mỏng → intent_rules.resolve_agents (giữ API cũ cho test/caller)."""
        return _resolve_agents_rule(message, selected)

    def _keyword_agent(self, message: str) -> str:
        """Wrapper mỏng → intent_rules.keyword_agent."""
        return _keyword_agent_rule(message)

    def _combine_results(
        self, agent_names: list[str], results: list[Any]
    ) -> tuple[str, list[str]]:
        """Gộp output các agent đã chạy thành một câu trả lời.

        Bỏ qua agent lỗi (exception) hoặc trả text rỗng. Một agent → trả thẳng.
        Nhiều agent → nối các đoạn (mỗi đoạn đã là prose hoàn chỉnh) bằng dòng
        trống, KHÔNG thêm nhãn và KHÔNG gọi LLM lần nữa.
        Chỉ trả về nội dung thôi, không kèm thông tin nào khác.
        """
        sections: list[tuple[str, str]] = []
        for name, result in zip(agent_names, results):
            if isinstance(result, Exception):
                logger.error("agent=%s failed: %s", name, result)
                continue
            text_value = (result or "").strip() if isinstance(result, str) else str(result).strip()
            if text_value:
                sections.append((name, text_value))

        ran_agents = [name for name, _ in sections]

        if not sections:
            return "", ran_agents
        if len(sections) == 1:
            return sections[0][1], ran_agents

        # ≥2 agent: mỗi đoạn đã là prose hoàn chỉnh (agent tự summarize bằng LLM),
        # chỉ nối bằng dòng trống — KHÔNG thêm nhãn, KHÔNG gọi LLM lần nữa.
        return "\n\n".join(body for _, body in sections), ran_agents

    async def _run_agent(
        self,
        agent_name: str,
        message: str,
        user_id: str,
        channel: str,
        thread_id: str | None,
        metadata: dict,
        memory_context: str = "",
        user_profile: dict | None = None,
        sql_sink: dict | None = None,
    ) -> str:
        if agent_name == "conversation":
            result = await self.conversation_agent.process_message_async(
                message,
                user_context=self._user_context(user_id, channel, thread_id, memory_context, metadata, user_profile),
                user_profile=user_profile or {},
                timezone_name=self._timezone_name(metadata),
            )
            return self._extract_message(result)

        if agent_name == "text2sql":
            user_role = (user_profile or {}).get("role")
            result = await self.text2sql_agent.execute(
                message,
                memory_context=memory_context,
                current_user_id=user_id,
                user_role=user_role,
            )
            # Đẩy SQL ra ngoài để lưu memory cho follow-up (xem save_memory/last_sql).
            if sql_sink is not None and isinstance(result, dict) and result.get("sql"):
                sql_sink["last_sql"] = result["sql"]
            return self._format_text2sql(result)

        if agent_name == "report":
            result = await self.report_agent.generate_report(message, memory_context=memory_context)
            return self._format_report(result)

        if agent_name == "planning":
            result = await self.planning_agent.generate_project_plan(
                message,
                memory_context=memory_context,
                user_profile=user_profile or {},
            )
            return self._format_planning(result)

        if agent_name == "notification":
            # Thử trước: "nhắn X ..." → gửi DM cho X (người khác), trả câu xác
            # nhận cho người hỏi. Không xác định được recipient thì rơi về soạn
            # nhắc nhở trong chính thread của người hỏi (hành vi cũ).
            outbound = await self.outbound_message_service.send_on_behalf(
                message=message,
                sender_user_id=user_id,
                memory_context=memory_context,
            )
            if outbound.status != "no_recipient":
                return self._format_outbound(outbound)

            # Câu có ý NHỜ NHẮN/NHẮC/PUSH người khác nhưng không bóc được tên người
            # nhận (vd "push deadline cho bạn") -> HỎI LẠI, KHÔNG soạn nhắc vào thread
            # người hỏi (tránh nhầm: bot soạn "X ơi..." nhưng đăng nhầm chỗ).
            if _ASKBACK_OUTBOUND_RE.search(message.lower()):
                return (
                    "Bạn muốn mình nhắn/nhắc giúp ai vậy? Cho mình biết tên người nhận "
                    "(hoặc @mention) để mình gửi đúng người nhé."
                )

            result = await self.notification_agent.prepare_notification(
                user_id=user_id,
                thread_id=thread_id,
                message=message,
                memory_context=memory_context,
            )
            return self._extract_message(result)

        if agent_name == "task_update":
            # Progress service tự quyết: có % ("đã xong 80%") -> cập nhật tiến độ;
            # câu hoàn thành ("xong rồi/done") đã resolve follow-up -> set DONE;
            # còn lại -> uỷ TaskVerifyService (chỉ xác minh, hỏi lại).
            result = await self.task_progress_service.update(
                message=message,
                user_id=user_id,
                memory_context=memory_context,
                thread_id=thread_id,
                user_profile=user_profile or {},
                channel=channel,
            )
            return self._extract_message(result)

        if agent_name == "create_task":
            result = await self.task_create_service.create_from_chat(
                message=message,
                sender_user_id=user_id,
                user_profile=user_profile or {},
                memory_context=memory_context,
                timezone_name=self._timezone_name(metadata),
            )
            return result.message

        if agent_name == "add_member":
            result = await self.add_member_service.add_from_chat(
                message=message,
                sender_user_id=user_id,
                user_profile=user_profile or {},
                memory_context=memory_context,
            )
            return result.message

        result = await self.conversation_agent.process_message_async(
            message,
            user_context=self._user_context(user_id, channel, thread_id, memory_context, metadata, user_profile),
            user_profile=user_profile or {},
            timezone_name=self._timezone_name(metadata),
        )
        return self._extract_message(result)

    async def _load_memory_context_new_session(self, conversation_id: str, message: str = "") -> str:
        t = time.perf_counter()
        async with AsyncSessionLocal() as db:
            result = await self._load_memory_context(conversation_id, db, message)
        logger.info("memory_load_ms=%.0f", (time.perf_counter() - t) * 1000)
        return result

    async def _load_user_profile_new_session(self, user_id: str) -> dict:
        t = time.perf_counter()
        async with AsyncSessionLocal() as db:
            result = await self._load_user_profile(user_id, db)
        logger.info("profile_load_ms=%.0f", (time.perf_counter() - t) * 1000)
        return result

    async def _handle_risk_command(
        self, user_id: str, db: AsyncSession | None, metadata: dict
    ) -> AgentReply:
        """/risk: quét rủi ro các dự án user liên quan, gửi cảnh báo cho PM (test thủ công)."""
        import pytz
        from datetime import datetime

        async def _run(session: AsyncSession) -> AgentReply:
            profile = await self._load_user_profile(user_id, session)
            role = (profile or {}).get("role")
            if role not in ("MANAGER", "ADMIN", "SUPER_ADMIN"):
                return AgentReply(
                    answer="Chỉ quản lý (MANAGER/ADMIN) mới quét rủi ro được nhé.",
                    agent="notification", metadata=metadata,
                )
            today = datetime.now(pytz.timezone("Asia/Ho_Chi_Minh")).date().isoformat()
            stats = await self.risk_alert_service.scan_and_alert_for_user(
                session, user_id=int(user_id), today_iso=today,
            )
            scanned, sent, skipped = stats["scanned"], stats["sent"], stats["skipped"]
            if scanned == 0:
                answer = "Bạn chưa tham gia dự án nào đang chạy để quét rủi ro."
            elif sent == 0:
                # skipped do: đã gửi hôm nay (dedup), không at-risk, hoặc PM chưa link Gapo.
                answer = (
                    f"Đã quét {scanned} dự án — không có cảnh báo mới gửi đi "
                    f"(đã gửi hôm nay, hoặc chưa tới ngưỡng rủi ro, hoặc PM chưa liên kết Gapo)."
                )
            else:
                answer = f"Đã quét {scanned} dự án, gửi {sent} cảnh báo rủi ro cho PM phụ trách."
            return AgentReply(answer=answer, agent="notification", metadata=metadata)

        if db is not None:
            return await _run(db)
        async with AsyncSessionLocal() as own_db:
            return await _run(own_db)

    async def _handle_deadline_command(
        self, user_id: str, db: AsyncSession | None, metadata: dict
    ) -> AgentReply:
        """/deadline: chạy ngay luồng nhắc deadline cho chính người gõ (test thủ công).

        Tái dùng run_deadline_notifications(only_user_id=...) — gửi digest + nút bấm
        + tạo follow-up đúng như cron. Job tự gửi qua Gapo nên reply ở đây chỉ là
        dòng trạng thái. Dedup theo ngày: gõ lần 2 cùng ngày sẽ không gửi lại.
        """
        from ai_agent.checkin.scheduler import run_deadline_notifications

        async def _count_due(session: AsyncSession) -> int:
            row = (await session.execute(text("""
                SELECT COUNT(*) FROM tasks t
                JOIN gapo_user_maps g ON g.user_id = t.assignee_id
                WHERE t.assignee_id = :uid
                  AND t.deadline IS NOT NULL
                  AND t.status::text <> 'DONE'
                  AND (t.snooze_reminder_until IS NULL OR t.snooze_reminder_until < CURRENT_DATE)
            """), {"uid": int(user_id)})).scalar()
            return int(row or 0)

        if db is not None:
            n = await _count_due(db)
        else:
            async with AsyncSessionLocal() as own_db:
                n = await _count_due(own_db)

        if n == 0:
            return AgentReply(
                answer="Bạn không có task nào đang chờ deadline để nhắc.",
                agent="notification", metadata=metadata,
            )

        # slot=morning để gồm cả due_today + sắp đến hạn (đầy đủ nhất cho test).
        await run_deadline_notifications(slot="morning", only_user_id=int(user_id))
        return AgentReply(
            answer=(
                "Đã chạy nhắc deadline cho bạn — kiểm tra tin nhắn nhắc + nút bấm phía trên nhé. "
                "(Nếu không thấy: hôm nay đã nhắc rồi, hoặc chưa task nào tới mốc nhắc.)"
            ),
            agent="notification", metadata=metadata,
        )

    async def _load_memory_context(self, conversation_id: str, db: AsyncSession, message: str = "") -> str:
        try:
            summary, recent_turns, last_sql = await load_memory(conversation_id, db)
        except Exception:
            logger.exception("Failed to load memory for conversation %s", conversation_id)
            return ""
        return self._build_memory_context(summary, recent_turns, last_sql, message)

    async def _load_user_profile(self, user_id: str, db: AsyncSession) -> dict:
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return {}
        try:
            # Query 1: user info + overdue count + nearest deadline
            row = (await db.execute(
                text("""
                    SELECT
                        u.full_name, u.role, u.department, u.position,
                        (SELECT COUNT(*) FROM tasks
                         WHERE assignee_id = u.id
                           AND status <> 'DONE'::"TaskStatus"
                           AND deadline < CURRENT_DATE) AS overdue_count,
                        (SELECT name FROM tasks
                         WHERE assignee_id = u.id
                           AND status <> 'DONE'::"TaskStatus"
                           AND deadline >= CURRENT_DATE
                         ORDER BY deadline ASC LIMIT 1) AS nearest_task,
                        (SELECT deadline FROM tasks
                         WHERE assignee_id = u.id
                           AND status <> 'DONE'::"TaskStatus"
                           AND deadline >= CURRENT_DATE
                         ORDER BY deadline ASC LIMIT 1) AS nearest_deadline
                    FROM users u WHERE u.id = :uid
                """),
                {"uid": uid},
            )).fetchone()
            if not row:
                return {}
            profile: dict = {
                "full_name": row[0], "role": row[1],
                "department": row[2], "position": row[3],
                "overdue_count": row[4] or 0,
            }
            if row[5]:
                profile["nearest_task"] = row[5]
                profile["nearest_deadline"] = str(row[6])
            # Query 2: active projects
            proj_rows = (await db.execute(
                text("""
                    SELECT DISTINCT p.id, p.name
                    FROM projects p
                    LEFT JOIN members m ON m.project_id = p.id
                    WHERE (p.owner_id = :uid OR m.user_id = :uid)
                      AND p.status IN ('PLANNED'::"ProjectStatus", 'IN_PROGRESS'::"ProjectStatus")
                    ORDER BY p.name LIMIT 10
                """),
                {"uid": uid},
            )).fetchall()
            profile["active_projects"] = [{"id": r[0], "name": r[1]} for r in proj_rows]
            return profile
        except Exception:
            logger.exception("Failed to load user profile for user_id=%s", user_id)
            return {}

    def _build_memory_context(
        self,
        summary: str,
        recent_turns: list[dict],
        last_sql: str = "",
        message: str = "",
    ) -> str:
        parts = []
        if summary:
            parts.append(f"Tóm tắt trước: {summary}")
        if recent_turns:
            lines = ["Các lượt gần đây:"]
            for turn in recent_turns:
                lines.append(f"User: {turn.get('user', '')}")
                lines.append(f"Bot: {turn.get('bot', '')}")
            parts.append("\n".join(lines))

        # Chỉ chèn SQL lượt trước khi câu hiện tại CÓ DẤU HIỆU tham chiếu lại lượt
        # trước ("66 task đó", "còn lại", "liệt kê chi tiết"). Câu chủ đề mới không
        # chèn → tránh phình token và tránh LLM dính nhầm điều kiện cũ. Kèm nhãn cho
        # LLM tự bỏ qua nếu thực ra không liên quan (van kiểm soát cuối).
        if last_sql and self._references_previous_turn(message):
            parts.append(
                "SQL của lượt truy vấn dữ liệu gần nhất (CHỈ tái sử dụng điều kiện "
                "WHERE/JOIN khi câu hỏi hiện tại tham chiếu lại lượt trước — vd "
                "\"… đó\", \"còn lại\", \"liệt kê chi tiết\". Nếu câu hỏi là chủ đề "
                f"mới, BỎ QUA hoàn toàn SQL này):\n{last_sql}"
            )
        return "\n\n".join(parts).strip()

    def _references_previous_turn(self, message: str) -> bool:
        """Câu có dấu hiệu tham chiếu lại lượt trước (anaphora) không?

        Đây là van mở rộng tay: thà chèn dư (LLM tự bỏ qua nhờ nhãn) còn hơn sót
        (sót → tái phát bug "66 task đó là gì"). Không phải bộ phân loại chính xác.
        """
        lowered = (message or "").lower()
        return any(p in lowered for p in _ANAPHORA_PATTERNS)

    def _user_context(
        self,
        user_id: str,
        channel: str,
        thread_id: str | None,
        memory_context: str = "",
        metadata: dict | None = None,
        user_profile: dict | None = None,
    ) -> str:
        profile = user_profile or {}
        parts = []

        name = profile.get("full_name", "")
        role = profile.get("role", "")
        dept = profile.get("department", "")
        position = profile.get("position", "")
        if name:
            label = " — ".join(filter(None, [role, dept, position]))
            parts.append(f"Tên: {name}" + (f" ({label})" if label else ""))

        projects = profile.get("active_projects", [])
        if projects:
            proj_names = ", ".join(p["name"] for p in projects[:4])
            parts.append(f"Dự án đang tham gia: {proj_names}")

        overdue = profile.get("overdue_count", 0)
        if overdue:
            parts.append(f"Task quá hạn: {overdue}")

        nearest_task = profile.get("nearest_task")
        nearest_deadline = profile.get("nearest_deadline")
        if nearest_task and nearest_deadline:
            parts.append(f"Deadline gần nhất: '{nearest_task}' ({nearest_deadline})")

        parts.append(f"Kênh: {channel} | Timezone: {self._timezone_name(metadata)}")

        if memory_context:
            parts.append(f"\nLịch sử hội thoại:\n{memory_context}")

        return "\n".join(parts)

    def _timezone_name(self, metadata: dict | None = None) -> str:
        if metadata and metadata.get("timezone"):
            return str(metadata["timezone"])
        return DEFAULT_TIMEZONE

    def _extract_message(self, result: Any) -> str:
        """Bóc text gửi được từ result kiểu prose-đơn (conversation/notification/
        task_update): dict thì lấy 'message'/'answer', còn lại ép str.

        Object có thuộc tính ``message`` (vd dataclass của NotificationAgent) cũng
        được hỗ trợ để không phải đối tượng nào cũng phải là dict.
        """
        if isinstance(result, dict):
            return str(result.get("message") or result.get("answer") or result)
        if hasattr(result, "message"):
            return str(result.message)
        return str(result)

    def _format_outbound(self, outbound) -> str:
        """Soạn câu PHẢN HỒI cho người hỏi sau khi (cố) nhắn hộ cho người khác.

        Tin nhắn thật đã được gửi cho recipient bên trong service; ở đây chỉ
        báo lại kết quả cho người hỏi để họ biết đã gửi/chưa rõ recipient.
        """
        name = outbound.recipient_name or "người bạn nhắc"
        if outbound.status == "sent":
            return f"Mình đã nhắn giúp bạn tới {name} rồi nhé:\n\n> {outbound.body}"
        if outbound.status == "not_found":
            return (
                f"Mình chưa tìm thấy ai tên \"{name}\" trong hệ thống. "
                "Bạn cho mình tên đầy đủ (hoặc @mention) để mình nhắn đúng người nhé."
            )
        if outbound.status == "ambiguous":
            options = ", ".join(outbound.candidates or [])
            return (
                f"Có nhiều người trùng tên \"{name}\": {options}. "
                "Bạn nói rõ giúp mình là ai để mình nhắn đúng nhé."
            )
        if outbound.status == "not_linked":
            return (
                f"{name} chưa liên kết tài khoản Gapo nên mình chưa gửi tin nhắn được. "
                "Bạn nhờ bạn ấy nhắn /link với bot trong chat 1-1 trước nhé."
            )
        return (
            f"Mình gặp trục trặc khi nhắn cho {name}, bạn thử lại sau giúp mình nhé."
        )

    def _format_text2sql(self, result: dict) -> str:
        answer = result.get("answer")
        if isinstance(answer, str) and answer.strip():
            return answer.strip()

        rows = result.get("result")

        if isinstance(rows, str):
            if "Unsafe SQL generated" in rows:
                return "Mình chưa tạo được truy vấn an toàn cho câu hỏi này. Bạn thử hỏi cụ thể hơn giúp mình nhé."
            return rows
        if not rows:
            return "Mình chưa tìm thấy dữ liệu phù hợp."

        lines = ["Kết quả truy vấn:"]
        for index, row in enumerate(rows[:MAX_DISPLAYED_ROWS], start=1):
            if isinstance(row, dict):
                values = ", ".join(f"{key}: {value}" for key, value in row.items())
                lines.append(f"{index}. {values}")
            else:
                lines.append(f"{index}. {row}")

        if len(rows) > MAX_DISPLAYED_ROWS:
            lines.append(f"... và {len(rows) - MAX_DISPLAYED_ROWS} dòng khác.")
        return "\n".join(lines)

    def _format_report(self, result: Any) -> str:
        if isinstance(result, str):
            return result.strip()
        return json.dumps(result, ensure_ascii=False, indent=2)

    def _format_planning(self, result: ProjectPlan | Any) -> str:
        if isinstance(result, ProjectPlan):
            lines = [f"Kế hoạch dự án: {result.project_name}"]
            if result.summary:
                lines.append(result.summary)

            for milestone in result.milestones:
                lines.append("")
                lines.append(f"- {milestone.name}: {milestone.goal}")
                for task in milestone.tasks:
                    lines.append(
                        f"  + {task.title} ({task.priority}, {task.estimated_hours}h, {task.role})"
                    )
            return "\n".join(lines)

        if hasattr(result, "model_dump"):
            return json.dumps(result.model_dump(), ensure_ascii=False, indent=2)
        if hasattr(result, "dict"):
            return json.dumps(result.dict(), ensure_ascii=False, indent=2)
        return str(result)

    def _jsonable(self, value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if hasattr(value, "dict"):
            return value.dict()
        if hasattr(value, "__dataclass_fields__"):
            return {key: self._jsonable(getattr(value, key)) for key in value.__dataclass_fields__}
        if isinstance(value, dict):
            return {key: self._jsonable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._jsonable(item) for item in value]
        return value

