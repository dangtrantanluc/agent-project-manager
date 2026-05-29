import os
import sys
from datetime import date, datetime
from pathlib import Path

os.environ["CHECKIN_SCHEDULER_ENABLED"] = "false"

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient

from app.core.deps import get_current_user, get_db
from main import app


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    async def execute(self, statement, params=None):
        self.statements.append((str(statement), params or {}))
        return _Result(self.rows)


PROJECT_ROW = (
    101,
    "Agent PM",
    "APM",
    "IN_PROGRESS",
    "HIGH",
    date(2026, 5, 1),
    date(2026, 6, 30),
    "Internal project management",
    48,
    7,
    3,
    11,
    2,
    1,
    9,
    "BBSW",
    None,
    1,
    datetime(2026, 5, 1, 8, 0, 0),
    datetime(2026, 5, 26, 18, 30, 0),
)


async def _current_user():
    return {
        "id": 9,
        "email": "tester@bluebolt.local",
        "fullName": "Senior Tester",
        "role": "ADMIN",
        "companyId": 1,
        "companyName": "Bluebolt",
        "isSuperAdmin": True,
    }


def _client_with_db(fake_db):
    async def _db_override():
        yield fake_db

    app.dependency_overrides[get_current_user] = _current_user
    app.dependency_overrides[get_db] = _db_override
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_health_endpoints_are_available():
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/api/v1/health").json() == {"status": "ok"}


def test_projects_list_returns_normalized_contract_and_forwards_filters():
    fake_db = _FakeSession([PROJECT_ROW])

    with _client_with_db(fake_db) as client:
        response = client.get(
            "/api/v1/projects",
            params={"status": "IN_PROGRESS", "q": "agent", "pageSize": 25},
        )

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 101,
            "name": "Agent PM",
            "code": "APM",
            "status": "IN_PROGRESS",
            "priority": "HIGH",
            "startDate": "2026-05-01",
            "endDate": "2026-06-30",
            "description": "Internal project management",
            "totalHours": 48,
            "taskCount": 7,
            "memberCount": 3,
            "worklogCount": 11,
            "scopeCount": 2,
            "milestoneCount": 1,
            "ownerId": 9,
            "customerName": "BBSW",
            "accountManagerId": None,
            "currencyId": 1,
            "createdAt": "2026-05-01T08:00:00",
            "updatedAt": "2026-05-26T18:30:00",
        }
    ]
    _, params = fake_db.statements[0]
    assert params == {"limit": 25, "status": "IN_PROGRESS", "q": "%agent%"}


def test_projects_list_requires_authentication_without_override():
    fake_db = _FakeSession([])

    async def _db_override():
        yield fake_db

    app.dependency_overrides[get_db] = _db_override
    with TestClient(app) as client:
        response = client.get("/api/v1/projects")

    assert response.status_code == 401
    assert response.json()["detail"] == "Yêu cầu xác thực"
