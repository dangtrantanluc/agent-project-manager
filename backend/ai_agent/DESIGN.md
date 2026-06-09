# PM-Bot — Tài liệu kỹ thuật chi tiết (Design Document)

> Tài liệu này đi sâu hơn [README.md](README.md): mô tả **từng quyết định thiết kế**, **chiến lược prompt**, **máy trạng thái**, **mô hình dữ liệu**, và **các luồng tuần tự** của hệ thống AI agent. Mục tiêu: đủ chi tiết để một engineer mới hiểu *vì sao* code được viết như vậy và *có thể viết document/onboarding* từ đây.

Mục lục:
1. [Bối cảnh & mục tiêu sản phẩm](#1-bối-cảnh--mục-tiêu-sản-phẩm)
2. [Nguyên tắc kiến trúc](#2-nguyên-tắc-kiến-trúc)
3. [Sơ đồ thành phần](#3-sơ-đồ-thành-phần)
4. [Tầng LLM — vì sao LangChain + OpenAI-compatible](#4-tầng-llm)
5. [Router & điều phối](#5-router--điều-phối)
6. [Text-to-SQL — phân tích sâu lớp an toàn](#6-text-to-sql)
7. [Report Agent — kiến trúc hybrid template-first](#7-report-agent)
8. [Planning Agent — structured output](#8-planning-agent)
9. [Conversation Agent](#9-conversation-agent)
10. [Notification Agent](#10-notification-agent)
11. [Memory — bộ nhớ hội thoại & tóm tắt](#11-memory)
12. [Schema prompt — vì sao "compact"](#12-schema-prompt)
13. [Check-in flow — máy trạng thái đầy đủ](#13-check-in-flow)
14. [Mô hình dữ liệu](#14-mô-hình-dữ-liệu)
15. [Hiệu năng & độ trễ](#15-hiệu-năng--độ-trễ)
16. [Bảo mật](#16-bảo-mật)
17. [Nợ kỹ thuật & rủi ro](#17-nợ-kỹ-thuật--rủi-ro)
18. [Hướng dẫn mở rộng](#18-hướng-dẫn-mở-rộng)

---

## 1. Bối cảnh & mục tiêu sản phẩm

PM-Bot là trợ lý AI nhúng trong hệ thống quản lý dự án nội bộ. Người dùng (PM, member, manager) tương tác bằng **tiếng Việt tự nhiên** qua **Gapo** (nền tảng chat nội bộ) hoặc HTTP API. Bot giải quyết 3 nhóm nhu cầu:

| Nhóm | Ví dụ | Agent phụ trách |
|---|---|---|
| **Hỏi-đáp dữ liệu** (reactive) | "Dự án CRM còn bao nhiêu task?", "Ai quản lý dự án MTL?" | text2sql, report |
| **Sinh nội dung** (generative) | "Lập kế hoạch dự án X", "Soạn thông báo nhắc deadline" | planning, notification |
| **Thu thập dữ liệu** (proactive) | Check-in worklog 2 lần/ngày, nhắc deadline tự động | checkin, notification + scheduler |

**Ràng buộc thiết kế quan trọng:**
- **Người dùng không biết SQL** → mọi truy vấn phải sinh từ ngôn ngữ tự nhiên.
- **LLM không được ghi vào DB** → chỉ đọc; mọi mutation bị chặn ở tầng validate.
- **Độ trễ phải thấp** → chat realtime; chọn model Flash + chạy song song + cache.
- **Không khoá nhà cung cấp LLM** → cấu hình qua biến môi trường.

---

## 2. Nguyên tắc kiến trúc

### 2.1 "Router + specialist agents" thay vì một prompt vạn năng

Một LLM duy nhất với một prompt khổng lồ chứa "hãy làm SQL, hoặc báo cáo, hoặc kế hoạch..." sẽ:
- **chậm** (prompt dài → nhiều token → latency cao),
- **dễ lệch** (model lẫn lộn nhiệm vụ),
- **khó kiểm soát an toàn** (không thể áp lớp validate SQL riêng).

Thay vào đó: một **router nhẹ** phân loại ý định, rồi giao cho **agent chuyên biệt** có prompt + logic + lớp an toàn riêng. Mỗi agent là một class Python độc lập, khởi tạo sẵn một lần trong `AgentMessageRouter.__init__` ([router/message_router.py:31-37](router/message_router.py#L31-L37)).

### 2.2 Phòng thủ nhiều lớp (defense in depth)

Vì LLM sinh SQL chạy thẳng trên DB production, không thể tin LLM. Có **3 lớp**:
1. **Prompt** cấm mutation (LLM được dặn).
2. **`is_safe_sql()`** chặn bằng regex trước khi chạy (LLM bị ép).
3. **Template-first** ở report (SQL viết sẵn, chỉ bind tham số) → bỏ qua LLM-sinh-SQL khi có thể.

### 2.3 Graceful degradation (suy giảm có kiểm soát)

Mọi tầng đều có fallback để không bao giờ "im lặng" hay crash:
- Router LLM lỗi → confidence = 0 → fallback `conversation` ([router.py:134-139](router/router.py#L134-L139)).
- Router trả về `conversation` confidence 0 → **fallback bằng từ khoá** ([message_router.py:131-160](router/message_router.py#L131-L160)).
- Template selector lỗi → freeform SQL ([report_agent.py:132-153](report_generator/report_agent.py#L132-L153)).
- Notification LLM lỗi/không cấu hình → **template tất định** ([notification_agent.py:94-121](notification/notification_agent.py#L94-L121)).
- Exception toàn cục → câu xin lỗi tiếng Việt ([message_router.py:108-119](router/message_router.py#L108-L119)).

### 2.4 Async-first

Toàn pipeline I/O-bound (gọi LLM, query DB, gọi Gapo). FastAPI + `asyncio` cho phép chạy song song 3 việc độc lập (phân loại + memory + profile) bằng `asyncio.gather` ([message_router.py:60-65](router/message_router.py#L60-L65)).

---

## 3. Sơ đồ thành phần

```
                         ┌──────────────────────────────────────┐
   Gapo / HTTP  ───────► │  app/modules/agent/router.py (FastAPI)│
                         └───────────────┬──────────────────────┘
                                         │
                         ┌───────────────▼──────────────────────┐
                         │  CheckinFlowService.handle_message    │  ← intercept TRƯỚC router
                         │  (nếu /checkin hoặc đang trong phiên) │
                         └───────────────┬──────────────────────┘
                                         │ (None → không phải checkin)
                         ┌───────────────▼──────────────────────┐
                         │  AgentMessageRouter.handle_message    │
                         │  • gather(intent, memory, profile)    │
                         │  • _pick_agent + fallback từ khoá     │
                         │  • _run_agent → _format_*             │
                         └──┬────┬────┬────┬────┬────────────────┘
            ┌───────────────┘    │    │    │    └───────────────┐
            ▼          ▼          ▼    ▼                          ▼
     PMMultiAgent  Text2SQL   Report Planning  Conversation  Notification
       Router       Agent      Agent   Agent      Agent         Agent
         │            │          │       │          │             │
         │      ┌─────▼────┐ ┌───▼────┐  │          │       ┌──────▼──────┐
         │      │is_safe   │ │template│  │          │       │fallback     │
         │      │_sql +    │ │registry│  │          │       │template tất │
         │      │asyncpg   │ │(SQL sẵn)│ │          │       │định         │
         │      └──────────┘ └────────┘  │          │       └─────────────┘
         │                                          │
    [Gemini LLM]                          [SCHEMA_COMPACT prompt]
                                                    │
                            ┌───────────────────────▼──────────┐
                            │  memory.load/save (agent_memory)  │
                            │  + tóm tắt mỗi 4 lượt              │
                            └───────────────────────────────────┘
```

---

## 4. Tầng LLM

### 4.1 Vì sao LangChain `ChatOpenAI`?

Mọi agent dùng `from langchain_openai import ChatOpenAI`. Đây **không** có nghĩa là dùng OpenAI — `ChatOpenAI` chỉ là client cho **giao thức OpenAI-compatible**. Bằng cách set `base_url`, ta trỏ tới bất kỳ endpoint nào nói cùng giao thức:

```python
self.llm = ChatOpenAI(
    model=os.getenv("MODEL_NAME"),         # vd "gemini-2.5-flash"
    api_key=os.getenv("API_KEY"),
    base_url=os.getenv("BASE_URL"),        # https://generativelanguage.googleapis.com/v1beta
)
```

**Lợi ích:** đổi từ Gemini sang OpenAI/Azure/local (vLLM, Ollama) chỉ là đổi 3 biến môi trường, không sửa code. Đây là điểm "LLM-agnostic" cốt lõi.

### 4.2 Cấu hình theo từng agent (và vì sao khác nhau)

| Agent | model | timeout | temperature | Lý do |
|---|---|---|---|---|
| Router | `gemini-2.5-flash` (hard-code!) | 10s | mặc định | Phân loại phải nhanh; timeout ngắn để fail-fast |
| Text2SQL | env `MODEL_NAME` | 45s | mặc định | Sinh SQL có thể lâu; cần chính xác (temp thấp) |
| Report | env | 60s | mặc định | Chạy nhiều query + tổng hợp |
| Planning | env | 60s | **0.4** | Sinh kế hoạch cần *một chút* sáng tạo nhưng vẫn bám cấu trúc |
| Conversation | env | mặc định | **0.7** | Trò chuyện cần tự nhiên, đa dạng |
| Notification | env | 60s | mặc định | Sinh nội dung nhắc |
| Memory summary | env `MODEL_NAME` (default `gpt-4o-mini`) | — | **0** | Tóm tắt cần ổn định, không sáng tạo |

> **Lưu ý:** Router là agent **duy nhất** hard-code `model` + `api_key` ngay trong code ([router.py:46-52](router/router.py#L46-L52)) — đây là nợ kỹ thuật (xem §17).

> **Đính chính so với hiểu lầm phổ biến:** `memory.py` dùng client `openai.AsyncOpenAI` *thuần* (không qua LangChain) nhưng vẫn đọc `API_KEY`/`BASE_URL`/`MODEL_NAME` từ env ([memory.py:196-207](memory/memory.py#L196-L207)) — nên nó **vẫn trỏ về Gemini** như phần còn lại; `gpt-4o-mini` chỉ là *default* khi thiếu `MODEL_NAME`, không phải đang thực sự gọi OpenAI.

---

## 5. Router & điều phối

Có **2 lớp** tách biệt: `PMMultiAgentRouter` (phân loại thuần) và `AgentMessageRouter` (điều phối toàn bộ).

### 5.1 `PMMultiAgentRouter` — phân loại ý định ([router/router.py](router/router.py))

**Mô hình confidence + threshold.** LLM trả về điểm tin cậy cho 5 agent (tổng = 1.0). Mỗi agent có ngưỡng riêng; agent được chọn nếu `confidence >= threshold` ([router.py:171-174](router/router.py#L171-L174)):

```python
agent.confidence = confidence_dict.get(agent.name, 0.0)
agent.selected = agent.confidence >= agent.threshold
```

**Vì sao ngưỡng khác nhau** ([router.py:54-80](router/router.py#L54-L80)):

| Agent | Threshold | Triết lý |
|---|---|---|
| `text2sql` | **0.2** | "Default" — đa số câu hỏi PM là truy vấn dữ liệu, để dễ trúng |
| `conversation` | **0.2** | Bắt câu xã giao; cũng là fallback cuối |
| `notification` | 0.5 | Trung bình — chỉ khi rõ ý định nhắc/thông báo |
| `report` | 0.6 | Cao — báo cáo "đắt" (nhiều query), tránh trúng nhầm |
| `planning` | **0.7** | Cao nhất — sinh kế hoạch là tác vụ nặng nhất |

→ Ngưỡng = "chi phí sai" của việc kích hoạt agent đó. Agent càng tốn token/càng đặc thù → ngưỡng càng cao.

**Parser chịu lỗi** (`parse_confidence_json`, [router.py:82-117](router/router.py#L82-L117)). LLM thường trả JSON "bẩn":
1. Bóc markdown fence ` ```json `.
2. Thử `json.loads` trên đoạn `{...}` đầu tiên.
3. Nếu vẫn lỗi (JSON bị cắt cụt thiếu `}`) → **regex từng key** `report: 0.3` để vớt điểm.
4. Nếu trắng tay → log error, trả toàn 0.0.

→ Triết lý: *một lỗi format không được làm sập cả request*.

**Fail-fast:** `timeout=10, max_retries=0` ([router.py:46-48](router/router.py#L46-L48)) — phân loại sai/chậm thì để tầng trên fallback, đừng treo người dùng.

### 5.2 `AgentMessageRouter` — bộ điều phối ([router/message_router.py](router/message_router.py))

`handle_message()` là entry point thực sự ([message_router.py:39](router/message_router.py#L39)). Trình tự:

1. **Chạy song song 3 việc I/O** ([message_router.py:60-65](router/message_router.py#L60-L65)):
   ```python
   selected_task = asyncio.create_task(self.intent_router.selected_agents(message))
   memory_context, user_profile = await asyncio.gather(
       self._load_memory_context_new_session(conversation_id),
       self._load_user_profile_new_session(user_id),
   )
   selected = await selected_task
   ```
   → tiết kiệm latency: phân loại LLM chạy đồng thời với 2 query DB.

2. **Chọn agent** (`_pick_agent`, [message_router.py:121-129](router/message_router.py#L121-L129)): lấy agent đầu danh sách (confidence cao nhất).

3. **Lưới an toàn từ khoá** (`_fallback_agent_for_message`, [message_router.py:131-160](router/message_router.py#L131-L160)): nếu router trả `conversation` + confidence 0 (tức "không chắc"), quét từ khoá tiếng Việt để đoán lại:
   - "lập kế hoạch", "milestone" → `planning`
   - "báo cáo", "thống kê", "tiến độ tổng thể" → `report`
   - "thông báo", "nhắc nhở" → `notification`
   - "dự án", "task", "deadline", "bao nhiêu", "ai là" → `text2sql`
   
   → Đây là phòng tuyến khi LLM phân loại kém — rẻ (chỉ so chuỗi) và đáng tin.

4. **Thực thi** (`_run_agent`, [message_router.py:162-217](router/message_router.py#L162-L217)): dispatch theo `agent_name`, truyền `memory_context` + `user_profile` vào agent.

5. **Định dạng** (`_format_text2sql`, `_format_report`, `_format_planning`, ...): biến output (dict/Pydantic) thành **text gửi được**. Ví dụ `_format_text2sql` ([message_router.py:361-385](router/message_router.py#L361-L385)) ưu tiên `answer` đã diễn giải; nếu không có thì in tối đa 10 dòng dữ liệu thô.

6. **Bọc lỗi**: mọi exception → `AgentReply(agent="error", ...)` với câu xin lỗi.

### 5.3 User profile — vì sao nạp sẵn mỗi tin nhắn

`_load_user_profile` ([message_router.py:241-296](router/message_router.py#L241-L296)) chạy **2 query**:
- Query 1: thông tin user + **đếm task quá hạn** + **deadline gần nhất**.
- Query 2: **dự án đang tham gia** (owner hoặc member, status PLANNED/IN_PROGRESS).

Nhờ đó bot xử lý được "task **của tôi**" mà không hỏi lại, và ConversationAgent chủ động nhắc "bạn có 3 task quá hạn" khi chào.

---

## 6. Text-to-SQL

Agent quan trọng và rủi ro nhất. File: [text_to_sql/text2sql.py](text_to_sql/text2sql.py). Pipeline `execute()` ([text2sql.py:269-316](text_to_sql/text2sql.py#L269-L316)): **generate → validate → execute → summarize**, mỗi tầng có cache và fallback.

### 6.1 Sinh SQL (`generate_sql`, [text2sql.py:159-203](text_to_sql/text2sql.py#L159-L203))

Prompt được lắp ghép động từ nhiều khối:
```
SYSTEM_PROMPT (cố định, có SCHEMA_COMPACT + quy tắc PostgreSQL)
+ tenant_rule        ("single-company, không thêm company_id")
+ user_context_block ("User hiện tại có users.id = 42...")
+ memory_block       (ngữ cảnh hội thoại trước)
+ "Câu hỏi: {question}"
```

**Các quy tắc trong SYSTEM_PROMPT đáng chú ý** ([text2sql.py:65-87](text_to_sql/text2sql.py#L65-L87)) — đều rút từ lỗi thực tế:
- **Cấm cú pháp MySQL**: tuyệt đối không `INTERVAL n DAY` (gây lỗi cú pháp trên PostgreSQL). Phải dùng `INTERVAL '7 days'` hoặc `make_interval(days => n)`.
- **"Tuần này"** = `date_trunc('week', CURRENT_DATE)` (tuần bắt đầu Thứ Hai).
- Chỉ `SELECT`/`WITH`, kết thúc `;`.
- Nếu không trả lời được bằng SQL → trả `SELECT '...' AS message;`.

### 6.2 Lớp an toàn `is_safe_sql` ([text2sql.py:140-157](text_to_sql/text2sql.py#L140-L157))

Đây là lá chắn cốt lõi. Một SQL chỉ "an toàn" khi qua **tất cả**:

```python
def is_safe_sql(self, sql: str) -> bool:
    normalized = self._clean_sql(sql).strip()
    if not normalized.lower().startswith(("select", "with")):   # 1. chỉ đọc
        return False
    if not normalized.endswith(";"):                            # 2. phải có ;
        return False
    if ";" in normalized.rstrip(";"):                           # 3. chặn multi-statement
        return False
    if _NAMED_SQL_PLACEHOLDER.search(normalized):               # 4. không placeholder chưa bind
        return False
    sql_for_check = _NAMED_SQL_PLACEHOLDER.sub("1", normalized)
    if _MUTATION_SQL.search(sql_for_check):                     # 5. chặn mọi mutation keyword
        return False
    return True
```

- Regex mutation chặn: `insert|update|delete|drop|alter|truncate|create|replace|merge|grant|revoke|vacuum|call|do` ([text2sql.py:57-60](text_to_sql/text2sql.py#L57-L60)).
- Chống **SQL injection 2 tầng**: (a) chặn `;` thứ hai → không chèn statement thứ hai; (b) chặn `:named` placeholder chưa bind → LLM không để lộ tham số chưa xử lý.
- Nếu không an toàn → `raise ValueError` ([text2sql.py:188-189](text_to_sql/text2sql.py#L188-L189)) → `execute()` bắt và trả câu "chưa tạo được truy vấn an toàn".

**Binding user_id an toàn:** chỉ `:user_id` được thay bằng giá trị đã ép kiểu int (`_coerce_user_id` → chỉ nhận int dương) ([text2sql.py:116-129](text_to_sql/text2sql.py#L116-L129)). Mọi placeholder khác bị coi là không an toàn.

### 6.3 Thực thi (`execute_sql`, [text2sql.py:205-217](text_to_sql/text2sql.py#L205-L217))

Dùng **asyncpg connection pool** (min 2, max 10 — [text2sql.py:35-43](text_to_sql/text2sql.py#L35-L43)), hỗ trợ positional args `$1,$2` (dùng bởi report templates). Trả `list[dict]`.

### 6.4 Diễn giải kết quả (`summarize_result`, [text2sql.py:237-247](text_to_sql/text2sql.py#L237-L247))

Gọi LLM lần 2 biến rows thô thành câu trả lời tiếng Việt. Prompt ([text2sql.py:220-235](text_to_sql/text2sql.py#L220-L235)) yêu cầu:
- Không lộ SQL/JSON/tên bảng.
- "Đừng chỉ đọc số — nói ý nghĩa" (tốt/chưa tốt, đúng hạn/trễ).
- Nếu rỗng → nói rõ không tìm thấy + gợi ý hỏi cụ thể hơn.

### 6.5 Chiến lược cache (Redis)

Hai cache riêng:
| Cache | Key | Khi nào |
|---|---|---|
| **SQL cache** | `md5(câu hỏi chuẩn hoá + user_id)` | Lưu SQL đã sinh+validate ([text2sql.py:131-134, 192-201](text_to_sql/text2sql.py#L131-L134)) |
| **Answer cache** | `md5(sql + kết quả JSON)` | Lưu câu trả lời đã diễn giải ([text2sql.py:249-267](text_to_sql/text2sql.py#L249-L267)) |

**Bỏ cache cho câu hỏi thời gian tương đối** ([text2sql.py:24-28, 136-138](text_to_sql/text2sql.py#L24-L28)): "hôm nay", "tuần này", "mới nhất"... vì kết quả thay đổi theo ngày — cache sẽ trả dữ liệu cũ.

TTL mặc định 1 giờ (`SQL_CACHE_TTL`). Redis lỗi → bỏ qua cache, không chặn luồng ([text2sql.py:173-174](text_to_sql/text2sql.py#L173-L174)).

---

## 7. Report Agent

File: [report_generator/report_agent.py](report_generator/report_agent.py) + [report_generator/report_templates.py](report_generator/report_templates.py).

### 7.1 Kiến trúc hybrid: template-first, freeform-fallback

`_plan_queries` ([report_agent.py:127-153](report_generator/report_agent.py#L127-L153)) chạy 2 nhánh:

```
select_template (LLM nhỏ: chọn template_id + trích params)
   │
   ├── khớp template + đủ params  →  build_queries()  →  SQL viết sẵn (an toàn)
   │
   └── không khớp / thiếu params  →  generate_report_plan()  →  LLM tự sinh SQL (freeform)
```

**Vì sao template-first?** SQL báo cáo phức tạp (nhiều JOIN, FILTER, date_trunc) — để LLM tự viết mỗi lần thì *chậm* và *dễ sai*. Thay vào đó, viết sẵn SQL đã test, LLM chỉ làm việc dễ: **chọn template nào + điền tham số gì**.

### 7.2 Template registry ([report_templates.py](report_generator/report_templates.py))

4 template có sẵn ([report_templates.py:205-261](report_generator/report_templates.py#L205-L261)):

| template_id | Mục đích | Params |
|---|---|---|
| `project_progress` | Tiến độ 1 dự án (task done/còn/quá hạn, % milestone, giờ log) | `project_kw` (bắt buộc) |
| `period_progress` | Tổng quan mọi dự án trong tuần/tháng | `period` (enum: week/month) |
| `overdue_upcoming` | Task quá hạn + sắp đến hạn (14 ngày) | `scope` (enum), `project_kw` |
| `workload_by_person` | Khối lượng của 1 người (task + giờ tháng) | `person_kw` (bắt buộc) |

Mỗi template trả `{name, sql, args}`. Tài liệu trong docstring đầu file ([report_templates.py:1-17](report_generator/report_templates.py#L1-L17)) nêu rõ ràng buộc an toàn.

### 7.3 Phòng SQL injection trong template

Đây là điểm tinh tế và quan trọng:
- **Tham số chuỗi** (tên dự án, tên người) **KHÔNG nội suy vào SQL** mà truyền qua **positional placeholder `$1`** + `args` ([report_templates.py:78, 94](report_generator/report_templates.py#L78)):
  ```python
  "WHERE p.name ILIKE '%'||$1||'%' ... ", "args": [kw]
  ```
  → asyncpg bind tham số → chống injection.
- **Tham số enum** (period, scope) **KHÔNG nhận text người dùng** mà **map qua whitelist trong code** ([report_templates.py:45-48, 57-59](report_generator/report_templates.py#L45-L48)):
  ```python
  _PERIOD_UNITS = {"week": ("week", "1 week"), "month": ("month", "1 month")}
  ```
  → giá trị enum chỉ dùng để *chọn nhánh SQL*, không bao giờ là input thô.
- So sánh enum bằng `::text` (vd `t.status::text='DONE'`) để **không phụ thuộc tên type** `"TaskStatus"` của DB.

### 7.4 Đồng bộ với is_safe_sql

`execute_report_queries` ([report_agent.py:169-199](report_generator/report_agent.py#L169-L199)) vẫn chạy mỗi query qua `sql_agent.is_safe_sql()` trước khi execute — kể cả SQL từ template. Lớp an toàn áp dụng cho **mọi** đường đi.

### 7.5 `render_catalog` — single source of truth

Prompt selector không hard-code danh sách template mà gọi `report_templates.render_catalog()` ([report_agent.py:70](report_generator/report_agent.py#L70), [report_templates.py:275-284](report_generator/report_templates.py#L275-L284)) → khi thêm template mới vào REGISTRY, prompt tự cập nhật. Tránh lệch giữa code và prompt.

---

## 8. Planning Agent

File: [planning/planning_agent.py](planning/planning_agent.py).

### 8.1 Structured output bằng Pydantic

Đầu ra là 3 model lồng nhau ([planning_agent.py:59-75](planning/planning_agent.py#L59-L75)):
```
ProjectPlan
 ├─ project_name, summary
 └─ milestones: [MilestonePlan]
      ├─ name, goal, estimated_days
      └─ tasks: [TaskPlan]
           └─ title, description, priority, estimated_hours, role
```

LLM được dặn trả **JSON thuần, không markdown** ([planning_agent.py:23-57](planning/planning_agent.py#L23-L57)), sau đó `JsonOutputParser` parse và `ProjectPlan(**plan_dict)` validate ([planning_agent.py:130-132](planning/planning_agent.py#L130-L132)). Pydantic là "hợp đồng" ép LLM trả đúng cấu trúc.

### 8.2 Giới hạn cứng trong prompt

"Tối đa 3 milestones, mỗi milestone tối đa 2 tasks, description ≤ 10 từ" ([planning_agent.py:50-54](planning/planning_agent.py#L50-L54)). Lý do: kế hoạch ngắn gọn, dễ đọc trong chat, và giảm token/latency.

### 8.3 Cá nhân hoá bằng profile

`_build_context_block` ([planning_agent.py:91-107](planning/planning_agent.py#L91-L107)) nhúng tên người lập + dự án đang tham gia → kế hoạch gán role phù hợp.

---

## 9. Conversation Agent

File: [coversation/conversation.py](coversation/conversation.py). *(Lưu ý: thư mục `coversation` viết sai chính tả — thiếu `n`.)*

### 9.1 Fast-path không cần LLM

`get_standard_response` ([conversation.py:112-149](coversation/conversation.py#L112-L149)) xử lý lời chào & yêu cầu trợ giúp **bằng code thuần, không gọi LLM**:
- Lời chào → trả câu chào theo buổi (`_greeting_word` dựa giờ VN) + tên người (lấy tên cuối tiếng Việt) + **gợi ý chủ động** ("Hiện có 3 task quá hạn").
- Yêu cầu trợ giúp ("bạn làm được gì") → menu năng lực tĩnh.

→ Tiết kiệm 1 lần gọi LLM cho các câu phổ biến nhất.

### 9.2 LLM-path cho câu mở

Nếu không phải câu chuẩn → gọi LLM với prompt persona "PM-Bot" ([conversation.py:53-77](coversation/conversation.py#L53-L77)): gọi tên người, ngắn gọn, nhận xét số liệu, chủ động nhắc deadline, **luôn tiếng Việt**. `temperature=0.7` cho tự nhiên. Có **retry 3 lần** ([conversation.py:156-172](coversation/conversation.py#L156-L172)).

### 9.3 Ngữ cảnh thời gian

`_tone_context`/`_now_in_timezone` ([conversation.py:20-37](coversation/conversation.py#L20-L37)) dùng `zoneinfo` với fallback về `Asia/Ho_Chi_Minh` nếu timezone lỗi → bot biết "sáng/chiều/tối".

---

## 10. Notification Agent

File: [notification/notification_agent.py](notification/notification_agent.py).

### 10.1 LLM tuỳ chọn — fallback tất định

Đặc biệt thận trọng vì thông báo theo lịch **không được mất**:
- Nếu thiếu cấu hình LLM → khởi tạo `llm = None`, **log warning** ([notification_agent.py:40-51](notification/notification_agent.py#L40-L51)).
- `prepare_deadline_digest` ([notification_agent.py:82-121](notification/notification_agent.py#L82-L121)): luôn tính `fallback` trước; chỉ gọi LLM nếu có; LLM lỗi/rỗng → dùng fallback template.

### 10.2 Template tất định ([notification_agent.py:158-223](notification/notification_agent.py#L158-L223))

Sinh tin nhắn đầy đủ không cần LLM: phân biệt 1 task vs nhiều task, "đến hạn hôm nay" vs "còn ~2 ngày" (`reminder_type`), gom đếm số task mỗi loại. → Dù LLM down, người dùng vẫn nhận nhắc deadline hữu ích.

---

## 11. Memory

File: [memory/memory.py](memory/memory.py). Bảng `agent_memory`.

### 11.1 Đọc (`load_memory`, [memory.py:99-135](memory/memory.py#L99-L135))

Trả `(summary, recent_turns)`:
- **summary**: bản tóm tắt mới nhất khác rỗng của hội thoại.
- **recent_turns**: tối đa `MAX_TURNS = 5` lượt gần nhất, **đảo thứ tự thành cũ→mới** để LLM đọc tự nhiên.

### 11.2 Ghi + tóm tắt định kỳ (`save_memory`, [memory.py:138-221](memory/memory.py#L138-L221))

- Insert mỗi lượt (user_text, reply_text, tools_used) vào `agent_memory`.
- **Cứ mỗi 4 lượt** (`turn_count % 4 == 0`) → gọi LLM tóm tắt và UPDATE cột `summary` ([memory.py:181-221](memory/memory.py#L181-L221)).
- Prompt tóm tắt ([memory.py:13-53](memory/memory.py#L13-L53)) rất cụ thể: **giữ** tên project/task/người/deadline/giờ/blocker/intent; **bỏ** lời chào/cảm ơn/bảng dài; tối đa 3 câu; `temperature=0`.

**Vì sao tóm tắt?** Lịch sử dài làm prompt phình to và đắt. Tóm tắt nén lại để bot vẫn hiểu follow-up ("dự án đó", "task này") mà không cần nhồi toàn bộ lịch sử.

### 11.3 Multi-tenant linh hoạt

`_has_column`/`_resolve_company_id` ([memory.py:56-97](memory/memory.py#L56-L97)) kiểm tra runtime xem bảng có cột `company_id` không, rồi resolve theo user → company mặc định. Cho phép cùng code chạy ở schema single-company lẫn multi-company.

---

## 12. Schema prompt

File: [prompt/prompt.py](prompt/prompt.py) — hằng `SCHEMA_COMPACT`.

### 12.1 Vì sao "compact"?

Schema đầy đủ (file `init.sql`) rất dài. Nhồi cả vào prompt → tốn token, chậm, và "nhiễu". `SCHEMA_COMPACT` là phiên bản **nén tối đa**, mỗi bảng một dòng:
```
tasks(id,name,status,priority,deadline,end_at,...,project_id,assignee_id,milestone_id,...)
```
Kèm 3 khối: **Relations** (FK), **Enums** (giá trị status hợp lệ), và **Rules** (định nghĩa nghiệp vụ).

### 12.2 Khối "Rules" — đưa tri thức nghiệp vụ vào prompt ([prompt.py:66-86](prompt/prompt.py#L66-L86))

Đây là điểm thông minh: dạy LLM *ngữ nghĩa nghiệp vụ* để khỏi đoán:
```
overdue_task = tasks.deadline<CURRENT_DATE AND tasks.status<>'DONE'
active_project = projects.status NOT IN ('DONE','CANCELLED')
project_progress = DONE tasks / total tasks
```
→ Khi user hỏi "task quá hạn", LLM biết chính xác điều kiện, không tự chế.

Dòng cuối cảnh báo **không query các cột cost/budget đã bị xoá** ([prompt.py:85](prompt/prompt.py#L85)) — ngăn LLM sinh SQL tham chiếu cột không còn tồn tại.

---

## 13. Check-in flow

File: [checkin/service.py](checkin/service.py). Đây là một **máy trạng thái hội thoại** (conversational state machine) cho việc thu thập worklog — phức tạp hơn các agent reactive vì nó **nhiều lượt, có trạng thái lưu DB**.

### 13.1 Intercept trước router

`CheckinFlowService.handle_message` ([service.py:65-97](checkin/service.py#L65-L97)) chạy **trước** intent router. Trả về:
- **string** → đã xử lý, dùng làm reply.
- **`""`** → đã gửi qua `gapo.send_menu/send_message`, không cần reply thêm.
- **`None`** → không liên quan check-in → caller chuyển cho intent router.

3 nhánh:
1. Khớp `CHECKIN_TRIGGER` ("checkin", "/checkin", "check-in") → `start_manual` (restart từ menu dự án).
2. Bắt đầu bằng `CHECKIN_PREFIX` (payload nút bấm) → `_handle_payload`.
3. Có session active → `_continue_flow` (xử lý free-text).

### 13.2 Các trạng thái (`CheckinState`)

```
AWAITING_PROJECT ──(chọn dự án)──► AWAITING_TASK ──(chọn/bỏ qua task)──► AWAITING_UPDATE
                                                                              │
                                                                  (nhập "fix bug 2h")
                                                                              ▼
                                                                         CONFIRMING
                                                                         │        │
                                                            (Thêm worklog)   (Xong)
                                                                  │              ▼
                                                                  └──► AWAITING_TASK   [hoàn tất]
```

### 13.3 Hai chế độ nhập: nút bấm + free-text fallback

Gapo có thể không hỗ trợ quick-reply ở mọi client, nên flow hỗ trợ **cả hai**:
- **Nút bấm** → payload như `proj:42`, `task:7` → `_handle_payload` ([service.py:101-172](checkin/service.py#L101-L172)).
- **Gõ số** ("1") → `_handle_numeric_input` dùng *menu mapping* đã lưu để map số → payload ([service.py:202-211](checkin/service.py#L202-L211)).
- **Gõ tên** ("CRM") → `_handle_text_search` tìm kiếm rồi gửi lại menu lọc ([service.py:213-272](checkin/service.py#L213-L272)).
- **Gõ "hủy"/"bỏ qua"** → map về `P_CANCEL`/`P_SKIP_TASK` ([service.py:191-194](checkin/service.py#L191-L194)).

→ Mỗi lần gửi menu đều lưu `set_state_with_menu_mapping` (atomically set state + lưu ánh xạ số→payload) để fallback số luôn hoạt động.

### 13.4 Nhập worklog & vòng lặp clarify (`_handle_worklog_input`, [service.py:276-396](checkin/service.py#L276-L396))

Bước xử lý tinh vi nhất:
1. **Lưu raw text trước** khi parse (parse có thể fail) ([service.py:285](checkin/service.py#L285)).
2. **Idempotency**: `check_duplicate_worklog` chặn worklog trùng từ cùng message ([service.py:288-295](checkin/service.py#L288-L295)).
3. **LLM parse** số giờ + mô tả (`WorklogParserService`), có truyền **ngữ cảnh clarify** nếu là lượt làm rõ ([service.py:298-300](checkin/service.py#L298-L300)).
4. **Vòng lặp làm rõ tối đa 3 lần** ([service.py:303-323](checkin/service.py#L303-L323)): nếu parse mơ hồ → hỏi lại, giữ `partial_draft`; quá 3 lần → hủy session.
5. **Validate giờ**: 0 < hours ≤ 24 ([service.py:329-334](checkin/service.py#L329-L334)).
6. **Insert worklog** + `apply_worklog_side_effects` (cập nhật tổng giờ...) ([service.py:347-367](checkin/service.py#L347-L367)).
7. Chuyển **CONFIRMING** (chưa hoàn tất — cho phép "thêm worklog khác") ([service.py:370](checkin/service.py#L370)).

### 13.5 Lập lịch

`start_for_user` ([service.py:26-47](checkin/service.py#L26-L47)) được gọi từ scheduler (APScheduler) tại 2 slot: `lunch` (11:50) và `end_day` (17:50) giờ VN. Nếu gửi menu thất bại → ghi audit + giữ session để user `/checkin` khôi phục.

---

## 14. Mô hình dữ liệu

Các bảng chính (từ [SCHEMA_COMPACT](prompt/prompt.py)):

| Bảng | Vai trò |
|---|---|
| `companies`, `currencies` | Tenant + tiền tệ |
| `users` | Người dùng (role: ADMIN/MANAGER/MEMBER/VIEWER/SUPER_ADMIN) |
| `projects` | Dự án (status: PLANNED/PENDING/IN_PROGRESS/DONE/CANCELLED) |
| `members` | Liên kết user ↔ project |
| `milestones` | Cột mốc (có completion_pct, task_count, done_count) |
| `tasks` | Công việc (status: TODO/IN_PROGRESS/DONE/CANCELLED, có deadline, assignee) |
| `task_blockers` | Vướng mắc (severity: LOW/MED/HIGH/CRITICAL) |
| `scopes` | Phạm vi/hạng mục trong task |
| `worklogs` | Log giờ làm (source: manual/checkin/import, slot) |
| `backlogs` | Worklog chờ duyệt (status: PENDING/APPROVED/REJECTED) |
| `agent_memory` | Bộ nhớ hội thoại của bot |
| `agent_follow_ups` | Câu hỏi follow-up bot gửi (status: PENDING/REPLIED/EXPIRED) |

**Enums dùng chung:** `priority: LOW/MEDIUM/HIGH/URGENT`.

> Lịch sử: các cột chi phí/ngân sách (`budget`, `total_cost`, `estimated_*`...) **đã bị xoá**; prompt cấm query chúng ([prompt.py:85](prompt/prompt.py#L85)).

---

## 15. Hiệu năng & độ trễ

Các tối ưu latency, từ "đắt" đến "rẻ":
1. **Cache Redis** (text2sql) — tránh hẳn gọi LLM cho câu lặp.
2. **Template-first** (report) — tránh LLM-sinh-SQL khi có template.
3. **Fast-path không LLM** (conversation) — chào hỏi/trợ giúp xử lý bằng code.
4. **Chạy song song** `asyncio.gather` — phân loại + memory + profile đồng thời.
5. **Model Flash** — Gemini Flash rẻ + nhanh hơn các model lớn.
6. **Fail-fast router** — `timeout=10, max_retries=0`.
7. **Connection pool** asyncpg (min 2, max 10) — tái dùng kết nối.

Mọi bước quan trọng đều có `time.perf_counter()` logging để đo (vd [message_router.py:74, 95-101](router/message_router.py#L74)).

---

## 16. Bảo mật

| Mối đe doạ | Biện pháp |
|---|---|
| LLM sinh SQL phá hoại | `is_safe_sql` chặn mọi mutation; chỉ SELECT/WITH |
| SQL injection (multi-statement) | Chặn `;` thứ hai |
| SQL injection (tham số) | Template dùng positional `$1` + asyncpg bind; enum qua whitelist |
| Lộ tham số chưa bind | Chặn `:named` placeholder |
| Truy cập dữ liệu sai quyền (check-in) | `validate_project_access`, `validate_task_in_project` ([service.py:136-155](checkin/service.py#L136-L155)) |
| Worklog trùng | `check_duplicate_worklog` (idempotency) |

**Rủi ro hiện hữu:** API key Gemini **hard-code** trong [router.py:50](router/router.py#L50) — cần đưa về secret/env.

---

## 17. Nợ kỹ thuật & rủi ro

1. **API key hard-code** trong [router.py:50](router/router.py#L50). Vừa là rủi ro bảo mật, vừa khiến router không LLM-agnostic (đính trực tiếp Gemini). → Chuyển sang `os.getenv`.
2. **Router hard-code `gemini-2.5-flash`** còn agent dùng `MODEL_NAME` → có thể lệch phiên bản model giữa phân loại và xử lý.
3. **Thư mục sai chính tả `coversation/`** (thiếu `n`) → đổi tên phải sửa mọi import ([message_router.py:12](router/message_router.py#L12), [router.py:23](router/router.py#L23)).
4. **Memory default `gpt-4o-mini`** — nếu vô tình thiếu `MODEL_NAME`, code dùng client `openai` thuần với model OpenAI, lệch nhà cung cấp. Nên bỏ default này hoặc đặt default an toàn.
5. **Hai cú pháp DB song song**: agent dùng `asyncpg` (positional `$1`), profile/memory dùng SQLAlchemy `text()` với `:named` + cast enum `::"TaskStatus"`. Lưu ý: trong asyncpg KHÔNG dùng `:param::"Type"`; phải `CAST(:param AS "Type")`.
6. **Phương thức gõ sai tên**: `benmark_time` (đáng lẽ `benchmark_time`) trong report_agent — vô hại nhưng nên sửa.

---

## 18. Hướng dẫn mở rộng

### Thêm một agent mới
1. Tạo class agent trong thư mục riêng, đọc LLM từ env như các agent khác.
2. Thêm `Agent(name=..., description=..., threshold=...)` vào `PMMultiAgentRouter.agents` ([router.py:54-80](router/router.py#L54-L80)) — chọn threshold theo "chi phí sai".
3. Thêm nhánh trong `AgentMessageRouter._run_agent` + một `_format_<agent>` ([message_router.py:162-217](router/message_router.py#L162-L217)).
4. (Tuỳ chọn) thêm từ khoá vào `_fallback_agent_for_message`.
5. Cập nhật prompt phân loại trong `_llm_intent_classification` ([router.py:149-167](router/router.py#L149-L167)).

### Thêm một report template
1. Viết hàm `_build_xxx(params)` trả `[{name, sql, args}]`, dùng `$1` cho chuỗi, whitelist cho enum.
2. Đăng ký vào `REGISTRY` với `ParamSpec`.
3. `render_catalog()` tự đưa vào prompt selector — không cần sửa prompt tay.

### Đổi nhà cung cấp LLM
Đổi `MODEL_NAME`/`API_KEY`/`BASE_URL` trong `.env`. **Nhớ sửa hard-code trong [router.py:46-52](router/router.py#L46-L52)** (nợ kỹ thuật #1).

### Thêm bảng/cột vào schema
Cập nhật `SCHEMA_COMPACT` ([prompt/prompt.py](prompt/prompt.py)) — thêm dòng bảng, FK vào Relations, enum vào Enums, và (nếu có nghiệp vụ) định nghĩa vào Rules để LLM hiểu ngữ nghĩa.

---

## Phụ lục: Luồng tuần tự đầy đủ (text2sql)

```
User: "task của tôi tuần này còn bao nhiêu cái chưa xong?"  (user_id=42)
  │
  ▼ CheckinFlowService.handle_message → None (không phải checkin)
  │
  ▼ AgentMessageRouter.handle_message
  │   ├─ gather:
  │   │    • intent_router → {text2sql: 0.7, ...} → chọn text2sql (≥0.2)
  │   │    • load_memory → "Tóm tắt trước: hỏi về dự án CRM..."
  │   │    • load_user_profile → {full_name, active_projects, overdue_count, ...}
  │   ▼
  ▼ Text2SQLAgent.execute(question, memory_context, current_user_id=42)
  │   ├─ generate_sql:
  │   │    • "tuần này" → _should_cache=False (bỏ cache)
  │   │    • prompt = SYSTEM_PROMPT + "users.id = 42" + memory + câu hỏi
  │   │    • LLM → "SELECT COUNT(*) FROM tasks WHERE assignee_id=42
  │   │             AND status<>'DONE' AND deadline >= date_trunc('week',CURRENT_DATE) ...;"
  │   │    • _bind: :user_id → 42 (đã có sẵn trong SQL)
  │   │    • is_safe_sql → True (SELECT, kết thúc ;, không mutation)
  │   ├─ execute_sql (asyncpg pool) → [{"count": 3}]
  │   ├─ summarize_result (LLM lần 2) → "Tuần này bạn còn 3 task chưa hoàn thành..."
  │   ▼ return {question, sql, result, answer}
  ▼ _format_text2sql → "Tuần này bạn còn 3 task chưa hoàn thành..."
  ▼ save_memory (async; nếu là lượt thứ 4,8,12... → tóm tắt lại)
  ▼ AgentReply{answer, agent="text2sql", confidence=0.7}
  ▼ Gapo gửi tin cho user
```
