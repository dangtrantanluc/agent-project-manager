from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


async def resolve_project_name(
    name_hint: str,
    db: AsyncSession,
) -> tuple[int | None, str | None, float]:
    """
    5-stage resolution pipeline for project names.

    Returns (project_id, project_name, confidence):
      1.0 = exact name match
      0.9 = project code match
      0.8 = ILIKE substring match
      0.7 = alias (tag) match
      0.6 = trigram fuzzy match (requires pg_trgm)
      0.0 = not found
    """
    if not name_hint or len(name_hint.strip()) < 2:
        return None, None, 0.0

    hint = name_hint.strip()

    # Stage 1: Exact match (case-insensitive)
    row = (await db.execute(
        text("SELECT id, name FROM projects WHERE LOWER(name) = LOWER(:hint) LIMIT 1"),
        {"hint": hint},
    )).fetchone()
    if row:
        return row[0], row[1], 1.0

    # Stage 2: Code match (e.g., "MTL", "WS-ABC")
    row = (await db.execute(
        text("SELECT id, name FROM projects WHERE LOWER(code) = LOWER(:hint) LIMIT 1"),
        {"hint": hint},
    )).fetchone()
    if row:
        return row[0], row[1], 0.9

    # Stage 3: ILIKE substring — shortest match wins (most specific)
    row = (await db.execute(
        text("""
            SELECT id, name FROM projects
            WHERE name ILIKE :hint_pct
            ORDER BY LENGTH(name) ASC
            LIMIT 1
        """),
        {"hint_pct": f"%{hint}%"},
    )).fetchone()
    if row:
        return row[0], row[1], 0.8

    # Stage 4: Alias match via tags (tag_type agnostic — any tag whose name matches)
    row = (await db.execute(
        text("""
            SELECT p.id, p.name FROM projects p
            JOIN tags t ON t.entity_id = p.id
            WHERE p.LOWER(t.name) = LOWER(:hint)
            LIMIT 1
        """),
        {"hint": hint},
    )).fetchone()
    if row:
        return row[0], row[1], 0.7

    # Stage 5: Trigram fuzzy (requires pg_trgm — silently skip if unavailable)
    try:
        row = (await db.execute(
            text("""
                SELECT id, name, similarity(name, :hint) AS sim FROM projects
                WHERE similarity(name, :hint) > 0.3
                ORDER BY sim DESC
                LIMIT 1
            """),
            {"hint": hint},
        )).fetchone()
        if row:
            return row[0], row[1], 0.6
    except Exception:
        pass  # pg_trgm not installed — graceful degradation

    return None, None, 0.0
