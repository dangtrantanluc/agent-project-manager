"""Luật định tuyến intent TẤT ĐỊNH (không LLM).

Tách khỏi message_router để: (1) test bộ luật độc lập, (2) message_router mỏng
hơn. Hành vi giữ NGUYÊN so với bản cũ trong message_router.

message_router gọi `resolve_agents(message, selected)` sau khi LLM phân loại;
hàm này chuẩn hoá danh sách + ép một số intent bằng từ khoá tiếng Việt.
"""
import re

from app.services.task_progress_service import has_percent

# Câu tự báo HOÀN THÀNH -> phải vào task_update để verify (LLM hay khen nhầm).
TASK_UPDATE_KEYWORDS = (
    "update rồi", "đã update", "xong rồi", "đã xong",
    "hoàn thành rồi", "done", "làm xong", "cập nhật rồi",
)

# Câu NHỜ BOT nhắn/nhắc/push NGƯỜI KHÁC -> outbound (agent 'notification').
_OUTBOUND_RE = re.compile(r"\b(?:push|nhắn|nhắc|giục|đốc thúc|thúc)\b")

# Câu GIAO VIỆC / tạo task mới -> agent create_task.
CREATE_TASK_KEYWORDS = ("giao task", "giao việc", "tạo task", "tạo việc", "assign task", "thêm task")

# Mã task hiện hữu "[2.4]" -> thao tác trên task ĐÃ CÓ, không phải tạo mới.
_TASK_CODE_RE = re.compile(r"\[\d+(?:\.\d+)*\]")


def keyword_agent(message: str) -> str:
    """Dò từ khoá tiếng Việt để cứu intent khi LLM không chắc."""
    lowered = message.lower()
    task_update_keywords = TASK_UPDATE_KEYWORDS
    planning_keywords = ("lập kế hoạch", "kế hoạch", "phân chia công việc", "milestone")
    report_keywords = ("báo cáo", "thống kê", "report", "tiến độ tổng thể")
    notification_keywords = ("thông báo", "nhắc nhở", "reminder", "notification")
    data_keywords = (
        "dự án", "project", "task", "công việc", "deadline", "worklog",
        "bao nhiêu", "danh sách", "ai là",
    )

    # task_update kiểm tra TRƯỚC data_keywords: "làm xong task X" có cả 'task'
    # (data) lẫn 'làm xong' (task_update) — ưu tiên xác minh hoàn thành.
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


def resolve_agents(message: str, selected: list[str]) -> list[str]:
    """Chuẩn hoá danh sách agent sẽ chạy.

    Chỉ fallback bằng từ khoá khi LLM trả về đúng ``["conversation"]`` (mặc
    định/không chắc). Mọi trường hợp khác giữ nguyên danh sách LLM trả về.
    """
    agents = [a for a in selected if a] or ["conversation"]

    lowered = message.lower()

    # Câu nêu MÃ task "[x.y]" -> thao tác trên task ĐÃ CÓ, ép task_update.
    if _TASK_CODE_RE.search(message):
        return ["task_update"]

    has_create = any(kw in lowered for kw in CREATE_TASK_KEYWORDS)
    has_update = any(kw in lowered for kw in TASK_UPDATE_KEYWORDS)

    # Có CẢ hai loại từ khoá: ưu tiên create khi có " cho " (giao cho ai đó).
    if has_create and (not has_update or " cho " in lowered):
        return ["create_task"]

    if has_update:
        return ["task_update"]

    # Nhờ bot nhắn/nhắc/push NGƯỜI KHÁC -> notification (outbound).
    if _OUTBOUND_RE.search(lowered):
        return ["notification"]

    # Câu THÔNG BÁO tiến độ kèm % -> task_update (loại câu HỎI).
    if has_percent(lowered) and not any(q in lowered for q in ("bao nhiêu", "mấy", "?", "chưa", "là bao")):
        progress_ctx = ("task", "công việc", "tiến độ", "update", "cập nhật",
                        "làm", "xong", "hoàn thành", "tôi", "mình", "em")
        if any(c in lowered for c in progress_ctx):
            return ["task_update"]

    if agents == ["conversation"]:
        # LLM không chắc → cứu intent bằng từ khoá tiếng Việt.
        agent = keyword_agent(message)
        return [agent] if agent else agents

    # >1 agent: loại 'conversation' thừa.
    business = [a for a in agents if a != "conversation"]
    if business:
        return business
    return agents
