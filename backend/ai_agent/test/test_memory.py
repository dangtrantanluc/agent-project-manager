import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import ai_agent.memory.memory as memory
from ai_agent.memory.memory import load_memory, save_memory


class _Result:
    def __init__(self, rows=None, scalar_value=None):
        self.rows = rows or []
        self.scalar_value = scalar_value

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

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

        if "select last_sql" in sql:
            rows = [
                row for row in self.rows
                if row["conversation_id"] == params["cid"] and (row.get("last_sql") or "").strip()
            ]
            rows.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
            return _Result(scalar_value=rows[0]["last_sql"] if rows else None)

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
                "last_sql": params.get("last_sql"),
                "created_at": datetime(2026, 5, 27, 12, 0, 0) + timedelta(seconds=row_id),
            })
            # CTE mới trả về (id, turn_count) qua fetchone().
            turn_count = sum(
                1 for row in self.rows if row["conversation_id"] == params["conv_id"]
            )
            return _Result(rows=[(row_id, turn_count)])

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


class _FakeOpenAIClient:
    """Mô phỏng openai.AsyncOpenAI: client.chat.completions.create(...) trả về
    object có .choices[0].message.content — đúng interface save_memory đang dùng.
    """

    def __init__(self, content="rolling summary", fail=False):
        self.content = content
        self.fail = fail
        self.calls = []  # mỗi phần tử là list messages truyền vào create()
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, *, model, messages, temperature=0, **kwargs):
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError("llm failed")
        message = SimpleNamespace(content=self.content)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


def _patch_openai(monkeypatch, client):
    """Trỏ memory.AsyncOpenAI(...) về fake client (bỏ qua api_key/base_url)."""
    monkeypatch.setattr(memory, "AsyncOpenAI", lambda *a, **k: client)


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

    summary, turns, last_sql = asyncio.run(load_memory("c1", db))

    assert summary == "latest useful summary"
    assert [turn["user"] for turn in turns] == ["user 2", "user 3", "user 4", "user 5", "user 6"]
    assert last_sql == ""  # schema chưa có cột last_sql -> không query, trả rỗng


def test_save_memory_inserts_raw_turns_before_summary_threshold(monkeypatch):
    db = _FakeMemorySession()
    client = _FakeOpenAIClient()
    _patch_openai(monkeypatch, client)

    for index in range(1, 4):
        asyncio.run(save_memory("c1", f"user {index}", f"bot {index}", ["conversation"], f"corr-{index}", db))

    assert len(db.rows) == 3
    assert all(row["summary"] == "" for row in db.rows)
    assert client.calls == []
    assert db.updates == []


def test_save_memory_updates_inserted_fourth_turn_with_rolling_summary(monkeypatch):
    db = _FakeMemorySession([_row(1), _row(2), _row(3, "previous summary")])
    client = _FakeOpenAIClient("new summary")
    _patch_openai(monkeypatch, client)

    asyncio.run(save_memory("c1", "user 4", "bot 4", ["text2sql"], "corr-4", db))

    assert len(db.rows) == 4
    assert db.rows[-1]["summary"] == "new summary"
    assert db.updates == [{"id": 4, "summary": "new summary"}]
    assert len(client.calls) == 1
    # messages = [system, user]; ctx (tóm tắt trước + các lượt) nằm ở user message.
    assert "Tóm tắt trước: previous summary" in client.calls[0][1]["content"]


def test_save_memory_keeps_raw_turn_when_summary_llm_fails(monkeypatch):
    db = _FakeMemorySession([_row(1), _row(2), _row(3)])
    client = _FakeOpenAIClient(fail=True)
    _patch_openai(monkeypatch, client)

    asyncio.run(save_memory("c1", "user 4", "bot 4", ["text2sql"], "corr-4", db))

    assert len(db.rows) == 4
    assert db.rows[-1]["summary"] == ""
    assert db.updates == []


def test_save_memory_includes_company_id_when_live_schema_requires_it(monkeypatch):
    db = _FakeMemorySession(columns={("agent_memory", "company_id")})
    client = _FakeOpenAIClient()
    _patch_openai(monkeypatch, client)

    asyncio.run(save_memory(
        "c1",
        "user 1",
        "bot 1",
        ["conversation"],
        "corr-1",
        db,
        company_id=7,
    ))

    assert db.rows[0]["company_id"] == 7


def test_save_memory_persists_last_sql_when_schema_has_column():
    db = _FakeMemorySession(columns={("agent_memory", "last_sql")})

    asyncio.run(save_memory(
        "c1", "66 task rủi ro của MTL?", "MTL có 66 task rủi ro.",
        ["text2sql"], "corr-1", db,
        last_sql="SELECT * FROM tasks WHERE project='MTL' AND risk=true;",
    ))

    assert db.rows[0]["last_sql"] == "SELECT * FROM tasks WHERE project='MTL' AND risk=true;"


def test_save_memory_skips_last_sql_when_schema_missing_column():
    db = _FakeMemorySession()  # không khai báo cột last_sql

    asyncio.run(save_memory(
        "c1", "q", "a", ["text2sql"], "corr-1", db,
        last_sql="SELECT 1;",
    ))

    assert db.rows[0].get("last_sql") is None


def test_save_memory_does_not_store_fallback_sql():
    db = _FakeMemorySession(columns={("agent_memory", "last_sql")})

    asyncio.run(save_memory(
        "c1", "câu linh tinh", "không trả lời được",
        ["text2sql"], "corr-1", db,
        last_sql="SELECT 'Câu hỏi không thể trả lời bằng SQL' AS message;",
    ))

    assert db.rows[0].get("last_sql") is None


def test_load_memory_returns_latest_text2sql_sql():
    db = _FakeMemorySession(
        columns={("agent_memory", "last_sql")},
        rows=[
            {**_row(1), "last_sql": "SELECT 1;"},
            {**_row(2), "last_sql": "SELECT 2;"},
            {**_row(3), "last_sql": None},  # lượt conversation xen giữa -> bỏ qua
        ],
    )

    _summary, _turns, last_sql = asyncio.run(load_memory("c1", db))

    assert last_sql == "SELECT 2;"  # SQL gần nhất, không phải turn cuối (None)
