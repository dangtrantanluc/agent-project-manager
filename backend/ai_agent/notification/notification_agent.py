import os
import logging
import time
import asyncio
from datetime import date
from dataclasses import dataclass
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

SYSTEM_PROMPT = """
Bạn là trợ lý tạo nội dung nhắc nhở quản lý dự án.

Yêu cầu:
- Viết ngắn gọn, rõ ràng, thân thiện.
- Không giải thích dài.
- Có hành động cụ thể cho người nhận.
- Chỉ trả về nội dung tin nhắn, không thêm tiêu đề.
"""

# Số task tối đa liệt kê chi tiết trong 1 tin nhắc deadline; dư ra gộp thành
# dòng "... và N task khác" để tin không quá dài (tối ưu UX).
DEADLINE_MAX_DISPLAY = int(os.getenv("DEADLINE_MAX_DISPLAY", "5"))

# Thứ tự ưu tiên hiển thị: URGENT > HIGH > MEDIUM > LOW (lạ -> cuối).
_PRIORITY_RANK = {"URGENT": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


def _prioritize_tasks(tasks: list[dict], max_display: int) -> tuple[list[dict], int]:
    """Sắp xếp task theo độ quan trọng và cắt còn tối đa max_display.

    Khoá sắp xếp: đến-hạn-hôm-nay trước, rồi priority cao trước, rồi deadline gần.
    Trả về (danh sách hiển thị, số task bị ẩn bớt).
    """
    def sort_key(t: dict):
        due_today = 0 if t.get("reminder_type") == "due_today" else 1
        prank = _PRIORITY_RANK.get(str(t.get("priority") or "").upper(), 4)
        deadline = t.get("deadline")
        return (due_today, prank, str(deadline))

    ordered = sorted(tasks, key=sort_key)
    if len(ordered) <= max_display:
        return ordered, 0
    return ordered[:max_display], len(ordered) - max_display

@dataclass
class NotificationPayload:
    user_id: str
    thread_id: str | None
    message: str

class NotificationAgent:
    def __init__(self, llm: ChatOpenAI | None = None):
        self.llm = llm
        if self.llm is None:
            model = os.getenv("MODEL_NAME")
            api_key = os.getenv("API_KEY")
            base_url = os.getenv("BASE_URL")

            if not model or not api_key or not base_url:
                log.warning(
                    "NotificationAgent LLM is not configured; deadline notifications "
                    "will use deterministic fallback messages."
                )
            else:
                self.llm = ChatOpenAI(
                    model=model,
                    timeout=60,
                    api_key=api_key,
                    base_url=base_url,
                )

    async def generate_notification_message(self, raw_message: str, memory_context: str = "") -> str:
        if self.llm is None:
            raise ValueError("NotificationAgent LLM is not configured")

        memory_block = f"Ngữ cảnh hội thoại trước đó:\n{memory_context}\n\n" if memory_context else ""
        start = time.perf_counter()
        response = await self.llm.ainvoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=f"{memory_block}Tạo nội dung thông báo từ thông tin sau:\n{raw_message}")
        ])
        end = time.perf_counter()
        log.info(f"Notification generation time: {end - start:.2f} seconds")
        return response.content.strip()

    async def prepare_notification(
        self,
        user_id: str,
        thread_id: str | None,
        message: str,
        memory_context: str = "",
    ) -> NotificationPayload:
        content = await self.generate_notification_message(message, memory_context=memory_context)

        return NotificationPayload(
            user_id=user_id,
            thread_id=thread_id,
            message=content,
        )

    async def prepare_deadline_digest(
        self,
        *,
        recipient_name: str | None,
        notify_date: date | str,
        tasks: list[dict[str, Any]],
    ) -> str:
        """Compose one deadline reminder message for a recipient.

        Falls back to a deterministic template whenever the LLM is unavailable
        or returns an empty response so scheduled reminders are not dropped.
        """
        # Ưu tiên + cắt bớt để tin không quá dài khi có nhiều task trễ.
        display_tasks, extra_count = _prioritize_tasks(tasks, DEADLINE_MAX_DISPLAY)
        fallback = self._fallback_deadline_digest(
            recipient_name=recipient_name,
            notify_date=notify_date,
            tasks=display_tasks,
            extra_count=extra_count,
            total=len(tasks),
        )
        if not tasks:
            return fallback
        if self.llm is None:
            return fallback

        try:
            prompt = self._deadline_digest_prompt(
                recipient_name=recipient_name,
                notify_date=notify_date,
                tasks=display_tasks,
                extra_count=extra_count,
                total=len(tasks),
            )
            start = time.perf_counter()
            response = await self.llm.ainvoke([
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            end = time.perf_counter()
            log.info("Deadline notification generation time: %.2f seconds", end - start)
            content = (response.content or "").strip()
            return content or fallback
        except Exception as exc:
            log.warning("Deadline notification LLM failed, using fallback: %s", exc)
            return fallback

    def _deadline_digest_prompt(
        self,
        *,
        recipient_name: str | None,
        notify_date: date | str,
        tasks: list[dict[str, Any]],
        extra_count: int = 0,
        total: int | None = None,
    ) -> str:
        task_lines = []
        for index, task in enumerate(tasks, start=1):
            reminder_note = self._reminder_note(task)
            task_lines.append(
                "\n".join([
                    f"{index}. Task: {task.get('task_name') or task.get('name')}",
                    f"   Project: {task.get('project_name')}",
                    f"   Deadline: {self._format_date(task.get('deadline'))}",
                    f"   Độ ưu tiên: {task.get('priority') or 'N/A'}",
                    f"   Status: {task.get('status') or 'N/A'}",
                    f"   Loại nhắc: {reminder_note}",
                ])
            )

        extra_note = (
            f"\n\nLƯU Ý: còn {extra_count} task khác ưu tiên thấp hơn — KẾT THÚC tin bằng "
            f'một dòng "...và {extra_count} task khác — gõ /update để xem & cập nhật".'
            if extra_count else ""
        )
        return (
            "Tạo một tin nhắn Gapo nhắc deadline bằng tiếng Việt.\n"
            "Chỉ trả về nội dung tin nhắn, không markdown phức tạp, không JSON.\n"
            "Nếu có một task, dùng format ngắn với Project/Task/Deadline.\n"
            "Nếu có nhiều task, gom thành danh sách đánh số, ưu tiên cao liệt kê trước.\n"
            "Giọng văn thân thiện, rõ hành động: cập nhật tiến độ, hoàn thành task hoặc báo blocker.\n"
            "Nếu loại nhắc là đến hạn hôm nay, nhấn mạnh task cần hoàn thành trong hôm nay.\n"
            "Nếu loại nhắc là sắp đến hạn, nhắc còn khoảng 2 ngày.\n\n"
            f"Người nhận: {recipient_name or 'bạn'}\n"
            f"Ngày gửi nhắc: {self._format_date(notify_date)}\n"
            f"Tổng số task đến hạn: {total if total is not None else len(tasks)} "
            f"(hiển thị {len(tasks)} task ưu tiên cao nhất)\n\n"
            "Danh sách task:\n"
            + "\n\n".join(task_lines)
            + extra_note
        )

    def _fallback_deadline_digest(
        self,
        *,
        recipient_name: str | None,
        notify_date: date | str,
        tasks: list[dict[str, Any]],
        extra_count: int = 0,
        total: int | None = None,
    ) -> str:
        if not tasks:
            return (
                "Nhắc deadline\n\n"
                f"Ngày nhắc: {self._format_date(notify_date)}\n"
                "Hiện không có task nào cần nhắc."
            )

        if total is None:
            total = len(tasks)

        if total == 1:
            task = tasks[0]
            reminder_text = self._fallback_reminder_text(task)
            return (
                "Nhắc deadline\n\n"
                f"Project: {task.get('project_name')}\n"
                f"Task: {task.get('task_name') or task.get('name')}\n"
                f"Deadline: {self._format_date(task.get('deadline'))}\n\n"
                f"{reminder_text}"
            )

        due_today_count = sum(1 for task in tasks if task.get("reminder_type") == "due_today")
        upcoming_count = len(tasks) - due_today_count
        lines = [
            "Nhắc deadline",
            "",
            self._fallback_digest_summary(due_today_count, upcoming_count),
            "",
        ]
        for index, task in enumerate(tasks, start=1):
            prio = task.get("priority")
            lines.extend([
                f"{index}. {task.get('task_name') or task.get('name')}"
                + (f" [{prio}]" if prio else ""),
                f"   Project: {task.get('project_name')}",
                f"   Deadline: {self._format_date(task.get('deadline'))}",
                f"   Ghi chú: {self._reminder_note(task)}",
                "",
            ])
        if extra_count:
            lines.append(f"...và {extra_count} task khác — gõ /update để xem & cập nhật.")
            lines.append("")
        lines.append("Bạn cập nhật tiến độ, hoàn thành task hoặc báo blocker nếu cần hỗ trợ nhé.")
        return "\n".join(lines).strip()

    def _format_date(self, value: Any) -> str:
        if isinstance(value, date):
            return value.isoformat()
        return str(value)

    def _reminder_note(self, task: dict[str, Any]) -> str:
        if task.get("reminder_type") == "due_today":
            return "Đến hạn hôm nay"
        return "Còn khoảng 2 ngày đến hạn"

    def _fallback_reminder_text(self, task: dict[str, Any]) -> str:
        if task.get("reminder_type") == "due_today":
            return "Task đến hạn hôm nay. Bạn hoàn thành trong hôm nay hoặc báo blocker nếu cần hỗ trợ nhé."
        return "Task còn khoảng 2 ngày nữa đến hạn. Bạn cập nhật tiến độ giúp mình nhé."

    def _fallback_digest_summary(self, due_today_count: int, upcoming_count: int) -> str:
        parts = []
        if due_today_count:
            parts.append(f"{due_today_count} task đến hạn hôm nay")
        if upcoming_count:
            parts.append(f"{upcoming_count} task còn khoảng 2 ngày đến hạn")
        return "Bạn có " + " và ".join(parts) + ":"

async def main():
    agent = NotificationAgent()

    notification = await agent.prepare_notification(
        user_id="user123",
        thread_id=None,
        message="Deadline của task ABC sắp đến vào ngày mai."
    )

    print(notification)

if __name__ == "__main__":
    asyncio.run(main())
