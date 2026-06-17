from typing import List
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv
from ai_agent.shared.llm_factory import make_llm
import asyncio
import logging
import time
import json
import os

logger = logging.getLogger(__name__)

load_dotenv()

PLANNING_SYSTEM_PROMPT = """
Bạn là Planning Agent cho hệ thống quản lý dự án.

Giới hạn:
- Tối đa 3 milestones
- Mỗi milestone tối đa 2 tasks
- Description tối đa 10 từ
- Không markdown, không deliverables, không dependencies
- Nếu có thông tin về dự án hiện tại, dựa vào đó để tạo kế hoạch phù hợp
- Nếu có thông tin về thành viên, gán role phù hợp với từng người
"""

class TaskPlan(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"
    estimated_hours: float = 0
    role: str = "Developer"

class MilestonePlan(BaseModel):
    name: str
    goal: str = ""
    estimated_days: int = 0
    tasks: List[TaskPlan] = Field(default_factory=list)

class ProjectPlan(BaseModel):
    project_name: str
    summary: str = ""
    milestones: List[MilestonePlan] = Field(default_factory=list)

class PlanningAgent:
    def __init__(self, llm: ChatOpenAI | None = None):
        """Khởi tạo PlanningAgent với một mô hình ngôn ngữ (LLM) để tạo kế hoạch dự án.
        Args:
            llm (ChatOpenAI | None): Một instance của ChatOpenAI để tạo kế hoạch dự án. Nếu None, sẽ tạo một instance mới với cấu hình mặc định.
        """
        base_llm = make_llm(
            purpose="planning", timeout=25, temperature=0.4, max_retries=1,
        ) if llm is None else llm
        # Ép LLM trả thẳng đối tượng ProjectPlan đã validate (qua tool-calling).
        # Bỏ hẳn parse JSON thủ công — proxy đã xác nhận hỗ trợ function_calling.
        self.llm = base_llm.with_structured_output(ProjectPlan, method="function_calling")

    
    def _build_context_block(self, user_profile: dict) -> str:
        if not user_profile:
            return ""
        parts = []
        name = user_profile.get("full_name", "")
        role = user_profile.get("role", "")
        if name:
            parts.append(f"Người lập kế hoạch: {name}" + (f" ({role})" if role else ""))

        projects = user_profile.get("active_projects", [])
        if projects:
            names = ", ".join(p["name"] for p in projects[:5])
            parts.append(f"Dự án đang tham gia: {names}")

        if not parts:
            return ""
        return "\n\nThông tin người dùng:\n" + "\n".join(parts)

    async def generate_project_plan(
        self,
        project_description: str,
        memory_context: str = "",
        user_profile: dict | None = None,
    ) -> ProjectPlan:
        context_block = self._build_context_block(user_profile or {})
        memory_block = f"\n\nNgữ cảnh hội thoại:\n{memory_context}" if memory_context else ""
        human_content = (
            f"Mô tả dự án: {project_description}"
            f"{context_block}"
            f"{memory_block}"
            "\n\nHãy tạo kế hoạch dự án theo mô tả trên."
        )
        start = time.perf_counter()
        # with_structured_output trả thẳng ProjectPlan đã validate (hoặc None nếu
        # model không gọi tool). Bọc lỗi để không ném exception lên router — trả
        # về ProjectPlan rỗng kèm thông báo thân thiện thay vì câu lỗi chung chung.
        try:
            plan = await self.llm.ainvoke([
                SystemMessage(content=PLANNING_SYSTEM_PROMPT),
                HumanMessage(content=human_content),
            ])
            if not isinstance(plan, ProjectPlan):
                raise ValueError(f"Kế hoạch không hợp lệ: {type(plan).__name__}")
        except Exception:
            logger.exception("generate_project_plan: không tạo/validate được kế hoạch")
            plan = ProjectPlan(
                project_name=project_description[:60].strip() or "Kế hoạch dự án",
                summary=(
                    "Mình chưa lập được kế hoạch chi tiết cho yêu cầu này. "
                    "Bạn mô tả rõ hơn về mục tiêu và phạm vi dự án giúp mình nhé."
                ),
            )
        finally:
            logger.info("generate_project_plan took %.2fs", time.perf_counter() - start)
        return plan

    def format_project_plan(self, plan: ProjectPlan) -> str:
        lines = [f"Kế hoạch dự án: {plan.project_name}"]
        if plan.summary:
            lines.append(plan.summary)

        for milestone in plan.milestones:
            lines.append("")
            lines.append(f"- {milestone.name}: {milestone.goal}")
            for task in milestone.tasks:
                lines.append(
                    f"  + {task.title} ({task.priority}, {task.estimated_hours}h, {task.role})"
                )
        return "\n".join(lines)

async def main():
    agent = PlanningAgent()
    project_description = "Phát triển một ứng dụng quản lý công việc cho nhóm nhỏ, bao gồm các tính năng như tạo task, phân công task, theo dõi tiến độ và báo cáo."
    project_plan = await agent.generate_project_plan(project_description)
    print(json.dumps(project_plan.model_dump(), indent=2, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())
