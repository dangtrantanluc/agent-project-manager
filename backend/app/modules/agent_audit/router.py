from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db

router = APIRouter(prefix="/agent/audit", tags=["agent-audit"])


def _row(r) -> dict:
    return {
        "id": r[0],
        "tool": r[1],
        "argsJson": r[2],
        "resultJson": r[3],
        "errorMessage": r[4],
        "durationMs": r[5],
        "correlationId": r[6],
        "source": r[7],
        "createdAt": r[8].isoformat(),
    }


@router.get("")
async def list_audit(
    tool: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    correlation_id: Optional[str] = Query(default=None, alias="correlationId"),
    has_error: Optional[bool] = Query(default=None, alias="hasError"),
    days_back: int = Query(default=7, ge=1, le=90, alias="daysBack"),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: Optional[int] = Query(default=None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    where = "WHERE created_at >= :cutoff"
    params: dict = {"cutoff": cutoff, "limit": limit}
    if tool:
        where += " AND tool = :tool"
        params["tool"] = tool
    if source:
        where += ' AND source = CAST(:source AS "AgentAuditSource")'
        params["source"] = source
    if correlation_id:
        where += " AND correlation_id = :corr"
        params["corr"] = correlation_id
    if has_error is not None:
        where += " AND error_message IS NOT NULL" if has_error else " AND error_message IS NULL"
    if cursor:
        where += " AND id < :cursor"
        params["cursor"] = cursor

    total = (await db.execute(text(f"SELECT COUNT(*) FROM agent_audit_log {where}"), params)).scalar()
    rows = (await db.execute(
        text(f"""
            SELECT id, tool, args_json, result_json, error_message, duration_ms,
                   correlation_id, source, created_at
            FROM agent_audit_log
            {where}
            ORDER BY id DESC
            LIMIT :limit
        """),
        params,
    )).fetchall()
    next_cursor = rows[-1][0] if len(rows) == limit else None
    return {"data": [_row(r) for r in rows], "meta": {"total": total, "cutoff": cutoff.isoformat(), "nextCursor": next_cursor}}


@router.get("/stats")
async def audit_stats(
    days_back: int = Query(default=7, ge=1, le=90, alias="daysBack"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days_back)
    totals = (await db.execute(
        text("""
            SELECT COUNT(*), COUNT(*) FILTER (WHERE error_message IS NOT NULL)
            FROM agent_audit_log WHERE created_at >= :start
        """),
        {"start": start},
    )).fetchone()
    by_tool = (await db.execute(
        text("""
            SELECT tool, COUNT(*), COUNT(*) FILTER (WHERE error_message IS NOT NULL),
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms),
                   percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)
            FROM agent_audit_log
            WHERE created_at >= :start
            GROUP BY tool
            ORDER BY COUNT(*) DESC
        """),
        {"start": start},
    )).fetchall()
    by_source = (await db.execute(
        text("""
            SELECT source, COUNT(*) FROM agent_audit_log
            WHERE created_at >= :start
            GROUP BY source
        """),
        {"start": start},
    )).fetchall()
    by_day = (await db.execute(
        text("""
            SELECT date_trunc('day', created_at)::date AS day,
                   COUNT(*), COUNT(*) FILTER (WHERE error_message IS NOT NULL)
            FROM agent_audit_log
            WHERE created_at >= :start
            GROUP BY 1 ORDER BY 1
        """),
        {"start": start},
    )).fetchall()
    top_corr = (await db.execute(
        text("""
            SELECT correlation_id, COUNT(*) FROM agent_audit_log
            WHERE created_at >= :start AND correlation_id IS NOT NULL
            GROUP BY correlation_id ORDER BY COUNT(*) DESC LIMIT 10
        """),
        {"start": start},
    )).fetchall()

    count = totals[0] or 0
    error_count = totals[1] or 0
    return {
        "data": {
            "window": {"start": start.isoformat(), "end": end.isoformat(), "days": days_back},
            "totals": {
                "count": count,
                "errorCount": error_count,
                "errorRate": round(error_count / count, 4) if count else 0,
            },
            "byTool": [
                {
                    "tool": r[0],
                    "count": r[1],
                    "errorCount": r[2],
                    "errorRate": round(r[2] / r[1], 4) if r[1] else 0,
                    "p50Ms": int(r[3]) if r[3] is not None else None,
                    "p95Ms": int(r[4]) if r[4] is not None else None,
                }
                for r in by_tool
            ],
            "bySource": {r[0]: r[1] for r in by_source},
            "byDay": [{"day": r[0].isoformat(), "count": r[1], "errorCount": r[2]} for r in by_day],
            "topCorrelations": [{"correlationId": r[0], "count": r[1]} for r in top_corr],
        }
    }
