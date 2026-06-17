"""Human-readable entity codes (Jira-style).

Project keeps its existing ``code`` column as the prefix (e.g. ``MTL``).
Tasks and milestones get a per-project running ``seq`` plus a full ``code``::

    Task:      MTL-T001, MTL-T002, ...
    Milestone: MTL-M001, MTL-M002, ...

Sequences are handed out atomically by ``project_counters`` so concurrent
INSERTs never collide. Always call these helpers inside the SAME transaction as
the entity INSERT — if the INSERT rolls back, the counter bump rolls back too
(no skipped numbers).
"""

import re
import unicodedata

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_MAX_PREFIX_LEN = 8


def generate_project_prefix(name: str) -> str:
    """Derive an uppercase A–Z prefix from a project name.

    Multi-word names use the initials of each word ("Migration Tool" -> "MTL");
    single-word names use the first three letters ("Phoenix" -> "PHO").
    Vietnamese diacritics are stripped. Falls back to "PRJ" if nothing usable.
    """
    # Strip diacritics: "Dự án" -> "Du an"
    ascii_name = unicodedata.normalize("NFKD", name or "")
    ascii_name = ascii_name.encode("ascii", "ignore").decode("ascii")

    words = [w for w in re.split(r"\s+", ascii_name.strip()) if re.search(r"[A-Za-z]", w)]
    if not words:
        return "PRJ"

    if len(words) > 1:
        prefix = "".join(re.sub(r"[^A-Za-z]", "", w)[:1] for w in words)
    else:
        prefix = re.sub(r"[^A-Za-z]", "", words[0])[:3]

    prefix = prefix.upper()[:_MAX_PREFIX_LEN]
    return prefix or "PRJ"


async def ensure_unique_prefix(prefix: str, db: AsyncSession) -> str:
    """Return ``prefix`` if free, else append a numeric suffix (MTL, MTL2, ...)."""
    candidate = prefix
    n = 1
    while True:
        exists = (await db.execute(
            text("SELECT 1 FROM projects WHERE code = :c"),
            {"c": candidate},
        )).fetchone()
        if not exists:
            return candidate
        n += 1
        candidate = f"{prefix}{n}"


async def ensure_unique_entity_prefix(code: str, db: AsyncSession) -> str:
    """Mã hiển thị 3 ký tự cho task/milestone/worklog, suy từ ``code`` dự án.

    Lấy 3 chữ cái A–Z đầu của ``code`` (MTL-LOGISTICS -> MTL), làm DUY NHẤT toàn
    cục bằng cách thêm số khi trùng (BB, BB2, BB3...). Mã entity gồm prefix + seq,
    seq lại đếm theo từng dự án nên prefix phải duy nhất để mã không đụng nhau.
    """
    base = re.sub(r"[^A-Za-z]", "", code or "")[:3].upper() or "PRJ"
    candidate = base
    n = 1
    while True:
        exists = (await db.execute(
            text("SELECT 1 FROM projects WHERE entity_prefix = :c"),
            {"c": candidate},
        )).fetchone()
        if not exists:
            return candidate
        n += 1
        candidate = f"{base}{n}"


async def _next_seq(project_id: int, column: str, db: AsyncSession) -> int:
    """Atomically claim the next per-project seq for the given counter column."""
    # Upsert so projects created before the counter table still get numbered.
    row = (await db.execute(
        text(f"""
            INSERT INTO project_counters (project_id, {column})
            VALUES (:pid, 2)
            ON CONFLICT (project_id) DO UPDATE
                SET {column} = project_counters.{column} + 1
            RETURNING {column} - 1
        """),
        {"pid": project_id},
    )).scalar()
    return int(row)


async def _project_prefix(project_id: int, db: AsyncSession) -> str:
    """Prefix mã entity của dự án: ưu tiên ``entity_prefix`` (3 ký tự, duy nhất);
    fallback 3 chữ đầu của ``code`` cho dữ liệu cũ chưa backfill."""
    row = (await db.execute(
        text("SELECT entity_prefix, code FROM projects WHERE id = :pid"),
        {"pid": project_id},
    )).fetchone()
    if not row:
        return "PRJ"
    if row[0]:
        return row[0]
    return (re.sub(r"[^A-Za-z]", "", row[1] or "")[:3].upper() or "PRJ")


async def next_task_code(project_id: int, db: AsyncSession) -> tuple[int, str]:
    """Claim the next task seq + full code for a project, e.g. (7, 'MTL-T0007')."""
    seq = await _next_seq(project_id, "next_task_seq", db)
    prefix = await _project_prefix(project_id, db)
    return seq, f"{prefix}-T{seq:04d}"


async def reserve_task_codes(
    project_id: int, count: int, db: AsyncSession
) -> list[tuple[int, str]]:
    """Cấp `count` mã task liên tiếp bằng MỘT lần bump counter (chống N+1).

    Tương đương gọi ``next_task_code`` `count` lần nhưng chỉ 2 query thay vì 2·N.
    Bump nguyên tử nên các luồng đồng thời không trùng số.
    """
    if count <= 0:
        return []
    end_val = (await db.execute(
        text("""
            INSERT INTO project_counters (project_id, next_task_seq)
            VALUES (:pid, :n_plus_1)
            ON CONFLICT (project_id) DO UPDATE
                SET next_task_seq = project_counters.next_task_seq + :n
            RETURNING next_task_seq
        """),
        {"pid": project_id, "n_plus_1": count + 1, "n": count},
    )).scalar()
    end_val = int(end_val)
    prefix = await _project_prefix(project_id, db)
    start = end_val - count
    return [(s, f"{prefix}-T{s:04d}") for s in range(start, end_val)]


async def next_milestone_code(project_id: int, db: AsyncSession) -> tuple[int, str]:
    """Claim the next milestone seq + full code, e.g. (3, 'MTL-M0003')."""
    seq = await _next_seq(project_id, "next_ms_seq", db)
    prefix = await _project_prefix(project_id, db)
    return seq, f"{prefix}-M{seq:04d}"


async def next_worklog_code(project_id: int, db: AsyncSession) -> tuple[int, str]:
    """Claim the next worklog seq + full code, e.g. (5, 'MTL-W0005')."""
    seq = await _next_seq(project_id, "next_wl_seq", db)
    prefix = await _project_prefix(project_id, db)
    return seq, f"{prefix}-W{seq:04d}"
