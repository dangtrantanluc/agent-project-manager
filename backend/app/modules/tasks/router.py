import json
from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_agent_user, get_current_user, get_db, require_role, is_restricted, project_access_exists_sql
from app.core.code_gen import next_task_code
from app.services.dependency_service import would_create_cycle
from app.services.task_assignment_notifier import notify_task_assigned, notify_group_new_task
from app.services.risk_alert_service import RiskAlertService
from app.modules.tasks.schemas import TaskCreateIn, TaskUpdateIn

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _parse_date(value: object) -> Optional[date]:
    """Chuyển chuỗi ISO ('YYYY-MM-DD' hoặc datetime đầy đủ) thành date object.
    asyncpg yêu cầu bind date object cho cột DATE, không nhận chuỗi (DataError).
    Trả None cho giá trị rỗng để clear cột."""
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()

_VALID_TRANSITIONS = {
    "TODO": {"IN_PROGRESS", "CANCELLED"},
    "IN_PROGRESS": {"DONE", "TODO", "CANCELLED"},
    "DONE": {"IN_PROGRESS"},
    "CANCELLED": set(),
}

def _normalize_task_status(raw: object) -> str:
    status = str(raw or "").strip().upper()
    if status in {"PLAN", "PLANNED"}:
        return "TODO"
    if status in {"REVIEW", "IN_REVIEW"}:
        return "DONE"
    return status

_SELECT_TASK = """
    SELECT t.id, t.name, t.status, t.priority, t.deadline, t.end_at,
           t.description, t.result, t.issues,
           t.total_hours,
           t.project_id, t.assignee_id, t.milestone_id, t.currency_id,
           t.created_at, t.updated_at,
           u.full_name AS assignee_full_name, u.avatar_url AS assignee_avatar_url,
           m.name AS milestone_name,
           COALESCE((
               SELECT json_agg(json_build_object('id', tg.id, 'name', tg.name, 'color', tg.color)
                               ORDER BY tg.name)
               FROM task_tags tt JOIN tags tg ON tg.id = tt.tag_id
               WHERE tt.task_id = t.id
                 -- Tag riêng: chỉ chủ thấy. :viewer_id BẮT BUỘC bind ở mọi nơi chạy _SELECT_TASK.
                 AND (tg.owner_user_id IS NULL OR tg.owner_user_id = :viewer_id)
           ), '[]'::json) AS tags,
           -- PHẢI ở cuối SELECT: _row_to_dict đọc theo chỉ số r[N]; chèn giữa sẽ lệch tags/assignee.
           (SELECT COUNT(*) FROM task_blockers b
            WHERE b.task_id = t.id AND b.resolved_at IS NULL) AS open_blockers,
           t.code,
           -- dependsOn: các task mà task này phụ thuộc (B). PHẢI ở cuối (đọc theo r[N]).
           COALESCE((
               SELECT json_agg(json_build_object('id', dt.id, 'name', dt.name,
                                                  'code', dt.code, 'status', dt.status::text))
               FROM task_dependencies d JOIN tasks dt ON dt.id = d.depends_on_task_id
               WHERE d.blocked_task_id = t.id
           ), '[]'::json) AS depends_on,
           -- blocks: các task phụ thuộc task này (A).
           COALESCE((
               SELECT json_agg(json_build_object('id', bt.id, 'name', bt.name, 'code', bt.code))
               FROM task_dependencies d JOIN tasks bt ON bt.id = d.blocked_task_id
               WHERE d.depends_on_task_id = t.id
           ), '[]'::json) AS blocks
    FROM tasks t
    LEFT JOIN users u ON u.id = t.assignee_id
    LEFT JOIN milestones m ON m.id = t.milestone_id
"""


def _is_privileged(current_user: dict) -> bool:
    return current_user.get("role") in ("MANAGER", "ADMIN") or current_user.get("isSuperAdmin")


async def _ensure_can_modify_task(db: AsyncSession, current_user: dict, assignee_id) -> None:
    """MANAGER/ADMIN sửa được mọi task; MEMBER/VIEWER chỉ sửa task được assign cho mình."""
    if _is_privileged(current_user):
        return
    if assignee_id is not None and assignee_id == current_user["id"]:
        return
    raise HTTPException(status_code=403, detail="Không có quyền thao tác task này")


def _row_to_dict(r) -> dict:
    return {
        "id": r[0], "name": r[1], "status": r[2], "priority": r[3],
        "deadline": r[4].isoformat() if r[4] else None,
        "endAt": r[5].isoformat() if r[5] else None,
        "description": r[6], "result": r[7], "issues": r[8],
        "totalHours": r[9],
        "projectId": r[10], "assigneeId": r[11],
        "milestoneId": r[12], "currencyId": r[13],
        "createdAt": r[14].isoformat(), "updatedAt": r[15].isoformat(),
        # assignee nested object is only present on rows from _SELECT_TASK
        # (which LEFT JOINs users). RETURNING-based rows omit it.
        "assignee": (
            {"id": r[11], "fullName": r[16], "avatarUrl": r[17]}
            if len(r) > 16 and r[11] is not None else None
        ),
        "milestone": (
            {"id": r[12], "name": r[18]}
            if len(r) > 18 and r[12] is not None else None
        ),
        # tags là json array (asyncpg trả chuỗi json) -> parse về list dict.
        "tags": (
            (json.loads(r[19]) if isinstance(r[19], str) else (r[19] or []))
            if len(r) > 19 else []
        ),
        # Số blocker chưa gỡ (open). Chỉ có ở row từ _SELECT_TASK; row RETURNING
        # (create/update/transition) ngắn hơn -> mặc định 0.
        "blockerCount": (r[20] if len(r) > 20 else 0),
        # Mã hiển thị (vd MTL-T001). Chỉ có ở row từ _SELECT_TASK; row RETURNING
        # ngắn hơn -> None (caller re-read qua _SELECT_TASK để hydrate).
        "code": (r[21] if len(r) > 21 else None),
        # Phụ thuộc: dependsOn = task này chờ (B); blocks = task chờ nó (A).
        # Chỉ có ở row từ _SELECT_TASK; RETURNING ngắn hơn -> [].
        "dependsOn": (
            (json.loads(r[22]) if isinstance(r[22], str) else (r[22] or []))
            if len(r) > 22 else []
        ),
        "blocks": (
            (json.loads(r[23]) if isinstance(r[23], str) else (r[23] or []))
            if len(r) > 23 else []
        ),
    }


async def _fetch_task_dict(task_id: int, db: AsyncSession, viewer_id: int) -> dict:
    """Re-fetch a task via _SELECT_TASK so the response includes the nested
    assignee object (RETURNING rows from INSERT/UPDATE don't join users).

    viewer_id: để lọc tag riêng (chỉ chủ thấy) trong _SELECT_TASK.
    """
    row = (await db.execute(
        text(f"{_SELECT_TASK} WHERE t.id = :tid"), {"tid": task_id, "viewer_id": viewer_id},
    )).fetchone()
    return _row_to_dict(row)


async def _recompute_milestone(milestone_id: int, db: AsyncSession):
    await db.execute(
        text("""
            UPDATE milestones SET
                done_count = (
                    SELECT COUNT(*) FROM tasks
                    WHERE milestone_id = :mid AND status = 'DONE'::"TaskStatus"
                ),
                completion_pct = (
                    SELECT CASE WHEN COUNT(*) = 0 THEN 0
                    ELSE ROUND(COUNT(*) FILTER (WHERE status = 'DONE'::"TaskStatus") * 100.0 / COUNT(*))
                    END FROM tasks WHERE milestone_id = :mid
                ),
                updated_at = NOW()
            WHERE id = :mid
        """),
        {"mid": milestone_id},
    )


@router.get("")
async def list_tasks(
    project_id: Optional[int] = Query(default=None, alias="projectId"),
    status: Optional[str] = Query(default=None),
    assignee_id: Optional[int] = Query(default=None, alias="assigneeId"),
    milestone_id: Optional[int] = Query(default=None, alias="milestoneId"),
    tag_id: Optional[int] = Query(default=None, alias="tagId"),
    tag_ids: Optional[list[int]] = Query(default=None, alias="tagIds"),
    priority: Optional[str] = Query(default=None),
    deadline_from: Optional[str] = Query(default=None, alias="deadlineFrom"),
    deadline_to: Optional[str] = Query(default=None, alias="deadlineTo"),
    q: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500, alias="pageSize"),
    sort: Optional[str] = Query(default=None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE TRUE"
    params: dict = {}
    # MEMBER/VIEWER chỉ thấy task thuộc project mình tham gia.
    if is_restricted(current_user):
        where += f" AND {project_access_exists_sql('t.project_id')}"
        params["access_uid"] = current_user["id"]
    if project_id:
        where += " AND t.project_id = :pid"; params["pid"] = project_id
    if status:
        status = _normalize_task_status(status)
        where += ' AND t.status = CAST(:status AS "TaskStatus")'; params["status"] = status
    if priority:
        where += ' AND t.priority = CAST(:priority AS "Priority")'; params["priority"] = priority
    if assignee_id:
        where += " AND t.assignee_id = :aid"; params["aid"] = assignee_id
    if milestone_id:
        where += " AND t.milestone_id = :mid"; params["mid"] = milestone_id
    # Lọc đa nhãn (OR): task khớp nếu mang ÍT NHẤT 1 trong các nhãn. Gộp cả tagId lẻ
    # (tương thích cũ) vào danh sách.
    all_tag_ids = list(tag_ids or [])
    if tag_id and tag_id not in all_tag_ids:
        all_tag_ids.append(tag_id)
    if all_tag_ids:
        where += (" AND EXISTS (SELECT 1 FROM task_tags tt WHERE tt.task_id = t.id "
                  "AND tt.tag_id = ANY(:tag_ids))")
        params["tag_ids"] = all_tag_ids
    if deadline_from:
        where += " AND t.deadline >= :dfrom"; params["dfrom"] = _parse_date(deadline_from)
    if deadline_to:
        where += " AND t.deadline <= :dto"; params["dto"] = _parse_date(deadline_to)
    if q:
        where += " AND t.name ILIKE :q"; params["q"] = f"%{q}%"

    order_by = "t.deadline NULLS LAST, t.priority DESC"
    if sort == "updatedAt:desc":
        order_by = "t.updated_at DESC"
    elif sort == "updatedAt:asc":
        order_by = "t.updated_at ASC"
    # Đếm tổng (cùng WHERE) để FE phân trang đúng; chỉ cần FROM tasks t.
    total = (await db.execute(
        text(f"SELECT COUNT(*) FROM tasks t {where}"), params,
    )).scalar() or 0

    params["limit"] = page_size
    params["offset"] = (page - 1) * page_size
    params["viewer_id"] = current_user["id"]  # lọc tag riêng theo người xem
    rows = (await db.execute(
        text(f"{_SELECT_TASK} {where} ORDER BY {order_by} LIMIT :limit OFFSET :offset"),
        params,
    )).fetchall()
    return {
        "data": [_row_to_dict(r) for r in rows],
        "meta": {"total": int(total), "page": page, "pageSize": page_size},
    }


@router.post("", status_code=201)
@router.post("/by-project/{project_id}", status_code=201)
async def create_task(
    body: TaskCreateIn,
    background_tasks: BackgroundTasks,
    project_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not _is_privileged(current_user):
        raise HTTPException(status_code=403, detail="Chỉ quản lý mới được tạo task")

    # Validate ở biên xong → dùng dict cho phần thân giữ nguyên.
    body = body.model_dump()
    target_project_id = project_id or body.get("projectId")
    if not target_project_id:
        raise HTTPException(status_code=422, detail="Thiếu projectId")
    project_row = (await db.execute(
        text("SELECT company_id FROM projects WHERE id = :pid"),
        {"pid": target_project_id},
    )).fetchone()
    if not project_row:
        raise HTTPException(status_code=404, detail="Project không tồn tại")

    seq, code = await next_task_code(target_project_id, db)
    row = (await db.execute(
        text("""
            INSERT INTO tasks (
                name, status, priority, deadline, end_at, description,
                project_id, assignee_id, milestone_id, currency_id, company_id,
                seq, code, updated_at
            ) VALUES (
                :name, COALESCE(:status, 'TODO')::"TaskStatus",
                COALESCE(:priority, 'MEDIUM')::"Priority",
                :deadline, :end_at, :description,
                :project_id, :assignee_id, :milestone_id, :currency_id, :company_id,
                :seq, :code, NOW()
            )
            RETURNING id, name, status, priority, deadline, end_at,
                      description, result, issues, total_hours,
                      project_id, assignee_id, milestone_id, currency_id,
                      created_at, updated_at
        """),
        {
            "name": body["name"], "status": _normalize_task_status(body.get("status")) if body.get("status") else None, "priority": body.get("priority"),
            "deadline": _parse_date(body.get("deadline")), "end_at": _parse_date(body.get("endAt")),
            "description": body.get("description"),
            "project_id": target_project_id,
            "assignee_id": body.get("assigneeId"),
            "milestone_id": body.get("milestoneId"),
            "currency_id": body.get("currencyId"),
            "company_id": project_row[0],
            "seq": seq, "code": code,
        },
    )).fetchone()

    if row[12]:  # milestone_id
        await _recompute_milestone(row[12], db)
        await db.execute(
            text("UPDATE milestones SET task_count = task_count + 1 WHERE id = :mid"),
            {"mid": row[12]},
        )

    await db.commit()

    if row[11]:  # assignee_id — báo cho người được giao (Gapo DM + in-app), chạy nền
        background_tasks.add_task(
            notify_task_assigned,
            task_id=row[0],
            assignee_id=row[11],
            actor_id=current_user["id"],
        )

    # Đăng tin giao việc vào group dự án (best-effort, tự bỏ qua nếu project chưa
    # liên kết group Gapo). Tách riêng để gửi cả khi task chưa có assignee.
    background_tasks.add_task(
        notify_group_new_task,
        task_id=row[0],
        actor_id=current_user["id"],
    )
    # Near-real-time: task mới có thể khiến project at-risk (vd tạo task đã quá hạn).
    background_tasks.add_task(RiskAlertService.trigger_for_project, row[10])

    return await _fetch_task_dict(row[0], db, current_user["id"])


@router.get("/overdue")
async def overdue_tasks(
    project_id: Optional[int] = Query(default=None, alias="projectId"),
    days: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE t.deadline < CURRENT_DATE AND t.status <> 'DONE'::\"TaskStatus\""
    params: dict = {"limit": limit}
    if project_id:
        where += " AND t.project_id = :pid"; params["pid"] = project_id
    if days:
        where += " AND t.deadline >= CURRENT_DATE - (:days * INTERVAL '1 day')"; params["days"] = days

    params["viewer_id"] = agent_user["id"]  # lọc tag riêng theo người xem
    rows = (await db.execute(
        text(f"{_SELECT_TASK} {where} ORDER BY t.deadline LIMIT :limit"),
        params,
    )).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.get("/stale")
async def stale_tasks(
    project_id: Optional[int] = Query(default=None, alias="projectId"),
    days_since_update: int = Query(default=7, alias="daysSinceUpdate"),
    limit: int = Query(default=50, ge=1, le=500),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE t.status NOT IN ('DONE'::\"TaskStatus\") AND t.updated_at < NOW() - INTERVAL '1 day' * :days"
    params: dict = {"days": days_since_update, "limit": limit}
    if project_id:
        where += " AND t.project_id = :pid"; params["pid"] = project_id

    params["viewer_id"] = agent_user["id"]  # lọc tag riêng theo người xem
    rows = (await db.execute(
        text(f"{_SELECT_TASK} {where} ORDER BY t.updated_at LIMIT :limit"),
        params,
    )).fetchall()
    return [_row_to_dict(r) for r in rows]


@router.get("/hygiene")
async def tasks_hygiene(
    project_id: Optional[int] = Query(default=None, alias="projectId"),
    stale_days: int = Query(default=14, alias="staleDays"),
    agent_user: dict = Depends(get_agent_user),
    db: AsyncSession = Depends(get_db),
):
    params: dict = {"stale_days": stale_days}
    base = "WHERE t.status <> 'DONE'::\"TaskStatus\""
    if project_id:
        base += " AND t.project_id = :pid"; params["pid"] = project_id

    no_assignee = (await db.execute(
        text(f"SELECT COUNT(*) FROM tasks t {base} AND t.assignee_id IS NULL"), params
    )).scalar()
    no_deadline = (await db.execute(
        text(f"SELECT COUNT(*) FROM tasks t {base} AND t.deadline IS NULL"), params
    )).scalar()
    overdue = (await db.execute(
        text(f"SELECT COUNT(*) FROM tasks t {base} AND t.deadline < CURRENT_DATE"), params
    )).scalar()
    stale = (await db.execute(
        text(f"SELECT COUNT(*) FROM tasks t {base} AND t.updated_at < NOW() - INTERVAL '1 day' * :stale_days"), params
    )).scalar()

    return {"noAssignee": no_assignee, "noDeadline": no_deadline, "overdue": overdue, "stale": stale}


@router.get("/candidates")
async def task_candidates(
    project_id: int = Query(alias="projectId"),
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=8, ge=1, le=20),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Task gợi ý để log worklog: ưu tiên task của chính user -> deadline gần ->
    vừa cập nhật, loại task DONE. Dùng cho quick-add trên web (giảm friction tìm
    task). Cùng logic với menu check-in Gapo (list_task_candidates).

    ĐẶT TRƯỚC route /{task_id} để FastAPI không match "candidates" thành id.
    """
    uid = current_user["id"]
    # MEMBER/VIEWER chỉ xem được dự án mình có quyền (chống IDOR), giống GET /tasks.
    if is_restricted(current_user):
        ok = (await db.execute(
            text(f"SELECT 1 WHERE {project_access_exists_sql(':pid')}"),
            {"pid": project_id, "access_uid": uid},
        )).fetchone()
        if not ok:
            raise HTTPException(status_code=403, detail="Không có quyền truy cập dự án này")

    params: dict = {"pid": project_id, "uid": uid, "lim": limit}
    q_clause = ""
    if q:
        q_clause = "AND name ILIKE :q"
        params["q"] = f"%{q}%"
    rows = (await db.execute(text(f"""
        SELECT id, name, status::text, deadline, assignee_id
        FROM tasks
        WHERE project_id = :pid AND status::text <> 'DONE' {q_clause}
        ORDER BY
          CASE WHEN assignee_id = :uid THEN 0 ELSE 1 END,
          deadline ASC NULLS LAST,
          updated_at DESC
        LIMIT :lim
    """), params)).fetchall()
    return {"data": [
        {"id": r[0], "name": r[1], "status": r[2],
         "deadline": r[3].isoformat() if r[3] else None,
         "assigneeId": r[4], "mine": r[4] == uid}
        for r in rows
    ]}


@router.get("/{task_id}")
async def get_task(
    task_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE t.id = :tid"
    params: dict = {"tid": task_id, "viewer_id": current_user["id"]}
    if is_restricted(current_user):
        where += f" AND {project_access_exists_sql('t.project_id')}"
        params["access_uid"] = current_user["id"]
    row = (await db.execute(
        text(f"{_SELECT_TASK} {where}"),
        params,
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task không tồn tại")
    return _row_to_dict(row)


# ── Lịch sử hoạt động của task (TaskActivityTimeline) ────────────────────────────
_ACTIVITY_STATUS_LABEL = {
    "TODO": "Cần làm", "IN_PROGRESS": "Đang làm",
    "CANCELLED": "Đã huỷ", "DONE": "Hoàn thành",
}
_ACTIVITY_LIMIT = 50


def _activity_status(s) -> str:
    return _ACTIVITY_STATUS_LABEL.get(str(s), str(s) if s else "?")


def _build_activity_event(tool, source, actor, args, result, at) -> dict:
    """Map 1 dòng (audit/blocker) -> sự kiện {at, type, icon, source, actor, summary}."""
    args = args or {}
    result = result or {}
    if tool == "task_progress_update":
        op, np = args.get("old_progress"), result.get("new_progress")
        os_, ns = args.get("old_status"), result.get("new_status")
        summary = f"Cập nhật tiến độ {op}% → {np}%"
        if os_ != ns:
            summary += f" ({_activity_status(os_)} → {_activity_status(ns)})"
        return {"type": "progress", "icon": "📈", "summary": summary,
                "source": source, "actor": actor, "at": at}
    if tool == "task_outcome_update":
        if args.get("kind") == "BLOCKER_REASON":
            summary = "Ghi lý do đang kẹt"
        else:
            parts = [p for p, v in (("kết quả", result.get("result_added")),
                                    ("khó khăn", result.get("issues_added"))) if v]
            summary = "Ghi " + (" & ".join(parts) or "ghi chú")
        return {"type": "outcome", "icon": "📝", "summary": summary,
                "source": source, "actor": actor, "at": at}
    if tool == "task_status_transition":
        summary = f"Đổi trạng thái: {_activity_status(args.get('old_status'))} → {_activity_status(result.get('new_status'))}"
        return {"type": "transition", "icon": "🔄", "summary": summary,
                "source": source, "actor": actor, "at": at}
    if tool == "create_task_from_chat":
        return {"type": "created", "icon": "✨", "summary": "Tạo task qua chat",
                "source": source, "actor": actor, "at": at}
    if tool == "blocker_open":
        return {"type": "blocker_open", "icon": "⛔",
                "summary": f"Báo blocker: {(args.get('desc') or '').strip() or '(không mô tả)'}",
                "source": source, "actor": actor, "at": at}
    if tool == "blocker_resolved":
        return {"type": "blocker_resolved", "icon": "✅", "summary": "Gỡ blocker",
                "source": source, "actor": actor, "at": at}
    return {"type": "other", "icon": "•", "summary": tool, "source": source, "actor": actor, "at": at}


@router.get("/{task_id}/activity")
async def task_activity(
    task_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dòng thời gian: đổi %/status, ghi kết quả/khó khăn, tạo/gỡ blocker (mới nhất trước)."""
    # Quyền: chỉ xem task user truy cập được (giống GET /{task_id}).
    where = "WHERE t.id = :tid"
    # :tid (int) cho cột task_id; :tid_txt (text) cho so sánh args_json->>'task_id'
    # — tránh asyncpg nhập nhằng kiểu khi dùng chung 1 param cho cả 2.
    params: dict = {"tid": task_id, "tid_txt": str(task_id), "lim": _ACTIVITY_LIMIT}
    if is_restricted(current_user):
        where += f" AND {project_access_exists_sql('t.project_id')}"
        params["access_uid"] = current_user["id"]
    exists = (await db.execute(text(f"SELECT 1 FROM tasks t {where}"), params)).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail="Task không tồn tại")

    rows = (await db.execute(text("""
        SELECT at, tool, source, actor, args_json, result_json FROM (
            SELECT a.created_at AS at, a.tool AS tool, a.source::text AS source,
                   u.full_name AS actor, a.args_json AS args_json, a.result_json AS result_json
            FROM agent_audit_log a
            LEFT JOIN users u ON u.id = (a.args_json->>'user_id')::int
            WHERE a.args_json->>'task_id' = :tid_txt
              AND a.tool IN ('task_progress_update','task_outcome_update',
                             'create_task_from_chat','task_status_transition')
            UNION ALL
            SELECT created_at, 'blocker_open', 'chat', NULL,
                   json_build_object('desc', description, 'sev', severity::text)::jsonb, NULL
            FROM task_blockers WHERE task_id = :tid
            UNION ALL
            SELECT resolved_at, 'blocker_resolved', 'system', NULL, NULL, NULL
            FROM task_blockers WHERE task_id = :tid AND resolved_at IS NOT NULL
        ) ev
        ORDER BY at DESC
        LIMIT :lim
    """), params)).fetchall()

    events = [
        _build_activity_event(
            r[1], r[2], r[3],
            r[4] if isinstance(r[4], dict) else (json.loads(r[4]) if r[4] else {}),
            r[5] if isinstance(r[5], dict) else (json.loads(r[5]) if r[5] else {}),
            r[0].isoformat() if r[0] else None,
        )
        for r in rows
    ]
    return {"events": events, "truncated": len(events) >= _ACTIVITY_LIMIT}


@router.patch("/{task_id}")
async def update_task(
    task_id: int,
    body: TaskUpdateIn,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # exclude_unset: chỉ giữ field client thực sự gửi → giữ ngữ nghĩa PATCH cũ
    # (vòng lặp `if js in body` bên dưới).
    body = body.model_dump(exclude_unset=True)
    existing = (await db.execute(
        text("SELECT id, milestone_id, assignee_id FROM tasks WHERE id = :tid"),
        {"tid": task_id},
    )).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Task không tồn tại")
    await _ensure_can_modify_task(db, current_user, existing[2])
    # MEMBER không được tự đổi người phụ trách (assignee) — chỉ MANAGER/ADMIN.
    if "assigneeId" in body and not _is_privileged(current_user):
        raise HTTPException(status_code=403, detail="Không có quyền đổi người phụ trách")

    field_map = {
        "name": "name", "description": "description", "result": "result", "issues": "issues",
        "deadline": "deadline", "endAt": "end_at",
        "assigneeId": "assignee_id", "milestoneId": "milestone_id", "currencyId": "currency_id",
    }
    _date_fields = {"deadline", "endAt"}
    sets, params = ["updated_at = NOW()"], {"tid": task_id}
    for js, col in field_map.items():
        if js in body:
            sets.append(f"{col} = :{js}")
            params[js] = _parse_date(body[js]) if js in _date_fields else body[js]
    if "status" in body:
        sets.append('status = CAST(:status AS "TaskStatus")'); params["status"] = _normalize_task_status(body["status"])
    if "priority" in body:
        sets.append('priority = CAST(:priority AS "Priority")'); params["priority"] = body["priority"]

    row = (await db.execute(
        text(f"""
            UPDATE tasks SET {', '.join(sets)} WHERE id = :tid
            RETURNING id, name, status, priority, deadline, end_at,
                      description, result, issues, total_hours,
                      project_id, assignee_id, milestone_id, currency_id,
                      created_at, updated_at
        """),
        params,
    )).fetchone()

    if row[12]:
        await _recompute_milestone(row[12], db)

    await db.commit()

    # Chỉ báo khi assignee ĐỔI sang người mới — sửa deadline/description của
    # task đã giao thì không nhắc lại. existing[2] là assignee cũ.
    if row[11] and row[11] != existing[2]:
        background_tasks.add_task(
            notify_task_assigned,
            task_id=task_id,
            assignee_id=row[11],
            actor_id=current_user["id"],
        )
    # Near-real-time: đổi status/deadline có thể khiến task quá hạn -> quét lại project.
    background_tasks.add_task(RiskAlertService.trigger_for_project, row[10])

    return await _fetch_task_dict(row[0], db, current_user["id"])


@router.delete("/{task_id}", status_code=204)
async def delete_task(
    task_id: int,
    current_user: dict = Depends(require_role("MANAGER", "ADMIN")),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("SELECT milestone_id FROM tasks WHERE id = :tid"),
        {"tid": task_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task không tồn tại")

    await db.execute(text("DELETE FROM tasks WHERE id = :tid"), {"tid": task_id})

    if row[0]:
        await db.execute(
            text("UPDATE milestones SET task_count = GREATEST(task_count - 1, 0) WHERE id = :mid"),
            {"mid": row[0]},
        )
        await _recompute_milestone(row[0], db)

    await db.commit()


@router.post("/{task_id}/transition")
async def transition_task(
    task_id: int,
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(
        text("SELECT status, milestone_id, assignee_id FROM tasks WHERE id = :tid"),
        {"tid": task_id},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task không tồn tại")
    await _ensure_can_modify_task(db, current_user, row[2])

    new_status = _normalize_task_status(body.get("status", ""))
    allowed = _VALID_TRANSITIONS.get(row[0], set())
    if new_status not in allowed:
        raise HTTPException(status_code=400, detail=f"Không thể chuyển từ {row[0]} sang {new_status}")

    updated = (await db.execute(
        text("""
            UPDATE tasks SET status = CAST(:status AS "TaskStatus"), updated_at = NOW()
            WHERE id = :tid
            RETURNING id, name, status, priority, deadline, end_at,
                      description, result, issues, total_hours,
                      project_id, assignee_id, milestone_id, currency_id,
                      created_at, updated_at
        """),
        {"tid": task_id, "status": new_status},
    )).fetchone()

    if row[1]:
        await _recompute_milestone(row[1], db)

    # Audit để Lịch sử task (TaskActivityTimeline) thấy cả lần đổi status từ web/UI.
    await db.execute(text("""
        INSERT INTO agent_audit_log (tool, args_json, result_json, source, created_at)
        VALUES ('task_status_transition', CAST(:args AS jsonb), CAST(:result AS jsonb),
                CAST('web' AS "AgentAuditSource"), NOW())
    """), {
        "args": json.dumps({"task_id": task_id, "user_id": current_user["id"], "old_status": row[0]}),
        "result": json.dumps({"new_status": new_status}),
    })

    await db.commit()
    background_tasks.add_task(RiskAlertService.trigger_for_project, updated[10])
    return await _fetch_task_dict(updated[0], db, current_user["id"])


@router.get("/{task_id}/blockers")
async def list_blockers(
    task_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        text("""
            SELECT b.id, b.task_id, b.severity, b.description, b.resolved_at, b.created_at
            FROM task_blockers b
            JOIN tasks t ON t.id = b.task_id
            WHERE b.task_id = :tid
            ORDER BY b.created_at DESC
        """),
        {"tid": task_id},
    )).fetchall()
    return [
        {
            "id": r[0], "taskId": r[1], "severity": r[2], "description": r[3],
            "resolvedAt": r[4].isoformat() if r[4] else None,
            "createdAt": r[5].isoformat(),
        }
        for r in rows
    ]


@router.post("/{task_id}/blockers", status_code=201)
@router.post("/{task_id}/blocker", status_code=201)
async def create_blocker(
    task_id: int,
    body: dict,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = (await db.execute(
        text("SELECT id, assignee_id, project_id FROM tasks WHERE id = :tid"),
        {"tid": task_id},
    )).fetchone()
    if not task:
        raise HTTPException(status_code=404, detail="Task không tồn tại")
    await _ensure_can_modify_task(db, current_user, task[1])

    row = (await db.execute(
        text("""
            INSERT INTO task_blockers (task_id, severity, description)
            VALUES (:tid, COALESCE(:severity, 'MED')::"BlockerSeverity", :desc)
            RETURNING id, task_id, severity, description, resolved_at, created_at
        """),
        {"tid": task_id, "severity": body.get("severity"), "desc": body["description"]},
    )).fetchone()
    await db.commit()
    # Near-real-time: thêm blocker -> task "blocked" -> đẩy rủi ro project lên ngay.
    background_tasks.add_task(RiskAlertService.trigger_for_project, task[2])
    return {
        "id": row[0], "taskId": row[1], "severity": row[2], "description": row[3],
        "resolvedAt": row[4], "createdAt": row[5].isoformat(),
    }


@router.patch("/blockers/{blocker_id}/resolve")
async def resolve_blocker(
    blocker_id: int,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Đánh dấu một blocker đã được gỡ (resolved_at = NOW())."""
    blocker = (await db.execute(
        text("""
            SELECT b.id, b.resolved_at, t.assignee_id, t.project_id
            FROM task_blockers b JOIN tasks t ON t.id = b.task_id
            WHERE b.id = :bid
        """),
        {"bid": blocker_id},
    )).fetchone()
    if not blocker:
        raise HTTPException(status_code=404, detail="Blocker không tồn tại")
    await _ensure_can_modify_task(db, current_user, blocker[2])
    if blocker[1] is not None:
        raise HTTPException(status_code=409, detail="Blocker này đã được gỡ rồi")

    row = (await db.execute(
        text("""
            UPDATE task_blockers SET resolved_at = NOW()
            WHERE id = :bid AND resolved_at IS NULL
            RETURNING id, task_id, severity, description, resolved_at, created_at
        """),
        {"bid": blocker_id},
    )).fetchone()
    await db.commit()
    # Gỡ blocker -> rủi ro project có thể giảm: quét lại near-real-time.
    background_tasks.add_task(RiskAlertService.trigger_for_project, blocker[3])
    return {
        "id": row[0], "taskId": row[1], "severity": row[2], "description": row[3],
        "resolvedAt": row[4].isoformat() if row[4] else None,
        "createdAt": row[5].isoformat(),
    }


# ── Phụ thuộc công việc (dependencies) ───────────────────────────────────────────

async def _list_depends_on(db: AsyncSession, task_id: int) -> list[dict]:
    """Danh sách task mà task_id phụ thuộc (B), kèm trạng thái."""
    rows = (await db.execute(
        text("""
            SELECT dt.id, dt.name, dt.code, dt.status::text
            FROM task_dependencies d JOIN tasks dt ON dt.id = d.depends_on_task_id
            WHERE d.blocked_task_id = :tid
            ORDER BY dt.deadline NULLS LAST, dt.id
        """),
        {"tid": task_id},
    )).fetchall()
    return [{"id": r[0], "name": r[1], "code": r[2], "status": r[3]} for r in rows]


@router.post("/{task_id}/dependencies", status_code=201)
async def add_dependency(
    task_id: int,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Đặt 'task_id phụ thuộc dependsOnTaskId' (task_id chỉ làm được sau khi kia xong)."""
    depends_on_id = body.get("dependsOnTaskId")
    if not depends_on_id:
        raise HTTPException(status_code=400, detail="Thiếu dependsOnTaskId.")
    if depends_on_id == task_id:
        raise HTTPException(status_code=400, detail="Task không thể phụ thuộc chính nó.")

    blocked = (await db.execute(
        text("SELECT project_id, assignee_id FROM tasks WHERE id = :tid"),
        {"tid": task_id},
    )).fetchone()
    if not blocked:
        raise HTTPException(status_code=404, detail="Task không tồn tại")
    await _ensure_can_modify_task(db, current_user, blocked[1])

    depends_on = (await db.execute(
        text("SELECT project_id FROM tasks WHERE id = :tid"),
        {"tid": depends_on_id},
    )).fetchone()
    if not depends_on:
        raise HTTPException(status_code=404, detail="Task phụ thuộc không tồn tại")
    if depends_on[0] != blocked[0]:
        raise HTTPException(status_code=400, detail="Chỉ liên kết phụ thuộc trong cùng dự án.")

    if await would_create_cycle(db, blocked_task_id=task_id, depends_on_task_id=depends_on_id):
        raise HTTPException(status_code=400, detail="Không thể tạo phụ thuộc vòng (A→B→…→A).")

    await db.execute(
        text("""
            INSERT INTO task_dependencies (blocked_task_id, depends_on_task_id, created_by)
            VALUES (:a, :b, :uid)
            ON CONFLICT (blocked_task_id, depends_on_task_id) DO NOTHING
        """),
        {"a": task_id, "b": depends_on_id, "uid": current_user["id"]},
    )
    await db.commit()
    return {"dependsOn": await _list_depends_on(db, task_id)}


@router.delete("/{task_id}/dependencies/{dep_task_id}", status_code=204)
async def remove_dependency(
    task_id: int,
    dep_task_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    blocked = (await db.execute(
        text("SELECT assignee_id FROM tasks WHERE id = :tid"),
        {"tid": task_id},
    )).fetchone()
    if not blocked:
        raise HTTPException(status_code=404, detail="Task không tồn tại")
    await _ensure_can_modify_task(db, current_user, blocked[0])

    await db.execute(
        text("""
            DELETE FROM task_dependencies
            WHERE blocked_task_id = :a AND depends_on_task_id = :b
        """),
        {"a": task_id, "b": dep_task_id},
    )
    await db.commit()
