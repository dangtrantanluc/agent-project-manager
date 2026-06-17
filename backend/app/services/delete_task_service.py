"""Xoá task qua chat với bước xác nhận."""
import json
import logging

from pydantic import BaseModel, Field
from sqlalchemy import text

from database import AsyncSessionLocal
from app.services.task_progress_service import TASKCANCEL_PAYLOAD, TaskProgressService
from ai_agent.shared.action_base import ActionAgentBase, ActionContext, ActionResult
from ai_agent.shared.entity_resolver import is_privileged, resolve_one, resolve_tasks

logger = logging.getLogger(__name__)


class DeleteTaskExtraction(BaseModel):
    task_ref: str = Field(default="")


class DeleteTaskService(ActionAgentBase):
    name = "delete_task"
    needs_confirm = True
    purpose = "delete_task"
    extraction_model = DeleteTaskExtraction
    intent_desc = '- delete_task: XOÁ một task (vd "xoá task [3.2]", "huỷ task X").'
    system_prompt = """\
Bóc tách yêu cầu XOÁ task.
- task_ref: mã [x.y] hoặc tên task cần xoá.
Nếu không phải yêu cầu xoá task, để task_ref rỗng.
"""
    llm_unavailable_msg = "Mình chưa xoá task qua chat được lúc này, bạn xoá trên web giúp nhé."

    async def _handle(self, ex: DeleteTaskExtraction, ctx: ActionContext) -> ActionResult:
        if not ex.task_ref.strip():
            return ActionResult("need_info", "Bạn muốn xoá task nào? Cho mình mã [x.y] hoặc tên nhé.")

        async with AsyncSessionLocal() as db:
            tasks = await resolve_tasks(db, ex.task_ref, ctx.sender_id_int)
            task, err = resolve_one(tasks, ex.task_ref, "task", "name")
            if err:
                return ActionResult("not_found" if not tasks else "ambiguous", err)

        code = f"[{task['code']}] " if task.get("code") else ""
        return ActionResult(
            "need_confirm",
            f"Bạn chắc muốn xoá task {code}**{task['name']}**? Hành động này không hoàn tác.",
            entity_id=task["id"],
            menu=[
                {"label": "Xác nhận xoá", "payload": f"ACTDEL|task|{task['id']}"},
                {"label": "Huỷ", "payload": TASKCANCEL_PAYLOAD},
            ],
        )

    async def _do_delete(self, task_id: int, sender_id: int | str) -> dict:
        try:
            sid = int(sender_id)
        except (TypeError, ValueError):
            return {"message": "Không xác định được người yêu cầu."}

        async with AsyncSessionLocal() as db:
            role = (await db.execute(
                text("SELECT role FROM users WHERE id = :sid"),
                {"sid": sid},
            )).scalar()
            if not is_privileged(role):
                return {"message": self.forbidden_msg}

            row = (await db.execute(text("""
                SELECT id, name, milestone_id
                FROM tasks
                WHERE id = :task_id
            """), {"task_id": task_id})).fetchone()
            if not row:
                return {"message": "Task không còn tồn tại."}

            await db.execute(text("DELETE FROM tasks WHERE id = :task_id"), {"task_id": task_id})
            if row[2]:
                await db.execute(text("""
                    UPDATE milestones
                    SET task_count = GREATEST(task_count - 1, 0)
                    WHERE id = :milestone_id
                """), {"milestone_id": row[2]})
                await TaskProgressService._recompute_milestone(db, row[2])

            await db.execute(text("""
                INSERT INTO agent_audit_log (tool, args_json, source, created_at)
                VALUES ('delete_task_from_chat', CAST(:args AS jsonb),
                        CAST('chat' AS "AgentAuditSource"), NOW())
            """), {"args": json.dumps({"task_id": task_id, "by": sid}, ensure_ascii=False)})
            await db.commit()

        return {"message": f"Đã xoá task **{row[1]}**."}
