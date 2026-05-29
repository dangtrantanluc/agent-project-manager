from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview")
async def get_overview(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    company = (await db.execute(
        text("""
            SELECT c.name, COUNT(p.id) AS project_count
            FROM companies c
            LEFT JOIN projects p ON p.company_id = c.id
            WHERE c.id = :cid
            GROUP BY c.id, c.name
        """),
        {"cid": current_user.get("companyId") or current_user.get("company_id") or 1},
    )).fetchone()

    project_counts = (await db.execute(
        text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status::text = 'IN_PROGRESS') AS in_progress,
                COUNT(*) FILTER (WHERE status::text IN ('DONE', 'COMPLETED')) AS done,
                COUNT(*) FILTER (WHERE status::text IN ('PENDING', 'ON_HOLD', 'CANCELLED')) AS paused
            FROM projects
        """),
    )).fetchone()

    task_counts = (await db.execute(
        text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status::text = 'DONE') AS done,
                COUNT(*) FILTER (WHERE status::text = 'IN_PROGRESS') AS in_progress,
                COUNT(*) FILTER (WHERE status::text = 'TODO') AS planned
            FROM tasks
        """),
    )).fetchone()

    upcoming = (await db.execute(
        text("""
            SELECT id, item_type, title, due_date FROM (
                SELECT m.id, 'milestone' AS item_type, m.name AS title, m.due_date
                FROM milestones m
                WHERE m.due_date IS NOT NULL
                  AND m.due_date >= CURRENT_DATE
                  AND COALESCE(m.status, '') <> 'DONE'
                UNION ALL
                SELECT t.id, 'task' AS item_type, t.name AS title, t.deadline AS due_date
                FROM tasks t
                WHERE t.deadline IS NOT NULL
                  AND t.deadline >= CURRENT_DATE
                  AND t.status::text <> 'DONE'
            ) timeline
            ORDER BY due_date ASC
            LIMIT 6
        """),
    )).fetchall()

    total_tasks = int(task_counts[0] or 0)
    done_tasks = int(task_counts[1] or 0)
    completion_pct = round(done_tasks * 100 / total_tasks) if total_tasks else 0

    return {"data": {
        "customer": {
            "name": company[0] if company else current_user.get("companyName") or "Khách hàng",
            "primaryContact": current_user.get("fullName") or current_user.get("full_name"),
            "projectCount": int(company[1] or 0) if company else 0,
            "active": True,
        },
        "projectOverview": {
            "total": int(project_counts[0] or 0),
            "inProgress": int(project_counts[1] or 0),
            "done": int(project_counts[2] or 0),
            "paused": int(project_counts[3] or 0),
        },
        "progressSummary": {
            "completionPct": completion_pct,
            "doneTasks": done_tasks,
            "totalTasks": total_tasks,
            "inProgressTasks": int(task_counts[2] or 0),
            "plannedTasks": int(task_counts[3] or 0),
        },
        "upcomingTimeline": [
            {"id": r[0], "type": r[1], "title": r[2], "date": r[3].isoformat()}
            for r in upcoming
        ],
        "agentCapabilities": ["Nhắc việc", "Theo dõi tiến độ", "Tóm tắt tình trạng", "Việc còn thiếu"],
    }}


@router.get("/kpis")
async def get_kpis(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    active_projects = (await db.execute(
        text("SELECT COUNT(*) FROM projects WHERE status::text = 'IN_PROGRESS'"),
    )).scalar()
    planned_projects = (await db.execute(
        text("SELECT COUNT(*) FROM projects WHERE status::text = 'PLANNED'"),
    )).scalar()
    pending_projects = (await db.execute(
        text("SELECT COUNT(*) FROM projects WHERE status::text IN ('PENDING', 'ON_HOLD')"),
    )).scalar()
    completed_projects = (await db.execute(
        text("SELECT COUNT(*) FROM projects WHERE status::text IN ('DONE', 'COMPLETED')"),
    )).scalar()
    cancelled_projects = (await db.execute(
        text("SELECT COUNT(*) FROM projects WHERE status::text = 'CANCELLED'"),
    )).scalar()

    task_status_rows = (await db.execute(
        text("""
            SELECT t.status, COUNT(*) FROM tasks t
            GROUP BY t.status
        """),
    )).fetchall()
    tasks_by_status = {r[0]: r[1] for r in task_status_rows}

    month_agg = (await db.execute(
        text("""
            SELECT COALESCE(SUM(w.hours), 0)
            FROM worklogs w
            WHERE w.work_date >= date_trunc('month', CURRENT_DATE)
        """),
    )).fetchone()
    pending_backlogs = (await db.execute(
        text("""
            SELECT COUNT(*) FROM backlogs
            WHERE status = 'PENDING'::"BacklogStatus"
        """),
    )).scalar()

    return {"data": {
        "projects": {
            "active": active_projects, "planned": planned_projects,
            "pending": pending_projects,
            "completed": completed_projects,
            "cancelled": cancelled_projects,
            "onHold": pending_projects,
        },
        "pendingBacklogs": pending_backlogs,
        "tasksByStatus": tasks_by_status,
        "thisMonth": {
            "hours": float(month_agg[0] or 0),
        },
    }}


@router.get("/charts")
async def get_charts(
    range: str = Query(default="30d", pattern="^(7d|30d|90d)$"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    days = 7 if range == "7d" else 90 if range == "90d" else 30

    hours_by_day = (await db.execute(
        text("""
            SELECT DATE_TRUNC('day', w.work_date) AS day,
                   SUM(w.hours)::float AS hours
            FROM worklogs w
            WHERE w.work_date >= CURRENT_DATE - :days * INTERVAL '1 day'
            GROUP BY 1 ORDER BY 1
        """),
        {"days": days},
    )).fetchall()

    hours_by_project = (await db.execute(
        text("""
            SELECT id, name, total_hours
            FROM projects
            ORDER BY total_hours DESC LIMIT 10
        """),
    )).fetchall()

    return {"data": {
        "hoursByDay": [
            {"day": r[0].isoformat(), "hours": float(r[1] or 0)}
            for r in hours_by_day
        ],
        "hoursByProject": [
            {"id": r[0], "name": r[1], "totalHours": r[2]}
            for r in hours_by_project
        ],
    }}
