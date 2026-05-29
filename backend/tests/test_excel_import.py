import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient

from app.core.deps import get_current_user, get_db
from app.modules.tasks.import_service import normalize_status, parse_xlsx
from main import app


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _FakeSession:
    async def execute(self, statement, params=None):
        return _Result([(4,)])


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


def _client():
    async def _db_override():
        yield _FakeSession()

    app.dependency_overrides[get_current_user] = _current_user
    app.dependency_overrides[get_db] = _db_override
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_regular_excel_import_auto_selects_first_sheet_with_tasks_for_thaco_file():
    path = ROOT_DIR / "doc" / "(BBSW_x_THACO_CRM)_Sprint_Plan_Go-Live_April_2026.xlsx"

    result = parse_xlsx(path.read_bytes(), filename=path.name)

    assert result.active_sheet == "🔒 Sprint 1 (25-31.03)"
    assert len(result.rows) > 20
    assert result.rows[0].name.startswith("Fix icon")
    assert result.rows[0].deadline == "2026-03-26"


def test_regular_excel_import_auto_selects_first_sheet_with_tasks_for_mtl_file():
    path = ROOT_DIR / "doc" / "PHAN_BO_GIAI_DOAN_MTL_ODOO19_VN(1).xlsx"

    result = parse_xlsx(path.read_bytes(), filename=path.name)

    assert result.active_sheet == "GD1 – Sales & CS"
    assert len(result.rows) > 30
    assert result.rows[0].name == "Quản lý đối tác (Partners)"
    assert result.rows[0].priority == "HIGH"


def test_regular_excel_import_maps_review_to_valid_task_status():
    assert normalize_status("Review") == "DONE"
    assert normalize_status("Đang review") == "DONE"


def test_import_preview_missing_file_returns_400_instead_of_422():
    with _client() as client:
        response = client.post("/api/v1/projects/4/import-tasks/preview")

    assert response.status_code == 400
    assert "Thiếu file upload" in response.json()["detail"]


def test_import_preview_accepts_xlsx_upload():
    path = ROOT_DIR / "doc" / "(BBSW_x_THACO_CRM)_Sprint_Plan_Go-Live_April_2026.xlsx"

    with _client() as client:
        response = client.post(
            "/api/v1/projects/4/import-tasks/preview",
            files={"file": (path.name, path.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["active_sheet"] == "🔒 Sprint 1 (25-31.03)"
    assert len(data["rows"]) > 20
