"""Khung chung cho các "write action qua chat".

Gom boilerplate LẶP giữa các luồng ghi (giao việc, thêm/gỡ thành viên, đổi người,
xoá task...): khởi tạo LLM + structured output, bóc tách (extract), và gate phân
quyền. Service con chỉ còn khai báo (schema + prompt + intent_desc) và viết
``_handle`` — phần nghiệp vụ RIÊNG.

Thiết kế (xem docs/action-agent-refactor.md):
  - ``run(ctx)`` chạy khung chung -> gọi ``_handle`` của con -> trả ``ActionResult``.
  - ``ActionResult.menu`` mang nút bấm khi cần XÁC NHẬN (vd xoá) — message_router
    đính vào metadata để render nút, KHÔNG đi qua đường gộp nhiều-agent (vì đường
    đó ép kết quả về str, nuốt mất nút bấm).
  - ``intent_desc`` là CLASS ATTRIBUTE (đọc không cần khởi tạo) để router import
    mô tả intent mà không kéo theo make_llm.
"""
import logging
import os
from dataclasses import dataclass

from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel

from ai_agent.shared.entity_resolver import is_privileged

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    """Kết quả một write-action. status gom các nhánh mọi luồng ghi đều dùng."""
    status: str  # done|forbidden|need_info|not_found|ambiguous|exists|error|need_confirm
    message: str
    entity_id: int | None = None
    # Nút bấm khi need_confirm (shape giống task menu: [{label, payload}, ...]).
    menu: list | None = None


@dataclass
class ActionContext:
    """Gói tham số lặp truyền vào mọi write-action (thay vì truyền rời từng cái)."""
    message: str
    sender_user_id: str | int
    user_profile: dict
    memory_context: str = ""
    timezone_name: str = "Asia/Ho_Chi_Minh"
    thread_id: str | None = None
    channel: str = "gapo"

    @property
    def sender_id_int(self) -> int | None:
        try:
            return int(self.sender_user_id)
        except (TypeError, ValueError):
            return None


class ActionAgentBase:
    """Lớp nền cho write-action. Con PHẢI khai: name, intent_desc, extraction_model,
    system_prompt, purpose. Tuỳ chọn override: forbidden_msg, llm_unavailable_msg,
    needs_confirm, _extra_prompt. BẮT BUỘC viết: _handle."""

    # ── Con khai (class attribute) ──────────────────────────────────────────
    name: str = ""
    intent_desc: str = ""          # 1 dòng cho prompt router
    extraction_model: type[BaseModel] | None = None
    system_prompt: str = ""
    purpose: str = "action"        # cho make_llm
    forbidden_msg: str = ("Chỉ quản lý (MANAGER/ADMIN) mới thao tác được. "
                          "Bạn nhờ quản lý dự án giúp nhé.")
    llm_unavailable_msg: str = ("Mình chưa xử lý được qua chat lúc này, "
                                "bạn thao tác trên web giúp nhé.")
    needs_confirm: bool = False

    def __init__(self, llm=None):
        self._llm = None
        model, api_key, base_url = (
            os.getenv("MODEL_NAME"), os.getenv("API_KEY"), os.getenv("BASE_URL"),
        )
        if llm is not None:
            self._llm = llm.with_structured_output(self.extraction_model, method="function_calling")
        elif model and api_key and base_url:
            # timeout ngắn + 1 retry: LLM chậm KHÔNG được treo cả luồng reply.
            from ai_agent.shared.llm_factory import make_llm
            base = make_llm(purpose=self.purpose, timeout=15, max_retries=1,
                            temperature=0.1, reasoning_effort="none",
                            model=model, api_key=api_key, base_url=base_url)
            self._llm = base.with_structured_output(self.extraction_model, method="function_calling")
        else:
            logger.warning("%s LLM chưa cấu hình; không xử lý qua chat được.", type(self).__name__)

    def _extra_prompt(self, ctx: ActionContext) -> str:
        """Phần phụ chèn vào system_prompt theo ngữ cảnh (vd create_task chèn 'hôm nay')."""
        return ""

    async def _extract(self, ctx: ActionContext):
        """Bóc tách câu người dùng -> extraction_model. None nếu lỗi."""
        memory_block = f"Ngữ cảnh trước:\n{ctx.memory_context}\n\n" if ctx.memory_context else ""
        try:
            return await self._llm.ainvoke([
                SystemMessage(content=self.system_prompt + self._extra_prompt(ctx)),
                HumanMessage(content=f"{memory_block}Câu của người dùng:\n{ctx.message}"),
            ])
        except Exception:
            logger.exception("%s bóc tách lỗi", type(self).__name__)
            return None

    async def run(self, ctx: ActionContext) -> ActionResult:
        """Khung chung: gate quyền -> gate LLM -> extract -> uỷ _handle của con."""
        if not is_privileged(ctx.user_profile.get("role")):
            return ActionResult("forbidden", self.forbidden_msg)
        if self._llm is None:
            return ActionResult("error", self.llm_unavailable_msg)
        extraction = await self._extract(ctx)
        if extraction is None:
            return ActionResult("error", self.llm_unavailable_msg)
        return await self._handle(extraction, ctx)

    async def _handle(self, extraction, ctx: ActionContext) -> ActionResult:
        raise NotImplementedError
