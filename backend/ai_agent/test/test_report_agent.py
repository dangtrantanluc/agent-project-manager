import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ai_agent.report_generator.report_agent import (
    ReportAgent, ReportPlan, ReportQuery, TemplateSelection,
)


class _StructuredLLM:
    """Bản wrap của with_structured_output: ainvoke trả thẳng object đã validate."""
    def __init__(self, value):
        self._value = value

    async def ainvoke(self, messages):
        return self._value


class _FakeLLM:
    """Mô phỏng ChatOpenAI sau refactor structured-output.

    - with_structured_output(ReportPlan/TemplateSelection) -> _StructuredLLM trả
      object tương ứng (không còn parse JSON từ .content).
    - ainvoke (gốc) chỉ dùng cho generate_report_result -> trả .content tự do.
    """
    def __init__(self, plan: ReportPlan | None = None, final: str = "Hiện tại có 7 dự án."):
        self.calls = []
        self._plan = plan or ReportPlan(queries=[
            ReportQuery(name="project_count",
                        sql="SELECT COUNT(*) AS total_projects FROM projects;")
        ])
        self._final = final

    def with_structured_output(self, schema, method=None):
        if schema is TemplateSelection:
            # Không khớp template nào -> fallback freeform (đi qua plan_llm).
            return _StructuredLLM(TemplateSelection(template_id=None, params={}))
        if schema is ReportPlan:
            return _StructuredLLM(self._plan)
        return _StructuredLLM(None)

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return SimpleNamespace(content=self._final)


class _FakeSQLAgent:
    def __init__(self):
        self.executed = []

    def _clean_sql(self, sql):
        return sql.strip()

    def is_safe_sql(self, sql):
        return sql.lower().startswith("select") and sql.endswith(";")

    async def execute_sql(self, sql, args=None):
        self.executed.append(sql)
        return [{"total_projects": 7}]


def test_report_agent_executes_plan_and_returns_final_answer():
    sql_agent = _FakeSQLAgent()
    agent = ReportAgent(llm=_FakeLLM(), sql_agent=sql_agent)

    answer = asyncio.run(agent.generate_report("Cho tôi báo cáo số lượng dự án"))

    assert answer == "Hiện tại có 7 dự án."
    assert sql_agent.executed == ["SELECT COUNT(*) AS total_projects FROM projects;"]


def test_report_agent_rejects_unsafe_plan_query_but_still_summarizes():
    # Plan trả về SQL nguy hiểm (DROP) -> is_safe_sql chặn -> không execute,
    # nhưng vẫn tóm tắt (báo không an toàn) thay vì crash.
    unsafe_plan = ReportPlan(queries=[ReportQuery(name="bad", sql="DROP TABLE projects;")])
    llm = _FakeLLM(plan=unsafe_plan, final="Không thể tạo báo cáo vì query không an toàn.")
    sql_agent = _FakeSQLAgent()
    agent = ReportAgent(llm=llm, sql_agent=sql_agent)

    answer = asyncio.run(agent.generate_report("Báo cáo dự án"))

    assert answer == "Không thể tạo báo cáo vì query không an toàn."
    assert sql_agent.executed == []
