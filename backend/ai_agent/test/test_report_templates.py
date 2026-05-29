"""Unit test cho thư viện report_templates.

Thuần logic — không cần DB hay LLM. Kiểm tra:
- mọi template build ra SQL pass is_safe_sql,
- số placeholder $n khớp đúng số phần tử args,
- tham số bắt buộc thiếu -> ValueError,
- enum period/scope map qua whitelist đúng,
- render_catalog liệt kê đủ template.
"""

import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ai_agent.report_generator import report_templates
from ai_agent.text_to_sql.text2sql import Text2SQLAgent

# Tránh khởi tạo ChatOpenAI (cần env) — chỉ cần is_safe_sql, không dùng llm.
_SQL = Text2SQLAgent(llm=object())

_PLACEHOLDER = re.compile(r"\$(\d+)")

# Bộ tham số hợp lệ cho từng template.
_VALID_PARAMS = {
    "project_progress": {"project_kw": "CRM"},
    "period_progress": {"period": "week"},
    "overdue_upcoming": {"scope": "all"},
    "workload_by_person": {"person_kw": "Lan"},
}


def _assert_query_ok(q):
    sql = q["sql"]
    args = q.get("args") or []
    assert _SQL.is_safe_sql(sql), f"is_safe_sql failed: {sql}"
    nums = {int(n) for n in _PLACEHOLDER.findall(sql)}
    if args:
        assert nums == set(range(1, len(args) + 1)), (
            f"placeholders {nums} != 1..{len(args)} for {q['name']}"
        )
    else:
        assert not nums, f"query {q['name']} has placeholders but empty args"


def test_all_templates_build_safe_sql():
    for tid, params in _VALID_PARAMS.items():
        queries = report_templates.build_queries(tid, params)
        assert queries, f"{tid} trả về 0 query"
        for q in queries:
            _assert_query_ok(q)


def test_required_param_missing_raises():
    for tid in ("project_progress", "workload_by_person"):
        try:
            report_templates.build_queries(tid, {})
        except ValueError:
            pass
        else:
            raise AssertionError(f"{tid} thiếu tham số bắt buộc nhưng không raise")


def test_period_whitelist():
    # week vs month dùng đơn vị date_trunc khác nhau
    week_sql = report_templates.build_queries("period_progress", {"period": "week"})[0]["sql"]
    month_sql = report_templates.build_queries("period_progress", {"period": "month"})[0]["sql"]
    assert "date_trunc('week'" in week_sql
    assert "date_trunc('month'" in month_sql
    # giá trị lạ -> fallback về 'week', không nội suy text người dùng
    bad_sql = report_templates.build_queries("period_progress", {"period": "DROP"})[0]["sql"]
    assert "date_trunc('week'" in bad_sql
    assert "DROP" not in bad_sql


def test_overdue_scope_param_binding():
    all_q = report_templates.build_queries("overdue_upcoming", {"scope": "all"})
    for q in all_q:
        assert q["args"] == []
        assert "$1" not in q["sql"]
        _assert_query_ok(q)

    proj_q = report_templates.build_queries(
        "overdue_upcoming", {"scope": "project", "project_kw": "CRM"}
    )
    for q in proj_q:
        assert q["args"] == ["CRM"]
        assert "$1" in q["sql"]
        _assert_query_ok(q)


def test_string_param_with_quote_is_bound_not_interpolated():
    # tên có dấu ' không được nội suy vào SQL (đi qua args -> bound param)
    queries = report_templates.build_queries("workload_by_person", {"person_kw": "O'Brien"})
    for q in queries:
        assert "O'Brien" not in q["sql"]
        assert q["args"] == ["O'Brien"]
        _assert_query_ok(q)


def test_render_catalog_lists_all_templates():
    catalog = report_templates.render_catalog()
    for tid in report_templates.REGISTRY:
        assert tid in catalog


if __name__ == "__main__":
    test_all_templates_build_safe_sql()
    test_required_param_missing_raises()
    test_period_whitelist()
    test_overdue_scope_param_binding()
    test_string_param_with_quote_is_bound_not_interpolated()
    test_render_catalog_lists_all_templates()
    print("OK: all report_templates tests passed")
