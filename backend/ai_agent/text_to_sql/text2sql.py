import hashlib
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
import logging
from pathlib import Path
import sys

logger = logging.getLogger(__name__)

SQL_CACHE_TTL = int(os.getenv("SQL_CACHE_TTL", 3600))


# Câu hỏi có thời gian tương đối ("hôm nay", "tuần này"...). Với loại câu này ta
# VẪN cache được CHUỖI SQL, miễn là SQL dùng hàm ngày động (CURRENT_DATE/now()/
# date_trunc) thay vì đóng băng một ngày cố định. CURRENT_DATE được Postgres tính
# lúc THỰC THI nên chuỗi SQL tái dùng ngày mai vẫn cho kết quả của ngày mai.
# => chỉ chặn cache khi SQL chứa literal ngày hard-code (xem _sql_is_date_safe).
_RELATIVE_TIME_PATTERNS = (
    "hôm nay", "hôm qua", "tuần này", "tuần trước",
    "tháng này", "tháng trước", "năm nay",
    "mới nhất", "gần đây", "vừa", "hiện tại",
)

# Literal ngày bị đóng băng trong SQL: 'YYYY-MM-DD' (có/không có giờ). Nếu xuất hiện
# trong câu thời-gian-tương-đối thì KHÔNG được cache (mai sẽ trả kết quả cũ).
_HARDCODED_DATE = re.compile(r"'\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2})?")

_db_pool: asyncpg.Pool | None = None

# Timeout cứng cho mọi câu truy vấn của agent (chặn pg_sleep / query nặng làm cạn pool).
_STATEMENT_TIMEOUT_MS = os.getenv("AGENT_STATEMENT_TIMEOUT_MS", "5000")


async def _get_pool() -> asyncpg.Pool:
    global _db_pool
    if _db_pool is None:
        # Ưu tiên credential read-only riêng cho agent (DB_AGENT_USER); nếu không
        # cấu hình thì fallback về DB_USER. Xem init/agent_role.sql để tạo role.
        _db_pool = await asyncpg.create_pool(
            user=os.getenv("DB_AGENT_USER") or os.getenv("DB_USER"),
            password=os.getenv("DB_AGENT_PASSWORD") or os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 5432)),
            min_size=2,
            max_size=10,
            # statement_timeout áp cho mọi connection trong pool → DoS-resistant.
            server_settings={"statement_timeout": _STATEMENT_TIMEOUT_MS},
        )
    return _db_pool

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

# Chặn truy cập dữ liệu nhạy cảm / hàm nguy hiểm ngay ở tầng ứng dụng.
# Đây là lớp phòng thủ phụ; lớp chính là DB role read-only (init/agent_role.sql).
# - password_hash: tránh exfiltration hash mật khẩu (kể cả qua prompt injection).
# - pg_catalog/information_schema: tránh liệt kê schema/đoán cột.
# - pg_read_file/pg_sleep/lo_*/dblink/copy: đọc file hệ thống, DoS, ra ngoài DB.
_FORBIDDEN_SQL = re.compile(
    r"\b(password_hash|pg_read_file|pg_read_binary_file|pg_ls_dir|pg_sleep|"
    r"pg_catalog|information_schema|dblink|lo_import|lo_export|copy)\b",
    re.IGNORECASE,
)

# Comment SQL có thể che mutation keyword hoặc dấu ; → phải bóc trước khi kiểm tra.
_SQL_LINE_COMMENT = re.compile(r"--[^\n]*")
_SQL_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_sql_comments(sql: str) -> str:
    sql = _SQL_BLOCK_COMMENT.sub(" ", sql)
    sql = _SQL_LINE_COMMENT.sub("", sql)
    return sql

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
- Nếu kết quả rỗng, nói rõ không tìm thấy và gợi ý hỏi lại cụ thể hơn
- ĐỊNH DẠNG ĐẦU RA (BẮT BUỘC): CHỈ trả về DUY NHẤT câu lệnh SQL, bắt đầu bằng SELECT hoặc WITH và kết thúc bằng dấu chấm phẩy. TUYỆT ĐỐI KHÔNG kèm lời giải thích, KHÔNG văn xuôi dẫn nhập ("Để trả lời..."), KHÔNG markdown, KHÔNG khối ```sql. Ký tự đầu tiên của câu trả lời phải là chữ S (SELECT) hoặc W (WITH).

Cú pháp ngày tháng (BẮT BUỘC dùng PostgreSQL, KHÔNG dùng cú pháp MySQL):
- Đây là PostgreSQL. TUYỆT ĐỐI KHÔNG viết `INTERVAL (biểu_thức) DAY` hay `INTERVAL n DAY` (đó là MySQL và sẽ gây lỗi cú pháp).
- Khoảng thời gian cố định: dùng literal `INTERVAL '7 days'`, `INTERVAL '1 month'`.
- Khoảng thời gian theo biểu thức/cột: dùng `make_interval(days => <int>)` hoặc `(<int> * INTERVAL '1 day')`.
- "Tuần này" (tuần bắt đầu từ Thứ Hai): dùng `date_trunc('week', CURRENT_DATE)` làm đầu tuần và `date_trunc('week', CURRENT_DATE) + INTERVAL '6 days'` làm cuối tuần.
- "Tháng này": `date_trunc('month', CURRENT_DATE)` đến `date_trunc('month', CURRENT_DATE) + INTERVAL '1 month' - INTERVAL '1 day'`.
- Lấy số thứ tự ngày trong tuần: `EXTRACT(DOW FROM CURRENT_DATE)` (Chủ Nhật = 0). Ưu tiên `date_trunc` thay vì tự tính bằng EXTRACT.

NHẮC LẠI LẦN CUỐI: Chỉ in ra câu SQL thuần. Không một từ nào khác ngoài SQL.
"""

class Text2SQLAgent:
    def __init__(self, db=None, llm: ChatOpenAI | None = None, top_k: int = 10):
        """Khởi tạo tác nhân TextToSql dùng để chuyển đổi câu hỏi về dự án, task thành SQL để truy vấn cơ sở dữ liệu.
        """
        self.db = db
        self.top_k = top_k
        # Sinh SQL là tác vụ xác định, KHÔNG cần "thinking" của Gemini Flash đời mới
        # (thinking ngầm sinh hàng nghìn token suy luận ẩn → chậm 5-15s vô ích).
        # reasoning_effort="none" tắt thinking qua lớp OpenAI-compat của Google.
        # timeout siết về 20s + max_retries=2 để fail nhanh khi endpoint trả 503.
        self.llm = ChatOpenAI(
            model=os.getenv("MODEL_NAME"),
            timeout=20,
            max_retries=2,
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL"),
            reasoning_effort="none"
        ) if llm is None else llm

    def _schema_context(self) -> str:
        if self.db is not None and hasattr(self.db, "get_table_info"):
            return self.db.get_table_info()
        return SCHEMA_COMPACT

    def _clean_sql(self, sql: str) -> str:
        """Bóc câu SQL từ output LLM kèm markdown — AN TOÀN.

        LLM (nhất là qua proxy) hay trả "Để trả lời ... đây là SQL: ```sql ...```"
        thay vì SQL thuần. Ở đây CHỈ gỡ khối markdown bao quanh, lấy NGUYÊN ruột
        fence (không cắt tại ; đầu) — để chuỗi nhiều câu lệnh / mutation ẩn / tiền
        tố lạ (EXPLAIN...) vẫn lộ nguyên cho is_safe_sql từ chối.

        TUYỆT ĐỐI không "trích" 1 câu SELECT ra khỏi văn bản: làm thế sẽ vô hiệu
        is_safe_sql (vd "SELECT 1; DROP" -> "SELECT 1;" thì lọt mutation; "EXPLAIN
        ... SELECT 1;" -> "SELECT 1;" thì lọt lệnh không phải SELECT).

        Không có fence -> trả nguyên (để is_safe_sql kiểm trên chuỗi gốc).
        """
        sql = sql.strip()

        fence = re.search(r"```(?:sql)?\s*(.*?)```", sql, re.DOTALL | re.IGNORECASE)
        if fence:
            return fence.group(1).strip()

        return sql

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

    def _cache_key(self, question: str, user_id: int | None) -> str:
        normalized = " ".join(question.lower().split())
        raw = f"{normalized}:{user_id or 'anon'}"
        return f"sql_cache:{hashlib.md5(raw.encode()).hexdigest()}"

    def _is_relative_time_question(self, question: str) -> bool:
        lowered = question.lower()
        return any(p in lowered for p in _RELATIVE_TIME_PATTERNS)

    def _sql_is_date_safe(self, sql: str) -> bool:
        """SQL có an toàn để cache lâu dài không (không đóng băng một ngày cụ thể)?

        An toàn = KHÔNG chứa literal ngày hard-code. SQL dùng CURRENT_DATE/now()/
        date_trunc tự cập nhật theo ngày chạy nên cache lại vẫn đúng; chỉ SQL ghi
        cứng 'YYYY-MM-DD' mới trả kết quả cũ vào hôm sau.
        """
        return _HARDCODED_DATE.search(sql) is None

    def _should_cache_write(self, question: str, sql: str) -> bool:
        """Có nên GHI chuỗi SQL này vào cache không (quyết định sau khi đã có SQL).

        - Câu thường: luôn cache.
        - Câu thời-gian-tương-đối: chỉ cache nếu SQL không hard-code ngày.
        """
        if not self._is_relative_time_question(question):
            return True
        return self._sql_is_date_safe(sql)

    def is_safe_sql(self, sql: str) -> bool:
        # Bóc comment TRƯỚC mọi kiểm tra: comment có thể che ; hoặc mutation keyword.
        normalized = _strip_sql_comments(self._clean_sql(sql)).strip()
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
        # Chặn đọc dữ liệu nhạy cảm / hàm nguy hiểm dù chỉ là SELECT.
        if _FORBIDDEN_SQL.search(sql_for_check):
            return False

        return True

    async def generate_sql(self, question: str, memory_context: str = "", current_user_id: int | str | None = None, user_role: str | None = None) -> str:
        user_id = self._coerce_user_id(current_user_id)
        restricted = (user_role or "").upper() not in ("ADMIN", "MANAGER")

        # Luôn thử đọc cache — kể cả câu thời-gian-tương-đối ("hôm nay"), vì cache chỉ
        # lưu chuỗi SQL chứa CURRENT_DATE (tính lúc chạy), không lưu dữ liệu. Cache key
        # gồm cả "restricted" để user bị giới hạn không nhận lại SQL toàn cục đã cache.
        try:
            from core.redis import get_redis
            redis = await get_redis()
            cache_key = self._cache_key(question, user_id) + (":r" if restricted else ":f")
            cached_sql = await redis.get(cache_key)
            if cached_sql:
                logger.info("SQL cache hit key=%s", cache_key)
                return cached_sql
        except Exception:
            logger.warning("Redis unavailable, skipping SQL cache read", exc_info=True)

        start = time.perf_counter()
        tenant_rule = "- Hệ thống hiện single-company; không thêm điều kiện company_id và không dùng bảng companies."
        memory_block = f"\n        Ngữ cảnh hội thoại trước đó:\n        {memory_context}\n" if memory_context else ""
        user_context_block = (
            f"\n        User hiện tại có users.id = {user_id}. "
            "Nếu người dùng hỏi 'của tôi', 'của mình', hãy lọc bằng id này; không dùng placeholder.\n"
            if user_id is not None else ""
        )
        # Với MEMBER/VIEWER: bắt buộc mọi truy vấn phải scope theo chính user này.
        # Không có user_id thì không thể scope an toàn → từ chối.
        restriction_block = ""
        if restricted:
            if user_id is None:
                raise ValueError("Restricted user without id cannot run data queries")
            restriction_block = (
                f"\n        QUYỀN TRUY CẬP (BẮT BUỘC): Người dùng chỉ được xem dữ liệu LIÊN QUAN ĐẾN CHÍNH HỌ "
                f"(users.id = {user_id}). MỌI truy vấn PHẢI lọc theo {user_id}: "
                f"task phải có assignee_id = {user_id}; worklog/backlog phải có user_id = {user_id}; "
                f"project phải là project họ tham gia (owner_id = {user_id}, account_manager_id = {user_id}, "
                f"hoặc có bản ghi trong members/tasks/worklogs/backlogs gắn {user_id}). "
                f"TUYỆT ĐỐI KHÔNG trả về dữ liệu của người khác hay toàn công ty, kể cả khi được yêu cầu.\n"
            )
        response = await self.llm.ainvoke(SYSTEM_PROMPT + tenant_rule + user_context_block + restriction_block + memory_block + f"\n\nCâu hỏi: {question}\n\nHãy tạo câu truy vấn SQL phù hợp để trả lời câu hỏi này, tuân thủ các yêu cầu đã nêu trong prompt.")
        elapsed = time.perf_counter() - start

        sql = self._bind_allowed_context_values(self._clean_sql(response.content), current_user_id)
        if not self.is_safe_sql(sql):
            raise ValueError(f"Unsafe SQL generated: {sql}")
        # Backstop: với user bị giới hạn, SQL phải có chứa id của họ — nếu không, từ chối.
        if restricted and str(user_id) not in sql:
            raise ValueError("Restricted query not scoped to current user")
        logger.info("SQL generated in %.3fs: %s", elapsed, sql)

        # Ghi cache sau khi validate. Câu thời-gian-tương-đối chỉ ghi nếu SQL không
        # hard-code ngày (xem _should_cache_write) — tránh trả kết quả cũ vào hôm sau.
        if self._should_cache_write(question, sql):
            try:
                from core.redis import get_redis
                redis = await get_redis()
                cache_key = self._cache_key(question, user_id) + (":r" if restricted else ":f")
                await redis.setex(cache_key, SQL_CACHE_TTL, sql)
                logger.info("SQL cache set key=%s ttl=%ds", cache_key, SQL_CACHE_TTL)
            except Exception:
                logger.warning("Redis unavailable, skipping SQL cache write", exc_info=True)
        else:
            logger.info("SQL cache skip (relative-time question with hard-coded date)")

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
        pool = await _get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *(args or []))
            return [dict(row) for row in rows]

    
    def _build_summary_prompt(self, question: str, rows: list[dict], memory_context: str = "") -> str:
        memory_block = f"\nNgữ cảnh hội thoại trước:\n{memory_context}\n" if memory_context else ""
        return f"""Bạn là PM-Bot, trợ lý quản lý dự án. Trả lời câu hỏi dựa trên kết quả truy vấn database.
{memory_block}
Câu hỏi: {question}

Kết quả:
{json.dumps(rows, ensure_ascii=False, default=str)}

Yêu cầu:
- Trả lời tự nhiên bằng tiếng Việt, ngắn gọn
- Không hiển thị SQL, tên bảng, hoặc JSON thô
- Đừng chỉ đọc số — hãy nói ý nghĩa: tốt hay chưa tốt, đúng hạn hay trễ
- Nếu dữ liệu cho thấy vấn đề (task trễ, không có worklog, milestone sắp hết), nhận xét 1 câu
- Nếu kết quả rỗng ([]), nghĩa là truy vấn chạy đúng nhưng KHÔNG có bản ghi nào thỏa câu hỏi. Hãy trả lời tự nhiên đúng theo câu hỏi rằng không có dữ liệu đó — ví dụ hỏi "hôm nay tôi có task gì không?" thì trả lời "Hôm nay bạn không có task nào cả." Tuyệt đối không nói chung chung kiểu "không tìm thấy dữ liệu phù hợp".
"""

    async def summarize_result(self, question: str, rows: list[dict], memory_context: str = "") -> str:
        """Dùng LLM diễn giải kết quả truy vấn thành câu trả lời gửi cho người dùng (1 call).

        Kể cả khi rows rỗng vẫn gọi LLM để câu trả lời "không có dữ liệu" bám sát
        câu hỏi (vd. "Hôm nay bạn không có task nào") thay vì câu chung chung.
        """
        prompt_text = self._build_summary_prompt(question, rows, memory_context)
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt_text),
            HumanMessage(content="Hãy trả lời câu hỏi dựa trên kết quả truy vấn database ở trên.")
        ])
        answer = (response.content or "").strip()
        # Fallback an toàn nếu LLM trả rỗng (vd. lỗi proxy) — vẫn ưu tiên LLM ở trên.
        if not answer:
            return "Hiện mình chưa tìm thấy dữ liệu nào khớp với câu hỏi của bạn."
        return answer

    def _answer_cache_key(self, sql: str, result: list[dict]) -> str:
        raw = f"{sql}:{json.dumps(result, sort_keys=True, default=str)}"
        return f"answer_cache:{hashlib.md5(raw.encode()).hexdigest()}"

    async def _get_cached_answer(self, sql: str, result: list[dict]) -> str | None:
        try:
            from core.redis import get_redis
            redis = await get_redis()
            return await redis.get(self._answer_cache_key(sql, result))
        except Exception:
            return None

    async def _set_cached_answer(self, sql: str, result: list[dict], answer: str) -> None:
        try:
            from core.redis import get_redis
            redis = await get_redis()
            await redis.setex(self._answer_cache_key(sql, result), SQL_CACHE_TTL, answer)
        except Exception:
            logger.warning("Redis unavailable, skipping answer cache write", exc_info=True)

    async def execute(self, question: str, memory_context: str = "", current_user_id: int | str | None = None, user_role: str | None = None,):
      """Thực thi câu truy vấn SQL được tạo ra từ câu hỏi của người dùng và trả về kết quả.
      Args:
          question (str): Câu hỏi của người dùng về dự án, task.
          user_role (str): Vai trò của người dùng; MEMBER/VIEWER chỉ được hỏi dữ liệu của chính mình.
      Returns:
          dict: Kết quả trả về từ việc thực thi câu truy vấn SQL, bao gồm câu hỏi gốc, câu truy vấn SQL và kết quả truy vấn.
      """
      try:
        sql = await self.generate_sql(
            question, memory_context=memory_context,
            current_user_id=current_user_id, user_role=user_role,
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
      logger.info("DB execution time: %.3fs", elapsed)

      cached_answer = await self._get_cached_answer(sql, result)
      if cached_answer:
          answer = cached_answer
      else:
          answer = await self.summarize_result(question, result, memory_context=memory_context)
          if answer:
              await self._set_cached_answer(sql, result, answer)

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
    async def _main():
        for q in question:
            result = await agent.execute(q)
            print(result)

    asyncio.run(_main())
