"""Thư viện SQL template báo cáo viết sẵn ("mask thông số").

Thay vì để LLM tự viết SQL từ đầu, LLM chỉ chọn `template_id` + điền các tham
số bị mask (tên dự án, kỳ thời gian, tên người). Code map template_id -> SQL
thật đã được test sẵn, rồi bind tham số an toàn qua positional placeholder `$1`.

Mỗi template `build()` trả về list các query dạng:
    {"name": str, "sql": "... ;", "args": [..]}
- SQL chỉ SELECT, một statement, kết thúc bằng ';', dùng `$1..$n`.
- Tham số chuỗi (tên dự án/người) truyền qua `args` -> chống SQL injection.
- Tham số enum (period, scope) KHÔNG nội suy giá trị người dùng mà map qua
  whitelist trong code; chỉ dùng để chọn nhánh SQL / đơn vị date_trunc.

Giữ đồng bộ với is_safe_sql() trong text_to_sql/text2sql.py:
- không có `:named` placeholder (chỉ `$n` positional),
- so sánh enum bằng `::text` để không lệ thuộc tên type "TaskStatus".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ParamSpec:
    name: str
    kind: str  # "str" | "enum"
    required: bool
    description: str
    choices: tuple[str, ...] = ()
    default: str | None = None


@dataclass(frozen=True)
class ReportTemplate:
    id: str
    description: str
    params: tuple[ParamSpec, ...]
    build: Callable[[dict[str, Any]], list[dict[str, Any]]]


# --- Whitelist cho tham số enum (KHÔNG nội suy text người dùng) ---------------
# period -> (đơn vị date_trunc, chuỗi interval của 1 kỳ)
_PERIOD_UNITS: dict[str, tuple[str, str]] = {
    "week": ("week", "1 week"),
    "month": ("month", "1 month"),
}


def _clean_kw(value: Any) -> str:
    """Chuẩn hoá tham số chuỗi (dùng làm giá trị bound param ILIKE)."""
    text = str(value or "").strip()
    return text[:120]


def _resolve_period(params: dict[str, Any]) -> tuple[str, str]:
    period = str(params.get("period") or "week").lower().strip()
    return _PERIOD_UNITS.get(period, _PERIOD_UNITS["week"])


# --- Template builders --------------------------------------------------------

def _build_project_progress(params: dict[str, Any]) -> list[dict[str, Any]]:
    kw = _clean_kw(params.get("project_kw"))
    if not kw:
        raise ValueError("project_progress yêu cầu tham số 'project_kw'")

    tasks_sql = (
        "SELECT p.name AS project_name, p.status::text AS project_status, "
        "p.total_hours AS logged_hours, "
        "COUNT(t.id) AS task_count, "
        "COUNT(t.id) FILTER (WHERE t.status::text='DONE') AS done_count, "
        "COUNT(t.id) FILTER (WHERE t.status::text<>'DONE') AS remaining_count, "
        "COUNT(t.id) FILTER (WHERE t.status::text<>'DONE' AND t.deadline < CURRENT_DATE) AS overdue_count "
        "FROM projects p "
        "LEFT JOIN tasks t ON t.project_id = p.id "
        "WHERE p.name ILIKE '%'||$1||'%' "
        "GROUP BY p.id "
        "ORDER BY p.updated_at DESC "
        "LIMIT 10;"
    )
    milestone_sql = (
        "SELECT p.name AS project_name, m.name AS milestone_name, "
        "m.status AS milestone_status, m.completion_pct, m.due_date, "
        "m.task_count, m.done_count "
        "FROM milestones m "
        "JOIN projects p ON p.id = m.project_id "
        "WHERE p.name ILIKE '%'||$1||'%' "
        "ORDER BY m.due_date NULLS LAST "
        "LIMIT 20;"
    )
    return [
        {"name": "tien_do_task_du_an", "sql": tasks_sql, "args": [kw]},
        {"name": "milestone_du_an", "sql": milestone_sql, "args": [kw]},
    ]


def _build_period_progress(params: dict[str, Any]) -> list[dict[str, Any]]:
    unit, interval = _resolve_period(params)

    progress_sql = (
        "SELECT p.name AS project_name, p.status::text AS project_status, "
        "COUNT(t.id) AS task_count, "
        "COUNT(t.id) FILTER (WHERE t.status::text='DONE') AS done_count, "
        "COALESCE(( "
        "  SELECT SUM(w.hours) FROM worklogs w "
        f"  WHERE w.project_id = p.id AND w.work_date >= date_trunc('{unit}', CURRENT_DATE) "
        "), 0) AS hours_in_period "
        "FROM projects p "
        "LEFT JOIN tasks t ON t.project_id = p.id "
        "WHERE p.status::text NOT IN ('DONE','CANCELLED') "
        "GROUP BY p.id "
        "ORDER BY hours_in_period DESC, p.updated_at DESC "
        "LIMIT 20;"
    )
    due_sql = (
        "SELECT p.name AS project_name, t.name AS task_name, t.status::text AS task_status, "
        "t.deadline, u.full_name AS assignee "
        "FROM tasks t "
        "JOIN projects p ON p.id = t.project_id "
        "LEFT JOIN users u ON u.id = t.assignee_id "
        "WHERE t.status::text <> 'DONE' AND t.deadline IS NOT NULL "
        f"  AND t.deadline >= date_trunc('{unit}', CURRENT_DATE) "
        f"  AND t.deadline < date_trunc('{unit}', CURRENT_DATE) + INTERVAL '{interval}' "
        "ORDER BY t.deadline "
        "LIMIT 30;"
    )
    return [
        {"name": "tien_do_theo_ky", "sql": progress_sql, "args": []},
        {"name": "task_den_han_trong_ky", "sql": due_sql, "args": []},
    ]


def _build_overdue_upcoming(params: dict[str, Any]) -> list[dict[str, Any]]:
    scope = str(params.get("scope") or "all").lower().strip()
    kw = _clean_kw(params.get("project_kw"))
    use_project = scope == "project" and bool(kw)

    project_filter = "AND p.name ILIKE '%'||$1||'%' " if use_project else ""
    args: list[Any] = [kw] if use_project else []

    overdue_sql = (
        "SELECT p.name AS project_name, t.name AS task_name, t.deadline, "
        "t.priority::text AS priority, u.full_name AS assignee "
        "FROM tasks t "
        "JOIN projects p ON p.id = t.project_id "
        "LEFT JOIN users u ON u.id = t.assignee_id "
        "WHERE t.status::text <> 'DONE' AND t.deadline < CURRENT_DATE "
        f"{project_filter}"
        "ORDER BY t.deadline "
        "LIMIT 50;"
    )
    upcoming_sql = (
        "SELECT p.name AS project_name, t.name AS task_name, t.deadline AS due_date, "
        "u.full_name AS assignee "
        "FROM tasks t "
        "JOIN projects p ON p.id = t.project_id "
        "LEFT JOIN users u ON u.id = t.assignee_id "
        "WHERE t.status::text <> 'DONE' AND t.deadline >= CURRENT_DATE "
        "  AND t.deadline < CURRENT_DATE + INTERVAL '14 day' "
        f"{project_filter}"
        "ORDER BY t.deadline "
        "LIMIT 50;"
    )
    return [
        {"name": "task_qua_han", "sql": overdue_sql, "args": list(args)},
        {"name": "task_sap_den_han", "sql": upcoming_sql, "args": list(args)},
    ]


def _build_workload_by_person(params: dict[str, Any]) -> list[dict[str, Any]]:
    kw = _clean_kw(params.get("person_kw"))
    if not kw:
        raise ValueError("workload_by_person yêu cầu tham số 'person_kw'")

    tasks_sql = (
        "SELECT u.full_name, u.role::text AS role, "
        "COUNT(t.id) FILTER (WHERE t.status::text<>'DONE') AS open_tasks, "
        "COUNT(t.id) FILTER (WHERE t.status::text='DONE') AS done_tasks, "
        "COUNT(t.id) FILTER (WHERE t.status::text<>'DONE' AND t.deadline < CURRENT_DATE) AS overdue_tasks "
        "FROM users u "
        "LEFT JOIN tasks t ON t.assignee_id = u.id "
        "WHERE u.full_name ILIKE '%'||$1||'%' "
        "GROUP BY u.id "
        "ORDER BY open_tasks DESC "
        "LIMIT 20;"
    )
    hours_sql = (
        "SELECT u.full_name, COALESCE(SUM(w.hours), 0) AS hours_this_month "
        "FROM users u "
        "LEFT JOIN worklogs w ON w.user_id = u.id "
        "  AND w.work_date >= date_trunc('month', CURRENT_DATE) "
        "WHERE u.full_name ILIKE '%'||$1||'%' "
        "GROUP BY u.id "
        "ORDER BY hours_this_month DESC "
        "LIMIT 20;"
    )
    return [
        {"name": "workload_task", "sql": tasks_sql, "args": [kw]},
        {"name": "workload_gio_thang", "sql": hours_sql, "args": [kw]},
    ]


REGISTRY: dict[str, ReportTemplate] = {
    "project_progress": ReportTemplate(
        id="project_progress",
        description=(
            "Tiến độ MỘT dự án cụ thể: số task done/còn lại/quá hạn, % milestone, "
            "giờ đã log, deadline milestone sắp tới. Dùng khi hỏi về tiến độ/tình "
            "hình một dự án theo tên."
        ),
        params=(
            ParamSpec("project_kw", "str", True, "Từ khoá tên dự án, ví dụ 'CRM', 'MTL'."),
        ),
        build=_build_project_progress,
    ),
    "period_progress": ReportTemplate(
        id="period_progress",
        description=(
            "Tổng quan tiến độ TẤT CẢ dự án đang chạy trong TUẦN hoặc THÁNG này: "
            "task done/tổng, giờ worklog trong kỳ, task đến hạn trong kỳ. Dùng khi "
            "hỏi 'tiến độ tuần này', 'tiến độ tháng này'."
        ),
        params=(
            ParamSpec(
                "period", "enum", False,
                "Kỳ thời gian: 'week' (tuần này) hoặc 'month' (tháng này).",
                choices=("week", "month"), default="week",
            ),
        ),
        build=_build_period_progress,
    ),
    "overdue_upcoming": ReportTemplate(
        id="overdue_upcoming",
        description=(
            "Danh sách task QUÁ HẠN và task SẮP ĐẾN HẠN (14 ngày tới). Dùng khi hỏi "
            "về việc trễ hạn, deadline sắp tới. Có thể giới hạn theo một dự án."
        ),
        params=(
            ParamSpec(
                "scope", "enum", False,
                "'all' = toàn hệ thống; 'project' = chỉ một dự án (kèm project_kw).",
                choices=("all", "project"), default="all",
            ),
            ParamSpec("project_kw", "str", False, "Từ khoá tên dự án (chỉ khi scope='project')."),
        ),
        build=_build_overdue_upcoming,
    ),
    "workload_by_person": ReportTemplate(
        id="workload_by_person",
        description=(
            "Khối lượng công việc của MỘT người: số task đang làm/đã xong/quá hạn và "
            "giờ worklog trong tháng. Dùng khi hỏi workload/khối lượng của một người theo tên."
        ),
        params=(
            ParamSpec("person_kw", "str", True, "Từ khoá tên người, ví dụ 'Lan', 'Phương Thảo'."),
        ),
        build=_build_workload_by_person,
    ),
}


def build_queries(template_id: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Trả về list query {name, sql, args} cho template_id + params đã chọn.

    Raises:
        KeyError: template_id không tồn tại.
        ValueError: thiếu tham số bắt buộc.
    """
    template = REGISTRY[template_id]
    return template.build(params or {})


def render_catalog() -> str:
    """Sinh mô tả template + param cho selector prompt (luôn đồng bộ REGISTRY)."""
    lines: list[str] = []
    for tpl in REGISTRY.values():
        lines.append(f"- {tpl.id}: {tpl.description}")
        for p in tpl.params:
            req = "bắt buộc" if p.required else "tùy chọn"
            extra = f" [{'|'.join(p.choices)}]" if p.choices else ""
            lines.append(f"    · {p.name} ({req}){extra}: {p.description}")
    return "\n".join(lines)
