"""
Load test: 40 concurrent users complete full checkin + worklog flow within 10 minutes.

Flow per user:
  1. /checkin              → session created, project menu shown
  2. checkin:project:<id>  → project selected, task menu shown
  3. checkin:task:<id>     → task selected, worklog prompt shown
  4. <worklog text>        → worklog parsed + saved, confirmation menu
  5. checkin:done          → session COMPLETED

Run:
  cd /home/bbsw/agent-pm/backend
  python -m ai_agent.test.load_test_checkin

Requirements:
  - Backend DB running (docker-compose up db)
  - PYTHONPATH=/home/bbsw/agent-pm/backend
"""

import asyncio
import logging
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# ── Path setup ─────────────────────────────────────────────────────────────────
BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(BACKEND_ROOT, ".env"))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("load_test_checkin")

# ── Test constants ─────────────────────────────────────────────────────────────
NUM_USERS       = 40
DURATION_LIMIT  = 600          # 10 minutes hard ceiling
BASE_USER_ID    = 9_000_001    # fake user_id range (not in real DB)
BASE_THREAD_ID  = "91%06d"     # fake thread_id pattern
SLOT            = "manual"

# Project/task combos to randomly pick from (real IDs in DB)
PROJECT_TASK_PAIRS = [
    (1, 3),   # Gapo Test CRM Rollout / Hardening webhook token
    (1, 25),  # Gapo Test CRM Rollout / Test notification
    (2, 5),   # Bluebolt PM Portal Revamp / Bộ lọc tìm kiếm project
    (3, 9),   # GapoWork Agent Integration / Audit log cho webhook
    (3, 10),  # GapoWork Agent Integration / Fallback route khi LLM lỗi
    (4, 13),  # CRM Data Migration / Kế hoạch migration rehearsal
    (4, 14),  # CRM Data Migration / Ước lượng dữ liệu lỗi
]

WORKLOG_TEMPLATES = [
    "fix bug login 2h",
    "review code 1.5h",
    "họp standup 0.5h",
    "implement API endpoint 3h",
    "viết unit test 2.5h",
    "debug lỗi production 1h",
    "pair programming với dev khác 2h",
    "refactor module auth 3.5h",
    "update tài liệu 1h",
    "deploy lên staging 0.5h",
]

# ── Result tracking ────────────────────────────────────────────────────────────
@dataclass
class StepResult:
    name: str
    ok: bool
    duration_ms: float
    error: str = ""

@dataclass
class UserResult:
    user_index: int
    user_id: int
    steps: list[StepResult] = field(default_factory=list)
    total_ms: float = 0.0
    completed: bool = False
    error: str = ""

# ── Mock GapoClient ───────────────────────────────────────────────────────────
class MockGapoClient:
    """Intercepts Gapo sends — records calls, never hits real Gapo API."""
    def __init__(self):
        self.sent: list[dict] = []
        self.bot_id = "mock_bot"

    async def send_message(self, thread_id: str, text: str) -> dict:
        self.sent.append({"thread_id": thread_id, "text": text[:80]})
        return {"ok": True}

    async def send_text(self, thread_id, bot_id, text) -> dict:
        self.sent.append({"thread_id": thread_id, "text": str(text)[:80]})
        return {"ok": True}

    async def send_menu(self, thread_id: str, title: str, actions: list) -> bool:
        self.sent.append({"thread_id": thread_id, "title": title[:60], "actions": len(actions)})
        return True

# ── DB seed / cleanup ─────────────────────────────────────────────────────────
async def seed_test_users(n: int) -> list[dict]:
    """Insert n fake users + gapo_user_maps. Returns list of user dicts."""
    from database import AsyncSessionLocal
    from sqlalchemy import text

    users = []
    async with AsyncSessionLocal() as db:
        company_id = (await db.execute(text("SELECT id FROM companies ORDER BY id LIMIT 1"))).scalar()
        if not company_id:
            raise RuntimeError("No company found in DB — cannot seed test users")

        for i in range(n):
            uid = BASE_USER_ID + i
            thread_id = BASE_USER_ID + i * 100  # bigint in DB

            await db.execute(text("""
                INSERT INTO users (id, full_name, email, password_hash, company_id, active, created_at, updated_at)
                VALUES (:id, :name, :email, 'loadtest-nologin', :company_id, true, NOW(), NOW())
                ON CONFLICT (id) DO NOTHING
            """), {
                "id": uid,
                "name": f"LoadTest User {i+1:02d}",
                "email": f"loadtest{i+1:02d}@test.local",
                "company_id": company_id,
            })

            await db.execute(text("""
                INSERT INTO gapo_user_maps (user_id, gapo_user_id, gapo_thread_id, created_at)
                VALUES (:uid, :gid, :tid, NOW())
                ON CONFLICT (user_id) DO UPDATE SET gapo_thread_id = :tid
            """), {"uid": uid, "gid": uid, "tid": thread_id})

            users.append({"user_id": uid, "gapo_user_id": str(uid), "thread_id": str(thread_id)})

        await db.commit()
    logger.warning("[Setup] Seeded %d test users (id=%d..%d)", n, BASE_USER_ID, BASE_USER_ID + n - 1)
    return users


async def cleanup_test_users(n: int) -> None:
    from database import AsyncSessionLocal
    from sqlalchemy import text

    ids = list(range(BASE_USER_ID, BASE_USER_ID + n))
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM worklogs WHERE user_id = ANY(:ids)"), {"ids": ids})
        await db.execute(text("DELETE FROM checkin_sessions WHERE user_id = ANY(:ids)"), {"ids": ids})
        await db.execute(text("DELETE FROM gapo_user_maps WHERE user_id = ANY(:ids)"), {"ids": ids})
        await db.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": ids})
        await db.commit()
    logger.warning("[Cleanup] Removed %d test users", n)

# ── Single user simulation ────────────────────────────────────────────────────
async def run_user_session(
    user_index: int,
    user: dict,
    worklog_parser,
    start_barrier: asyncio.Event,
) -> UserResult:
    from database import AsyncSessionLocal
    from langchain_openai import ChatOpenAI
    from ai_agent.checkin.service import CheckinFlowService
    from ai_agent.checkin.constants import P_PROJECT, P_TASK, P_DONE

    result = UserResult(user_index=user_index, user_id=user["user_id"])
    gapo = MockGapoClient()

    project_id, task_id = random.choice(PROJECT_TASK_PAIRS)
    worklog_text = random.choice(WORKLOG_TEMPLATES)
    uid = user["user_id"]
    thread_id = user["thread_id"]
    gapo_user_id = user["gapo_user_id"]

    svc = CheckinFlowService(gapo=gapo, worklog_parser=worklog_parser)

    # Wait until all users are ready to fire simultaneously
    await start_barrier.wait()

    t_total = time.perf_counter()

    async def step(name: str, message: str) -> bool:
        t0 = time.perf_counter()
        ok = True
        err = ""
        try:
            async with AsyncSessionLocal() as db:
                await svc.handle_message(
                    db,
                    message_text=message,
                    gapo_user_id=gapo_user_id,
                    conversation_id=thread_id,
                    user_id=uid,
                )
        except Exception as exc:
            ok = False
            err = str(exc)
        ms = (time.perf_counter() - t0) * 1000
        result.steps.append(StepResult(name=name, ok=ok, duration_ms=ms, error=err))
        return ok

    # Step 1: trigger checkin
    if not await step("1_trigger", "checkin"):
        result.error = result.steps[-1].error
        return result

    # Step 2: select project
    if not await step("2_project", f"{P_PROJECT}{project_id}"):
        result.error = result.steps[-1].error
        return result

    # Step 3: select task
    if not await step("3_task", f"{P_TASK}{task_id}"):
        result.error = result.steps[-1].error
        return result

    # Step 4: enter worklog
    if not await step("4_worklog", worklog_text):
        result.error = result.steps[-1].error
        return result

    # Step 5: done
    if not await step("5_done", P_DONE):
        result.error = result.steps[-1].error
        return result

    result.total_ms = (time.perf_counter() - t_total) * 1000
    result.completed = all(s.ok for s in result.steps)
    return result

# ── Report ────────────────────────────────────────────────────────────────────
def print_report(results: list[UserResult], wall_ms: float) -> None:
    completed = [r for r in results if r.completed]
    failed    = [r for r in results if not r.completed]

    print("\n" + "=" * 65)
    print(f"  LOAD TEST REPORT — {NUM_USERS} users, 5-step checkin flow")
    print("=" * 65)
    print(f"  Wall time         : {wall_ms/1000:.2f}s")
    print(f"  Completed         : {len(completed)}/{len(results)}")
    print(f"  Failed            : {len(failed)}")
    if completed:
        totals = [r.total_ms for r in completed]
        print(f"  Total latency     : avg={statistics.mean(totals):.0f}ms  "
              f"p50={statistics.median(totals):.0f}ms  "
              f"p95={sorted(totals)[int(len(totals)*0.95)]:.0f}ms  "
              f"max={max(totals):.0f}ms")

    # Per-step stats
    step_names = ["1_trigger", "2_project", "3_task", "4_worklog", "5_done"]
    print()
    print(f"  {'Step':<12} {'OK':>4} {'FAIL':>5} {'avg ms':>8} {'p95 ms':>8} {'max ms':>8}")
    print("  " + "-" * 53)
    for sname in step_names:
        steps = [s for r in results for s in r.steps if s.name == sname]
        ok_steps  = [s for s in steps if s.ok]
        fail_steps = [s for s in steps if not s.ok]
        if ok_steps:
            ms_list = sorted([s.duration_ms for s in ok_steps])
            avg_ms  = statistics.mean(ms_list)
            p95_ms  = ms_list[int(len(ms_list) * 0.95)]
            max_ms  = max(ms_list)
        else:
            avg_ms = p95_ms = max_ms = 0.0
        print(f"  {sname:<12} {len(ok_steps):>4} {len(fail_steps):>5} "
              f"{avg_ms:>8.0f} {p95_ms:>8.0f} {max_ms:>8.0f}")

    # Errors
    if failed:
        print("\n  Errors:")
        for r in failed[:10]:
            print(f"    user#{r.user_index+1:02d}: {r.error[:100]}")
        if len(failed) > 10:
            print(f"    ... and {len(failed)-10} more")

    # Throughput
    if wall_ms > 0 and completed:
        tps = len(completed) / (wall_ms / 1000)
        print(f"\n  Throughput        : {tps:.1f} completed sessions/sec")
    print("=" * 65 + "\n")

# ── Main ──────────────────────────────────────────────────────────────────────
async def main() -> None:
    from langchain_openai import ChatOpenAI
    from ai_agent.checkin.worklog_parser.service import WorklogParserService

    print(f"\n[Load Test] Initializing {NUM_USERS} users, 5-step checkin flow...")

    # Seed users
    users = await seed_test_users(NUM_USERS)

    # Build shared LLM + parser (reused across sessions to avoid N init calls)
    llm = ChatOpenAI(
        model=os.getenv("MODEL_NAME"),
        api_key=os.getenv("API_KEY"),
        base_url=os.getenv("BASE_URL"),
        timeout=30,
        max_retries=1,
    )
    parser = WorklogParserService(llm=llm)

    # Barrier: all coroutines start simultaneously
    barrier = asyncio.Event()

    tasks = [
        asyncio.create_task(run_user_session(i, users[i], parser, barrier))
        for i in range(NUM_USERS)
    ]

    print(f"[Load Test] Firing {NUM_USERS} users simultaneously...\n")
    t_start = time.perf_counter()
    barrier.set()  # release all

    results: list[UserResult] = await asyncio.gather(*tasks, return_exceptions=False)
    wall_ms = (time.perf_counter() - t_start) * 1000

    # Inline progress per user
    for r in results:
        status = "OK" if r.completed else "FAIL"
        steps_ok = sum(1 for s in r.steps if s.ok)
        print(f"  user#{r.user_index+1:02d} [{status}] {steps_ok}/5 steps  "
              f"{r.total_ms:.0f}ms"
              + (f"  err: {r.error[:60]}" if r.error else ""))

    print_report(results, wall_ms)

    # Cleanup
    await cleanup_test_users(NUM_USERS)
    print("[Load Test] Done. Test data removed.")


if __name__ == "__main__":
    asyncio.run(main())
