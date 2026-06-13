"""Phát hiện dự án "at-risk" một cách tất định từ dữ liệu task (sơ đồ Luồng 4, ⑰).

Thuần SQL + công thức điểm — KHÔNG gọi LLM (để chạy đều, test được). Phần LLM chỉ
dùng ở bước SOẠN cảnh báo (risk_alert_service), không dùng để phát hiện.

Tín hiệu rủi ro / trọng số:
  - overdue          (deadline < hôm nay, chưa xong/huỷ)              x3
  - blocked          (task có blocker chưa giải quyết)               x3
  - due_soon_low     (đến hạn ≤3 ngày, progress < 50%, chưa xong)    x2
  - milestone_overdue(milestone quá due_date mà chưa 100%)           x2
  - stale            (TODO/IN_PROGRESS, >7 ngày không cập nhật)      x1
  - unassigned       (chưa có người phụ trách, chưa xong/huỷ)        x1
Ngưỡng at-risk: score >= 4. Level HIGH nếu score >= 10, overdue >= 3, hoặc có blocker.
"""
import logging
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

AT_RISK_THRESHOLD = 4
HIGH_SCORE = 10
HIGH_OVERDUE = 3

_W_OVERDUE = 3
_W_BLOCKED = 3
_W_DUE_SOON_LOW = 2
_W_MILESTONE = 2
_W_STALE = 1
_W_UNASSIGNED = 1


# Số task cụ thể tối đa liệt kê trong cảnh báo (tránh tin quá dài).
TOP_TASKS_LIMIT = 5


@dataclass
class RiskTask:
    """Một task góp phần gây rủi ro — để nêu đích danh trong cảnh báo."""
    id: int
    name: str
    reason: str          # 'overdue' | 'due_soon_low' | 'stale' | 'unassigned'
    deadline: str | None
    assignee: str | None


@dataclass
class ProjectRisk:
    project_id: int
    project_name: str
    owner_id: int | None
    account_manager_id: int | None
    overdue: int
    due_soon_low: int
    stale: int
    unassigned: int
    blocked: int = 0
    milestone_overdue: int = 0
    score: int = 0
    level: str = "MEDIUM"
    reasons: list[str] = field(default_factory=list)
    top_tasks: list[RiskTask] = field(default_factory=list)
    extra_tasks: int = 0  # số task rủi ro còn lại không liệt kê chi tiết

    @property
    def pm_user_id(self) -> int | None:
        """Người nhận cảnh báo: ưu tiên owner, fallback account_manager."""
        return self.owner_id or self.account_manager_id


def _build_reasons(overdue, due_soon_low, stale, unassigned, blocked=0, milestone_overdue=0) -> list[str]:
    reasons = []
    if overdue:
        reasons.append(f"{overdue} task đã quá hạn")
    if blocked:
        reasons.append(f"{blocked} task đang bị blocker chưa giải quyết")
    if due_soon_low:
        reasons.append(f"{due_soon_low} task sắp đến hạn (≤3 ngày) nhưng tiến độ <50%")
    if milestone_overdue:
        reasons.append(f"{milestone_overdue} milestone quá hạn mà chưa hoàn thành")
    if stale:
        reasons.append(f"{stale} task >7 ngày không cập nhật")
    if unassigned:
        reasons.append(f"{unassigned} task chưa có người phụ trách")
    return reasons


def _score_and_level(overdue, due_soon_low, stale, unassigned, blocked=0, milestone_overdue=0) -> tuple[int, str]:
    score = (overdue * _W_OVERDUE + blocked * _W_BLOCKED
             + due_soon_low * _W_DUE_SOON_LOW + milestone_overdue * _W_MILESTONE
             + stale * _W_STALE + unassigned * _W_UNASSIGNED)
    # Blocker là tín hiệu nghiêm trọng -> đẩy lên HIGH ngay.
    level = "HIGH" if (score >= HIGH_SCORE or overdue >= HIGH_OVERDUE or blocked >= 1) else "MEDIUM"
    return score, level


async def _fetch_risk_tasks(db: AsyncSession, project_id: int) -> tuple[list[RiskTask], int]:
    """Lấy các task góp phần rủi ro của 1 project, ưu tiên nặng nhất trước.

    Mỗi task gắn 1 'reason' chính (overdue > due_soon_low > stale > unassigned).
    Trả (top N task, số task rủi ro còn lại).
    """
    # has_blocker: task có blocker chưa giải quyết.
    rows = (await db.execute(text("""
        WITH blk AS (
            SELECT DISTINCT task_id FROM task_blockers WHERE resolved_at IS NULL
        )
        SELECT t.id, t.name, t.deadline, u.full_name AS assignee,
            CASE
              WHEN t.id IN (SELECT task_id FROM blk) THEN 'blocked'
              WHEN t.deadline < CURRENT_DATE AND t.status::text NOT IN ('DONE','CANCELLED')
                   THEN 'overdue'
              WHEN t.deadline >= CURRENT_DATE AND t.deadline <= CURRENT_DATE + 3
                   AND t.progress < 50 AND t.status::text NOT IN ('DONE','CANCELLED')
                   THEN 'due_soon_low'
              WHEN t.assignee_id IS NULL AND t.status::text NOT IN ('DONE','CANCELLED')
                   THEN 'unassigned'
              WHEN t.status::text IN ('TODO','IN_PROGRESS')
                   AND t.updated_at < NOW() - INTERVAL '7 days'
                   THEN 'stale'
            END AS reason
        FROM tasks t
        LEFT JOIN users u ON u.id = t.assignee_id
        WHERE t.project_id = :pid
          AND (
            t.id IN (SELECT task_id FROM blk)
            OR (t.deadline < CURRENT_DATE AND t.status::text NOT IN ('DONE','CANCELLED'))
            OR (t.deadline >= CURRENT_DATE AND t.deadline <= CURRENT_DATE + 3
                AND t.progress < 50 AND t.status::text NOT IN ('DONE','CANCELLED'))
            OR (t.assignee_id IS NULL AND t.status::text NOT IN ('DONE','CANCELLED'))
            OR (t.status::text IN ('TODO','IN_PROGRESS')
                AND t.updated_at < NOW() - INTERVAL '7 days')
          )
        ORDER BY
          CASE
            WHEN t.id IN (SELECT task_id FROM blk) THEN 0
            WHEN t.deadline < CURRENT_DATE AND t.status::text NOT IN ('DONE','CANCELLED') THEN 1
            WHEN t.deadline >= CURRENT_DATE AND t.deadline <= CURRENT_DATE + 3
                 AND t.progress < 50 AND t.status::text NOT IN ('DONE','CANCELLED') THEN 2
            WHEN t.assignee_id IS NULL AND t.status::text NOT IN ('DONE','CANCELLED') THEN 3
            ELSE 4
          END,
          t.deadline ASC NULLS LAST, t.id ASC
    """), {"pid": project_id})).fetchall()

    tasks = [RiskTask(id=r[0], name=r[1],
                      deadline=r[2].isoformat() if r[2] else None,
                      assignee=r[3], reason=r[4]) for r in rows]
    top = tasks[:TOP_TASKS_LIMIT]
    return top, max(0, len(tasks) - len(top))


async def detect_at_risk_projects(db: AsyncSession, project_id: int | None = None) -> list[ProjectRisk]:
    """Trả danh sách project at-risk (score >= ngưỡng), sắp xếp score giảm dần.

    project_id != None -> chỉ xét đúng 1 project (dùng cho quét near-real-time khi
    1 task của project đó vừa thay đổi).
    """
    proj_filter = "AND p.id = :pid" if project_id is not None else ""
    rows = (await db.execute(text(f"""
        SELECT p.id, p.name, p.owner_id, p.account_manager_id,
            COUNT(*) FILTER (
                WHERE t.deadline < CURRENT_DATE
                  AND t.status::text NOT IN ('DONE','CANCELLED')) AS overdue,
            COUNT(*) FILTER (
                WHERE t.deadline >= CURRENT_DATE
                  AND t.deadline <= CURRENT_DATE + 3
                  AND t.progress < 50
                  AND t.status::text NOT IN ('DONE','CANCELLED')) AS due_soon_low,
            COUNT(*) FILTER (
                WHERE t.status::text IN ('TODO','IN_PROGRESS')
                  AND t.updated_at < NOW() - INTERVAL '7 days') AS stale,
            COUNT(*) FILTER (
                WHERE t.assignee_id IS NULL
                  AND t.status::text NOT IN ('DONE','CANCELLED')) AS unassigned,
            (SELECT COUNT(DISTINCT tb.task_id) FROM task_blockers tb
               JOIN tasks t2 ON t2.id = tb.task_id
              WHERE t2.project_id = p.id AND tb.resolved_at IS NULL) AS blocked,
            (SELECT COUNT(*) FROM milestones m
              WHERE m.project_id = p.id AND m.due_date < CURRENT_DATE
                AND m.completion_pct < 100) AS milestone_overdue
        FROM projects p
        LEFT JOIN tasks t ON t.project_id = p.id
        WHERE p.status::text IN ('PLANNED','IN_PROGRESS')
          {proj_filter}
        GROUP BY p.id, p.name, p.owner_id, p.account_manager_id
    """), ({"pid": project_id} if project_id is not None else {}))).fetchall()

    risks: list[ProjectRisk] = []
    for (pid, name, owner_id, am_id, overdue, due_soon_low, stale, unassigned,
         blocked, milestone_overdue) in rows:
        score, level = _score_and_level(overdue, due_soon_low, stale, unassigned,
                                        blocked, milestone_overdue)
        if score < AT_RISK_THRESHOLD:
            continue
        top_tasks, extra = await _fetch_risk_tasks(db, pid)
        risks.append(ProjectRisk(
            project_id=pid, project_name=name, owner_id=owner_id, account_manager_id=am_id,
            overdue=overdue, due_soon_low=due_soon_low, stale=stale, unassigned=unassigned,
            blocked=blocked, milestone_overdue=milestone_overdue,
            score=score, level=level,
            reasons=_build_reasons(overdue, due_soon_low, stale, unassigned,
                                   blocked, milestone_overdue),
            top_tasks=top_tasks, extra_tasks=extra,
        ))

    risks.sort(key=lambda r: r.score, reverse=True)
    return risks
