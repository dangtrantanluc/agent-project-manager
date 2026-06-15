from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, is_restricted, project_access_exists_sql

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/tags-summary")
async def get_tags_summary(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Thống kê task theo NHÃN (task-tag): mỗi nhãn có bao nhiêu task, done, quá hạn.

    Scope theo company; MEMBER/VIEWER chỉ tính task thuộc dự án mình tham gia.
    Chỉ trả nhãn đang có task (JOIN), sắp theo tổng số task giảm dần.
    """
    cid = current_user.get("companyId") or current_user.get("company_id") or 1
    params: dict = {"cid": cid}
    task_access = ""
    if is_restricted(current_user):
        task_access = f" AND {project_access_exists_sql('t.project_id')}"
        params["access_uid"] = current_user["id"]

    rows = (await db.execute(
        text(f"""
            SELECT tg.id, tg.name, tg.color,
                   COUNT(t.id) AS total,
                   COUNT(t.id) FILTER (WHERE t.status::text = 'DONE') AS done,
                   COUNT(t.id) FILTER (
                       WHERE t.deadline < CURRENT_DATE
                         AND t.status::text NOT IN ('DONE','CANCELLED')) AS overdue
            FROM tags tg
            JOIN task_tags tt ON tt.tag_id = tg.id
            JOIN tasks t ON t.id = tt.task_id{task_access}
            WHERE tg.company_id = :cid
              -- Tag riêng: chỉ chủ thấy trong thống kê của mình.
              AND (tg.owner_user_id IS NULL OR tg.owner_user_id = :viewer_id)
            GROUP BY tg.id, tg.name, tg.color
            ORDER BY total DESC, tg.name ASC
        """),
        {**params, "viewer_id": current_user["id"]},
    )).fetchall()
    return {
        "data": [
            {"id": r[0], "name": r[1], "color": r[2],
             "total": int(r[3]), "done": int(r[4]), "overdue": int(r[5])}
            for r in rows
        ]
    }


@router.get("/overview")
async def get_overview(
    project_id: Optional[int] = Query(default=None, alias="projectId"),
    project_status: Optional[str] = Query(default=None, alias="projectStatus"),
    assignee_id: Optional[int] = Query(default=None, alias="assigneeId"),
    days: Optional[int] = Query(default=None, ge=1, le=3650),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cid = current_user.get("companyId") or current_user.get("company_id") or 1
    company_params: dict = {"cid": cid}
    # Đếm dự án của công ty: MEMBER/VIEWER chỉ tính dự án mình tham gia.
    company_proj_filter = ""
    if is_restricted(current_user):
        company_proj_filter = f" AND {project_access_exists_sql('p.id')}"
        company_params["access_uid"] = current_user["id"]
    company = (await db.execute(
        text(f"""
            SELECT c.name, COUNT(p.id) AS project_count
            FROM companies c
            LEFT JOIN projects p ON p.company_id = c.id{company_proj_filter}
            WHERE c.id = :cid
            GROUP BY c.id, c.name
        """),
        company_params,
    )).fetchone()

    # Bộ lọc dùng chung. Mỗi điều kiện chỉ thêm vào khi param có giá trị,
    # nên dashboard không filter vẫn chạy y như trước.
    proj_where = "WHERE TRUE"
    task_where = "WHERE TRUE"
    params: dict = {}
    if project_id:
        proj_where += " AND id = :pid"
        task_where += " AND t.project_id = :pid"
        params["pid"] = project_id
    if project_status:
        proj_where += " AND status::text = :pstatus"
        # Task gắn với project có trạng thái tương ứng.
        task_where += " AND t.project_id IN (SELECT id FROM projects WHERE status::text = :pstatus)"
        params["pstatus"] = project_status
    if assignee_id:
        task_where += " AND t.assignee_id = :aid"
        params["aid"] = assignee_id

    # MEMBER/VIEWER chỉ thấy dữ liệu thuộc project mình tham gia. MANAGER/ADMIN thấy tất cả.
    if is_restricted(current_user):
        proj_where += f" AND {project_access_exists_sql('projects.id')}"
        task_where += f" AND {project_access_exists_sql('t.project_id')}"
        params["access_uid"] = current_user["id"]

    project_counts = (await db.execute(
        text(f"""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status::text = 'IN_PROGRESS') AS in_progress,
                COUNT(*) FILTER (WHERE status::text IN ('DONE', 'COMPLETED')) AS done,
                COUNT(*) FILTER (WHERE status::text IN ('PENDING', 'ON_HOLD', 'CANCELLED')) AS paused
            FROM projects {proj_where}
        """),
        params,
    )).fetchone()

    task_counts = (await db.execute(
        text(f"""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE t.status::text = 'DONE') AS done,
                COUNT(*) FILTER (WHERE t.status::text = 'IN_PROGRESS') AS in_progress,
                COUNT(*) FILTER (WHERE t.status::text = 'TODO') AS planned
            FROM tasks t {task_where}
        """),
        params,
    )).fetchone()

    # Timeline: tái dùng cùng bộ lọc task; milestone lọc theo project khi có projectId.
    ms_where = "WHERE m.due_date IS NOT NULL AND m.due_date >= CURRENT_DATE AND COALESCE(m.status, '') <> 'DONE'"
    if project_id:
        ms_where += " AND m.project_id = :pid"
    if project_status:
        ms_where += " AND m.project_id IN (SELECT id FROM projects WHERE status::text = :pstatus)"
    if is_restricted(current_user):
        ms_where += f" AND {project_access_exists_sql('m.project_id')}"
    tl_params = dict(params)
    if days:
        # Giới hạn cửa sổ timeline tới N ngày kể từ hôm nay.
        tl_params["tl_days"] = days
    upcoming = (await db.execute(
        text(f"""
            SELECT id, item_type, title, due_date FROM (
                SELECT m.id, 'milestone' AS item_type, m.name AS title, m.due_date
                FROM milestones m
                {ms_where}
                UNION ALL
                SELECT t.id, 'task' AS item_type, t.name AS title, t.deadline AS due_date
                FROM tasks t
                {task_where.replace("WHERE TRUE", "WHERE t.deadline IS NOT NULL AND t.deadline >= CURRENT_DATE AND t.status::text <> 'DONE'")}
            ) timeline
            {"WHERE due_date <= CURRENT_DATE + (:tl_days || ' day')::interval" if days else ""}
            ORDER BY due_date ASC
            LIMIT 6
        """),
        tl_params,
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
    # MEMBER/VIEWER chỉ tính KPI trên project mình tham gia; MANAGER/ADMIN tính toàn bộ.
    restricted = is_restricted(current_user)
    kparams: dict = {}
    proj_acc = task_acc = wl_acc = bl_acc = ""
    if restricted:
        kparams["access_uid"] = current_user["id"]
        proj_acc = f" AND {project_access_exists_sql('projects.id')}"
        task_acc = f" AND {project_access_exists_sql('t.project_id')}"
        wl_acc = f" AND {project_access_exists_sql('w.project_id')}"
        bl_acc = f" AND {project_access_exists_sql('backlogs.project_id')}"

    active_projects = (await db.execute(
        text(f"SELECT COUNT(*) FROM projects WHERE status::text = 'IN_PROGRESS'{proj_acc}"), kparams,
    )).scalar()
    planned_projects = (await db.execute(
        text(f"SELECT COUNT(*) FROM projects WHERE status::text = 'PLANNED'{proj_acc}"), kparams,
    )).scalar()
    pending_projects = (await db.execute(
        text(f"SELECT COUNT(*) FROM projects WHERE status::text IN ('PENDING', 'ON_HOLD'){proj_acc}"), kparams,
    )).scalar()
    completed_projects = (await db.execute(
        text(f"SELECT COUNT(*) FROM projects WHERE status::text IN ('DONE', 'COMPLETED'){proj_acc}"), kparams,
    )).scalar()
    cancelled_projects = (await db.execute(
        text(f"SELECT COUNT(*) FROM projects WHERE status::text = 'CANCELLED'{proj_acc}"), kparams,
    )).scalar()

    task_status_rows = (await db.execute(
        text(f"""
            SELECT t.status, COUNT(*) FROM tasks t
            WHERE TRUE{task_acc}
            GROUP BY t.status
        """), kparams,
    )).fetchall()
    tasks_by_status = {r[0]: r[1] for r in task_status_rows}

    month_agg = (await db.execute(
        text(f"""
            SELECT COALESCE(SUM(w.hours), 0)
            FROM worklogs w
            WHERE w.work_date >= date_trunc('month', CURRENT_DATE){wl_acc}
        """), kparams,
    )).fetchone()
    pending_backlogs = (await db.execute(
        text(f"""
            SELECT COUNT(*) FROM backlogs
            WHERE status = 'PENDING'::"BacklogStatus"{bl_acc}
        """), kparams,
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

    # MEMBER/VIEWER chỉ thấy giờ công / dự án mình tham gia; MANAGER/ADMIN thấy toàn bộ.
    restricted = is_restricted(current_user)
    wl_acc = proj_acc = ""
    cparams: dict = {"days": days}
    if restricted:
        cparams["access_uid"] = current_user["id"]
        wl_acc = f" AND {project_access_exists_sql('w.project_id')}"
        proj_acc = f" WHERE {project_access_exists_sql('projects.id')}"

    hours_by_day = (await db.execute(
        text(f"""
            SELECT DATE_TRUNC('day', w.work_date) AS day,
                   SUM(w.hours)::float AS hours
            FROM worklogs w
            WHERE w.work_date >= CURRENT_DATE - :days * INTERVAL '1 day'{wl_acc}
            GROUP BY 1 ORDER BY 1
        """),
        cparams,
    )).fetchall()

    hours_by_project = (await db.execute(
        text(f"""
            SELECT id, name, total_hours
            FROM projects{proj_acc}
            ORDER BY total_hours DESC LIMIT 10
        """),
        cparams if restricted else {},
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
