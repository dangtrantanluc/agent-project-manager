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
from ai_agent.report_generator import report_templates


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

REPORT_TEMPLATE_PROMPT = f"""
Bạn là Report Template Selector.

Có sẵn các template báo cáo (đã tối ưu). Hãy chọn template phù hợp nhất với yêu
cầu và trích xuất tham số. Nếu KHÔNG có template nào phù hợp, trả template_id = null.

Danh sách template:
{report_templates.render_catalog()}

Output JSON DUY NHẤT, không markdown, không giải thích:
{{
  "template_id": "<id template>" hoặc null,
  "params": {{ "ten_tham_so": "giá trị" }}
}}

Quy tắc:
- Chỉ chọn template khi yêu cầu khớp rõ ràng; nếu mơ hồ/khác loại, để template_id = null.
- Điền đủ tham số bắt buộc; tham số chuỗi chỉ lấy từ khoá ngắn gọn (vd 'CRM', 'Lan').
- Tham số enum chỉ dùng đúng các giá trị trong [ngoặc vuông].
- Không bịa template_id ngoài danh sách trên.
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

    async def select_template(self, request: str, memory_context: str = "") -> dict[str, Any]:
        """LLM call NHỎ: chọn template báo cáo + trích tham số bị mask.

        Trả về {"template_id": str|None, "params": {...}}. Nếu không khớp template
        nào, template_id = None để gọi đường fallback freeform.
        """
        memory_block = f"\nNgữ cảnh hội thoại trước đó:\n{memory_context}\n" if memory_context else ""
        prompt = f"{REPORT_TEMPLATE_PROMPT}{memory_block}\nYêu cầu báo cáo: {request}\nOutput JSON:"
        result = await self.benmark_time("select_template", self.llm.ainvoke, [
            SystemMessage(content=prompt),
            HumanMessage(content="Chọn template báo cáo"),
        ])
        return self._parse_report_plan(result.content)

    async def _plan_queries(self, request: str, memory_context: str = "") -> dict[str, Any]:
        """Tạo plan query theo hybrid: template-first, fallback freeform.

        Trả về plan dạng {"queries": [{name, sql, args}], "need_clarification", "_source"}.
        """
        try:
            selection = await self.select_template(request, memory_context=memory_context)
        except Exception as exc:  # selector lỗi -> fallback freeform
            print(f"select_template failed, fallback freeform: {exc}")
            selection = {}

        template_id = selection.get("template_id")
        if template_id and template_id in report_templates.REGISTRY:
            try:
                queries = report_templates.build_queries(template_id, selection.get("params") or {})
                return {
                    "queries": queries,
                    "need_clarification": False,
                    "_source": f"template:{template_id}",
                }
            except (KeyError, ValueError) as exc:  # thiếu tham số -> fallback freeform
                print(f"template build failed ({template_id}), fallback freeform: {exc}")

        raw_plan = await self.generate_report_plan(request, memory_context=memory_context)
        plan = self._parse_report_plan(raw_plan)
        plan["_source"] = "freeform"
        return plan

    async def generate_report(self, request: str, memory_context: str = "") -> str:
        """Generate a final user-facing report by planning, executing, then summarizing SQL queries."""
        plan = await self._plan_queries(request, memory_context=memory_context)

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
        plan = await self._plan_queries(request, memory_context=memory_context)

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
            args = item.get("args") or None
            if not self.sql_agent.is_safe_sql(sql):
                query_results.append({
                    "name": name,
                    "sql": None,
                    "rows": [],
                    "error": "Unsafe SQL generated",
                })
                continue

            try:
                rows = await self.sql_agent.execute_sql(sql, args)
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
    agent = ReportAgent()
    requests = [
        "tiến độ của dự án CRM là gì",          # -> template:project_progress (project_kw=CRM)
        "tiến độ tuần này ra sao",               # -> template:period_progress (period=week)
        "tiến độ tháng này thì sao",             # -> template:period_progress (period=month)
        "những task nào đang quá hạn",           # -> template:overdue_upcoming
        "workload của Phương Thảo thế nào",      # -> template:workload_by_person
        "báo cáo chi phí dự án THACO",           # -> freeform fallback (không có template)
    ]

    for r in requests:
        plan = await agent._plan_queries(r)
        print(f"\n=== {r}  ->  source={plan.get('_source')}")
        for q in plan.get("queries", []):
            print(f"  - {q.get('name')}: args={q.get('args')}")
        results = await agent.execute_report_queries(plan)
        answer = await agent.generate_report_result(request=r, query_results=results)
        print(answer)
      
if __name__ == "__main__":
  asyncio.run(main())
