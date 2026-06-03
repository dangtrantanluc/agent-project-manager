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
from ai_agent.router.router import Agent, PMMultiAgentRouter
from ai_agent.text_to_sql.text2sql import Text2SQLAgent
from ai_agent.notification.notification_agent import NotificationAgent

logger = logging.getLogger(__name__)
DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"

@dataclass
class AgentReply:
    answer: str
    agent: str
    confidence: float = 0.0
    metadata: dict | None = None

class AgentMessageRouter:
    def __init__(self):
        self.intent_router = PMMultiAgentRouter()
        self.conversation_agent = ConversationAgent()
        self.text2sql_agent = Text2SQLAgent()
        self.report_agent = ReportAgent()
        self.planning_agent = PlanningAgent()
        self.notification_agent = NotificationAgent()

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

            agent_name, confidence = self._pick_agent(selected)
            agent_name = self._fallback_agent_for_message(message, agent_name, confidence)

            logger.info(
                "routed agent=%s confidence=%.2f route_ms=%.0f user_id=%s thread_id=%s",
                agent_name, confidence, route_ms, user_id, thread_id,
            )

            t_exec = time.perf_counter()
            answer = await self._run_agent(
                agent_name,
                message,
                user_id,
                channel,
                thread_id,
                metadata,
                memory_context,
                user_profile,
            )
            exec_ms = (time.perf_counter() - t_exec) * 1000
            total_ms = (time.perf_counter() - t_total) * 1000

            logger.info(
                "request_done agent=%s exec_ms=%.0f total_ms=%.0f user_id=%s thread_id=%s",
                agent_name, exec_ms, total_ms, user_id, thread_id,
            )
            return AgentReply(
                answer=answer,
                agent=agent_name,
                confidence=confidence,
                metadata={"selected_agents": self._selected_metadata(selected), **metadata},
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
                confidence=0.0,
                metadata=metadata,
            )

    def _pick_agent(self, selected: list[Agent] | list[str]) -> tuple[str, float]:
        if not selected:
            return "conversation", 0.0

        first = selected[0]
        if isinstance(first, str):
            return first or "conversation", 0.0

        return first.name or "conversation", float(first.confidence or 0.0)

    def _fallback_agent_for_message(self, message: str, agent_name: str, confidence: float) -> str:
        if agent_name != "conversation" or confidence > 0:
            logger.info("No fallback needed for agent=%s with confidence=%s", agent_name, confidence)
            return agent_name

        lowered = message.lower()
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

        if any(keyword in lowered for keyword in planning_keywords):
            return "planning"
        if any(keyword in lowered for keyword in report_keywords):
            return "report"
        if any(keyword in lowered for keyword in notification_keywords):
            return "notification"
        if any(keyword in lowered for keyword in data_keywords):
            return "text2sql"
        return agent_name

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
            result = await self.text2sql_agent.execute(
                message,
                memory_context=memory_context,
                current_user_id=user_id,
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

    def _selected_metadata(self, selected: list[Agent] | list[str]) -> list[dict]:
        items = []
        for item in selected:
            if isinstance(item, str):
                items.append({"name": item, "confidence": 0.0})
            else:
                items.append({"name": item.name, "confidence": item.confidence})
        return items
