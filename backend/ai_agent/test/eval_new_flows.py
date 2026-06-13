"""Eval end-to-end 3 luồng mới: push người khác, giao việc (create_task),
hoàn thành->DONE. Chạy trong container, GAPO_DRY_RUN=true, tự cleanup.

    docker exec -e GAPO_DRY_RUN=true backend python ai_agent/test/eval_new_flows.py
"""
import os as _os
# AN TOÀN: eval drive agent THẬT với user/thread thật — bắt buộc dry-run Gapo
# để không bắn tin nhắn thật cho đồng nghiệp khi chạy nhầm.
assert _os.getenv("GAPO_DRY_RUN", "").lower() in {"1", "true", "yes", "on"}, \
    "Phải chạy với GAPO_DRY_RUN=true (docker exec -e GAPO_DRY_RUN=true backend python ...)"


import asyncio
import sys

sys.path.insert(0, "/app")
from sqlalchemy import text
from database import AsyncSessionLocal
from ai_agent.router.message_router import AgentMessageRouter

LUC = "608678190"          # MANAGER
LUC_THREAD = "1779201401766"


def _trunc(s, n=240):
    return " ".join((s or "").split())[:n]


async def part_push(router):
    print("\n=== 1) PUSH người khác (trước đây nhầm task_update) ===")
    async with AsyncSessionLocal() as db:
        r = await router.handle_message(
            message="em push thảo hoàn thành deadline hôm nay đi",
            user_id=LUC, channel="gapo", thread_id="eval-push", db=db,
            conversation_id="eval-push", correlation_id="evp",
        )
    print(f"agent=<{r.agent}>  (mong đợi: notification)")
    print(f"Đáp: {_trunc(r.answer)}")


async def part_create(router):
    print("\n=== 2) GIAO VIỆC qua Gapo (create_task) ===")
    msg = "giao task Viết tài liệu API cho Thảo, dự án Logistics, deadline 2026-06-25, ưu tiên cao"
    async with AsyncSessionLocal() as db:
        r = await router.handle_message(
            message=msg, user_id=LUC, channel="gapo", thread_id="eval-create", db=db,
            conversation_id="eval-create", correlation_id="evc",
        )
    print(f"agent=<{r.agent}>  (mong đợi: create_task)")
    print(f"Đáp: {_trunc(r.answer)}")
    # kiểm DB + cleanup
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT id, name, priority::text, deadline, assignee_id FROM tasks "
            "WHERE name='Viết tài liệu API' ORDER BY id DESC LIMIT 1"))).fetchone()
        if row:
            print(f"DB: task #{row[0]} '{row[1]}' priority={row[2]} deadline={row[3]} assignee={row[4]}")
            await db.execute(text("DELETE FROM tasks WHERE id=:i"), {"i": row[0]})
            await db.execute(text("DELETE FROM agent_audit_log WHERE tool='create_task_from_chat' AND created_at::date=CURRENT_DATE"))
            await db.commit()
            print("=> PASS (đã tạo & cleanup)")
        else:
            print("=> FAIL: không thấy task được tạo")


async def part_done(router):
    print("\n=== 3) HOÀN THÀNH (không %) -> set DONE qua follow-up ===")
    TASK = 4  # IN_PROGRESS, assignee = Lực
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE tasks SET status='IN_PROGRESS'::\"TaskStatus\", progress=0 WHERE id=:t"), {"t": TASK})
        await db.execute(text("""
            INSERT INTO agent_follow_ups (task_id, user_id, channel, thread_id, question,
                status, correlation_id, asked_at, updated_at)
            VALUES (:t, :u, 'gapo', 'eval-done', 'q', 'PENDING'::"FollowUpStatus",
                    'eval-done-corr', NOW(), NOW())"""), {"t": TASK, "u": int(LUC)})
        await db.commit()
    async with AsyncSessionLocal() as db:
        r = await router.handle_message(
            message="task đó tôi đã xong rồi nhé", user_id=LUC, channel="gapo",
            thread_id="eval-done", db=db, conversation_id="eval-done", correlation_id="evd",
        )
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text("SELECT status::text, progress FROM tasks WHERE id=:t"), {"t": TASK})).fetchone()
    print(f"agent=<{r.agent}>")
    print(f"Đáp: {_trunc(r.answer)}")
    print(f"DB: task #{TASK} status={row[0]} progress={row[1]}")
    print(f"=> {'PASS' if row[0]=='DONE' and row[1]==100 else 'FAIL'}")
    # cleanup
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE tasks SET status='IN_PROGRESS'::\"TaskStatus\", progress=0 WHERE id=:t"), {"t": TASK})
        await db.execute(text("DELETE FROM agent_follow_ups WHERE correlation_id='eval-done-corr'"))
        await db.execute(text("DELETE FROM agent_audit_log WHERE tool='task_progress_update' AND created_at::date=CURRENT_DATE"))
        await db.commit()


async def main():
    router = AgentMessageRouter()
    await part_push(router)
    await part_create(router)
    await part_done(router)
    print("\n=== Hoàn tất, đã cleanup ===")


if __name__ == "__main__":
    asyncio.run(main())
