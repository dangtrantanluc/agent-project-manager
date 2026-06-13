"""Tags (nhãn) — quản lý task & project tự do theo nhãn người dùng tự tạo.

Tag scope theo company; mọi thành viên trong company được tạo/sửa/gắn/gỡ (tinh thần
"tự do quản lý"). Gắn nhiều-nhiều với task và project qua bảng task_tags/project_tags.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db

router = APIRouter(tags=["tags"])


def _ensure_can_write(current_user: dict) -> None:
    """Mọi thành viên được tạo/gắn nhãn (tinh thần 'tự do quản lý'), trừ VIEWER —
    vai trò chỉ-đọc không được sửa bất kỳ dữ liệu nào."""
    if current_user.get("role") == "VIEWER" and not current_user.get("isSuperAdmin"):
        raise HTTPException(status_code=403, detail="VIEWER không có quyền sửa nhãn")


def _tag_row(r) -> dict:
    return {
        "id": r[0], "name": r[1], "color": r[2],
        "taskCount": int(r[3]) if len(r) > 3 and r[3] is not None else 0,
        "projectCount": int(r[4]) if len(r) > 4 and r[4] is not None else 0,
    }


_SELECT_TAG_COUNTS = """
    SELECT t.id, t.name, t.color,
           (SELECT COUNT(*) FROM task_tags tt WHERE tt.tag_id = t.id)    AS task_count,
           (SELECT COUNT(*) FROM project_tags pt WHERE pt.tag_id = t.id) AS project_count
    FROM tags t
"""


# ── CRUD tags ─────────────────────────────────────────────────────────────────
@router.get("/tags")
async def list_tags(
    q: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE t.company_id = :cid"
    params: dict = {"cid": current_user["companyId"]}
    if q:
        where += " AND t.name ILIKE :like"
        params["like"] = f"%{q}%"
    rows = (await db.execute(
        text(f"{_SELECT_TAG_COUNTS} {where} ORDER BY t.name ASC"), params,
    )).fetchall()
    return {"data": [_tag_row(r) for r in rows]}


@router.post("/tags", status_code=201)
async def create_tag(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_can_write(current_user)
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Tên nhãn không được rỗng")
    color = (body.get("color") or "#3b82f6").strip()
    try:
        row = (await db.execute(
            text("""
                INSERT INTO tags (name, color, company_id, created_by, updated_at)
                VALUES (:name, :color, :cid, :uid, NOW())
                RETURNING id, name, color
            """),
            {"name": name, "color": color, "cid": current_user["companyId"],
             "uid": current_user["id"]},
        )).fetchone()
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Nhãn '{name}' đã tồn tại")
    return {"data": _tag_row(row)}


@router.patch("/tags/{tag_id}")
async def update_tag(
    tag_id: int,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_can_write(current_user)
    existing = (await db.execute(
        text("SELECT id FROM tags WHERE id = :id AND company_id = :cid"),
        {"id": tag_id, "cid": current_user["companyId"]},
    )).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Nhãn không tồn tại")

    field_map = {"name": "name", "color": "color"}
    sets, params = ["updated_at = NOW()"], {"id": tag_id}
    for js, col in field_map.items():
        if js in body and body[js] is not None:
            value = str(body[js]).strip()
            if js == "name" and not value:
                raise HTTPException(status_code=422, detail="Tên nhãn không được rỗng")
            sets.append(f"{col} = :{js}")
            params[js] = value
    try:
        row = (await db.execute(
            text(f"UPDATE tags SET {', '.join(sets)} WHERE id = :id RETURNING id, name, color"),
            params,
        )).fetchone()
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Tên nhãn đã tồn tại")
    return {"data": _tag_row(row)}


@router.delete("/tags/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_can_write(current_user)
    row = (await db.execute(
        text("SELECT id FROM tags WHERE id = :id AND company_id = :cid"),
        {"id": tag_id, "cid": current_user["companyId"]},
    )).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Nhãn không tồn tại")
    # task_tags/project_tags tự gỡ nhờ ON DELETE CASCADE.
    await db.execute(text("DELETE FROM tags WHERE id = :id"), {"id": tag_id})
    await db.commit()


# ── Gắn tag cho TASK / PROJECT (set toàn bộ danh sách) ─────────────────────────
async def _set_entity_tags(
    db: AsyncSession, *, link_table: str, id_col: str, entity_id: int,
    tag_ids: list[int], company_id: int,
) -> list[dict]:
    """Đặt lại toàn bộ tag cho 1 thực thể. Chỉ nhận tag cùng company."""
    clean_ids = sorted({int(t) for t in (tag_ids or [])})
    if clean_ids:
        valid = (await db.execute(
            text("SELECT id FROM tags WHERE company_id = :cid AND id = ANY(:ids)"),
            {"cid": company_id, "ids": clean_ids},
        )).fetchall()
        valid_ids = {r[0] for r in valid}
        invalid = set(clean_ids) - valid_ids
        if invalid:
            raise HTTPException(status_code=422, detail=f"Nhãn không hợp lệ: {sorted(invalid)}")
    await db.execute(
        text(f"DELETE FROM {link_table} WHERE {id_col} = :eid"), {"eid": entity_id})
    for tid in clean_ids:
        await db.execute(
            text(f"INSERT INTO {link_table} ({id_col}, tag_id) VALUES (:eid, :tid)"),
            {"eid": entity_id, "tid": tid})
    await db.commit()
    rows = (await db.execute(
        text(f"""
            SELECT tg.id, tg.name, tg.color FROM {link_table} lt
            JOIN tags tg ON tg.id = lt.tag_id
            WHERE lt.{id_col} = :eid ORDER BY tg.name
        """), {"eid": entity_id},
    )).fetchall()
    return [{"id": r[0], "name": r[1], "color": r[2]} for r in rows]


@router.put("/tasks/{task_id}/tags")
async def set_task_tags(
    task_id: int,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_can_write(current_user)
    exists = (await db.execute(
        text("SELECT id FROM tasks WHERE id = :id AND company_id = :cid"),
        {"id": task_id, "cid": current_user["companyId"]},
    )).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail="Task không tồn tại")
    tags = await _set_entity_tags(
        db, link_table="task_tags", id_col="task_id", entity_id=task_id,
        tag_ids=body.get("tagIds", []), company_id=current_user["companyId"],
    )
    return {"data": tags}


@router.put("/projects/{project_id}/tags")
async def set_project_tags(
    project_id: int,
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ensure_can_write(current_user)
    exists = (await db.execute(
        text("SELECT id FROM projects WHERE id = :id AND company_id = :cid"),
        {"id": project_id, "cid": current_user["companyId"]},
    )).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail="Dự án không tồn tại")
    tags = await _set_entity_tags(
        db, link_table="project_tags", id_col="project_id", entity_id=project_id,
        tag_ids=body.get("tagIds", []), company_id=current_user["companyId"],
    )
    return {"data": tags}
