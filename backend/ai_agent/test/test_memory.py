import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from ai_agent.memory.memory import load_memory, save_memory


class _Result:
    def __init__(self, rows=None, scalar_value=None):
        self.rows = rows or []
        self.scalar_value = scalar_value

    def fetchall(self):
        return self.rows

    def scalar(self):
        return self.scalar_value

    def scalar_one(self):
        return self.scalar_value


class _FakeMemorySession:
    def __init__(self, rows=None, columns=None, user_company_id=1):
        self.rows = rows or []
        self.columns = columns or set()
        self.user_company_id = user_company_id
        self.next_id = max([row["id"] for row in self.rows], default=0) + 1
        self.commits = 0
        self.updates = []
        self.statements = []

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).lower().split())
        params = params or {}
        self.statements.append((sql, params))

        if "information_schema.columns" in sql:
            return _Result(scalar_value=(params["table_name"], params["column_name"]) in self.columns)

        if "select company_id from users" in sql:
            return _Result(scalar_value=self.user_company_id)

        if "select id from companies" in sql:
            return _Result(scalar_value=1)

        if "select summary" in sql:
            rows = [
                row for row in self.rows
                if row["conversation_id"] == params["cid"] and row["summary"].strip()
            ]
            rows.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
            return _Result(scalar_value=rows[0]["summary"] if rows else None)

        if "select user_text, reply_text" in sql:
            rows = [row for row in self.rows if row["conversation_id"] == params["cid"]]
            rows.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
            return _Result(rows=[(row["user_text"], row["reply_text"]) for row in rows[:params["n"]]])

        if "insert into agent_memory" in sql:
            row_id = self.next_id
            self.next_id += 1
            self.rows.append({
                "id": row_id,
                "company_id": params.get("company_id"),
                "conversation_id": params["conv_id"],
                "user_text": params["user_text"],
                "reply_text": params["reply_text"],
                "summary": "",
                "created_at": datetime(2026, 5, 27, 12, 0, 0) + timedelta(seconds=row_id),
            })
            return _Result(scalar_value=row_id)

        if "select count(*)" in sql:
            count = sum(1 for row in self.rows if row["conversation_id"] == params["cid"])
            return _Result(scalar_value=count)

        if "update agent_memory set summary" in sql:
            self.updates.append(params)
            for row in self.rows:
                if row["id"] == params["id"]:
                    row["summary"] = params["summary"]
            return _Result()

        raise AssertionError(f"Unexpected SQL: {sql}")

    async def commit(self):
        self.commits += 1


class _FakeLLM:
    def __init__(self, content="rolling summary", fail=False):
        self.content = content
        self.fail = fail
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError("llm failed")
        return SimpleNamespace(content=self.content)


def _row(row_id, summary=""):
    return {
        "id": row_id,
        "conversation_id": "c1",
        "user_text": f"user {row_id}",
        "reply_text": f"bot {row_id}",
        "summary": summary,
        "created_at": datetime(2026, 5, 27, 12, 0, 0) + timedelta(seconds=row_id),
    }


def test_load_memory_uses_latest_non_empty_summary_and_five_recent_turns():
    db = _FakeMemorySession([
        _row(1, "old summary"),
        _row(2, ""),
        _row(3, "latest useful summary"),
        _row(4, ""),
        _row(5, ""),
        _row(6, ""),
    ])

    summary, turns = asyncio.run(load_memory("c1", db))

    assert summary == "latest useful summary"
    assert [turn["user"] for turn in turns] == ["user 2", "user 3", "user 4", "user 5", "user 6"]


def test_save_memory_inserts_raw_turns_before_summary_threshold():
    db = _FakeMemorySession()
    llm = _FakeLLM()

    for index in range(1, 4):
        asyncio.run(save_memory("c1", f"user {index}", f"bot {index}", ["conversation"], f"corr-{index}", db, llm))

    assert len(db.rows) == 3
    assert all(row["summary"] == "" for row in db.rows)
    assert llm.calls == []
    assert db.updates == []


def test_save_memory_updates_inserted_fourth_turn_with_rolling_summary():
    db = _FakeMemorySession([_row(1), _row(2), _row(3, "previous summary")])
    llm = _FakeLLM("new summary")

    asyncio.run(save_memory("c1", "user 4", "bot 4", ["text2sql"], "corr-4", db, llm))

    assert len(db.rows) == 4
    assert db.rows[-1]["summary"] == "new summary"
    assert db.updates == [{"id": 4, "summary": "new summary"}]
    assert len(llm.calls) == 1
    assert "Tóm tắt trước: previous summary" in llm.calls[0][1].content


def test_save_memory_keeps_raw_turn_when_summary_llm_fails():
    db = _FakeMemorySession([_row(1), _row(2), _row(3)])
    llm = _FakeLLM(fail=True)

    asyncio.run(save_memory("c1", "user 4", "bot 4", ["text2sql"], "corr-4", db, llm))

    assert len(db.rows) == 4
    assert db.rows[-1]["summary"] == ""
    assert db.updates == []


def test_save_memory_includes_company_id_when_live_schema_requires_it():
    db = _FakeMemorySession(columns={("agent_memory", "company_id")})
    llm = _FakeLLM()

    asyncio.run(save_memory(
        "c1",
        "user 1",
        "bot 1",
        ["conversation"],
        "corr-1",
        db,
        llm,
        company_id=7,
    ))

    assert db.rows[0]["company_id"] == 7
