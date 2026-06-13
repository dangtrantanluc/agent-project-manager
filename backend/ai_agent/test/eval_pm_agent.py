"""Eval end-to-end PM agent: chạy bộ câu hỏi thực tế qua AgentMessageRouter (LLM + DB
thật) và kiểm chứng 2 luồng mới (cập nhật % + cảnh báo rủi ro có duyệt PM).

Chạy trong container backend (đủ env LLM + DB seeded), bắt buộc GAPO_DRY_RUN=true để
KHÔNG gửi tin Gapo thật:
    docker exec -e GAPO_DRY_RUN=true backend python ai_agent/test/eval_pm_agent.py

Self-cleanup: mọi dữ liệu eval ghi vào DB (follow-up, risk_alerts, audit, progress)
đều được hoàn tác ở cuối.
"""
import os as _os
# AN TOÀN: eval drive agent THẬT với user/thread thật — bắt buộc dry-run Gapo
# để không bắn tin nhắn thật cho đồng nghiệp khi chạy nhầm.
assert _os.getenv("GAPO_DRY_RUN", "").lower() in {"1", "true", "yes", "on"}, \
    "Phải chạy với GAPO_DRY_RUN=true (docker exec -e GAPO_DRY_RUN=true backend python ...)"


import asyncio
import sys
import time

sys.path.insert(0, "/app")

from sqlalchemy import text
from database import AsyncSessionLocal
from ai_agent.router.message_router import AgentMessageRouter
from app.services.risk_alert_service import RiskAlertService

ASKER = "608678190"          # Đặng Trần Tấn Lực (MANAGER, đã map Gapo)
PM_THREAD = "1779201401766"  # gapo_thread_id của PM ở trên
PROG_TASK_ID = 3             # "Hardening webhook token" — assignee = ASKER
RISK_PROJECT = 14            # "Phần mềm Quản lý Logistics" — 25 task overdue, owner = ASKER


def _trunc(s: str, n: int = 280) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n] + " […]"


class _FakeGapo:
    """Nuốt mọi lần gửi (eval không chạm mạng)."""
    def __init__(self):
        self.sent = []

    async def send_message(self, thread_id, text, **kw):
        self.sent.append((str(thread_id), text)); return {"ok": True}

    async def send_to_user(self, receiver_id, text, **kw):
        self.sent.append((str(receiver_id), text)); return {"ok": True}


# ── PART A: câu hỏi PM thực tế ────────────────────────────────────────────────
PART_A = [
    ("Chào hỏi", "Chào bạn, bạn giúp được gì cho mình?"),
    ("Truy vấn dữ liệu", "Dự án Logistics còn bao nhiêu task chưa hoàn thành?"),
    ("Task quá hạn", "Có những task nào của tôi đang quá hạn?"),
    ("Báo cáo tiến độ", "Cho mình báo cáo tiến độ tổng thể các dự án đang chạy."),
    ("Lập kế hoạch", "Giúp tôi lập kế hoạch cho dự án làm app mobile chấm công."),
    ("Workload", "Ai đang ôm nhiều task nhất hiện giờ?"),
    ("Nhắn hộ", "Nhắc giúp tôi anh Lực cập nhật tiến độ task nhé."),
    ("Xác nhận xong (không %)", "task webhook tôi làm xong rồi nhé"),
    ("Hỏi rủi ro", "Dự án nào đang có rủi ro trễ tiến độ không?"),
]


async def run_part_a(router):
    print("\n" + "=" * 78)
    print("PART A — Bộ câu hỏi PM thực tế (định tuyến + phản hồi của agent)")
    print("=" * 78)
    for i, (label, q) in enumerate(PART_A):
        async with AsyncSessionLocal() as db:
            t = time.perf_counter()
            try:
                reply = await router.handle_message(
                    message=q, user_id=ASKER, channel="gapo", thread_id="eval-A",
                    db=db, conversation_id=f"eval-A-{i}", correlation_id=f"evalA{i}",
                )
                ms = (time.perf_counter() - t) * 1000
                print(f"\n[{label}] ({ms:.0f}ms)  agent=<{reply.agent}>")
                print(f"  Hỏi: {q}")
                print(f"  Đáp: {_trunc(reply.answer)}")
            except Exception as e:
                print(f"\n[{label}] LỖI: {type(e).__name__}: {e}")


# ── PART B1: cập nhật tiến độ % (Luồng 3) ─────────────────────────────────────
async def run_part_b1(router):
    print("\n" + "=" * 78)
    print("PART B1 — Cập nhật tiến độ % từ chat (Luồng 3, ⑬⑭)")
    print("=" * 78)
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE tasks SET progress=0, status='TODO'::\"TaskStatus\" WHERE id=:t"),
                         {"t": PROG_TASK_ID})
        await db.execute(text("""
            INSERT INTO agent_follow_ups (task_id, user_id, channel, thread_id, question,
                status, correlation_id, asked_at, updated_at)
            VALUES (:t, :u, 'gapo', 'eval-prog', 'Task sắp đến hạn, bạn cập nhật giúp nhé?',
                'PENDING'::"FollowUpStatus", 'eval-prog-corr', NOW(), NOW())
        """), {"t": PROG_TASK_ID, "u": int(ASKER)})
        await db.commit()

    msg = "task hardening webhook tôi làm xong 70% rồi nhé"
    async with AsyncSessionLocal() as db:
        reply = await router.handle_message(
            message=msg, user_id=ASKER, channel="gapo", thread_id="eval-prog",
            db=db, conversation_id="eval-prog", correlation_id="evalB1",
        )
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text("SELECT progress, status::text FROM tasks WHERE id=:t"),
                                {"t": PROG_TASK_ID})).fetchone()
        audit = (await db.execute(text(
            "SELECT result_json FROM agent_audit_log WHERE tool='task_progress_update' "
            "ORDER BY id DESC LIMIT 1"))).fetchone()
    print(f"\n  Hỏi: {msg}")
    print(f"  Đáp: {_trunc(reply.answer)}  (agent=<{reply.agent}>)")
    print(f"  DB sau cập nhật: task #{PROG_TASK_ID} progress={row[0]} status={row[1]}")
    print(f"  audit_log mới nhất (task_progress_update): {audit[0] if audit else 'KHÔNG CÓ'}")
    ok = row[0] == 70 and row[1] == "IN_PROGRESS"
    print(f"  => {'PASS' if ok else 'FAIL'}: progress=70 & status=IN_PROGRESS")


# ── PART B2: cảnh báo rủi ro + duyệt PM (Luồng 4) ─────────────────────────────
async def run_part_b2(router):
    print("\n" + "=" * 78)
    print("PART B2 — Cảnh báo rủi ro at-risk + PM duyệt (Luồng 4, ⑰–⑳)")
    print("=" * 78)
    today = "2026-06-12"
    # Dọn dữ liệu cũ để eval lặp lại được.
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM risk_alerts WHERE correlation_id LIKE :c"),
                         {"c": f"risk:%:{today}"})
        await db.commit()

    # Quét + tạo cảnh báo PENDING (FakeGapo: không gửi thật, llm=None: tất định).
    svc = RiskAlertService(gapo=_FakeGapo(), llm=None)
    async with AsyncSessionLocal() as db:
        stats = await svc.scan_and_alert(db, today_iso=today)
    print(f"\n  scan_and_alert -> {stats}")

    # Lực sở hữu nhiều project at-risk -> nhiều cảnh báo cùng thread. Cô lập đúng
    # project 14 để demo end-to-end rõ ràng (state-gate vốn chọn cảnh báo MỚI NHẤT
    # của PM+thread — hành vi latest-wins khi có nhiều cảnh báo, xem ghi chú eval).
    async with AsyncSessionLocal() as db:
        await db.execute(text("""
            DELETE FROM risk_alerts
            WHERE thread_id=:th AND status='PENDING_PM_CONFIRMATION'
              AND project_id <> :p AND correlation_id LIKE :c
        """), {"th": PM_THREAD, "p": RISK_PROJECT, "c": f"risk:%:{today}"})
        await db.commit()
        alert = (await db.execute(text("""
            SELECT id, risk_level, risk_score, left(draft_message, 400)
            FROM risk_alerts WHERE project_id=:p AND status='PENDING_PM_CONFIRMATION'
            ORDER BY id DESC LIMIT 1"""), {"p": RISK_PROJECT})).fetchone()
    if not alert:
        print("  (không tạo được cảnh báo cho project 14 — bỏ qua B2)"); return
    print(f"  Cảnh báo PENDING #{alert[0]} | level={alert[1]} score={alert[2]}")
    print(f"  Nội dung dự thảo gửi PM:\n    {_trunc(alert[3], 400)}")

    # PM trả lời trong DM -> state-gate bắt được -> duyệt.
    pm_msg = "ok em, duyệt gửi cảnh báo này đi"
    async with AsyncSessionLocal() as db:
        reply = await router.handle_message(
            message=pm_msg, user_id=ASKER, channel="gapo", thread_id=PM_THREAD,
            db=db, conversation_id="eval-risk", correlation_id="evalB2",
        )
    async with AsyncSessionLocal() as db:
        st = (await db.execute(text("SELECT status FROM risk_alerts WHERE id=:i"),
                               {"i": alert[0]})).fetchone()
    print(f"\n  PM trả lời: {pm_msg}")
    print(f"  Đáp: {_trunc(reply.answer)}  (agent=<{reply.agent}>)")
    print(f"  DB: risk_alert #{alert[0]} status={st[0]}")
    print(f"  => {'PASS' if st[0] == 'APPROVED' else 'FAIL'}: status=APPROVED")

    # cleanup
    async with AsyncSessionLocal() as db:
        await db.execute(text("DELETE FROM risk_alerts WHERE correlation_id LIKE :c"),
                         {"c": f"risk:%:{today}"})
        await db.execute(text("DELETE FROM agent_audit_log WHERE tool IN ('risk_alert','risk_alert_decision') AND created_at::date = CURRENT_DATE"))
        await db.execute(text("DELETE FROM notifications WHERE type='risk_alert' AND created_at::date = CURRENT_DATE"))
        await db.commit()


async def cleanup_b1():
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE tasks SET progress=0, status='TODO'::\"TaskStatus\" WHERE id=:t"),
                         {"t": PROG_TASK_ID})
        await db.execute(text("DELETE FROM agent_follow_ups WHERE correlation_id='eval-prog-corr'"))
        await db.execute(text("DELETE FROM agent_audit_log WHERE tool='task_progress_update' AND created_at::date = CURRENT_DATE"))
        await db.commit()


async def main():
    only = sys.argv[1] if len(sys.argv) > 1 else "all"
    router = AgentMessageRouter()
    if only in ("all", "a"):
        await run_part_a(router)
    if only in ("all", "b1"):
        await run_part_b1(router)
        await cleanup_b1()
    if only in ("all", "b2"):
        await run_part_b2(router)
    print("\n" + "=" * 78)
    print("ĐÃ DỌN DỮ LIỆU EVAL. Hoàn tất.")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
