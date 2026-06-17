"""Phụ thuộc công việc (task dependencies) — helper dùng chung.

"A phụ thuộc B" = task_dependencies(blocked_task_id=A, depends_on_task_id=B):
A chỉ làm được sau khi B (depends_on) DONE.

Người dùng set thủ công (API ở tasks/router). Các hàm ở đây phục vụ:
- agent quét cảnh báo (unfinished_blockers, newly_unblocked)
- chống chu trình khi thêm (would_create_cycle)
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def unfinished_blockers(db: AsyncSession, task_id: int) -> list[dict]:
    """Các task chặn (B) của task_id mà CHƯA DONE — task_id đang phải chờ chúng."""
    rows = (await db.execute(text("""
        SELECT dt.id, dt.name, dt.code, dt.status::text
        FROM task_dependencies d
        JOIN tasks dt ON dt.id = d.depends_on_task_id
        WHERE d.blocked_task_id = :tid AND dt.status::text <> 'DONE'
        ORDER BY dt.deadline NULLS LAST, dt.id
    """), {"tid": task_id})).fetchall()
    return [{"id": r[0], "name": r[1], "code": r[2], "status": r[3]} for r in rows]


async def newly_unblocked(db: AsyncSession, done_task_id: int) -> list[dict]:
    """Khi done_task_id (B) vừa DONE: các task A phụ thuộc B mà GIỜ không còn
    task chặn nào chưa xong (đã sẵn sàng để bắt đầu)."""
    rows = (await db.execute(text("""
        SELECT a.id, a.name, a.code
        FROM task_dependencies d
        JOIN tasks a ON a.id = d.blocked_task_id
        WHERE d.depends_on_task_id = :bid
          AND a.status::text <> 'DONE'
          -- A không còn bất kỳ task chặn nào chưa DONE
          AND NOT EXISTS (
              SELECT 1 FROM task_dependencies d2
              JOIN tasks b2 ON b2.id = d2.depends_on_task_id
              WHERE d2.blocked_task_id = a.id AND b2.status::text <> 'DONE'
          )
        ORDER BY a.id
    """), {"bid": done_task_id})).fetchall()
    return [{"id": r[0], "name": r[1], "code": r[2]} for r in rows]


async def would_create_cycle(db: AsyncSession, blocked_task_id: int, depends_on_task_id: int) -> bool:
    """True nếu thêm 'blocked phụ thuộc depends_on' tạo chu trình.

    Tạo cycle khi depends_on (B) đã (gián tiếp) phụ thuộc blocked (A): nếu từ B
    đi theo chuỗi depends_on mà tới được A thì A->B sẽ khép vòng.
    """
    row = (await db.execute(text("""
        WITH RECURSIVE chain(tid) AS (
            SELECT depends_on_task_id FROM task_dependencies
            WHERE blocked_task_id = CAST(:b AS integer)
            UNION
            SELECT d.depends_on_task_id FROM task_dependencies d
            JOIN chain c ON d.blocked_task_id = c.tid
        )
        SELECT 1 FROM chain WHERE tid = CAST(:a AS integer) LIMIT 1
    """), {"a": blocked_task_id, "b": depends_on_task_id})).fetchone()
    return row is not None


def format_blocker_warning(blockers: list[dict]) -> str:
    """Dòng cảnh báo mềm khi task đang phụ thuộc task chưa xong."""
    names = ", ".join(f"{b['code'] or ''} {b['name']}".strip() for b in blockers)
    return f"⚠️ Lưu ý: task này đang phụ thuộc {names} — chưa hoàn thành."


def format_unblocked_note(unblocked: list[dict]) -> str:
    """Dòng thông báo khi hoàn thành task chặn -> các task khác sẵn sàng."""
    names = ", ".join(f"{u['code'] or ''} {u['name']}".strip() for u in unblocked)
    return f"✅ {names} giờ đã sẵn sàng (không còn bị chặn)."
