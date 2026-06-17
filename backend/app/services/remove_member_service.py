"""Gỡ thành viên khỏi dự án qua chat với bước xác nhận."""
import json
import logging

from pydantic import BaseModel, Field
from sqlalchemy import text

from database import AsyncSessionLocal
from app.services.task_progress_service import TASKCANCEL_PAYLOAD
from ai_agent.shared.action_base import ActionAgentBase, ActionContext, ActionResult
from ai_agent.shared.entity_resolver import (
    is_privileged,
    resolve_one,
    resolve_projects,
    resolve_users,
)

logger = logging.getLogger(__name__)


class RemoveMemberExtraction(BaseModel):
    member: str = Field(default="")
    project: str = Field(default="")


class RemoveMemberService(ActionAgentBase):
    name = "remove_member"
    needs_confirm = True
    purpose = "remove_member"
    extraction_model = RemoveMemberExtraction
    intent_desc = (
        '- remove_member: GỠ thành viên khỏi dự án (vd "bỏ Nam khỏi dự án Logistics"). '
        "Đối lập add_member."
    )
    system_prompt = """\
Bóc tách yêu cầu GỠ thành viên khỏi dự án.
- member: tên người cần gỡ.
- project: tên dự án.
Nếu không phải yêu cầu gỡ thành viên khỏi dự án, để rỗng.
"""
    llm_unavailable_msg = "Mình chưa gỡ thành viên qua chat được lúc này, bạn gỡ trên web giúp nhé."

    async def _handle(self, ex: RemoveMemberExtraction, ctx: ActionContext) -> ActionResult:
        if not ex.member.strip() or not ex.project.strip():
            return ActionResult("need_info", "Bạn cho mình rõ: gỡ **ai** khỏi **dự án nào** nhé.")

        sid = ctx.sender_id_int
        if sid is None:
            return ActionResult("error", "Không xác định được người yêu cầu.")

        async with AsyncSessionLocal() as db:
            users = await resolve_users(db, ex.member.strip(), sid)
            user, err = resolve_one(users, ex.member, "người", "full_name")
            if err:
                return ActionResult("not_found" if not users else "ambiguous", err)

            projects = await resolve_projects(db, ex.project.strip(), sid)
            project, err = resolve_one(projects, ex.project, "dự án", "name")
            if err:
                return ActionResult("not_found" if not projects else "ambiguous", err)

            member_row = (await db.execute(text("""
                SELECT id
                FROM members
                WHERE project_id = :project_id AND user_id = :user_id
            """), {"project_id": project["id"], "user_id": user["user_id"]})).fetchone()
            if not member_row:
                return ActionResult(
                    "exists",
                    f"**{user['full_name']}** không ở trong dự án **{project['name']}**.",
                )

        return ActionResult(
            "need_confirm",
            f"Bạn chắc muốn gỡ **{user['full_name']}** khỏi dự án **{project['name']}**?",
            entity_id=member_row[0],
            menu=[
                {"label": "Xác nhận gỡ", "payload": f"ACTDEL|member|{member_row[0]}"},
                {"label": "Huỷ", "payload": TASKCANCEL_PAYLOAD},
            ],
        )

    async def _do_remove(self, member_id: int, sender_id: int | str) -> dict:
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
                SELECT m.project_id, u.full_name, p.name
                FROM members m
                JOIN users u ON u.id = m.user_id
                JOIN projects p ON p.id = m.project_id
                WHERE m.id = :member_id
            """), {"member_id": member_id})).fetchone()
            if not row:
                return {"message": "Thành viên không còn trong dự án."}

            await db.execute(text("DELETE FROM members WHERE id = :member_id"), {"member_id": member_id})
            await db.execute(text("""
                UPDATE projects
                SET member_count = GREATEST(member_count - 1, 0), updated_at = NOW()
                WHERE id = :project_id
            """), {"project_id": row[0]})
            await db.execute(text("""
                INSERT INTO agent_audit_log (tool, args_json, source, created_at)
                VALUES ('remove_member_from_chat', CAST(:args AS jsonb),
                        CAST('chat' AS "AgentAuditSource"), NOW())
            """), {"args": json.dumps({
                "member_id": member_id,
                "project_id": row[0],
                "by": sid,
            }, ensure_ascii=False)})
            await db.commit()

        return {"message": f"Đã gỡ **{row[1]}** khỏi dự án **{row[2]}**."}
