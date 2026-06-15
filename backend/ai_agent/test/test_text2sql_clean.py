"""Test _clean_sql: bóc câu SQL thuần từ output LLM kèm văn xuôi/markdown.

Bug thật (log 2026-06-15): hỏi "task trễ deadline" -> LLM trả "Để trả lời ...
đây là SQL: ```sql SELECT ...```" -> _clean_sql cũ chỉ bóc fence ở ĐẦU chuỗi
nên trả nguyên văn xuôi -> is_safe_sql từ chối ("Unsafe SQL generated").
"""
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ai_agent.text_to_sql.text2sql import Text2SQLAgent


class _FakeLLM:
    def __init__(self, content):
        self.content = content

    async def ainvoke(self, messages):
        return SimpleNamespace(content=self.content)


def _agent():
    return Text2SQLAgent(db=None, llm=_FakeLLM(""))


def test_clean_plain_sql_unchanged():
    a = _agent()
    assert a._clean_sql("SELECT 1;") == "SELECT 1;"


def test_clean_fence_at_start():
    a = _agent()
    out = a._clean_sql("```sql\nSELECT * FROM tasks;\n```")
    assert out == "SELECT * FROM tasks;"


def test_clean_prose_before_fence():
    # Đây là CHÍNH ca trong log đã gây Unsafe SQL.
    raw = (
        'Để trả lời câu hỏi "dự án đó (MTL) có bao nhiêu task trễ deadline", '
        "chúng ta sẽ đếm...\n\nDưới đây là câu truy vấn SQL chính xác:\n\n"
        "```sql\n"
        "SELECT COUNT(t.id) AS total_overdue_tasks\n"
        "FROM tasks t JOIN projects p ON t.project_id = p.id\n"
        "WHERE p.code = 'MTL' AND t.deadline < CURRENT_DATE AND t.status <> 'DONE';\n"
        "```"
    )
    out = _agent()._clean_sql(raw)
    assert out.lower().startswith("select")
    assert out.endswith(";")
    assert "Để trả lời" not in out
    assert _agent().is_safe_sql(out) is True


def test_clean_prose_without_fence_kept_raw_for_safety():
    # AN TOÀN: văn xuôi KHÔNG fence -> KHÔNG trích SELECT ra (tránh che mutation
    # ẩn / lệnh lạ). Trả nguyên để is_safe_sql tự từ chối. Đổi lại prompt đã siết
    # buộc LLM trả SQL thuần / có fence, nên ca này hiếm.
    raw = "Câu trả lời: SELECT count(*) FROM tasks;"
    out = _agent()._clean_sql(raw)
    assert out == raw  # giữ nguyên, không bóc
    assert _agent().is_safe_sql(out) is False  # không bắt đầu bằng SELECT -> bị chặn


def test_clean_does_not_extract_from_multistatement():
    # CHỐNG REGRESSION BẢO MẬT: không được trích "SELECT 1;" khỏi chuỗi có DROP.
    raw = "SELECT 1; DROP TABLE users;"
    out = _agent()._clean_sql(raw)
    assert "DROP" in out  # mutation vẫn còn -> is_safe_sql sẽ chặn
    assert _agent().is_safe_sql(out) is False


def test_clean_with_cte_in_fence():
    raw = "Đây là truy vấn:\n```\nWITH x AS (SELECT 1) SELECT * FROM x;\n```"
    out = _agent()._clean_sql(raw)
    assert out.lower().startswith("with")
    assert out.endswith(";")
