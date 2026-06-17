"""Đổi người phụ trách task đã có qua chat."""
import asyncio
import json
import logging

from pydantic import BaseModel, Field
from sqlalchemy import text

from database import AsyncSessionLocal
from app.services.risk_alert_service import RiskAlertService
from app.services.task_assignment_notifier import notify_task_assigned
from ai_agent.shared.action_base import ActionAgentBase, ActionContext, ActionResult
from ai_agent.shared.entity_resolver import resolve_one, resolve_tasks, resolve_users

logger = logging.getLogger(__name__)


class ChangeAssigneeExtraction(BaseModel):
    task_ref: str = Field(default="")
    new_assignee: str = Field(default="")
    assign_to_self: bool = Field(default=False)


class ChangeAssigneeService(ActionAgentBase):
    name = "change_assignee"
    purpose = "change_assignee"
    extraction_model = ChangeAssigneeExtraction
    intent_desc = (
        "- change_assignee: GIAO LẠI một task ĐÃ CÓ cho người khác "
        '(vd "chuyển task [3.2] cho Thảo", "task X để Nam làm"). Khác create_task (tạo mới).'
    )
    system_prompt = """\
Bóc tách yêu cầu GIAO LẠI task đã có cho người khác.
- task_ref: mã [x.y] hoặc tên task cần chuyển. Bắt buộc.
- new_assignee: TÊN người nhận mới (bỏ kính ngữ). Rỗng nếu tự nhận.
- assign_to_self: true nếu "cho tôi/mình/em". Mặc định false.
Nếu không phải yêu cầu giao lại task đã có, để rỗng hết.
"""
    llm_unavailable_msg = "Mình chưa đổi người phụ trách qua chat được lúc này, bạn đổi trên web giúp nhé."

    async def _handle(self, ex: ChangeAssigneeExtraction, ctx: ActionContext) -> ActionResult:
        if not ex.task_ref.strip() or not (ex.new_assignee.strip() or ex.assign_to_self):
            return ActionResult(
                "need_info",
                'Bạn cho mình rõ: chuyển **task nào** cho **ai** nhé. Vd "chuyển task [3.2] cho Thảo".',
            )

        sid = ctx.sender_id_int
        if sid is None:
            return ActionResult("error", "Không xác định được người yêu cầu.")

        async with AsyncSessionLocal() as db:
            tasks = await resolve_tasks(db, ex.task_ref, sid)
            task, err = resolve_one(tasks, ex.task_ref, "task", "name")
            if err:
                return ActionResult("not_found" if not tasks else "ambiguous", err)

            if ex.assign_to_self and not ex.new_assignee.strip():
                row = (await db.execute(
                    text("SELECT id, full_name FROM users WHERE id = :id"),
                    {"id": sid},
                )).fetchone()
                if row is None:
                    return ActionResult("error", "Mình chưa xác định được tài khoản của bạn, bạn thử lại nhé.")
                new_user = {"user_id": row[0], "full_name": row[1]}
            else:
                users = await resolve_users(db, ex.new_assignee.strip(), sid)
                new_user, err = resolve_one(users, ex.new_assignee, "người", "full_name")
                if err:
                    return ActionResult("not_found" if not users else "ambiguous", err)

            await db.execute(text("""
                UPDATE tasks SET assignee_id = :assignee_id, updated_at = NOW()
                WHERE id = :task_id
            """), {"assignee_id": new_user["user_id"], "task_id": task["id"]})
            await db.execute(text("""
                INSERT INTO agent_audit_log (tool, args_json, source, created_at)
                VALUES ('change_assignee_from_chat', CAST(:args AS jsonb),
                        CAST('chat' AS "AgentAuditSource"), NOW())
            """), {"args": json.dumps({
                "task_id": task["id"],
                "assignee_id": new_user["user_id"],
                "project_id": task["project_id"],
                "by": sid,
            }, ensure_ascii=False)})
            await db.commit()

        asyncio.create_task(
            notify_task_assigned(task_id=task["id"], assignee_id=new_user["user_id"], actor_id=sid)
        )
        asyncio.create_task(RiskAlertService.trigger_for_project(task["project_id"]))

        code = f"[{task['code']}] " if task.get("code") else ""
        return ActionResult(
            "done",
            f"Đã chuyển task {code}**{task['name']}** cho **{new_user['full_name']}**. "
            "Mình đã báo bạn ấy rồi nhé.",
            entity_id=task["id"],
        )
