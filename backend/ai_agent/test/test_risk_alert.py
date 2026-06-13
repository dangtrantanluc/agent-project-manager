"""Test phát hiện rủi ro + cảnh báo PM có phê duyệt (Luồng 4).

Bao phủ:
  - risk_detector: công thức điểm/level, ngưỡng at-risk, lọc & sắp xếp.
  - risk_alert_service: build_draft_message (template), classify_decision (rule path,
    LLM=None), find_pending_for & handle_decision (approve/dismiss) với _FakeSession.

Không gọi LLM/mạng: llm=None -> rule/template; gapo = _FakeGapo.
"""
import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.risk_detector import (
    detect_at_risk_projects, _score_and_level, _build_reasons, AT_RISK_THRESHOLD,
)
from app.services.risk_alert_service import RiskAlertService, PendingAlert
from app.services.risk_detector import ProjectRisk


class _Result:
    def __init__(self, rows, rowcount=1):
        self._rows = rows
        # apply_decision dùng rowcount để chống race (UPDATE có guard status):
        # 1 = chính transaction này chốt alert. Mặc định 1 = happy path.
        self.rowcount = rowcount

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.statements = []

    async def execute(self, statement, params=None):
        sql = str(statement).lower()
        self.statements.append((sql, params))
        for key, rows in self.responses.items():
            if key in sql:
                return _Result(rows)
        return _Result([])

    async def commit(self):
        pass


class _FakeGapo:
    def __init__(self):
        self.sent = []

    async def send_message(self, thread_id, text, **kw):
        self.sent.append(("thread", str(thread_id), text))
        return {"ok": True}

    async def send_to_user(self, receiver_id, text, **kw):
        self.sent.append(("user", str(receiver_id), text))
        return {"ok": True}


def _svc():
    return RiskAlertService(gapo=_FakeGapo(), llm=None)


# ── risk_detector: scoring ────────────────────────────────────────────────────
def test_score_and_level():
    # 3 overdue -> score 9, nhưng overdue>=3 -> HIGH
    score, level = _score_and_level(overdue=3, due_soon_low=0, stale=0, unassigned=0)
    assert score == 9 and level == "HIGH"
    # score >= 10 -> HIGH
    score, level = _score_and_level(overdue=2, due_soon_low=2, stale=0, unassigned=0)
    assert score == 10 and level == "HIGH"
    # nhỏ -> MEDIUM
    score, level = _score_and_level(overdue=1, due_soon_low=0, stale=1, unassigned=0)
    assert score == 4 and level == "MEDIUM"


def test_build_reasons_only_nonzero():
    reasons = _build_reasons(overdue=2, due_soon_low=0, stale=1, unassigned=0)
    assert any("quá hạn" in r for r in reasons)
    assert any("không cập nhật" in r for r in reasons)
    assert not any("phụ trách" in r for r in reasons)


def test_detect_filters_and_sorts():
    # project 1: nặng (overdue 4 -> HIGH); project 2: dưới ngưỡng (score 1 -> bỏ);
    # project 3: vừa (overdue 1 + stale 1 = 4 -> MEDIUM).
    # 10 cột: id, name, owner, am, overdue, due_soon_low, stale, unassigned, blocked, milestone_overdue
    db = _FakeSession({"from projects": [
        (1, "Alpha", 10, None, 4, 0, 0, 0, 0, 0),
        (2, "Beta", 11, None, 0, 0, 1, 0, 0, 0),
        (3, "Gamma", 12, None, 1, 0, 1, 0, 0, 0),
    ]})
    risks = asyncio.run(detect_at_risk_projects(db))
    ids = [r.project_id for r in risks]
    assert ids == [1, 3]                  # Beta bị loại, sắp theo score giảm dần
    assert risks[0].level == "HIGH"
    assert all(r.score >= AT_RISK_THRESHOLD for r in risks)


# ── risk_alert_service: draft + classify ──────────────────────────────────────
def test_build_draft_message_template():
    risk = ProjectRisk(
        project_id=1, project_name="Alpha", owner_id=10, account_manager_id=None,
        overdue=2, due_soon_low=1, stale=0, unassigned=0, score=8, level="MEDIUM",
        reasons=["2 task đã quá hạn", "1 task sắp đến hạn (≤3 ngày) nhưng tiến độ <50%"],
    )
    msg = _svc().build_draft_message(risk)
    assert "Alpha" in msg and "MEDIUM" in msg
    assert "quá hạn" in msg and "Đề xuất hành động" in msg
    assert "OK/duyệt" in msg               # câu hỏi xác nhận


def test_classify_decision_rule():
    s = _svc()
    assert s.classify_decision("ok duyệt gửi đi") == "approve"
    assert s.classify_decision("ừ") == "approve"
    assert s.classify_decision("thôi bỏ qua") == "dismiss"
    assert s.classify_decision("không gửi đâu") == "dismiss"   # phủ định thắng "gửi"
    assert s.classify_decision("để mình xem đã") == "unclear"


# ── find_pending_for + handle_decision ────────────────────────────────────────
def test_find_pending_for():
    db = _FakeSession({"from risk_alerts": [(7, 1, "Alpha", "draft...", 10)]})
    alert = asyncio.run(_svc().find_pending_for(db, user_id="10", thread_id="t1"))
    assert alert is not None and alert.id == 7 and alert.project_name == "Alpha"


def test_find_pending_none_without_thread():
    db = _FakeSession({"from risk_alerts": [(7, 1, "Alpha", "draft", 10)]})
    assert asyncio.run(_svc().find_pending_for(db, user_id="10", thread_id=None)) is None


def test_handle_decision_approve():
    db = _FakeSession({"from projects": [(None,)]})   # project không có group thread
    alert = PendingAlert(id=7, project_id=1, project_name="Alpha",
                         draft_message="draft", pm_user_id=10)
    out = asyncio.run(_svc().handle_decision(db, alert, "ok duyệt"))
    assert "xác nhận" in out.lower()
    ups = [(s, p) for s, p in db.statements if "update risk_alerts" in s]
    assert ups and ups[0][1]["st"] == "APPROVED"


def test_handle_decision_dismiss():
    db = _FakeSession({})
    alert = PendingAlert(id=7, project_id=1, project_name="Alpha",
                         draft_message="draft", pm_user_id=10)
    out = asyncio.run(_svc().handle_decision(db, alert, "thôi bỏ qua"))
    assert "bỏ qua" in out.lower()
    ups = [(s, p) for s, p in db.statements if "update risk_alerts" in s]
    assert ups and ups[0][1]["st"] == "DISMISSED"


def test_handle_decision_unclear_no_write():
    db = _FakeSession({})
    alert = PendingAlert(id=7, project_id=1, project_name="Alpha",
                         draft_message="draft", pm_user_id=10)
    out = asyncio.run(_svc().handle_decision(db, alert, "ờ để xem"))
    assert "chưa rõ" in out.lower()
    assert not any("update risk_alerts" in s for s, _ in db.statements)


def test_find_pending_list_returns_all():
    # PM có NHIỀU alert pending cùng thread -> trả đủ list (không latest-wins).
    db = _FakeSession({"from risk_alerts": [
        (8, 2, "Beta", "draft-b", 10),
        (7, 1, "Alpha", "draft-a", 10),
    ]})
    alerts = asyncio.run(_svc().find_pending_list(db, user_id="10", thread_id="t1"))
    assert [a.id for a in alerts] == [8, 7]


def test_apply_decision_bulk_approves_all():
    # Quyết định approve áp cho TOÀN BỘ alerts; reply nêu đủ tên dự án.
    db = _FakeSession({"from projects": [(None,)]})
    alerts = [
        PendingAlert(id=7, project_id=1, project_name="Alpha", draft_message="a", pm_user_id=10),
        PendingAlert(id=8, project_id=2, project_name="Beta", draft_message="b", pm_user_id=10),
    ]
    out = asyncio.run(_svc().apply_decision(db, alerts, "approve", "ok duyệt"))
    ups = [(s, p) for s, p in db.statements if "update risk_alerts" in s]
    assert len(ups) == 2 and all(p["st"] == "APPROVED" for _, p in ups)
    assert "Alpha" in out and "Beta" in out
