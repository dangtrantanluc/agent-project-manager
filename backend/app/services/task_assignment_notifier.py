"""Thông báo cho assignee khi được giao task (Gapo DM + in-app).

Best-effort và chạy nền: lỗi gửi thông báo KHÔNG được làm fail request
tạo/sửa task. Luôn mở session DB riêng vì chạy sau khi request đã trả về.
"""
import logging

from sqlalchemy import text

from database import AsyncSessionLocal
from gapo.gapo_client import GapoClient
from ai_agent.notification.inapp_repository import create_notification

log = logging.getLogger(__name__)
_gapo = GapoClient()


async def notify_task_assigned(
    *,
    task_id: int,
    assignee_id: int,
    actor_id: int | None = None,
) -> None:
    # Tự giao cho chính mình thì không cần báo.
    if assignee_id is None or assignee_id == actor_id:
        return
    try:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                text("""
                    SELECT t.name, t.deadline, t.priority::text, p.name,
                           g.gapo_thread_id, g.gapo_user_id,
                           actor.full_name
                    FROM tasks t
                    JOIN projects p ON p.id = t.project_id
                    LEFT JOIN gapo_user_maps g ON g.user_id = :assignee_id
                    LEFT JOIN users actor ON actor.id = :actor_id
                    WHERE t.id = :task_id
                """),
                {"task_id": task_id, "assignee_id": assignee_id, "actor_id": actor_id},
            )).fetchone()
            if not row:
                return
            task_name, deadline, priority, project_name, thread_id, gapo_user_id, actor_name = row

            message = "\n".join(filter(None, [
                "**Bạn vừa được giao task mới**",
                "",
                f"- Task: {task_name}",
                f"- Dự án: {project_name}",
                f"- Deadline: {deadline}" if deadline else None,
                f"- Độ ưu tiên: {priority}" if priority else None,
                f"- Người giao: {actor_name}" if actor_name else None,
                "",
                "Bạn vào xem chi tiết và cập nhật tiến độ khi bắt đầu nhé.",
            ]))

            # In-app (bell + trang notifications) — create_notification tự nuốt lỗi.
            await create_notification(
                db,
                user_id=assignee_id,
                type="task_assigned",
                title=f"Bạn được giao task: {task_name}",
                body=f"Dự án {project_name}" + (f" — deadline {deadline}" if deadline else ""),
                link=f"/tasks/{task_id}",
            )

        # Gapo DM CHỦ ĐỘNG: ưu tiên receiver_id để Gapo định tuyến đúng thread 1-1
        # (POST vào thread_id cũ có thể trả 200 nhưng KHÔNG giao). thread_id chỉ
        # dùng khi thiếu gapo_user_id.
        if gapo_user_id:
            await _gapo.send_to_user(receiver_id=gapo_user_id, text=message)
        elif thread_id:
            await _gapo.send_message(thread_id=str(thread_id), text=message)
        else:
            log.info("assignee %s chưa liên kết Gapo — chỉ có in-app notification", assignee_id)
    except Exception:
        # Không bao giờ để lỗi notify lan ra ngoài.
        log.exception("notify_task_assigned failed task=%s assignee=%s", task_id, assignee_id)


async def notify_group_new_task(
    *,
    task_id: int,
    actor_id: int | None = None,
) -> None:
    """Đăng tin giao việc vào GROUP dự án trên Gapo (sơ đồ Luồng 1, bước ③).

    Best-effort: chỉ gửi khi project có gapo_thread_id (group đã liên kết). Không
    có group thì im lặng bỏ qua. Lỗi gửi không được làm fail request tạo task.
    """
    try:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                text("""
                    SELECT t.name, t.deadline, t.priority::text,
                           p.name AS project_name, p.gapo_thread_id,
                           u.full_name AS assignee_name,
                           actor.full_name AS actor_name
                    FROM tasks t
                    JOIN projects p ON p.id = t.project_id
                    LEFT JOIN users u ON u.id = t.assignee_id
                    LEFT JOIN users actor ON actor.id = :actor_id
                    WHERE t.id = :task_id
                """),
                {"task_id": task_id, "actor_id": actor_id},
            )).fetchone()
            if not row:
                return
            task_name, deadline, priority, project_name, group_thread, assignee_name, actor_name = row

        if not group_thread:
            log.info("project của task=%s chưa liên kết group Gapo — bỏ qua tin group", task_id)
            return

        message = "\n".join(filter(None, [
            "📋 **Công việc mới trong dự án**",
            "",
            f"- Task: {task_name}",
            f"- Dự án: {project_name}",
            f"- Phụ trách: {assignee_name}" if assignee_name else "- Phụ trách: (chưa giao)",
            f"- Deadline: {deadline}" if deadline else None,
            f"- Độ ưu tiên: {priority}" if priority else None,
            f"- Người giao: {actor_name}" if actor_name else None,
        ]))
        await _gapo.send_message(thread_id=str(group_thread), text=message)
    except Exception:
        log.exception("notify_group_new_task failed task=%s", task_id)
