"""Test phát hiện rủi ro + GỬI cảnh báo (thông báo thuần, không duyệt).

Bao phủ:
  - risk_detector: công thức điểm/level, ngưỡng at-risk, lọc & sắp xếp.
  - risk_alert_service: build_draft_message (template), scan_and_alert (gửi thẳng
    DM cho PM, ghi 'APPROVED', dedup theo correlation_id).

Không gọi LLM/mạng: llm=None -> template; gapo = _FakeGapo.
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
from app.services.risk_alert_service import RiskAlertService
from app.services.risk_detector import ProjectRisk


class _Result:
    def __init__(self, rows, rowcount=1):
        self._rows = rows
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


def _svc(gapo=None):
    return RiskAlertService(gapo=gapo or _FakeGapo(), llm=None)


# ── risk_detector: scoring ────────────────────────────────────────────────────
def test_score_and_level():
    score, level = _score_and_level(overdue=3, due_soon_low=0, stale=0, unassigned=0)
    assert score == 9 and level == "HIGH"
    score, level = _score_and_level(overdue=2, due_soon_low=2, stale=0, unassigned=0)
    assert score == 10 and level == "HIGH"
    score, level = _score_and_level(overdue=1, due_soon_low=0, stale=1, unassigned=0)
    assert score == 4 and level == "MEDIUM"


def test_build_reasons_only_nonzero():
    reasons = _build_reasons(overdue=2, due_soon_low=0, stale=1, unassigned=0)
    assert any("quá hạn" in r for r in reasons)
    assert any("không cập nhật" in r for r in reasons)
    assert not any("phụ trách" in r for r in reasons)


def test_detect_filters_and_sorts():
    db = _FakeSession({"from projects": [
        (1, "Alpha", 10, None, 4, 0, 0, 0, 0, 0),
        (2, "Beta", 11, None, 0, 0, 1, 0, 0, 0),
        (3, "Gamma", 12, None, 1, 0, 1, 0, 0, 0),
    ]})
    risks = asyncio.run(detect_at_risk_projects(db))
    ids = [r.project_id for r in risks]
    assert ids == [1, 3]
    assert risks[0].level == "HIGH"
    assert all(r.score >= AT_RISK_THRESHOLD for r in risks)


# ── risk_alert_service: draft là THÔNG BÁO (không hỏi duyệt) ──────────────────
def test_build_draft_message_template_no_confirm_question():
    risk = ProjectRisk(
        project_id=1, project_name="Alpha", owner_id=10, account_manager_id=None,
        overdue=2, due_soon_low=1, stale=0, unassigned=0, score=8, level="MEDIUM",
        reasons=["2 task đã quá hạn", "1 task sắp đến hạn (≤3 ngày) nhưng tiến độ <50%"],
    )
    msg = _svc().build_draft_message(risk)
    assert "Alpha" in msg and "MEDIUM" in msg
    assert "quá hạn" in msg and "Đề xuất hành động" in msg
    # KHÔNG còn câu hỏi duyệt/bỏ qua.
    assert "OK/duyệt" not in msg
    assert "bỏ qua" not in msg


# ── scan_and_alert: gửi thẳng, ghi APPROVED, dedup ────────────────────────────
def _alert_responses(*, pm_thread=None, pm_user="900", exists=False):
    return {
        # detect_at_risk_projects: 1 project HIGH, owner=10
        "from projects p": [(1, "Alpha", 10, None, 4, 0, 0, 0, 0, 0)],
        # dedup check
        "from risk_alerts where correlation_id": [(1,)] if exists else [],
        # _resolve_pm_channel
        "from gapo_user_maps": [(pm_thread, pm_user)] if (pm_thread or pm_user) else [],
    }


def test_scan_sends_dm_and_writes_approved():
    gapo = _FakeGapo()
    db = _FakeSession(_alert_responses(pm_user="900"))
    stats = asyncio.run(_svc(gapo).scan_and_alert(db, today_iso="2026-06-15"))
    assert stats["sent"] == 1
    # Đã gửi DM tới PM qua receiver_id.
    assert any(kind == "user" and rid == "900" for kind, rid, _ in gapo.sent)
    # Bản ghi ghi trạng thái APPROVED (đã gửi), KHÔNG phải PENDING.
    inserts = [p for s, p in db.statements if "insert into risk_alerts" in s]
    assert inserts  # có INSERT
    assert not any("pending_pm_confirmation" in s for s, _ in db.statements
                   if "insert into risk_alerts" in s)


def test_scan_dedup_skips_when_exists():
    db = _FakeSession(_alert_responses(pm_user="900", exists=True))
    stats = asyncio.run(_svc().scan_and_alert(db, today_iso="2026-06-15"))
    assert stats["sent"] == 0 and stats["skipped"] == 1


def test_scan_skips_when_pm_not_linked():
    # PM không có gapo map -> không gửi được -> skipped.
    db = _FakeSession(_alert_responses(pm_user=None, pm_thread=None))
    stats = asyncio.run(_svc().scan_and_alert(db, today_iso="2026-06-15"))
    assert stats["sent"] == 0
