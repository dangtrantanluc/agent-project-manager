# backend/integrations/gapo/gapo_adapter.py

import json
import logging
import os
import time
from sqlalchemy import text
from langchain_openai import ChatOpenAI

from database import AsyncSessionLocal
from gapo.gapo_schema import GapoWebhookPayload
from gapo.gapo_client import GapoClient
from ai_agent.checkin.service import CheckinFlowService
from ai_agent.checkin.worklog_parser.service import WorklogParserService
from ai_agent.memory.memory import save_memory
from ai_agent.router.message_router import AgentMessageRouter
logger = logging.getLogger(__name__)


class GapoAdapter:
    def __init__(self):
        self.client = GapoClient()
        self.router = AgentMessageRouter()
        llm = ChatOpenAI(
            model=os.getenv("MODEL_NAME"),
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL"),
        )
        self.llm = llm
        self.checkin = CheckinFlowService(
            gapo=self.client,
            worklog_parser=WorklogParserService(llm=llm),
        )

    async def handle_event(self, raw_payload: dict, headers: dict | None = None):
        response_timer = self.start_response_timer()
        headers = headers or {}
        payload = GapoWebhookPayload(**raw_payload)
        bot_id = self._resolve_bot_id(payload, headers)
        correlation_id = str(payload.message.id or payload.id) if payload.message else str(payload.id)

        logger.info("gapo event=%s payload_id=%s", payload.event, payload.id)

        if payload.event == "thread_created":
            return {"ok": True, "ignored": "thread_created"}

        if payload.event != "message_created":
            return {"ok": True, "ignored": payload.event}

        if not payload.message:
            return {"ok": True, "ignored": "empty_message"}

        if not payload.thread_id or not bot_id:
            logger.warning("gapo missing thread_id or bot_id")
            return {"ok": False, "error": "missing_thread_or_bot_id"}
        if bot_id and not self.client.bot_id:
            self.client.bot_id = str(bot_id)

        message_type = payload.message.type
        user_text = self._extract_user_text(payload)
        timing_context = {
            "event_id": payload.id,
            "message_id": payload.message.id,
            "thread_id": payload.thread_id,
            "from_user_id": payload.from_user_id,
            "bot_id": bot_id,
            "message_type": message_type,
        }

        if not user_text:
            elapsed_ms = await self.send_text_with_response_time(
                thread_id=payload.thread_id,
                bot_id=bot_id,
                text="Mình chưa đọc được nội dung tin nhắn này.",
                started_at=response_timer,
                correlation_id=correlation_id,
                audit_context={**timing_context, "reply_kind": "empty_message"},
            )
            return {"ok": True, "response_time_ms": elapsed_ms}

        if message_type not in ["text", "quick_reply", "menu"]:
            elapsed_ms = await self.send_text_with_response_time(
                thread_id=payload.thread_id,
                bot_id=bot_id,
                text="Hiện tại bot chỉ hỗ trợ tin nhắn văn bản.",
                started_at=response_timer,
                correlation_id=correlation_id,
                audit_context={**timing_context, "reply_kind": "unsupported_message_type"},
            )
            return {"ok": True, "response_time_ms": elapsed_ms}

        logger.info("gapo user_id=%s text=%s", payload.from_user_id, user_text)

        mapped_user = await self._lookup_gapo_user(str(payload.from_user_id))
        if mapped_user:
            async with AsyncSessionLocal() as db:
                checkin_answer = await self.checkin.handle_message(
                    db,
                    message_text=user_text,
                    gapo_user_id=str(payload.from_user_id),
                    conversation_id=str(payload.thread_id),
                    user_id=mapped_user["user_id"],
                )
            if checkin_answer is not None:
                if checkin_answer:
                    elapsed_ms = await self.send_text_with_response_time(
                        thread_id=payload.thread_id,
                        bot_id=bot_id,
                        text=checkin_answer,
                        started_at=response_timer,
                        correlation_id=correlation_id,
                        audit_context={**timing_context, "reply_kind": "checkin"},
                    )
                    return {"ok": True, "handled_by": "checkin", "response_time_ms": elapsed_ms}
                elapsed_ms = self.response_time_ms(response_timer)
                logger.info(
                    "gapo message handled without reply thread_id=%s correlation_id=%s response_time_ms=%s",
                    payload.thread_id,
                    correlation_id,
                    elapsed_ms,
                )
                return {"ok": True, "handled_by": "checkin", "response_time_ms": elapsed_ms}

        conversation_id = str(payload.thread_id)
        async with AsyncSessionLocal() as db:
            result = await self.router.handle_message(
                message=user_text,
                user_id=str(mapped_user["user_id"]) if mapped_user else str(payload.from_user_id),
                channel="gapo",
                thread_id=conversation_id,
                metadata={
                    "gapo_event_id": payload.id,
                    "gapo_message_id": payload.message.id,
                    "gapo_bot_id": bot_id,
                    "gapo_message_type": message_type,
                    "timezone": mapped_user.get("timezone") if mapped_user else "Asia/Ho_Chi_Minh",
                },
                db=db,
                conversation_id=conversation_id,
                correlation_id=correlation_id,
            )
            
            answer = getattr(result, "answer", None) or str(result)
            elapsed_ms = await self.send_text_with_response_time(
                thread_id=payload.thread_id,
                bot_id=bot_id,
                text=answer,
                started_at=response_timer,
                correlation_id=correlation_id,
                audit_context={
                    **timing_context,
                    "reply_kind": "agent",
                    "agent": getattr(result, "agent", "unknown"),
                },
            )
            
            if getattr(result, "agent", "") != "error":
                try:
                    await save_memory(
                        conversation_id=conversation_id,
                        user_text=user_text,
                        reply_text=getattr(result, "answer", None) or str(result),
                        tools_used=[getattr(result, "agent", "unknown")],
                        correlation_id=correlation_id,
                        db=db,
                        llm=self.llm,
                        user_id=mapped_user["user_id"] if mapped_user else None,
                        company_id=mapped_user.get("company_id") if mapped_user else None,
                    )
                except Exception:
                    await db.rollback()
                    logger.exception("Failed to save memory for conversation %s", conversation_id)


        return {"ok": True, "response_time_ms": elapsed_ms}

    def start_response_timer(self) -> float:
        """Mark the moment a Gapo user message starts being handled."""
        return time.perf_counter()

    def response_time_ms(self, started_at: float) -> int:
        """Return elapsed milliseconds since the Gapo user message was received."""
        return max(0, round((time.perf_counter() - started_at) * 1000))

    async def send_text_with_response_time(
        self,
        *,
        thread_id: int | str,
        bot_id: int | str | None,
        text: str,
        started_at: float,
        correlation_id: str | None = None,
        audit_context: dict | None = None,
    ) -> int:
        await self.client.send_text(
            thread_id=thread_id,
            bot_id=bot_id,
            text=text,
        )
        elapsed_ms = self.response_time_ms(started_at)
        logger.info(
            "[GAPO_RESPONSE_TIME] thread_id=%s correlation_id=%s response_time_ms=%s",
            thread_id,
            correlation_id,
            elapsed_ms,
        )
        print(
            f"[GAPO_RESPONSE_TIME] thread_id={thread_id} "
            f"correlation_id={correlation_id} response_time_ms={elapsed_ms}",
            flush=True,
        )
        await self._record_response_time(
            elapsed_ms=elapsed_ms,
            correlation_id=correlation_id,
            audit_context=audit_context,
        )
        return elapsed_ms

    async def _record_response_time(
        self,
        *,
        elapsed_ms: int,
        correlation_id: str | None = None,
        audit_context: dict | None = None,
    ) -> None:
        try:
            async with AsyncSessionLocal() as db:
                await db.execute(text("""
                    INSERT INTO agent_audit_log
                        (tool, args_json, result_json, duration_ms, correlation_id, source, created_at)
                    VALUES
                        (:tool, CAST(:args AS jsonb), CAST(:result AS jsonb), :duration_ms,
                         :correlation_id, CAST('chat' AS "AgentAuditSource"), NOW())
                """), {
                    "tool": "gapo_response_time",
                    "args": json.dumps(audit_context or {}),
                    "result": json.dumps({"response_time_ms": elapsed_ms}),
                    "duration_ms": elapsed_ms,
                    "correlation_id": correlation_id,
                })
                await db.commit()
        except Exception:
            logger.exception(
                "Failed to record Gapo response time correlation_id=%s response_time_ms=%s",
                correlation_id,
                elapsed_ms,
            )

    async def _lookup_gapo_user(self, gapo_user_id: str) -> dict | None:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(text("""
                SELECT u.id, COALESCE(u.timezone, 'Asia/Ho_Chi_Minh') AS timezone
                FROM gapo_user_maps gum
                JOIN users u ON u.id = gum.user_id
                WHERE gum.gapo_user_id::text = :gid
                  AND u.active = true
                LIMIT 1
            """), {"gid": gapo_user_id})).fetchone()
        if not row:
            return None
        return {"user_id": row[0], "timezone": row[1]}

    def _extract_user_text(self, payload: GapoWebhookPayload) -> str:
        message = payload.message
        if not message:
            return ""
        if message.type == "quick_reply":
            return message.payload or message.text or ""
        if message.type == "menu":
            return message.payload or message.text or ""
        return message.text or ""

    def _resolve_bot_id(self, payload: GapoWebhookPayload, headers: dict) -> str | int | None:
        header_bot_id = headers.get("x-gapo-bot-id") or headers.get("X-Gapo-Bot-Id")
        return header_bot_id or payload.to_bot_id
