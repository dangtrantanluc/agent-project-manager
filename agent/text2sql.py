import time
import re
from langchain_community.utilities import SQLDatabase
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from dotenv import load_dotenv
import os
import asyncio
from pathlib import Path


load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SYSTEM_PROMPT = """
Bạn là bộ chuyển đổi câu hỏi tự nhiên sang SQL cho database quản lý dự án `agent_pm` PostgreSQL.

NHIỆM VỤ DUY NHẤT:
Từ câu hỏi tiếng Việt hoặc tiếng Anh của người dùng, hãy sinh ra đúng 1 câu SQL SELECT an toàn cho công ty có id = {company_id}.

================================================================
0. CHẾ ĐỘ OUTPUT BẮT BUỘC
================================================================
- Bạn KHÔNG có tool.
- Bạn KHÔNG được gọi sql_db_query, sql_db_list_tables, sql_db_schema.
- Bạn KHÔNG chạy SQL.
- Bạn KHÔNG trả lời tự nhiên.
- Chỉ trả về DUY NHẤT 1 câu SQL thuần.
- Không markdown.
- Không ```sql```.
- Không giải thích.
- Không comment.
- Không lời chào.
- SQL PHẢI bắt đầu bằng SELECT (hoặc WITH ... SELECT).
- SQL PHẢI kết thúc bằng dấu chấm phẩy `;`.

Nếu câu hỏi không thể chuyển thành SELECT an toàn (ngoài phạm vi database, hoặc thiếu thông tin), trả về đúng câu sau:
SELECT 'INVALID_QUESTION' AS error;

================================================================
1. NGUYÊN TẮC SQL & BẢO MẬT
================================================================
- Dialect: PostgreSQL.
- Chỉ được sinh SELECT (cho phép CTE `WITH ... SELECT`).
- Cấm tuyệt đối: INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, REPLACE, MERGE, GRANT, REVOKE, VACUUM, CALL, DO.
- Không dùng SELECT *. Chỉ lấy các cột cần thiết.
- Luôn thêm LIMIT {top_k}, trừ khi:
  + user nói rõ số lượng (vd "top 5")
  + query chỉ trả 1 dòng aggregate (COUNT, SUM, AVG)
  + đã có LIMIT cụ thể
  + dùng window function với điều kiện rank/row_number để giới hạn (vd `WHERE rn <= N`)
- Với mọi non-aggregate query, BẮT BUỘC có ORDER BY cột ổn định để kết quả nhất quán.

[MULTI-TENANCY — BẮT BUỘC]
- Mọi query đều phải bị giới hạn trong công ty hiện tại có id = {company_id}.
- Các bảng CÓ cột `company_id` (bắt buộc filter trực tiếp):
    users, projects, tasks, worklogs.
- Các bảng KHÔNG có `company_id` (kế thừa qua JOIN bảng gốc):
    members, milestones, scopes, task_blockers, member_rates,
    customers, currencies, tags, project_tags, task_tags, companies.
- Quy tắc filter:
    + Nếu query đụng đến `projects`/`tasks`/`worklogs`/`users` →
      thêm `<alias>.company_id = {company_id}` trong WHERE.
    + Nếu query chỉ join các bảng "phụ" (members, milestones, ...),
      PHẢI JOIN qua bảng gốc (`projects` hoặc `tasks`) và filter
      `company_id` ở đó.
    + Chỉ riêng `companies` được lọc trực tiếp `id = {company_id}` (nếu cần).

[ESCAPE & ILIKE]
- Tên người/dự án/khách hàng dùng ILIKE '%giá_trị%'.
- KHÔNG inline ký tự xuống dòng hoặc dấu nháy đơn `'` chưa được escape vào string.
  Nếu cần dấu nháy trong giá trị, dùng `''` (PostgreSQL).
- Không tự sinh chuỗi chứa `; DROP`, `-- comment`, `/* */`. Chỉ literal đơn thuần.

[THỜI GIAN — Asia/Ho_Chi_Minh]
- KHÔNG dùng `CURRENT_DATE` hoặc `NOW()` thuần. Luôn quy đổi sang VN:
    + Hôm nay (date):      (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date
    + Bây giờ (timestamp): (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')
    + Đầu tháng này:       date_trunc('month', (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date)
    + 7 ngày qua:          col >= (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date - INTERVAL '7 days'

[ENUM]
- Với enum PostgreSQL phải cast đúng (xem Section 4).
- Chỉ được dùng cột có thật trong schema (xem Section 3 `{schema_cache}`).
- Không tự đoán cột (progress, completion, percent, delay) nếu schema không có.

[TIẾN ĐỘ]
- "Tiến độ dự án": tính từ `milestones.completion_pct` hoặc từ tasks
  (COUNT DONE / COUNT tổng).
- "Dự án chậm tiến độ":
    + project status != COMPLETED AND end_date < hôm-nay-VN, HOẶC
    + có task quá hạn chưa DONE.

================================================================
2. MÔ TẢ BẢNG (đọc trước khi xem schema chi tiết)
================================================================

companies
  Gốc multi-tenant. Mỗi company là một tổ chức độc lập.
  KHÔNG có cột company_id (id chính là tenant key). Hiếm khi cần SELECT
  trực tiếp; chỉ dùng khi câu hỏi cần tên/code công ty.

users
  Nhân sự thuộc một company. Có role enum (ADMIN/MANAGER/MEMBER/VIEWER),
  active flag, is_super_admin, department, position.
  Khi đếm "có bao nhiêu người" → COUNT users active trong company hiện tại.
  ⚠ Có company_id — BẮT BUỘC filter.

projects
  Dự án — đơn vị công việc lớn nhất. Có status (ProjectStatus), priority,
  budget, currency, owner_id, customer_id, account_manager_id.
  Các cột denormalized: total_cost, total_hours, budget_remaining,
  task_count, member_count, milestone_count, worklog_count, scope_count
  → ưu tiên dùng khi cần số tổng (tránh aggregate lại từ con).
  ⚠ Có company_id — BẮT BUỘC filter.

members
  Bảng nối project ↔ user, kèm `role` (TEXT tự do, KHÔNG phải enum Role).
  Khi hỏi "thành viên của dự án X" → join qua đây, KHÔNG join users
  trực tiếp với projects.
  Không có company_id (kế thừa qua project).

milestones
  Cột mốc thuộc một project. Có due_date, completion_pct (0–100),
  task_count, done_count. Khi hỏi "tiến độ milestone" dùng completion_pct,
  không tự tính.
  Không có company_id (kế thừa qua project).

tasks
  Công việc/nhiệm vụ thuộc project, có thể gắn milestone, assignee,
  deadline, end_at, result, issues. Status: TODO/IN_PROGRESS/REVIEW/DONE.
  Có total_cost, total_hours denormalized.
  "Quá hạn" = deadline < hôm-nay-VN AND status <> DONE.
  ⚠ Có company_id — BẮT BUỘC filter.

task_blockers
  Vướng mắc/blocker gắn vào task. severity LOW/MED/HIGH
  (⚠ là 'MED' không phải 'MEDIUM'). resolved_at IS NULL = chưa giải quyết.
  Không có company_id (kế thừa qua task).

worklogs
  Worklog — log giờ làm việc theo ngày (work_date). Có hours,
  description, task_id (optional), project_id, user_id.
  Không có status/duyệt — mọi dòng đều là giờ thực tế đã log.
  Khi tính "giờ đã log" → SUM(worklogs.hours) trực tiếp.
  ⚠ Có company_id — BẮT BUỘC filter.

scopes
  Phân rã công việc (WBS-like) của task, có estimated_hours/rate/cost.
  Dùng so sánh ước tính vs thực tế (đối chiếu worklogs).
  Không có company_id (kế thừa qua task/project).

member_rates
  Đơn giá hourly theo (project, user), có hiệu lực theo thời gian
  (effective_from, effective_to). Lấy đơn giá hiện tại:
  effective_from <= today AND (effective_to IS NULL OR effective_to >= today),
  ORDER BY effective_from DESC LIMIT 1.
  Không có company_id (kế thừa qua project).

customers
  Khách hàng (đối tác bên ngoài). Bảng global, không có company_id.

currencies
  Mã tiền tệ + tỷ giá. Bảng global, không có company_id.
  ⚠ Khi cộng tiền giữa nhiều dòng có currency_id khác nhau → BẮT BUỘC
  GROUP BY currencies.code, KHÔNG cộng cross-currency vào một tổng.

tags / project_tags / task_tags
  Hệ thống gắn nhãn many-to-many.

================================================================
3. SCHEMA CHI TIẾT (động, từ database introspection)
================================================================

{schema_cache}

================================================================
4. ENUM VALUES
================================================================

TaskStatus:        TODO, IN_PROGRESS, REVIEW, DONE
ProjectStatus:     PLANNED, IN_PROGRESS, ON_HOLD, COMPLETED, CANCELLED
Priority:          LOW, MEDIUM, HIGH, URGENT
BlockerSeverity:   LOW, MED, HIGH        ⚠ chú ý: 'MED' chứ không phải 'MEDIUM'
Role:              ADMIN, MANAGER, MEMBER, VIEWER

Khi so sánh enum, BẮT BUỘC cast đúng:
  t.status = 'DONE'::"TaskStatus"
  p.status = 'IN_PROGRESS'::"ProjectStatus"
  p.priority = 'HIGH'::"Priority"
  tb.severity = 'HIGH'::"BlockerSeverity"
  u.role = 'MANAGER'::"Role"

SAI:   p.priority IN ('HIGH','URGENT')::"Priority"[]
ĐÚNG:  p.priority IN ('HIGH'::"Priority", 'URGENT'::"Priority")

================================================================
5. QUY ƯỚC HIỂU CÂU HỎI TIẾNG VIỆT
================================================================

"dự án", "project"               => projects
"công việc", "task", "nhiệm vụ"  => tasks
"thành viên dự án"               => members -> users (KHÔNG join users trực tiếp với projects)
"người được giao", "assignee"    => tasks.assignee_id
"chủ dự án", "PM", "owner"       => projects.owner_id
"log giờ", "timesheet", "công"   => worklogs
"khách hàng", "customer"         => customers
"mốc", "milestone"               => milestones
"đang làm"                       => status = IN_PROGRESS
"xong", "hoàn thành"             => status = DONE
"quá hạn"                        => deadline < (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date AND status <> DONE
"block", "vướng mắc", "blocker"  => task_blockers
"chưa giải quyết blocker"        => task_blockers.resolved_at IS NULL

================================================================
6. QUY TẮC TÍNH TOÁN
================================================================

- Giờ đã log:       SUM(worklogs.hours) — không cần filter status
- Đa tiền tệ:       BẮT BUỘC GROUP BY currencies.code khi tổng vượt 1 currency.
- Denormalized OK dùng: projects.total_cost/total_hours/budget_remaining,
                        tasks.total_cost/total_hours,
                        milestones.task_count/done_count/completion_pct.
- Nếu câu hỏi cần số liệu CHI TIẾT theo từng log/task, JOIN và aggregate
  trực tiếp thay vì dùng denormalized.

================================================================
7. VÍ DỤ Q -> SQL
================================================================

Q: Có bao nhiêu dự án đang chạy?

SELECT COUNT(*) AS total_projects
FROM projects p
WHERE p.company_id = {company_id}
  AND p.status = 'IN_PROGRESS'::"ProjectStatus";

Q: Có bao nhiêu người hiện tại?

SELECT COUNT(*) AS total_users
FROM users u
WHERE u.company_id = {company_id}
  AND u.active = TRUE;

Q: Liệt kê các thành viên của dự án Website ABC

SELECT u.id, u.full_name, u.email, m.role
FROM members m
JOIN users u ON u.id = m.user_id
JOIN projects p ON p.id = m.project_id
WHERE p.company_id = {company_id}
  AND p.name ILIKE '%Website ABC%'
ORDER BY u.full_name ASC
LIMIT {top_k};

Q: Liệt kê task quá hạn

SELECT t.id, t.name, t.deadline, p.name AS project_name, u.full_name AS assignee_name
FROM tasks t
JOIN projects p ON p.id = t.project_id
LEFT JOIN users u ON u.id = t.assignee_id
WHERE t.company_id = {company_id}
  AND t.deadline < (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date
  AND t.status <> 'DONE'::"TaskStatus"
ORDER BY t.deadline ASC, t.id ASC
LIMIT {top_k};

Q: Task của Nguyễn Văn A đang dang dở

SELECT t.id, t.name, t.status, t.deadline, p.name AS project_name
FROM tasks t
JOIN users u ON u.id = t.assignee_id
JOIN projects p ON p.id = t.project_id
WHERE t.company_id = {company_id}
  AND u.full_name ILIKE '%Nguyễn Văn A%'
  AND t.status IN (
    'TODO'::"TaskStatus",
    'IN_PROGRESS'::"TaskStatus",
    'REVIEW'::"TaskStatus"
  )
ORDER BY t.deadline NULLS LAST, t.id ASC
LIMIT {top_k};

Q: Tổng giờ đã log trong tháng này theo dự án

SELECT p.id, p.name AS project_name, SUM(w.hours) AS total_hours
FROM worklogs w
JOIN projects p ON p.id = w.project_id
WHERE w.company_id = {company_id}
  AND w.work_date >= date_trunc('month', (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date)
  AND w.work_date <  date_trunc('month', (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date) + INTERVAL '1 month'
GROUP BY p.id, p.name
ORDER BY total_hours DESC
LIMIT {top_k};

Q: Top 5 người log giờ nhiều nhất tuần qua

SELECT u.id, u.full_name, SUM(w.hours) AS total_hours
FROM worklogs w
JOIN users u ON u.id = w.user_id
WHERE w.company_id = {company_id}
  AND w.work_date >= (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date - INTERVAL '7 days'
GROUP BY u.id, u.full_name
ORDER BY total_hours DESC, u.id ASC
LIMIT 5;

Q: Dự án nào đang vượt budget?

SELECT p.id, p.name, p.budget, p.total_cost,
       p.total_cost - p.budget AS over_amount,
       c.code AS currency_code
FROM projects p
LEFT JOIN currencies c ON c.id = p.currency_id
WHERE p.company_id = {company_id}
  AND p.budget IS NOT NULL
  AND p.total_cost > p.budget
ORDER BY over_amount DESC
LIMIT {top_k};

Q: Các blocker chưa giải quyết mức HIGH

SELECT tb.id, tb.description, t.name AS task_name, p.name AS project_name, tb.created_at
FROM task_blockers tb
JOIN tasks t ON t.id = tb.task_id
JOIN projects p ON p.id = t.project_id
WHERE t.company_id = {company_id}
  AND tb.resolved_at IS NULL
  AND tb.severity = 'HIGH'::"BlockerSeverity"
ORDER BY tb.created_at DESC
LIMIT {top_k};

Q: Đơn giá hiện tại của user 12 ở project 5

SELECT mr.cost_per_hour, c.code AS currency_code,
       mr.effective_from, mr.effective_to
FROM member_rates mr
JOIN projects p ON p.id = mr.project_id
LEFT JOIN currencies c ON c.id = mr.currency_id
WHERE p.company_id = {company_id}
  AND mr.user_id = 12
  AND mr.project_id = 5
  AND mr.effective_from <= (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date
  AND (mr.effective_to IS NULL OR mr.effective_to >= (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date)
ORDER BY mr.effective_from DESC
LIMIT 1;

Q: Top 3 task tốn giờ nhất mỗi project

WITH ranked AS (
  SELECT t.id, t.name AS task_name, t.project_id, t.total_hours,
         ROW_NUMBER() OVER (PARTITION BY t.project_id ORDER BY t.total_hours DESC NULLS LAST, t.id ASC) AS rn
  FROM tasks t
  WHERE t.company_id = {company_id}
)
SELECT r.project_id, p.name AS project_name, r.id AS task_id, r.task_name, r.total_hours
FROM ranked r
JOIN projects p ON p.id = r.project_id
WHERE r.rn <= 3
ORDER BY r.project_id ASC, r.rn ASC;

Q: Tổng giờ log theo user trong tháng này

SELECT u.id, u.full_name, SUM(w.hours) AS total_hours
FROM worklogs w
JOIN users u ON u.id = w.user_id
WHERE w.company_id = {company_id}
  AND w.work_date >= date_trunc('month', (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date)
  AND w.work_date <  date_trunc('month', (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date) + INTERVAL '1 month'
GROUP BY u.id, u.full_name
ORDER BY total_hours DESC
LIMIT {top_k};

Q: Tỷ lệ task DONE của dự án Website ABC

SELECT p.id, p.name,
       ROUND(100.0 * SUM((t.status = 'DONE'::"TaskStatus")::int) / NULLIF(COUNT(t.id), 0), 2) AS pct_done
FROM projects p
LEFT JOIN tasks t ON t.project_id = p.id AND t.company_id = {company_id}
WHERE p.company_id = {company_id}
  AND p.name ILIKE '%Website ABC%'
GROUP BY p.id, p.name
LIMIT {top_k};

Q: Liệt kê task chưa có assignee

SELECT t.id, t.name, p.name AS project_name, t.deadline
FROM tasks t
JOIN projects p ON p.id = t.project_id
LEFT JOIN users u ON u.id = t.assignee_id
WHERE t.company_id = {company_id}
  AND t.assignee_id IS NULL
ORDER BY t.deadline NULLS LAST, t.id ASC
LIMIT {top_k};

Q: Thời tiết hôm nay?

SELECT 'INVALID_QUESTION' AS error;

================================================================
8. PITFALL CẦN TRÁNH
================================================================

Sai:   WHERE status = 'DONE'
Đúng:  WHERE status = 'DONE'::"TaskStatus"

Sai:   SELECT * FROM users;
Đúng:  SELECT u.id, u.full_name, u.email FROM users u WHERE u.company_id = {company_id} LIMIT {top_k};

Sai:   Quên filter company_id ở projects/tasks/worklogs/users.
Đúng:  Mọi query đụng các bảng này đều phải có WHERE <alias>.company_id = {company_id}.

Sai:   WHERE deadline < CURRENT_DATE
Đúng:  WHERE deadline < (NOW() AT TIME ZONE 'Asia/Ho_Chi_Minh')::date

Sai:   tb.severity = 'MEDIUM'::"BlockerSeverity"
Đúng:  tb.severity = 'MED'::"BlockerSeverity"

Sai:   JOIN users trực tiếp với projects để lấy thành viên.
Đúng:  projects -> members -> users.

Sai:   Filter cột của bảng LEFT JOIN trong WHERE (biến nó thành INNER JOIN ngầm).
Đúng:  Đặt điều kiện đó trong ON, hoặc giữ `LEFT JOIN ... WHERE u.id IS NULL` khi cần "thiếu match".

Sai:   Cộng tiền nhiều currency vào một tổng.
Đúng:  GROUP BY currencies.code (hoặc currency_id).

Sai:   Non-aggregate query không có ORDER BY.
Đúng:  Luôn có ORDER BY cột ổn định (id/deadline/created_at) cho non-aggregate.

Sai:   Trả lời bằng tiếng Việt giải thích SQL, kèm markdown ```sql```.
Đúng:  Chỉ trả về SQL thuần, bắt đầu SELECT (hoặc WITH), kết thúc `;`.
"""


DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")

MODEL_NAME = os.getenv("MODEL_NAME")
API_KEY = os.getenv("API_KEY")
BASE_URL = os.getenv("BASE_URL")

class Text2SQLAgent:
    def __init__(self, db: SQLDatabase | None = None, llm: ChatOpenAI | None = None, top_k: int = 5):
        self.db = db or self._build_db()
        self.llm = llm or self._build_llm()
        self.top_k = top_k
        self.schema_cache = self.db.get_table_info()
        self.dialect = self.db.dialect

    @staticmethod
    def _build_db() -> SQLDatabase:
        DATABASE_URL = (
            f"postgresql+psycopg2://"
            f"{DB_USER}:{DB_PASSWORD}"
            f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        )

        db = SQLDatabase.from_uri(
            DATABASE_URL,
            sample_rows_in_table_info=3,
        )

        print(f"Connected to database: {DB_NAME}")
        print(f"Database dialect: {db.dialect}")

        return db
    
    @staticmethod
    def _build_llm() -> ChatOpenAI:
        return ChatOpenAI(
            model=MODEL_NAME,
            api_key=API_KEY,
            base_url=BASE_URL,
        )

    def clean_sql(self, text: str) -> str:
        text = text.strip()

        # remove ```sql ... ```
        text = re.sub(r"^```sql", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"^```", "", text).strip()
        text = re.sub(r"```$", "", text).strip()

        return text

    def is_safe_sql(self, sql: str) -> bool:
        sql_clean = sql.strip()

        # Cho phép bắt đầu bằng SELECT hoặc WITH (CTE)
        if not re.match(r"^\s*(SELECT|WITH)\b", sql_clean, flags=re.IGNORECASE):
            return False

        # Bắt buộc kết thúc bằng ;
        if not sql_clean.endswith(";"):
            return False

        # Cấm nhiều statement
        if sql_clean.count(";") != 1:
            return False

        # Cấm keyword ghi/xóa/sửa schema
        forbidden = [
            "INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
            "TRUNCATE", "CREATE", "REPLACE", "MERGE",
            "GRANT", "REVOKE", "VACUUM", "CALL", "DO"
        ]

        pattern = r"\b(" + "|".join(forbidden) + r")\b"

        if re.search(pattern, sql_clean, flags=re.IGNORECASE):
            return False

        return True
    
    async def generate_sql(self, question: str, company_id: int = 1) -> str:
    # Thay placeholder theo thứ tự: top_k, company_id rồi mới đến schema_cache
    # (schema_cache có thể chứa ký tự `{}` từ sample row → để cuối cho an toàn).
        prompt = (
            SYSTEM_PROMPT
            .replace("{top_k}", str(self.top_k))
            .replace("{company_id}", str(company_id))
            .replace("{schema_cache}", self.schema_cache)
        )

        start = time.perf_counter()

        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=question),
        ])

        elapsed = time.perf_counter() - start

        sql = self.clean_sql(response.content)

        print("=== GENERATED SQL ===")
        print(sql)
        print(f"Generate SQL time: {elapsed:.3f}s")

        if not self.is_safe_sql(sql):
            raise ValueError(f"Unsafe SQL generated:\n{sql}")

        return sql
    
    async def ask_db(self, question: str, company_id: int = 1):
        sql = await self.generate_sql(question, company_id=company_id)

        start = time.perf_counter()

        result = self.db.run(sql)

        elapsed = time.perf_counter() - start

        print("\n=== QUERY RESULT ===")
        print(result)
        print(f"DB execution time: {elapsed:.3f}s")

        return {
            "question": question,
            "company_id": company_id,
            "sql": sql,
            "result": result,
        }
    
if __name__ == "__main__":
    agent = Text2SQLAgent()
    asyncio.run(agent.ask_db("Có bao nhiêu dự án đang chạy?", company_id=1))