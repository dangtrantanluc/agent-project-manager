"""Bot chủ động nhắn cho NGƯỜI KHÁC theo yêu cầu của user.

Vd: Lực nhắn "nhắn Thảo chắc deadline hôm nay đi" → bot phải gửi DM cho Thảo
(không phải trả lời lại Lực). Khác hẳn notification_agent cũ vốn chỉ soạn text
rồi trả về thread của chính người hỏi.

Luồng:
  1. LLM bóc {recipient, body} từ câu tự do (structured output).
  2. Tra recipient trong cùng company của người gửi → user + gapo target.
  3. Gửi DM cho recipient; trả về kết quả để router soạn câu xác nhận cho
     người gửi (hoặc hỏi lại nếu không rõ recipient).

Không tự ý gửi khi không chắc recipient là ai — thà hỏi lại còn hơn gửi nhầm.
"""
import logging
import os
from dataclasses import dataclass

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import AsyncSessionLocal
from gapo.gapo_client import GapoClient

log = logging.getLogger(__name__)

_EXTRACT_SYSTEM_PROMPT = """\
Bạn bóc tách yêu cầu "nhờ bot nhắn hộ một người khác" trong môi trường quản lý dự án.

Nhiệm vụ: từ câu của người dùng, xác định:
- recipient: TÊN người sẽ nhận tin (ví dụ "Thảo", "anh Nam"). Bỏ kính ngữ
  (anh/chị/em/bạn) nếu có, chỉ giữ tên. Nếu câu không nhắm tới ai cụ thể để
  bot nhắn hộ, để recipient rỗng.
- body: NỘI DUNG cần truyền đạt cho người nhận, viết lại ở ngôi thứ hai, ngắn
  gọn, lịch sự, thân thiện. KHÔNG thêm lời chào của bot, KHÔNG xưng là bot.

Ví dụ: "nhắn thảo chắc deadline hôm nay đi và update task"
→ recipient="Thảo", body="Bạn kiểm tra giúp các task đến hạn hôm nay và cập nhật tiến độ trên hệ thống nhé."
"""


class OutboundExtraction(BaseModel):
    recipient: str = Field(default="", description="Tên người nhận, rỗng nếu không xác định")
    body: str = Field(default="", description="Nội dung cần nhắn cho người nhận")


@dataclass
class OutboundResult:
    status: str  # sent | not_found | ambiguous | not_linked | no_recipient | error
    recipient_name: str | None = None
    body: str | None = None
    candidates: list[str] | None = None


class OutboundMessageService:
    def __init__(self, llm: ChatOpenAI | None = None, gapo: GapoClient | None = None):
        self._gapo = gapo or GapoClient()
        self._llm = None
        model = os.getenv("MODEL_NAME")
        api_key = os.getenv("API_KEY")
        base_url = os.getenv("BASE_URL")
        if llm is not None:
            self._llm = llm.with_structured_output(OutboundExtraction, method="function_calling")
        elif model and api_key and base_url:
            # timeout ngắn + 1 retry: bóc recipient là tác vụ nhẹ; LLM chậm KHÔNG
            # được treo cả luồng reply (trước đây 60s×retry -> ~200s ReadTimeout).
            base = ChatOpenAI(model=model, timeout=15, max_retries=1, temperature=0.3,
                              api_key=api_key, base_url=base_url)
            self._llm = base.with_structured_output(OutboundExtraction, method="function_calling")
        else:
            log.warning("OutboundMessageService LLM chưa cấu hình; không bóc tách được recipient.")

    async def send_on_behalf(
        self,
        *,
        message: str,
        sender_user_id: str | int,
        memory_context: str = "",
    ) -> OutboundResult:
        """Bóc recipient/body từ ``message`` rồi gửi DM cho recipient.

        ``sender_user_id`` là users.id của người yêu cầu (để giới hạn tìm
        recipient trong cùng company và không cho tự nhắn cho chính mình).
        """
        extraction = await self._extract(message, memory_context)
        if extraction is None or not extraction.recipient.strip():
            return OutboundResult(status="no_recipient")

        recipient_name = extraction.recipient.strip()
        body = extraction.body.strip() or message.strip()

        matches = await self._resolve_recipients(recipient_name, sender_user_id)
        if not matches:
            return OutboundResult(status="not_found", recipient_name=recipient_name)
        if len(matches) > 1:
            return OutboundResult(
                status="ambiguous",
                recipient_name=recipient_name,
                candidates=[m["full_name"] for m in matches],
            )

        target = matches[0]
        if not target["gapo_thread_id"] and not target["gapo_user_id"]:
            return OutboundResult(
                status="not_linked",
                recipient_name=target["full_name"],
            )

        try:
            # DM CHỦ ĐỘNG cho người thứ ba: ưu tiên receiver_id để Gapo tự định tuyến
            # tới thread 1-1 đúng người. (Trước đây ưu tiên thread_id đã lưu -> Gapo
            # trả 200 nhưng KHÔNG giao nếu thread cũ/không phải DM bot<->người nhận.)
            if target["gapo_user_id"]:
                await self._gapo.send_to_user(receiver_id=target["gapo_user_id"], text=body)
            else:
                await self._gapo.send_message(thread_id=str(target["gapo_thread_id"]), text=body)
        except Exception:
            log.exception(
                "send_on_behalf gửi thất bại recipient=%s (user_id=%s)",
                target["full_name"], target["user_id"],
            )
            return OutboundResult(status="error", recipient_name=target["full_name"], body=body)

        return OutboundResult(status="sent", recipient_name=target["full_name"], body=body)

    async def _extract(self, message: str, memory_context: str) -> OutboundExtraction | None:
        if self._llm is None:
            return None
        memory_block = f"Ngữ cảnh hội thoại trước đó:\n{memory_context}\n\n" if memory_context else ""
        try:
            return await self._llm.ainvoke([
                SystemMessage(content=_EXTRACT_SYSTEM_PROMPT),
                HumanMessage(content=f"{memory_block}Câu của người dùng:\n{message}"),
            ])
        except Exception:
            log.exception("OutboundMessageService bóc tách recipient thất bại")
            return None

    async def _resolve_recipients(
        self, recipient_name: str, sender_user_id: str | int,
    ) -> list[dict]:
        """Tìm user khớp tên trong CÙNG company với người gửi, kèm gapo target.

        Khớp không phân biệt hoa/thường, theo cả full_name lẫn gapo_full_name;
        loại chính người gửi để tránh tự nhắn cho mình.
        """
        like = f"%{recipient_name.lower()}%"
        # asyncpg suy kiểu tham số từ cách dùng — bind int trực tiếp cho cột
        # integer, KHÔNG wrap CAST(:sender AS INTEGER) quanh một str (sẽ lỗi
        # "'str' object cannot be interpreted as an integer").
        sender_id = int(sender_user_id)
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                text("""
                    SELECT u.id, u.full_name, g.gapo_thread_id, g.gapo_user_id
                    FROM users u
                    LEFT JOIN gapo_user_maps g ON g.user_id = u.id
                    WHERE u.active = true
                      AND u.id <> :sender
                      AND u.company_id = (
                          SELECT company_id FROM users WHERE id = :sender
                      )
                      AND (
                          lower(u.full_name) LIKE :like
                          OR lower(COALESCE(g.gapo_full_name, '')) LIKE :like
                      )
                    ORDER BY u.full_name
                """),
                {"sender": sender_id, "like": like},
            )).fetchall()

        return [
            {
                "user_id": r[0],
                "full_name": r[1],
                "gapo_thread_id": r[2],
                "gapo_user_id": r[3],
            }
            for r in rows
        ]
