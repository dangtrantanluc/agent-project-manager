import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from collections.abc import AsyncIterator
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv
from ai_agent.prompt.prompt import SCHEMA_COMPACT
from ai_agent.text_to_sql.text2sql import Text2SQLAgent


load_dotenv()

SQL_SCHEMA = BACKEND_ROOT.parent / "init" / "init.sql"
schema = SQL_SCHEMA.read_text() if SQL_SCHEMA.exists() else ""

REPORT_SYSTEM_PROMPT = f"""
Bạn là Report SQL Planner.

Schema compact:
{SCHEMA_COMPACT}

Tạo tối đa 2 SQL query.

Output JSON:
{{
  "need_clarification": false,
  "clarification_question": "",
  "queries": [
    {{"name": "string", "sql": "SELECT ...;"}}
  ]
}}

Rule:
- Chỉ SELECT/WITH
- Không markdown
- Không giải thích
"""

REPORT_RESULT_PROMPT = """
Bạn là trợ lý báo cáo quản lý dự án.

Hãy tổng hợp kết quả truy vấn thành câu trả lời cuối cùng cho người dùng.

Yêu cầu:
- Trả lời bằng tiếng Việt.
- Không hiển thị SQL.
- Không hiển thị JSON thô.
- Nêu số liệu chính, trạng thái/rủi ro đáng chú ý nếu có.
- Nếu dữ liệu trống, nói rõ chưa tìm thấy dữ liệu phù hợp.
- Ngắn gọn, dễ đọc.
"""


class ReportAgent:
    def __init__(self, llm: ChatOpenAI | None = None, sql_agent: Text2SQLAgent | None = None):
        self.llm = ChatOpenAI(
            model=os.getenv("MODEL_NAME"),
            timeout=60,
            streaming = True,
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL"),
        ) if llm is None else llm
        self.sql_agent = sql_agent or Text2SQLAgent(llm=self.llm)

    
    async def benmark_time(self, name:str, func, *args, **kwargs):
        start = time.time()
        result = await func(*args, **kwargs)
        end = time.time()
        print(f"{name} took {end - start:.2f} seconds")
        return result
    
    async def generate_report_plan(self, request: str, memory_context: str = "") -> dict:
      """Tạo kế hoạch báo cáo: gồm loại báo cáo, tiêu đề, tóm tắt ý định, danh sách câu truy vấn SQL cần chạy và hướng dẫn tổng hợp kết quả cuối cùng."""
      memory_block = f"\nNgữ cảnh hội thoại trước đó:\n{memory_context}\n" if memory_context else ""
      prompt = f"{REPORT_SYSTEM_PROMPT}{memory_block}\nYêu cầu báo cáo: {request}\nOutput JSON:"
      benchmark_result = await self.benmark_time("generate_report_plan", self.llm.ainvoke, [
          SystemMessage(content=prompt),
          HumanMessage(content="Tạo kế hoạch báo cáo"),
      ])
      return benchmark_result.content

    async def generate_report(self, request: str, memory_context: str = "") -> str:
        """Generate a final user-facing report by planning, executing, then summarizing SQL queries."""
        raw_plan = await self.generate_report_plan(request, memory_context=memory_context)
        plan = self._parse_report_plan(raw_plan)

        if plan.get("need_clarification"):
            return plan.get("clarification_question") or "Bạn cho mình thêm thông tin để tạo báo cáo chính xác hơn nhé."

        query_results = await self.execute_report_queries(plan)
        return await self.generate_report_result(
            request=request,
            query_results=query_results,
            memory_context=memory_context,
        )

    async def stream_generate_report(
        self,
        request: str,
        memory_context: str = "",
    ) -> AsyncIterator[dict]:
        full_answer = ""
        yield {"type": "status", "content": "Đang lập kế hoạch báo cáo..."}
        raw_plan = await self.generate_report_plan(request, memory_context=memory_context)
        plan = self._parse_report_plan(raw_plan)

        if plan.get("need_clarification"):
            answer = plan.get("clarification_question") or "Bạn cho mình thêm thông tin để tạo báo cáo chính xác hơn nhé."
            yield {"type": "answer_chunk", "content": answer}
            yield {
                "type": "result",
                "content": {"request": request, "plan": plan, "query_results": [], "answer": answer},
            }
            return

        yield {"type": "status", "content": "Đang chạy truy vấn báo cáo..."}
        query_results = await self.execute_report_queries(plan)

        yield {"type": "status", "content": "Đang tổng hợp báo cáo..."}
        async for event in self.stream_generate_report_result(
            request=request,
            query_results=query_results,
            memory_context=memory_context,
        ):
            if event["type"] == "answer_chunk":
                full_answer += event["content"]
            yield event

        yield {
            "type": "result",
            "content": {
                "request": request,
                "plan": plan,
                "query_results": query_results,
                "answer": full_answer.strip(),
            },
        }
    
    async def execute_report_queries(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        query_results = []
        for item in plan.get("queries") or []:
            name = str(item.get("name") or "query")
            sql = self.sql_agent._clean_sql(str(item.get("sql") or ""))
            if not self.sql_agent.is_safe_sql(sql):
                query_results.append({
                    "name": name,
                    "sql": None,
                    "rows": [],
                    "error": "Unsafe SQL generated",
                })
                continue

            try:
                rows = await self.sql_agent.execute_sql(sql)
                query_results.append({
                    "name": name,
                    "sql": sql,
                    "rows": rows,
                    "row_count": len(rows),
                })
            except Exception as exc:
                query_results.append({
                    "name": name,
                    "sql": sql,
                    "rows": [],
                    "error": str(exc),
                })
        return query_results

    async def generate_report_result(self, request: str, query_results: list[dict[str, Any]], memory_context: str = "") -> str:
        """Tạo kết quả báo cáo cuối cùng dựa trên kết quả câu truy vấn SQL và ngữ cảnh hội thoại."""
        memory_block = f"\nNgữ cảnh hội thoại trước đó:\n{memory_context}\n" if memory_context else ""
        prompt = f"""
        {memory_block}

        Yêu cầu báo cáo:
        {request}

        Kết quả truy vấn dạng JSON:
        {json.dumps(query_results, ensure_ascii=False, default=str)}
        """
        response = await self.llm.ainvoke([
            SystemMessage(content=REPORT_RESULT_PROMPT),
            HumanMessage(content=prompt),
        ])
        return response.content.strip()

    async def stream_generate_report_result(
        self,
        request: str,
        query_results: list[dict[str, Any]],
        memory_context: str = "",
    ) -> AsyncIterator[dict[str, str]]:
        memory_block = f"\nNgữ cảnh hội thoại trước đó:\n{memory_context}\n" if memory_context else ""
        prompt = f"""
        {memory_block}

        Yêu cầu báo cáo:
        {request}

        Kết quả truy vấn dạng JSON:
        {json.dumps(query_results, ensure_ascii=False, default=str)}
        """
        async for chunk in self.llm.astream([
            SystemMessage(content=REPORT_RESULT_PROMPT),
            HumanMessage(content=prompt),
        ]):
            if chunk.content:
                yield {"type": "answer_chunk", "content": chunk.content}

    def _parse_report_plan(self, raw_plan: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(raw_plan, dict):
            return raw_plan

        text = raw_plan.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"```$", "", text).strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                raise ValueError(f"Report plan is not valid JSON: {raw_plan}")
            parsed = json.loads(match.group(0))

        if not isinstance(parsed, dict):
            raise ValueError("Report plan must be a JSON object")
        return parsed


async def main():
    agent=ReportAgent()
    request = ["Cho tôi một báo cáo về tiến độ dự án MTL trong tháng 5, bao gồm số lượng task đã hoàn thành, số lượng task còn lại, và những rủi ro tiềm ẩn mà dự án đang gặp phải.", 
               "Tôi muốn một báo cáo về workload của Trần Thị Lan, bao gồm số lượng task đang làm, số lượng task đã hoàn thành, và dự đoán khối lượng công việc trong tuần tới dựa trên tiến độ hiện tại.",
               "Hãy tạo một báo cáo về chi phí của dự án THACO, bao gồm tổng chi phí đã phát sinh, chi phí dự kiến cho phần còn lại của dự án, và những yếu tố nào đang ảnh hưởng đến chi phí."]
    
    for r in request:
        result = await agent.generate_report(r)
        print(result)
      
if __name__ == "__main__":
  asyncio.run(main())
