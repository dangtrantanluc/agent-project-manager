# backend/integrations/gapo/gapo_adapter.py

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime
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
        self.checkin = CheckinFlowService(
            gapo=self.client,
            worklog_parser=WorklogParserService(llm=llm),
        )

    @staticmethod
    def verify_signature(raw_body: bytes, headers: dict) -> bool:
        """Xác thực chữ ký HMAC-SHA256 của webhook Gapo.

        Chỉ enforce khi GAPO_WEBHOOK_SECRET được cấu hình (rollout an toàn cho dev).
        Tên header chữ ký cấu hình qua GAPO_SIGNATURE_HEADER (mặc định x-gapo-signature).
        Trả về True nếu hợp lệ HOẶC nếu chưa bật xác thực; False nếu sai chữ ký.
        """
        secret = os.getenv("GAPO_WEBHOOK_SECRET", "")
        if not secret:
            # Production: từ chối khi chưa cấu hình secret (fail-closed, chống giả mạo).
            # Dev: cho qua để dễ thử webhook cục bộ.
            is_prod = os.getenv("APP_ENV", os.getenv("ENV", "development")).lower() in {
                "prod", "production",
            }
            if is_prod:
                logger.error("gapo webhook: GAPO_WEBHOOK_SECRET chưa đặt — từ chối trong production")
                return False
            return True  # dev: chưa bật xác thực

        header_name = os.getenv("GAPO_SIGNATURE_HEADER", "x-gapo-signature").lower()
        # headers có thể là dict thường (case-sensitive) → so khớp không phân biệt hoa thường.
        provided = ""
        for key, value in headers.items():
            if key.lower() == header_name:
                provided = (value or "").strip()
                break
        if not provided:
            logger.warning("gapo webhook thiếu header chữ ký %s", header_name)
            return False

        # Hỗ trợ định dạng "sha256=<hex>" lẫn "<hex>" thuần.
        if "=" in provided:
            provided = provided.split("=", 1)[1]

        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, provided):
            logger.warning("gapo webhook chữ ký không hợp lệ")
            return False
        return True

    async def handle_event(
        self,
        raw_payload: dict,
        headers: dict | None = None,
        raw_body: bytes | None = None,
    ):
        response_timer = self.start_response_timer()
        headers = headers or {}
        # Xác thực chữ ký trước khi xử lý bất kỳ nội dung nào (chống webhook giả mạo).
        if raw_body is not None and not self.verify_signature(raw_body, headers):
            return {"ok": False, "error": "invalid_signature"}
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

        # Lệnh tự-liên-kết: xử lý TRƯỚC khi chặn user chưa map, vì đây chính là
        # cách user chưa map gắn tài khoản Gapo của họ vào hệ thống.
        if user_text.strip().lower().startswith("/link"):
            reply = await self._handle_link_command(
                user_text=user_text,
                gapo_user_id=payload.from_user_id,
                thread_id=payload.thread_id,
            )
            elapsed_ms = await self.send_text_with_response_time(
                thread_id=payload.thread_id,
                bot_id=bot_id,
                text=reply,
                started_at=response_timer,
                correlation_id=correlation_id,
                audit_context={**timing_context, "reply_kind": "link_command"},
            )
            return {"ok": True, "handled_by": "link_command", "response_time_ms": elapsed_ms}

        mapped_user = await self._lookup_gapo_user(str(payload.from_user_id))
        # An ninh: chỉ phục vụ user đã được liên kết (gapo_user_maps) và đang active.
        # KHÔNG fallback dùng from_user_id thô làm user_id — đó là input từ webhook
        # bên ngoài, có thể bị giả mạo để truy vấn dữ liệu của người khác.
        if not mapped_user:
            logger.warning(
                "gapo unmapped user from_user_id=%s thread_id=%s — từ chối route vào agent",
                payload.from_user_id, payload.thread_id,
            )
            elapsed_ms = await self.send_text_with_response_time(
                thread_id=payload.thread_id,
                bot_id=bot_id,
                text=(
                    "Tài khoản Gapo của bạn chưa được liên kết với hệ thống. "
                    "Vui lòng liên hệ quản trị viên để được cấp quyền sử dụng bot."
                ),
                started_at=response_timer,
                correlation_id=correlation_id,
                audit_context={**timing_context, "reply_kind": "unmapped_user"},
            )
            return {"ok": True, "handled_by": "rejected_unmapped", "response_time_ms": elapsed_ms}

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
                user_id=str(mapped_user["user_id"]),
                channel="gapo",
                thread_id=conversation_id,
                metadata={
                    "gapo_event_id": payload.id,
                    "gapo_message_id": payload.message.id,
                    "gapo_bot_id": bot_id,
                    "gapo_message_type": message_type,
                    "timezone": mapped_user.get("timezone") or "Asia/Ho_Chi_Minh",
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
                        user_id=mapped_user["user_id"],
                        company_id=mapped_user.get("company_id"),
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

    async def _handle_link_command(
        self,
        *,
        user_text: str,
        gapo_user_id: int | None,
        thread_id: int | None,
    ) -> str:
        """Xử lý lệnh "/link <mã>" để gắn tài khoản Gapo vào user nội bộ.

        Lấy gapo_user_id + thread_id trực tiếp từ webhook (nguồn đáng tin duy
        nhất), nên admin/nhân viên không bao giờ phải nhập tay 2 số này.
        """
        parts = user_text.strip().split()
        if len(parts) < 2 or not parts[1].strip():
            return (
                "Cú pháp: /link <mã>\n"
                "Ví dụ: /link 7K2P9X\n"
                "Mã liên kết do quản trị viên cấp cho bạn."
            )
        code = parts[1].strip().upper()

        if gapo_user_id is None or thread_id is None:
            logger.warning(
                "gapo /link thiếu from_user_id/thread_id (user_id=%s thread_id=%s)",
                gapo_user_id, thread_id,
            )
            return "Không xác định được tài khoản Gapo của bạn. Vui lòng thử lại."

        async with AsyncSessionLocal() as db:
            code_row = (await db.execute(text("""
                SELECT id, user_id, expires_at, used_at
                FROM gapo_link_codes
                WHERE code = :code
                LIMIT 1
            """), {"code": code})).fetchone()

            if not code_row:
                return "Mã liên kết không đúng. Vui lòng kiểm tra lại với quản trị viên."
            code_id, target_user_id, expires_at, used_at = code_row
            if used_at is not None:
                return "Mã liên kết này đã được sử dụng. Vui lòng yêu cầu mã mới."
            if expires_at <= datetime.utcnow():
                return "Mã liên kết đã hết hạn. Vui lòng yêu cầu quản trị viên cấp mã mới."

            # Một tài khoản Gapo không được gắn cho 2 user nội bộ khác nhau.
            conflict = (await db.execute(text("""
                SELECT user_id FROM gapo_user_maps
                WHERE gapo_user_id = :gid AND user_id <> :uid
                LIMIT 1
            """), {"gid": gapo_user_id, "uid": target_user_id})).fetchone()
            if conflict:
                logger.warning(
                    "gapo /link xung đột: gapo_user_id=%s đã gắn user_id=%s, mã yêu cầu user_id=%s",
                    gapo_user_id, conflict[0], target_user_id,
                )
                return (
                    "Tài khoản Gapo này đã được liên kết với một người dùng khác. "
                    "Vui lòng liên hệ quản trị viên."
                )

            # user_id là UNIQUE trong gapo_user_maps → ON CONFLICT cho phép relink.
            await db.execute(text("""
                INSERT INTO gapo_user_maps
                    (user_id, gapo_user_id, gapo_thread_id, last_seen_at, created_at)
                VALUES
                    (:uid, :gid, :tid, NOW(), NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    gapo_user_id = EXCLUDED.gapo_user_id,
                    gapo_thread_id = EXCLUDED.gapo_thread_id,
                    last_seen_at = NOW()
            """), {"uid": target_user_id, "gid": gapo_user_id, "tid": thread_id})

            await db.execute(text("""
                UPDATE gapo_link_codes
                SET used_at = NOW(), used_by_gapo_user_id = :gid
                WHERE id = :cid
            """), {"gid": gapo_user_id, "cid": code_id})

            await db.execute(text("""
                INSERT INTO agent_audit_log
                    (tool, args_json, result_json, source, created_at)
                VALUES
                    ('gapo_link', CAST(:args AS jsonb), CAST(:result AS jsonb),
                     CAST('chat' AS "AgentAuditSource"), NOW())
            """), {
                "args": json.dumps({
                    "code": code,
                    "user_id": target_user_id,
                    "gapo_user_id": gapo_user_id,
                    "thread_id": thread_id,
                }),
                "result": json.dumps({"status": "linked"}),
            })
            await db.commit()

        logger.info(
            "gapo /link thành công: user_id=%s gapo_user_id=%s thread_id=%s",
            target_user_id, gapo_user_id, thread_id,
        )
        return "✅ Liên kết thành công! Bạn đã có thể trò chuyện với bot."

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
