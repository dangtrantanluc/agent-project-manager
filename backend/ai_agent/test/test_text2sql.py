import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from cases_text2sql import (
    ROUTER_LEVEL_CASES,
    TEXT2SQL_INVALID_CASES,
    TEXT2SQL_TEST_CASES,
)
from ai_agent.text_to_sql import text2sql
from ai_agent.text_to_sql.text2sql import Text2SQLAgent


class FakeDB:
    dialect = "postgresql"

    def get_table_info(self):
        return """
        companies(id, name, code)
        projects(id, name, status, total_hours, company_id)
        tasks(id, name, status, deadline, total_hours, project_id, company_id)
        users(id, full_name, active, company_id)
        worklogs(id, hours, work_date, project_id, user_id)
        """


class FakeLLM:
    def __init__(self, content):
        self.content = content
        self.messages = None

    async def ainvoke(self, messages):
        self.messages = messages
        return SimpleNamespace(content=self.content)


def normalize_sql(sql: str) -> str:
    return " ".join(sql.lower().strip().split())


def build_agent(llm_sql: str, monkeypatch) -> Text2SQLAgent:
    monkeypatch.setattr(text2sql, "_shared_schema_cache", None)
    return Text2SQLAgent(db=FakeDB(), llm=FakeLLM(llm_sql), top_k=5)


@pytest.mark.parametrize("case", TEXT2SQL_TEST_CASES, ids=lambda case: case["id"])
def test_text2sql_generates_safe_select(case, monkeypatch):
    agent = build_agent(case["llm_sql"], monkeypatch)

    sql = asyncio.run(agent.generate_sql(case["question"]))
    normalized_sql = normalize_sql(sql)

    assert agent.is_safe_sql(sql)
    assert normalized_sql.startswith(("select", "with"))
    assert normalized_sql.endswith(";")
    assert "select *" not in normalized_sql

    for keyword in case["expected_sql_contains"]:
        assert keyword.lower() in normalized_sql, f"SQL thiếu `{keyword}`.\nSQL: {sql}"


@pytest.mark.parametrize("case", TEXT2SQL_TEST_CASES, ids=lambda case: case["id"])
def test_text2sql_keeps_single_company_schema(case, monkeypatch):
    agent = build_agent(case["llm_sql"], monkeypatch)

    sql = asyncio.run(agent.generate_sql(case["question"]))
    normalized_sql = normalize_sql(sql)

    for table in case.get("tenant_tables", []):
        assert table in normalized_sql


@pytest.mark.parametrize("case", TEXT2SQL_INVALID_CASES, ids=lambda case: case["id"])
def test_text2sql_out_of_scope_returns_invalid_question_sql(case, monkeypatch):
    agent = build_agent(case["llm_sql"], monkeypatch)

    sql = asyncio.run(agent.generate_sql(case["question"]))
    normalized_sql = normalize_sql(sql)

    assert agent.is_safe_sql(sql)
    for keyword in case["expected_sql_contains"]:
        assert keyword.lower() in normalized_sql


def test_text2sql_rejects_unsafe_sql(monkeypatch):
    agent = build_agent("DROP TABLE projects;", monkeypatch)

    with pytest.raises(ValueError, match="Unsafe SQL generated"):
        asyncio.run(agent.generate_sql("Xóa toàn bộ dự án"))


def test_text2sql_rejects_named_placeholders(monkeypatch):
    agent = build_agent("""
        SELECT t.id, t.name
        FROM tasks t
        WHERE t.project_id = :project_id
        LIMIT :limit;
    """, monkeypatch)

    with pytest.raises(ValueError, match="Unsafe SQL generated"):
        asyncio.run(agent.generate_sql("Danh sách task của dự án này"))


def test_text2sql_binds_current_user_placeholder(monkeypatch):
    agent = build_agent("""
        SELECT w.id, w.work_date, w.hours
        FROM worklogs w
        WHERE w.user_id = :user_id
        ORDER BY w.work_date DESC
        LIMIT 5;
    """, monkeypatch)

    sql = asyncio.run(agent.generate_sql("Danh sách worklog của tôi", current_user_id=9))
    normalized_sql = normalize_sql(sql)

    assert agent.is_safe_sql(sql)
    assert ":user_id" not in normalized_sql
    assert "w.user_id = 9" in normalized_sql


def test_multi_intent_cases_are_router_level_only():
    assert ROUTER_LEVEL_CASES
    assert ROUTER_LEVEL_CASES[0]["expected_sql_count_min"] == 2
