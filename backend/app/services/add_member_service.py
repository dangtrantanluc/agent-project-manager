"""Thêm thành viên vào dự án qua chat.

Vd (PM/quản lý nhắn): "thêm Lực vào dự án Logistics với vai trò dev" -> resolve
người + dự án trong cùng company -> INSERT members.

Quy tắc an toàn (giống POST /members/by-project):
  - CHỈ MANAGER/ADMIN/SUPER_ADMIN được thêm thành viên.
  - Resolve mơ hồ (không thấy / trùng tên) -> HỎI LẠI, KHÔNG thêm bừa.
  - Đã là thành viên -> báo, không thêm trùng.

KHÔNG có bước xác nhận OK/Hủy (hướng C): resolve_one đã chặn nhập nhằng nên rủi
ro thêm nhầm thấp; cơ chế confirm chung để dành cho ActionAgent sau này.
"""
import json
import logging
from dataclasses import dataclass

from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel, Field
from sqlalchemy import text

from database import AsyncSessionLocal
from ai_agent.shared.action_base import ActionAgentBase, ActionContext, ActionResult
from ai_agent.shared.entity_resolver import (
    is_privileged,
    resolve_users,
    resolve_projects,
    resolve_one,
)

logger = logging.getLogger(__name__)

# Vai trò thành viên hợp lệ trong dự án (cột members.role là text tự do; whitelist
# để không ghi giá trị rác từ LLM). Mặc định MEMBER nếu không nói rõ.
_VALID_MEMBER_ROLES = {"MEMBER", "MANAGER", "VIEWER"}
_DEFAULT_MEMBER_ROLE = "MEMBER"

_EXTRACT_SYSTEM_PROMPT = """\
Bạn bóc tách yêu cầu THÊM THÀNH VIÊN vào dự án trong hệ thống quản lý dự án.
Từ câu của người dùng, trích:
- member: TÊN người cần thêm (bỏ kính ngữ anh/chị/em, chỉ giữ tên). Bắt buộc.
- project: tên dự án cần thêm vào. Bắt buộc.
- role: vai trò trong dự án nếu có nhắc (MEMBER/MANAGER/VIEWER); rỗng nếu không.
  ("dev/thành viên/nhân viên"=MEMBER, "quản lý/PM"=MANAGER, "xem/khách"=VIEWER).
Nếu câu KHÔNG phải thêm thành viên, để member và project rỗng.
"""


class AddMemberExtraction(BaseModel):
    member: str = Field(default="")
    project: str = Field(default="")
    role: str = Field(default="")


@dataclass
class AddMemberResult:
    status: str  # added | forbidden | need_info | not_found | ambiguous | exists | error
    message: str
    member_id: int | None = None


class AddMemberService(ActionAgentBase):
    # Khai báo cho ActionAgentBase / registry (router đọc intent_desc qua class).
    name = "add_member"
    purpose = "add_member"
    extraction_model = AddMemberExtraction
    system_prompt = _EXTRACT_SYSTEM_PROMPT
    intent_desc = (
        "- add_member: người dùng THÊM THÀNH VIÊN vào DỰ ÁN (vd: "
        '"thêm Thảo vào dự án Logistics", "add Nam vào project CRM vai trò dev"). '
        "KHÁC create_task: add_member gắn người vào DỰ ÁN (không tạo task)."
    )

    async def _handle(self, extraction, ctx: ActionContext) -> ActionResult:
        """Adapter ActionAgentBase: uỷ thẳng sang add_from_chat (giữ logic & test cũ)."""
        r = await self.add_from_chat(
            message=ctx.message, sender_user_id=ctx.sender_user_id,
            user_profile=ctx.user_profile, memory_context=ctx.memory_context,
        )
        # status 'added' của add_member -> 'done' chuẩn của ActionResult.
        status = "done" if r.status == "added" else r.status
        return ActionResult(status=status, message=r.message, entity_id=r.member_id)

    async def add_from_chat(
        self,
        *,
        message: str,
        sender_user_id: str | int,
        user_profile: dict | None = None,
        memory_context: str = "",
    ) -> AddMemberResult:
        profile = user_profile or {}
        # 1. Phân quyền: chỉ quản lý được thêm thành viên.
        if not is_privileged(profile.get("role")):
            return AddMemberResult(
                status="forbidden",
                message="Chỉ quản lý (MANAGER/ADMIN) mới thêm thành viên được. Bạn nhờ quản lý dự án giúp nhé.",
            )
        if self._llm is None:
            return AddMemberResult(
                status="error",
                message="Mình chưa thêm thành viên qua chat được lúc này, bạn thêm trên web giúp nhé.",
            )

        # 2. Bóc tách.
        extraction = await self._extract_member(message, memory_context)
        if extraction is None or not extraction.member.strip() or not extraction.project.strip():
            return AddMemberResult(
                status="need_info",
                message=("Bạn cho mình rõ: **thêm ai** vào **dự án nào** (và vai trò gì nếu cần) nhé. "
                         "Vd: \"thêm Thảo vào dự án Logistics với vai trò dev\"."),
            )

        try:
            sender_id = int(sender_user_id)
        except (TypeError, ValueError):
            return AddMemberResult(status="error", message="Không xác định được người yêu cầu.")

        async with AsyncSessionLocal() as db:
            # 3. Resolve người được thêm.
            users = await resolve_users(db, extraction.member.strip(), sender_id)
            user, err = resolve_one(users, extraction.member, "người", "full_name")
            if err:
                return AddMemberResult(status="not_found" if not users else "ambiguous", message=err)

            # 4. Resolve dự án.
            projects = await resolve_projects(db, extraction.project.strip(), sender_id)
            project, err = resolve_one(projects, extraction.project, "dự án", "name")
            if err:
                return AddMemberResult(status="not_found" if not projects else "ambiguous", message=err)

            # 5. Map vai trò.
            role = extraction.role.strip().upper()
            role = role if role in _VALID_MEMBER_ROLES else _DEFAULT_MEMBER_ROLE

            # 6. Thêm vào members (ON CONFLICT: đã là thành viên -> không thêm trùng).
            row = (await db.execute(text("""
                INSERT INTO members (project_id, user_id, role, updated_at)
                VALUES (:pid, :uid, :role, NOW())
                ON CONFLICT (project_id, user_id) DO NOTHING
                RETURNING id
            """), {"pid": project["id"], "uid": user["user_id"], "role": role})).fetchone()

            if row is None:
                return AddMemberResult(
                    status="exists",
                    message=f"**{user['full_name']}** đã là thành viên của dự án **{project['name']}** rồi nhé.",
                )

            member_id = row[0]
            await db.execute(text("""
                UPDATE projects SET member_count = member_count + 1, updated_at = NOW()
                WHERE id = :pid
            """), {"pid": project["id"]})
            await db.execute(text("""
                INSERT INTO agent_audit_log (tool, args_json, source, created_at)
                VALUES ('add_member_from_chat', CAST(:args AS jsonb),
                        CAST('chat' AS "AgentAuditSource"), NOW())
            """), {"args": json.dumps({"member_id": member_id, "user_id": user["user_id"],
                                       "project_id": project["id"], "role": role, "by": sender_id},
                                      ensure_ascii=False)})
            await db.commit()

        return AddMemberResult(
            status="added", member_id=member_id,
            message=(f"Đã thêm **{user['full_name']}** vào dự án **{project['name']}** "
                     f"với vai trò {role}. Bạn cần thêm ai nữa cứ nhắn mình nhé!"),
        )

    async def _extract_member(self, message: str, memory_context: str) -> AddMemberExtraction | None:
        # Tên KHÁC base._extract(ctx) để không override nó (base.run dùng chữ ký khác).
        memory_block = f"Ngữ cảnh trước:\n{memory_context}\n\n" if memory_context else ""
        try:
            return await self._llm.ainvoke([
                SystemMessage(content=_EXTRACT_SYSTEM_PROMPT),
                HumanMessage(content=f"{memory_block}Câu của người dùng: {message}"),
            ])
        except Exception:
            logger.exception("AddMemberService bóc tách lỗi")
            return None
