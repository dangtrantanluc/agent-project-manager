import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ai_agent.report_generator.report_agent import ReportAgent


class _FakeLLM:
    def __init__(self):
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        if len(self.calls) == 1:
            # select_template: không khớp template nào -> fallback freeform
            return SimpleNamespace(content='{"template_id": null, "params": {}}')
        if len(self.calls) == 2:
            # generate_report_plan (freeform fallback)
            return SimpleNamespace(content="""
            {
              "need_clarification": false,
              "queries": [
                {"name": "project_count", "sql": "SELECT COUNT(*) AS total_projects FROM projects;"}
              ]
            }
            """)
        return SimpleNamespace(content="Hiện tại có 7 dự án.")


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
    class UnsafeLLM(_FakeLLM):
        async def ainvoke(self, messages):
            self.calls.append(messages)
            if len(self.calls) == 1:
                return SimpleNamespace(content='{"template_id": null, "params": {}}')
            if len(self.calls) == 2:
                return SimpleNamespace(content='{"need_clarification": false, "queries": [{"name": "bad", "sql": "DROP TABLE projects;"}]}')
            return SimpleNamespace(content="Không thể tạo báo cáo vì query không an toàn.")

    sql_agent = _FakeSQLAgent()
    agent = ReportAgent(llm=UnsafeLLM(), sql_agent=sql_agent)

    answer = asyncio.run(agent.generate_report("Báo cáo dự án"))

    assert answer == "Không thể tạo báo cáo vì query không an toàn."
    assert sql_agent.executed == []
