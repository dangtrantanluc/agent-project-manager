from typing import List
from urllib import response
from pydantic import BaseModel, Field
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import JsonOutputParser
from dotenv import load_dotenv
import asyncio
import time
import json
import os   
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv()

PLANNING_SYSTEM_PROMPT = """
Bạn là Planning Agent.

Chỉ trả về JSON hợp lệ.

Output:
{
  "project_name": "string",
  "summary": "string",
  "milestones": [
    {
      "name": "string",
      "goal": "string",
      "estimated_days": 1,
      "tasks": [
        {
          "title": "string",
          "description": "string",
          "priority": "high|medium|low",
          "estimated_hours": 1,
          "role": "string"
        }
      ]
    }
  ]
}

Giới hạn:
- Tối đa 3 milestones
- Mỗi milestone tối đa 2 tasks
- Không assumptions
- Không deliverables
- Không dependencies
- Không acceptance_criteria
- Description tối đa 10 từ
- Không markdown
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
        self.llm = ChatOpenAI(model=os.getenv("MODEL_NAME"),
                              timeout=60,

                              api_key=os.getenv("API_KEY"), 
                              base_url=os.getenv("BASE_URL")) if llm is None else llm
        self.output_parser = JsonOutputParser()

    
    async def generate_project_plan(self, project_description: str, memory_context: str = "") -> ProjectPlan:
        memory_block = f"\n\nNgữ cảnh hội thoại trước đó:\n{memory_context}" if memory_context else ""
        prompt = f"{PLANNING_SYSTEM_PROMPT}{memory_block}\n\nMô tả dự án: {project_description}\n\nHãy tạo kế hoạch dự án chi tiết theo mô tả trên."
        start = time.perf_counter()
        response = await self.llm.ainvoke([
            SystemMessage(content=PLANNING_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        elapsed = time.perf_counter() - start
        print(f"generate_project_plan took {elapsed:.2f} seconds")
        raw = response.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        plan_dict = self.output_parser.parse(raw)
        return ProjectPlan(**plan_dict)

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
    print(json.dumps(project_plan.dict(), indent=2, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())
