import time
import re
import json

import asyncpg
from langchain_community.utilities import SQLDatabase
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv
import os
import asyncio
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from ai_agent.prompt.prompt import SCHEMA_COMPACT
load_dotenv()

SQL_SCHEMA = BACKEND_ROOT.parent / "init" / "init.sql"
schema = SQL_SCHEMA.read_text() if SQL_SCHEMA.exists() else ""
_shared_schema_cache = None

_MUTATION_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|replace|merge|grant|revoke|vacuum|call|do)\b",
    re.IGNORECASE,
)

_NAMED_SQL_PLACEHOLDER = re.compile(r"(?<!:):[A-Za-z_][A-Za-z0-9_]*")
_USER_ID_PLACEHOLDER = re.compile(r"(?<!:):user_id\b")

SYSTEM_PROMPT = f"""Bạn là một trợ lý AI chuyên nghiệp giúp chuyển đổi các câu hỏi liên quan đến dự án, 
task thành các câu truy vấn SQL để truy xuất dữ liệu từ cơ sở dữ liệu quản lý dự án. Bạn sẽ nhận được một câu hỏi 
từ người dùng và cần tạo ra một câu truy vấn SQL chính xác, an toàn và hiệu quả để trả lời câu hỏi đó dựa trên schema của cơ sở dữ liệu đã được cung cấp.

Dưới đây là schema:
{SCHEMA_COMPACT}
Lưu ý quan trọng:
- Chỉ tạo câu truy vấn SQL sử dụng các bảng và cột đã được cung cấp
- Câu truy vấn phải bắt đầu bằng SELECT hoặc WITH và kết thúc bằng dấu chấm phẩy (;)
- Không được phép tạo câu truy vấn có chứa các lệnh nguy hiểm như INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, REPLACE, MERGE, GRANT, REVOKE, VACUUM, CALL, DO
- Câu truy vấn phải trả về dữ liệu phù hợp để trả lời câu hỏi, không được trả về dữ liệu thừa hoặc thiếu
- Cố gắng tối ưu câu truy vấn để trả về kết quả nhanh nhất có thể, tránh sử dụng các phép toán phức tạp hoặc subquery không cần thiết
- Viết câu truy vấn bằng tiếng Việt nếu có thể, nhưng vẫn phải tuân thủ cú pháp SQL chuẩn
- Nếu câu hỏi không thể trả lời bằng SQL, hãy trả về một câu truy vấn đơn giản trả về một thông báo phù hợp, ví dụ: SELECT 'Câu hỏi không thể trả lời bằng SQL' AS message;
"""

class Text2SQLAgent:
    def __init__(self, db=None, llm: ChatOpenAI | None = None, top_k: int = 10):
        """Khởi tạo tác nhân TextToSql dùng để chuyển đổi câu hỏi về dự án, task thành SQL để truy vấn cơ sở dữ liệu.
        """
        self.db = db
        self.top_k = top_k
        self.llm = ChatOpenAI(model=os.getenv("MODEL_NAME"), timeout=60, api_key=os.getenv("API_KEY"), base_url=os.getenv("BASE_URL")) if llm is None else llm

    def _schema_context(self) -> str:
        if self.db is not None and hasattr(self.db, "get_table_info"):
            return self.db.get_table_info()
        return SCHEMA_COMPACT

    def _clean_sql(self, sql: str) -> str:
        sql = sql.strip()
        if sql.startswith("```"):
            parts = sql.split("```")
            sql = parts[1] if len(parts) > 1 else sql
            if sql.lstrip().lower().startswith("sql"):
                sql = sql.lstrip()[3:]
        return sql.strip()

    def _coerce_user_id(self, current_user_id: int | str | None) -> int | None:
        if current_user_id is None:
            return None
        try:
            value = int(current_user_id)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def _bind_allowed_context_values(self, sql: str, current_user_id: int | str | None = None) -> str:
        user_id = self._coerce_user_id(current_user_id)
        if user_id is None:
            return sql
        return _USER_ID_PLACEHOLDER.sub(str(user_id), sql)
    
    def is_safe_sql(self, sql: str) -> bool:
        normalized = self._clean_sql(sql).strip()
        if not normalized.lower().startswith(("select", "with")):
            return False
        if not normalized.endswith(";"):
            return False
        if ";" in normalized.rstrip(";"):
            return False
        if _NAMED_SQL_PLACEHOLDER.search(normalized):
            return False
        sql_for_check = _NAMED_SQL_PLACEHOLDER.sub(
            "1",
            normalized
        )
        if _MUTATION_SQL.search(sql_for_check):
            return False

        return True

    async def generate_sql(
        self,
        question: str,
        memory_context: str = "",
        current_user_id: int | str | None = None,
    ) -> str:
        """Sử dụng LLM để tạo câu truy vấn SQL từ câu hỏi của người dùng.
            Args:
                question (str): Câu hỏi của người dùng về dự án, task.
            Returns:
                str: Câu truy vấn SQL được tạo ra để trả lời câu hỏi."""

        start = time.perf_counter()

        tenant_rule = "- Hệ thống hiện single-company; không thêm điều kiện company_id và không dùng bảng companies."
        memory_block = f"\n        Ngữ cảnh hội thoại trước đó:\n        {memory_context}\n" if memory_context else ""
        user_id = self._coerce_user_id(current_user_id)
        user_context_block = (
            f"\n        User hiện tại có users.id = {user_id}. "
            "Nếu người dùng hỏi 'của tôi', 'của mình', hãy lọc bằng id này; không dùng placeholder.\n"
            if user_id is not None else ""
        )
        response = await self.llm.ainvoke([
            SystemMessage(content=SYSTEM_PROMPT + "\n\n" + tenant_rule + memory_block + user_context_block),
            HumanMessage(content=f"Hãy tạo SQL cho câu hỏi: {question}"),
        ])

        elapsed = time.perf_counter() - start
        print("GENERATED SQL")
        sql = self._bind_allowed_context_values(self._clean_sql(response.content), current_user_id)
        if not self.is_safe_sql(sql):
            raise ValueError(f"Unsafe SQL generated: {sql}")
        print(sql)
        print(f"Generate SQL time: {elapsed:.3f}s")
        return sql
    
    async def execute_sql(self, sql: str, args: list | tuple | None = None):
        """Thực thi câu truy vấn SQL trên cơ sở dữ liệu và trả về kết quả.
        Args:
            sql (str): Câu truy vấn SQL cần thực thi.
            args (list|tuple|None): Tham số positional ($1,$2,...) cho query template.
                Mặc định None -> chạy như cũ (không tham số), tương thích ngược.
        Returns:
            list[dict]: Kết quả trả về từ việc thực thi câu truy vấn SQL, dưới dạng một danh sách các dictionary, mỗi dictionary đại diện cho một hàng kết quả với tên cột là key và giá trị là value.
        """
        conn = await asyncpg.connect(
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 5432)),
        )

        try:
            rows = await conn.fetch(sql, *(args or []))
            return [dict(row) for row in rows]

        finally:
            await conn.close()
    
    def _build_summary_prompt(self, question: str, rows: list[dict], memory_context: str = "") -> str:
            memory_block = f"""
        Ngữ cảnh hội thoại trước đó:
        {memory_context}
        """ if memory_context else ""

            return f"""
        Bạn là trợ lý quản lý dự án. Hãy trả lời câu hỏi của người dùng dựa trên kết quả truy vấn database.
        {memory_block}

        Câu hỏi:
        {question}

        Kết quả truy vấn dạng JSON:
        {json.dumps(rows, ensure_ascii=False, default=str)}

        Yêu cầu output:
        - Chỉ trả về câu trả lời cuối cùng cho người dùng
        - Không hiển thị SQL
        - Không hiển thị schema, tên bảng kỹ thuật, hoặc JSON thô
        - Trả lời ngắn gọn, tự nhiên bằng tiếng Việt
        """

    async def summarize_result(self, question: str, rows: list[dict], memory_context: str = "") -> str:
        """Dùng LLM diễn giải kết quả truy vấn thành câu trả lời gửi cho người dùng (1 call)."""
        if not rows:
            return "Mình không tìm thấy dữ liệu phù hợp để trả lời câu hỏi này."

        prompt_text = self._build_summary_prompt(question, rows, memory_context)
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt_text),
            HumanMessage(content="Hãy trả lời câu hỏi dựa trên kết quả truy vấn database ở trên.")
        ])
        return (response.content or "").strip()

    async def execute(
        self,
        question: str,
        memory_context: str = "",
        current_user_id: int | str | None = None,
    ):
      """Thực thi câu truy vấn SQL được tạo ra từ câu hỏi của người dùng và trả về kết quả.
      Args:
          question (str): Câu hỏi của người dùng về dự án, task.
      Returns:
          dict: Kết quả trả về từ việc thực thi câu truy vấn SQL, bao gồm câu hỏi gốc, câu truy vấn SQL và kết quả truy vấn.
      """
      try:
        sql = await self.generate_sql(
            question,
            memory_context=memory_context,
            current_user_id=current_user_id,
        )
      except ValueError as e:
        print(f"Error generating SQL: {e}")
        return {
            "question": question,
            "sql": None,
            "result": str(e),
            "answer": "Mình chưa tạo được truy vấn an toàn cho câu hỏi này. Bạn thử hỏi cụ thể hơn giúp mình nhé.",
        }
      
      start = time.perf_counter()
      try:
        result = await self.execute_sql(sql)
      except Exception as e:
        elapsed = time.perf_counter() - start
        print(f"DB execution failed after {elapsed:.3f}s: {e}", flush=True)
        return {
            "question": question,
            "sql": sql,
            "result": str(e),
            "answer": "Mình đã tạo được truy vấn nhưng gặp lỗi khi chạy trên database. Bạn thử hỏi lại cụ thể hơn giúp mình nhé.",
        }

      elapsed = time.perf_counter() - start
      print(f"DB execution time: {elapsed:.3f}s")
      answer = await self.summarize_result(question, result, memory_context=memory_context)

      return {
          "question": question,
          "sql": sql,
          "result": result,
          "answer": answer,
      }
    
if __name__ == "__main__":
    agent = Text2SQLAgent()
    question = ["Có bao nhiêu dự án đang chạy?", 
                "Danh sách các task đang được thực hiện trong dự án CRM Thaco Go-Live Phase 1?", 
                "Ai là người quản lý dự án MTL?", 
                "Dự án nào có deadline sắp tới nhất?", 
                "Tổng số giờ đã được ghi lại cho dự án Vingroup?"]
    for q in question:
        result = asyncio.run(agent.execute(q))
        print(result)
