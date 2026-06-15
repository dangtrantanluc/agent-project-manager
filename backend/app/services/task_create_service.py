"""Giao việc trực tiếp trên Gapo: tạo task MỚI cho người khác qua chat.

Vd (PM/quản lý nhắn): "giao task '[8.6] Viết tài liệu API' cho Thảo, dự án
Logistics, deadline 20/06, ưu tiên cao" -> tạo task thật + DM cho người được
giao + đăng group dự án (sơ đồ Luồng 1 ①②③④ qua kênh chat).

Quy tắc an toàn:
  - CHỈ MANAGER/ADMIN/SUPER_ADMIN được giao việc (giống POST /tasks).
  - Không đủ thông tin (thiếu tên task / người nhận / dự án) hoặc mơ hồ -> HỎI LẠI,
    KHÔNG tạo bừa.
  - Resolve người & dự án trong CÙNG company của người giao.
"""
import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime

import pytz
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import AsyncSessionLocal
from app.services.task_assignment_notifier import notify_task_assigned, notify_group_new_task
from ai_agent.shared.entity_resolver import (
    is_privileged,
    resolve_users,
    resolve_projects,
)

logger = logging.getLogger(__name__)
_VALID_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "URGENT"}

_EXTRACT_SYSTEM_PROMPT = """\
Bạn bóc tách yêu cầu GIAO VIỆC (tạo task mới) trong hệ thống quản lý dự án.
Từ câu của người dùng, trích:
- task_name: tên/nội dung công việc cần giao (bắt buộc).
- assignee: TÊN người được giao (bỏ kính ngữ anh/chị/em, chỉ giữ tên). Bắt buộc.
- project: tên dự án nếu có nhắc tới, rỗng nếu không.
- deadline: hạn chót dạng YYYY-MM-DD nếu suy ra được (dựa trên ngày hôm nay được
  cung cấp); rỗng nếu không nhắc.
- priority: một trong LOW/MEDIUM/HIGH/URGENT nếu có nhắc (vd "ưu tiên cao"=HIGH,
  "gấp/khẩn"=URGENT); rỗng nếu không.
Nếu câu KHÔNG phải giao việc, để task_name và assignee rỗng.
"""


class TaskCreateExtraction(BaseModel):
    task_name: str = Field(default="")
    assignee: str = Field(default="")
    project: str = Field(default="")
    deadline: str = Field(default="")
    priority: str = Field(default="")


@dataclass
class TaskCreateResult:
    status: str  # created | forbidden | need_info | not_found | ambiguous | error
    message: str
    task_id: int | None = None


def _parse_deadline(s: str) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s.strip()[:10])
    except ValueError:
        return None


class TaskCreateService:
    def __init__(self, llm: ChatOpenAI | None = None):
        self._llm = None
        model, api_key, base_url = (
            os.getenv("MODEL_NAME"), os.getenv("API_KEY"), os.getenv("BASE_URL"),
        )
        if llm is not None:
            self._llm = llm.with_structured_output(TaskCreateExtraction, method="function_calling")
        elif model and api_key and base_url:
            # timeout ngắn + 1 retry: LLM chậm KHÔNG được treo cả luồng reply
            # (trước đây 60s×retry -> ~180s như log đã thấy).
            base = ChatOpenAI(model=model, timeout=15, max_retries=1, temperature=0.1,
                              api_key=api_key, base_url=base_url, reasoning_effort="none")
            self._llm = base.with_structured_output(TaskCreateExtraction, method="function_calling")
        else:
            logger.warning("TaskCreateService LLM chưa cấu hình; không giao việc qua chat được.")

    async def create_from_chat(
        self,
        *,
        message: str,
        sender_user_id: str | int,
        user_profile: dict | None = None,
        memory_context: str = "",
        timezone_name: str = "Asia/Ho_Chi_Minh",
    ) -> TaskCreateResult:
        profile = user_profile or {}
        # 1. Phân quyền: chỉ quản lý được giao việc.
        if not is_privileged(profile.get("role")):
            return TaskCreateResult(
                status="forbidden",
                message="Chỉ quản lý (MANAGER/ADMIN) mới giao việc được. Bạn nhờ quản lý dự án giúp nhé.",
            )

        if self._llm is None:
            return TaskCreateResult(
                status="error",
                message="Mình chưa giao việc qua chat được lúc này, bạn tạo task trên web giúp nhé.",
            )

        # 2. Bóc tách thông tin.
        extraction = await self._extract(message, memory_context)
        if extraction is None or not extraction.task_name.strip() or not extraction.assignee.strip():
            return TaskCreateResult(
                status="need_info",
                message=("Bạn cho mình rõ hơn: **giao task gì**, **cho ai**, thuộc **dự án nào** "
                         "và **deadline** khi nào nhé. Vd: \"giao task Viết tài liệu API cho Thảo, "
                         "dự án Logistics, deadline 20/06\"."),
            )

        try:
            sender_id = int(sender_user_id)
        except (TypeError, ValueError):
            return TaskCreateResult(status="error", message="Không xác định được người giao việc.")

        async with AsyncSessionLocal() as db:
            # 3. Resolve người được giao (cùng company).
            assignees = await self._resolve_users(db, extraction.assignee.strip(), sender_id)
            if not assignees:
                return TaskCreateResult(
                    status="not_found",
                    message=f"Mình chưa tìm thấy ai tên \"{extraction.assignee}\" trong hệ thống. "
                            "Bạn cho mình tên đầy đủ giúp nhé.")
            if len(assignees) > 1:
                names = ", ".join(a["full_name"] for a in assignees)
                return TaskCreateResult(
                    status="ambiguous",
                    message=f"Có nhiều người tên \"{extraction.assignee}\": {names}. "
                            "Bạn nói rõ giúp mình là ai nhé.")
            assignee = assignees[0]

            # 4. Resolve dự án (cùng company).
            if not extraction.project.strip():
                return TaskCreateResult(
                    status="need_info",
                    message=self._ask_project_message(profile))
            projects = await self._resolve_projects(db, extraction.project.strip(), sender_id)
            if not projects:
                return TaskCreateResult(
                    status="not_found",
                    message=f"Mình chưa tìm thấy dự án \"{extraction.project}\". "
                            "Bạn kiểm tra lại tên dự án giúp nhé.")
            if len(projects) > 1:
                names = ", ".join(p["name"] for p in projects)
                return TaskCreateResult(
                    status="ambiguous",
                    message=f"Có nhiều dự án khớp \"{extraction.project}\": {names}. "
                            "Bạn nói rõ dự án nào nhé.")
            project = projects[0]

            # 5. Tạo task.
            priority = extraction.priority.strip().upper()
            priority = priority if priority in _VALID_PRIORITIES else "MEDIUM"
            deadline = _parse_deadline(extraction.deadline)
            row = (await db.execute(text("""
                INSERT INTO tasks (name, status, priority, deadline, project_id,
                                   assignee_id, company_id, updated_at)
                VALUES (:name, 'TODO'::"TaskStatus", CAST(:priority AS "Priority"),
                        :deadline, :project_id, :assignee_id, :company_id, NOW())
                RETURNING id
            """), {
                "name": extraction.task_name.strip(),
                "priority": priority,
                "deadline": deadline,
                "project_id": project["id"],
                "assignee_id": assignee["user_id"],
                "company_id": project["company_id"],
            })).fetchone()
            task_id = row[0]
            await db.execute(text("""
                INSERT INTO agent_audit_log (tool, args_json, source, created_at)
                VALUES ('create_task_from_chat', CAST(:args AS jsonb),
                        CAST('chat' AS "AgentAuditSource"), NOW())
            """), {"args": _json({"task_id": task_id, "assignee_id": assignee["user_id"],
                                  "project_id": project["id"], "by": sender_id})})
            await db.commit()

        # 6. Thông báo chạy NỀN (fire-and-forget): hai notify tự mở session riêng và
        # tự nuốt lỗi; await trực tiếp sẽ cộng latency Gapo/DB vào reply chat.
        asyncio.create_task(
            notify_task_assigned(task_id=task_id, assignee_id=assignee["user_id"], actor_id=sender_id))
        asyncio.create_task(notify_group_new_task(task_id=task_id, actor_id=sender_id))

        deadline_str = f" (deadline {deadline.isoformat()})" if deadline else ""
        return TaskCreateResult(
            status="created", task_id=task_id,
            message=(f"Đã tạo task **{extraction.task_name.strip()}** giao cho "
                     f"**{assignee['full_name']}**{deadline_str} trong dự án "
                     f"**{project['name']}**, ưu tiên {priority}. Mình đã báo cho bạn ấy rồi nhé!"),
        )

    async def _extract(self, message: str, memory_context: str) -> TaskCreateExtraction | None:
        # Lấy "hôm nay" theo giờ VN, KHÔNG theo TZ container (UTC): 6h sáng VN vẫn
        # là hôm qua theo UTC -> LLM tính "deadline ngày mai" lệch 1 ngày.
        today = datetime.now(pytz.timezone("Asia/Ho_Chi_Minh")).date().isoformat()
        memory_block = f"Ngữ cảnh trước:\n{memory_context}\n\n" if memory_context else ""
        try:
            return await self._llm.ainvoke([
                SystemMessage(content=_EXTRACT_SYSTEM_PROMPT + f"\nNgày hôm nay: {today}"),
                HumanMessage(content=f"{memory_block}Câu của người dùng:\n{message}"),
            ])
        except Exception:
            logger.exception("TaskCreateService bóc tách thất bại")
            return None

    # Resolve người/dự án dùng chung với các luồng ghi khác (entity_resolver).
    async def _resolve_users(self, db, name: str, sender_id: int) -> list[dict]:
        return await resolve_users(db, name, sender_id)

    async def _resolve_projects(self, db, name: str, sender_id: int) -> list[dict]:
        return await resolve_projects(db, name, sender_id)

    def _ask_project_message(self, profile: dict) -> str:
        projects = profile.get("active_projects") or []
        if projects:
            names = ", ".join(p["name"] for p in projects[:6])
            return (f"Bạn muốn tạo task này trong dự án nào? Một số dự án đang chạy: {names}.")
        return "Bạn cho mình biết task này thuộc dự án nào nhé."


def _json(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)
