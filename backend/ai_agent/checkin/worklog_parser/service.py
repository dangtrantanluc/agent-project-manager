import json
from datetime import date, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from ai_agent.checkin.worklog_parser.prompt import WORKLOG_EXTRACT_PROMPT
from app.core.code_gen import next_worklog_code


def _build_clarify_block(
    text: str,
    prev_question: str | None,
    prev_partial: dict | None,
) -> str:
    """Inject clarification context into the user message for the LLM."""
    parts: list[str] = []
    if prev_question:
        parts.append(f'CONTEXT — câu hỏi trước: "{prev_question}"')
    if prev_partial:
        parts.append("CONTEXT — thông tin đã có:")
        for k in ("description", "work_date", "status", "blocker"):
            v = prev_partial.get(k)
            if v:
                parts.append(f"  - {k}: {v}")
    parts.append("")
    parts.append(f'Câu trả lời mới: "{text}"')
    parts.append("Hãy COMBINE thông tin và trả ParsedWorklog hoàn chỉnh.")
    return "\n".join(parts)


class WorklogParserService:
    def __init__(self, llm: ChatOpenAI):
        self.llm = llm

    async def parse_and_save(self, message: str, user_id: int, db: AsyncSession) -> str:
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        prompt = WORKLOG_EXTRACT_PROMPT.replace("{today}", today).replace("{yesterday}", yesterday)

        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=message),
        ])

        try:
            data = json.loads(response.content.strip())
        except json.JSONDecodeError:
            return "Không thể phân tích. Hãy thử: 'Tôi làm 3h dự án X hôm nay'."

        if "error" in data:
            return data["error"]

        # Resolve project (3-step fallback)
        project_id, project_name = await self._resolve_project(
            data.get("project_name"), data.get("task_name"), user_id, db
        )
        if project_id is None:
            hours = data.get("hours", "")
            return (
                f"Tôi chưa xác định được dự án để ghi công. "
                f"Bạn đang làm dự án nào? "
                f"(Ví dụ: 'Tôi làm {hours}h dự án [tên dự án] hôm nay')"
            )

        # Resolve task (optional)
        task_id = None
        if data.get("task_name"):
            task_row = (await db.execute(
                text("""
                    SELECT id FROM tasks
                    WHERE project_id = :pid AND name ILIKE :tname
                    LIMIT 1
                """),
                {"pid": project_id, "tname": f"%{data['task_name']}%"},
            )).fetchone()
            if task_row:
                task_id = task_row[0]

        wl_seq, wl_code = await next_worklog_code(project_id, db)
        await db.execute(
            text("""
                INSERT INTO worklogs
                    (work_date, description, hours, project_id, task_id,
                     user_id, seq, code, updated_at)
                VALUES
                    (:work_date, :description, :hours,
                     :project_id, :task_id, :user_id, :seq, :code, NOW())
            """),
            {
                "work_date": data["work_date"],
                "description": data.get("description"),
                "hours": data["hours"],
                "project_id": project_id,
                "task_id": task_id,
                "user_id": user_id,
                "seq": wl_seq, "code": wl_code,
            },
        )
        await db.commit()

        task_info = f" (task: {data['task_name']})" if data.get("task_name") else ""
        return (
            f"✅ Đã ghi **{data['hours']}h** cho dự án **{project_name}**"
            f"{task_info} ngày {data['work_date']}."
        )

    async def parse(
        self,
        message: str,
        *,
        prev_question: str | None = None,
        prev_partial: dict | None = None,
    ) -> dict:
        """Parse worklog from free text. Does NOT resolve project/task.

        Returns one of:
        - {"hours": float, "work_date": str, ...}          — success
        - {"needs_clarification": True, "clarification_question": str, ...}
        - {"error": str}
        """
        from ai_agent.checkin.prompts import get_worklog_extract_prompt
        from ai_agent.checkin.worklog_parser.hours_parser import extract_hours, has_relative_now_range
        from langchain_core.messages import SystemMessage, HumanMessage

        regex_hours = extract_hours(message)
        is_relative = has_relative_now_range(message)

        prompt = get_worklog_extract_prompt()
        user_block = _build_clarify_block(message, prev_question, prev_partial) \
            if (prev_question or prev_partial) else message

        try:
            response = await self.llm.ainvoke([
                SystemMessage(content=prompt),
                HumanMessage(content=user_block),
            ])
            raw = response.content.strip()
            if raw.startswith("```"):
                parts = raw.split("```")
                raw = parts[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
        except Exception:
            if regex_hours is not None:
                return {
                    "hours": regex_hours,
                    "work_date": date.today().isoformat(),
                    "description": message.strip(),
                }
            return {"error": "Không parse được, vui lòng thử lại với định dạng: '2h fix bug login'"}

        # If LLM says needs_clarification but regex already has hours, rescue immediately
        if data.get("needs_clarification") and regex_hours is not None:
            return {
                "hours": regex_hours,
                "work_date": data.get("work_date") or date.today().isoformat(),
                "description": data.get("description") or message.strip(),
                "status": data.get("status"),
            }

        # Propagate needs_clarification as-is (no regex rescue)
        if data.get("needs_clarification"):
            return data

        # On error, try regex rescue
        if "error" in data:
            if regex_hours is not None:
                return {
                    "hours": regex_hours,
                    "work_date": date.today().isoformat(),
                    "description": message.strip(),
                }
            return data

        # Normalize hours: LLM can't know current time for relative ranges
        if is_relative and regex_hours is not None:
            data["hours"] = regex_hours
        else:
            try:
                llm_hours = float(data.get("hours", 0))
            except (TypeError, ValueError):
                llm_hours = 0.0
            if llm_hours <= 0 and regex_hours is not None:
                data["hours"] = regex_hours

        return data

    async def _resolve_project(
        self,
        project_name: str | None,
        task_name: str | None,
        user_id: int,
        db: AsyncSession,
    ) -> tuple[int | None, str | None]:
        """3-step fallback:
        1) match project_name trực tiếp
        2) match task được assign cho user → lấy project của task đó
        3) active project mà user là member
        """
        # 1. Explicit project_name
        if project_name:
            row = (await db.execute(
                text("""
                    SELECT p.id, p.name FROM projects p
                    WHERE p.name ILIKE :pname
                    ORDER BY p.created_at DESC LIMIT 1
                """),
                {"pname": f"%{project_name}%"},
            )).fetchone()
            if row:
                return row[0], row[1]

        # 2. task_name → lookup project via assigned task
        if task_name:
            row = (await db.execute(
                text("""
                    SELECT p.id, p.name FROM tasks t
                    JOIN projects p ON p.id = t.project_id
                    WHERE t.assignee_id = :uid
                      AND t.name ILIKE :tname
                      AND t.status <> 'DONE'::"TaskStatus"
                    ORDER BY t.deadline ASC NULLS LAST LIMIT 1
                """),
                {"uid": user_id, "tname": f"%{task_name}%"},
            )).fetchone()
            if row:
                return row[0], row[1]

        # 3. Fallback: most recently updated IN_PROGRESS project the user is a member of
        row = (await db.execute(
            text("""
                SELECT p.id, p.name FROM members m
                JOIN projects p ON p.id = m.project_id
                WHERE m.user_id = :uid
                  AND p.status = 'IN_PROGRESS'::"ProjectStatus"
                ORDER BY p.updated_at DESC LIMIT 1
            """),
            {"uid": user_id},
        )).fetchone()
        if row:
            return row[0], row[1]

        return None, None
