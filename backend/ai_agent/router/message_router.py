import json
import logging
from dataclasses import dataclass
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

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

        try:
            if db is not None and conversation_id:
                memory_context = await self._load_memory_context(conversation_id, db)
                metadata = {
                    **metadata,
                    "conversation_id": conversation_id,
                    "correlation_id": correlation_id,
                    "memory_loaded": bool(memory_context),
                }

            selected = self.intent_router.selected_agents(message)
            agent_name, confidence = self._pick_agent(selected)
            agent_name = self._fallback_agent_for_message(message, agent_name, confidence)

            logger.info(
                "message routed agent=%s confidence=%s user_id=%s channel=%s thread_id=%s",
                agent_name,
                confidence,
                user_id,
                channel,
                thread_id,
            )

            answer = await self._run_agent(
                agent_name,
                message,
                user_id,
                channel,
                thread_id,
                metadata,
                memory_context,
            )
            return AgentReply(
                answer=answer,
                agent=agent_name,
                confidence=confidence,
                metadata={"selected_agents": self._selected_metadata(selected), **metadata},
            )
        except Exception:
            logger.exception(
                "message routing failed user_id=%s channel=%s thread_id=%s",
                user_id,
                channel,
                thread_id,
            )
            return AgentReply(
                answer="Xin lỗi, mình đang gặp lỗi khi xử lý tin nhắn này. Bạn thử lại giúp mình nhé.",
                agent="error",
                confidence=0.0,
                metadata=metadata,
            )

    async def stream_message(
        self,
        message: str,
        user_id: str,
        channel: str = "gapo",
        thread_id: str | None = None,
        metadata: dict | None = None,
        db: AsyncSession | None = None,
        conversation_id: str | None = None,
        correlation_id: str | None = None,
    ) -> AsyncIterator[dict]:
        metadata = metadata or {}
        conversation_id = conversation_id or thread_id
        memory_context = ""

        try:
            if db is not None and conversation_id:
                memory_context = await self._load_memory_context(conversation_id, db)
                metadata = {
                    **metadata,
                    "conversation_id": conversation_id,
                    "correlation_id": correlation_id,
                    "memory_loaded": bool(memory_context),
                }

            selected = self.intent_router.selected_agents(message)
            agent_name, confidence = self._pick_agent(selected)
            agent_name = self._fallback_agent_for_message(message, agent_name, confidence)
            metadata = {"selected_agents": self._selected_metadata(selected), **metadata}

            yield {"type": "status", "content": f"Đang xử lý bằng agent {agent_name}..."}

            full_answer = ""
            agent_result: Any = None
            async for event in self._stream_agent(
                agent_name,
                message,
                user_id,
                channel,
                thread_id,
                metadata,
                memory_context,
            ):
                event_type = event.get("type")
                if event_type == "answer_chunk":
                    full_answer += str(event.get("content") or "")
                    yield event
                elif event_type == "result":
                    agent_result = event.get("content")
                else:
                    yield event

            if not full_answer.strip() and agent_result is not None:
                full_answer = self._format_agent_result(agent_name, agent_result)

            yield {
                "type": "result",
                "content": {
                    "answer": full_answer.strip(),
                    "agent": agent_name,
                    "confidence": confidence,
                    "metadata": metadata,
                    "agent_result": self._jsonable(agent_result),
                },
            }
        except Exception:
            logger.exception(
                "stream message routing failed user_id=%s channel=%s thread_id=%s",
                user_id,
                channel,
                thread_id,
            )
            answer = "Xin lỗi, mình đang gặp lỗi khi xử lý tin nhắn này. Bạn thử lại giúp mình nhé."
            yield {"type": "answer_chunk", "content": answer}
            yield {
                "type": "result",
                "content": {
                    "answer": answer,
                    "agent": "error",
                    "confidence": 0.0,
                    "metadata": metadata,
                    "agent_result": None,
                },
            }

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
    ) -> str:
        if agent_name == "conversation":
            result = await self.conversation_agent.process_message_async(
                message,
                user_context=self._user_context(user_id, channel, thread_id, memory_context, metadata),
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
            result = await self.planning_agent.generate_project_plan(message, memory_context=memory_context)
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
            user_context=self._user_context(user_id, channel, thread_id, memory_context, metadata),
            timezone_name=self._timezone_name(metadata),
        )
        return self._format_conversation(result)

    async def _stream_agent(
        self,
        agent_name: str,
        message: str,
        user_id: str,
        channel: str,
        thread_id: str | None,
        metadata: dict,
        memory_context: str = "",
    ) -> AsyncIterator[dict]:
        if agent_name == "conversation":
            async for event in self.conversation_agent.stream_process_message(
                message,
                user_context=self._user_context(user_id, channel, thread_id, memory_context, metadata),
                timezone_name=self._timezone_name(metadata),
            ):
                yield event
            return

        if agent_name == "text2sql":
            async for event in self.text2sql_agent.stream_execute(
                message,
                memory_context=memory_context,
                current_user_id=user_id,
            ):
                yield event
            return

        if agent_name == "report":
            async for event in self.report_agent.stream_generate_report(message, memory_context=memory_context):
                yield event
            return

        if agent_name == "planning":
            async for event in self.planning_agent.stream_generate_project_plan(message, memory_context=memory_context):
                yield event
            return

        if agent_name == "notification":
            async for event in self.notification_agent.stream_prepare_notification(
                user_id=user_id,
                thread_id=thread_id,
                message=message,
                memory_context=memory_context,
            ):
                yield event
            return

        async for event in self.conversation_agent.stream_process_message(
            message,
            user_context=self._user_context(user_id, channel, thread_id, memory_context, metadata),
            timezone_name=self._timezone_name(metadata),
        ):
            yield event

    async def _load_memory_context(self, conversation_id: str, db: AsyncSession) -> str:
        try:
            summary, recent_turns = await load_memory(conversation_id, db)
        except Exception:
            logger.exception("Failed to load memory for conversation %s", conversation_id)
            return ""
        return self._build_memory_context(summary, recent_turns)

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
    ) -> str:
        parts = [f"user_id={user_id}", f"channel={channel}"]
        parts.append(f"timezone={self._timezone_name(metadata)}")
        if thread_id:
            parts.append(f"thread_id={thread_id}")
        if memory_context:
            parts.append(f"memory_context={memory_context}")
        return ", ".join(parts)

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
