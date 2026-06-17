"""Phân loại text tự do giữa phiên check-in: thuộc check-in hay là intent khác.

Khi user đang trong check-in mà gõ một câu tự do (không phải số / "hủy" / "bỏ
qua"), cần biết câu đó là input của check-in (mô tả worklog, từ khoá tìm task)
hay là một ý định khác (tạo task, xem báo cáo...). Nếu là intent khác, check-in
phải nhường quyền cho router thay vì nuốt câu đó.

Fail-safe: mọi lỗi LLM -> coi như THUỘC check-in (giữ hành vi an toàn cũ, không
bao giờ tự ý thoát check-in khi không chắc chắn).
"""

import logging
import os

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ai_agent.shared.llm_factory import make_llm

logger = logging.getLogger(__name__)

# Các intent "mạnh" mà router xử lý — khớp VALID_AGENTS của router.
_KNOWN_INTENTS = {
    "create_task", "report", "text2sql", "planning",
    "task_update", "add_member", "conversation",
}

_SYSTEM_PROMPT = """Bạn là bộ phân loại cho một chatbot quản lý dự án (tiếng Việt).
Người dùng ĐANG trong một phiên check-in (báo cáo công việc trong ngày). Nhiệm vụ
của bạn: xác định câu người dùng vừa gõ có thuộc luồng check-in không, hay là một
ý định KHÁC cần chuyển sang chức năng riêng.

THUỘC check-in (belongs_to_checkin=true) khi câu là:
- Mô tả công việc ĐÃ LÀM kèm/không kèm số giờ (vd "fix bug login 2h", "tạo xong
  trang đăng nhập 3h", "review code", "họp team 1h"). Lưu ý: câu mô tả việc đã
  làm vẫn THUỘC check-in dù có chứa từ "tạo", "làm", "báo cáo".
- Từ khoá để tìm/chọn dự án hoặc task (vd "dự án CRM", "task login").
- Câu trả lời ngắn cho câu hỏi của bot trong flow.

KHÔNG thuộc check-in (belongs_to_checkin=false) khi câu là MỆNH LỆNH rõ ràng muốn
làm việc khác:
- Tạo task mới: "tạo task ...", "thêm task ...", "tôi muốn tạo task mới" -> intent=create_task
- Xem báo cáo: "báo cáo tuần", "report dự án X" -> intent=report
- Tra cứu dữ liệu/thống kê: "có bao nhiêu task quá hạn" -> intent=text2sql
- Lập kế hoạch dự án mới -> intent=planning
- Thêm thành viên -> intent=add_member

Khi phân vân giữa "mô tả việc đã làm" và "mệnh lệnh tạo task": nếu có số giờ hoặc
mô tả ở thì quá khứ -> THUỘC check-in. Chỉ chọn create_task khi rõ ràng là yêu
cầu tạo việc MỚI."""


class _Verdict(BaseModel):
    belongs_to_checkin: bool = Field(
        description="True nếu câu thuộc luồng check-in; False nếu là intent khác."
    )
    intent: str | None = Field(
        default=None,
        description="Nếu belongs_to_checkin=False: tên intent (create_task, report, "
                    "text2sql, planning, task_update, add_member). Ngược lại để null.",
    )


class CheckinIntentGuard:
    def __init__(self, llm: ChatOpenAI | None = None):
        base_llm = make_llm(
            purpose="intent_guard", timeout=10, max_retries=1, router=True,
            reasoning_effort="none",
        ) if llm is None else llm
        # function_calling: proxy đã xác nhận hỗ trợ (json_mode fail qua proxy).
        self.llm = base_llm.with_structured_output(_Verdict, method="function_calling")

    async def classify(self, message_text: str, *, state: str) -> dict:
        """Trả {'belongs_to_checkin': bool, 'intent': str|None}.

        Fail-safe: lỗi/None -> {'belongs_to_checkin': True} để không tự ý thoát.
        """
        try:
            verdict = await self.llm.ainvoke([
                SystemMessage(content=_SYSTEM_PROMPT),
                HumanMessage(content=f"Trạng thái flow: {state}\nCâu người dùng: {message_text}"),
            ])
            if verdict is None:
                return {"belongs_to_checkin": True, "intent": None}
            intent = verdict.intent if verdict.intent in _KNOWN_INTENTS else None
            return {"belongs_to_checkin": verdict.belongs_to_checkin, "intent": intent}
        except Exception as exc:  # noqa: BLE001 — fail-safe, không để vỡ check-in
            logger.warning("CheckinIntentGuard.classify failed, defaulting to checkin: %s", exc)
            return {"belongs_to_checkin": True, "intent": None}
