import asyncio
import json
import logging
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
from ai_agent.task_update.task_verify_agent import TaskVerifyAgent

logger = logging.getLogger(__name__)
DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"

@dataclass
class AgentReply:
    answer: str
    agent: str
    metadata: dict | None = None

class AgentMessageRouter:
    def __init__(self):
        self.intent_router = PMMultiAgentRouter()
        self.conversation_agent = ConversationAgent()
        self.text2sql_agent = Text2SQLAgent()
        self.report_agent = ReportAgent()
        self.planning_agent = PlanningAgent()
        self.notification_agent = NotificationAgent()
        self.task_verify_agent = TaskVerifyAgent()

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
            user_profile: dict = {}
            t_route = time.perf_counter()
            if db is not None and conversation_id:
                selected_task = asyncio.create_task(self.intent_router.selected_agents(message))
                memory_context, user_profile = await asyncio.gather(
                    self._load_memory_context_new_session(conversation_id),
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

            logger.info(
                "routed agents=%s selected=%s route_ms=%.0f user_id=%s thread_id=%s",
                agent_names, selected, route_ms, user_id, thread_id,
            )

            t_exec = time.perf_counter()
            # Chạy song song mọi agent được chọn; mỗi agent độc lập, lỗi 1 agent
            # không làm hỏng cả reply (return_exceptions=True).
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

    def _fallback_agent_for_message(self, message: str, selected: list[str]) -> list[str]:
        """Chuẩn hoá danh sách agent sẽ chạy.

        Chỉ fallback bằng từ khoá khi LLM trả về đúng ``["conversation"]`` (mặc
        định/không chắc). Mọi trường hợp khác giữ nguyên danh sách LLM trả về.
        """
        agents = [a for a in selected if a] or ["conversation"]
        if agents == ["conversation"]:
            # LLM không chắc → cứu intent bằng từ khoá tiếng Việt.
            keyword_agent = self._keyword_agent(message)
            return [keyword_agent] if keyword_agent else agents

        # >1 agent: loại 'conversation' thừa — agent nghiệp vụ đã tự chào & trả lời
        # đủ ngữ cảnh (qua user_context/memory_context), thêm conversation chỉ lặp ý.
        business = [a for a in agents if a != "conversation"]
        if business:
            logger.info("Loại 'conversation' thừa, giữ agents=%s", business)
            return business
        return agents

    def _keyword_agent(self, message: str) -> str:
        lowered = message.lower()
        task_update_keywords = (
            "update rồi",
            "đã update",
            "xong rồi",
            "đã xong",
            "hoàn thành rồi",
            "done",
            "làm xong",
            "cập nhật rồi",
        )
        planning_keywords = ("lập kế hoạch", "kế hoạch", "phân chia công việc", "milestone")
        report_keywords = ("báo cáo", "thống kê", "report", "tiến độ tổng thể")
        notification_keywords = ("thông báo", "nhắc nhở", "reminder", "notification")
        data_keywords = (
            "dự án",
            "project",
            "task",
            "công việc",
            "deadline",
            "worklog",
            "bao nhiêu",
            "danh sách",
            "ai là",
        )

        # task_update kiểm tra TRƯỚC data_keywords: câu "làm xong task X" có cả 'task'
        # (data) lẫn 'làm xong' (task_update) — phải ưu tiên xác minh hoàn thành.
        if any(keyword in lowered for keyword in task_update_keywords):
            return "task_update"
        if any(keyword in lowered for keyword in planning_keywords):
            return "planning"
        if any(keyword in lowered for keyword in report_keywords):
            return "report"
        if any(keyword in lowered for keyword in notification_keywords):
            return "notification"
        if any(keyword in lowered for keyword in data_keywords):
            return "text2sql"
        return "conversation"

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
    ) -> str:
        if agent_name == "conversation":
            result = await self.conversation_agent.process_message_async(
                message,
                user_context=self._user_context(user_id, channel, thread_id, memory_context, metadata, user_profile),
                user_profile=user_profile or {},
                timezone_name=self._timezone_name(metadata),
            )
            return self._format_conversation(result)

        if agent_name == "text2sql":
            user_role = (user_profile or {}).get("role")
            result = await self.text2sql_agent.execute(
                message,
                memory_context=memory_context,
                current_user_id=user_id,
                user_role=user_role,
            )
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
            result = await self.notification_agent.prepare_notification(
                user_id=user_id,
                thread_id=thread_id,
                message=message,
                memory_context=memory_context,
            )
            return self._format_notification(result)

        if agent_name == "task_update":
            result = await self.task_verify_agent.verify(
                message=message,
                user_id=user_id,
                memory_context=memory_context,
                thread_id=thread_id,
                user_profile=user_profile or {},
            )
            return self._format_task_update(result)

        result = await self.conversation_agent.process_message_async(
            message,
            user_context=self._user_context(user_id, channel, thread_id, memory_context, metadata, user_profile),
            user_profile=user_profile or {},
            timezone_name=self._timezone_name(metadata),
        )
        return self._format_conversation(result)

    async def _load_memory_context_new_session(self, conversation_id: str) -> str:
        t = time.perf_counter()
        async with AsyncSessionLocal() as db:
            result = await self._load_memory_context(conversation_id, db)
        logger.info("memory_load_ms=%.0f", (time.perf_counter() - t) * 1000)
        return result

    async def _load_user_profile_new_session(self, user_id: str) -> dict:
        t = time.perf_counter()
        async with AsyncSessionLocal() as db:
            result = await self._load_user_profile(user_id, db)
        logger.info("profile_load_ms=%.0f", (time.perf_counter() - t) * 1000)
        return result

    async def _load_memory_context(self, conversation_id: str, db: AsyncSession) -> str:
        try:
            summary, recent_turns = await load_memory(conversation_id, db)
        except Exception:
            logger.exception("Failed to load memory for conversation %s", conversation_id)
            return ""
        return self._build_memory_context(summary, recent_turns)

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

    def _build_memory_context(self, summary: str, recent_turns: list[dict]) -> str:
        parts = []
        if summary:
            parts.append(f"Tóm tắt trước: {summary}")
        if recent_turns:
            lines = ["Các lượt gần đây:"]
            for turn in recent_turns:
                lines.append(f"User: {turn.get('user', '')}")
                lines.append(f"Bot: {turn.get('bot', '')}")
            parts.append("\n".join(lines))
        return "\n\n".join(parts).strip()

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

    def _format_conversation(self, result: Any) -> str:
        if isinstance(result, dict):
            return str(result.get("message") or result.get("answer") or result)
        return str(result)

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
        for index, row in enumerate(rows[:10], start=1):
            if isinstance(row, dict):
                values = ", ".join(f"{key}: {value}" for key, value in row.items())
                lines.append(f"{index}. {values}")
            else:
                lines.append(f"{index}. {row}")

        if len(rows) > 10:
            lines.append(f"... và {len(rows) - 10} dòng khác.")
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

    def _format_notification(self, result: Any) -> str:
        if hasattr(result, "message"):
            return str(result.message)
        if isinstance(result, dict):
            return str(result.get("message") or result)
        return str(result)

    def _format_task_update(self, result: Any) -> str:
        if isinstance(result, dict):
            return str(result.get("message") or result)
        return str(result)

    def _format_agent_result(self, agent_name: str, result: Any) -> str:
        if agent_name == "conversation":
            return self._format_conversation(result)
        if agent_name == "text2sql" and isinstance(result, dict):
            return self._format_text2sql(result)
        if agent_name == "report":
            return self._format_report(result.get("answer") if isinstance(result, dict) else result)
        if agent_name == "planning":
            if isinstance(result, dict) and result.get("answer"):
                return str(result["answer"])
            return self._format_planning(result)
        if agent_name == "notification":
            return self._format_notification(result)
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

