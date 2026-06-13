# Kiến Trúc Hệ Thống Agent-PM (Full: Frontend → Backend → Agent)

> Sơ đồ dựng từ code thực tế: `frontend/`, `backend/app/modules/`, `backend/ai_agent/`, `backend/gapo/`, `docker-compose.yml`.

---

## 1. Sơ đồ tổng thể (container / service)

```mermaid
flowchart TB
    %% Tầng 1: Client
    WEB["Web"]
    GAPO["Gapo"]

    %% Tầng 2: Cổng vào
    SPA["Frontend SPA (React)"]
    WH["Webhook /gapo"]

    %% Tầng 3: Backend
    REST["REST API /api/v1"]
    AGENT["Lớp AI Agent"]

    %% Tầng 4: Xử lý phụ
    BIZ["API nghiệp vụ"]
    SCHED["Scheduler"]

    %% Tầng 5: Lưu trữ + LLM
    PG[("PostgreSQL")]
    REDIS[("Redis")]
    MINIO[("MinIO")]
    LLM["Gemini API"]

    %% ── Luồng đi xuống ──
    WEB <--> SPA
    GAPO -->|webhook| WH
    SPA <-->|"request / JSON·status"| REST
    WH --> AGENT
    REST <--> BIZ
    BIZ --> AGENT
    SCHED --> AGENT
    BIZ <--> PG
    BIZ <--> MINIO
    SCHED <--> PG
    AGENT <--> PG
    AGENT <--> REDIS
    AGENT --> LLM

    %% ── Phản hồi ngược ──
    AGENT -.->|tin trả lời| GAPO

    classDef client fill:#dbeafe,stroke:#2563eb,color:#0b2545;
    classDef fe fill:#ffedd5,stroke:#ea580c,color:#3a1d00;
    classDef be fill:#dcfce7,stroke:#16a34a,color:#06381b;
    classDef store fill:#ede9fe,stroke:#7c3aed,color:#2b0f57;
    classDef llm fill:#fee2e2,stroke:#dc2626,color:#4a0a0a;

    class GAPO,WEB client;
    class SPA fe;
    class REST,WH,BIZ,AGENT,SCHED be;
    class PG,REDIS,MINIO store;
    class LLM llm;
```

**Ghi chú đường mạng quan trọng:**
- FE gọi BE qua `/api/v1` (axios + JWT trong header).
- Webhook Gapo vào **thẳng backend:8000** qua router NAT (WAN 3637) — **không qua nginx**; backend phải publish cổng 8000.
- Toàn bộ lời gọi LLM đi tới **Gemini API**. Các agent đọc cấu hình từ env (`MODEL_NAME`/`BASE_URL`/`API_KEY`); riêng intent router (`PMMultiAgentRouter`) **hardcode** model + key trong source — xem mục 4.2.

---

## 2. Frontend (chi tiết)

```mermaid
flowchart LR
    PAGES["Pages / UI"]
    STATE["State<br/>zustand + react-query"]
    API["axios client<br/>(+JWT · bắt 401)"]
    BE["FastAPI /api/v1"]

    PAGES <--> STATE
    STATE <--> API
    API -->|request + JWT| BE
    BE -.->|JSON · status| API

    classDef c fill:#fff3e0,stroke:#e08a00;
    class PAGES,STATE,API c;
```

**Luồng phản hồi quay lại (FE):**
- **Thành công:** response JSON → react-query ghi vào cache → component re-render. Mutation thành công thì `invalidateQueries` để đồng bộ lại.
- **401 Unauthorized:** response interceptor ([apiClient.ts:20-31](../frontend/src/lib/apiClient.ts#L20-L31)) gọi `useAuth.clear()` rồi `window.location.assign("/login")` (chỉ khi đang có token, tránh vòng lặp tại trang login).
- **Lỗi khác (4xx/5xx):** `Promise.reject(error)` → component/`onError` của react-query hiển thị thông báo.
- **Polling chủ động (server → UI một chiều logic):** `NotificationBell` & `AgentAuditPage` đặt `refetchInterval: 30_000` ([NotificationBell.tsx:25](../frontend/src/components/NotificationBell.tsx#L25)) — cứ 30s tự gọi lại API để kéo dữ liệu mới (FR-11), không cần WebSocket.
- **Kanban kéo-thả + bảng** cho Projects/Tasks; optimistic update qua react-query (cập nhật cache ngay, rollback nếu response lỗi).

---

## 3. API nghiệp vụ (19 module REST)

```mermaid
flowchart LR
    FE["FE"] <-->|request / JSON·status| MODULES
    subgraph MODULES["API nghiệp vụ — 19 module (app/modules/)"]
        direction TB
        M1["auth · users · admin"]
        M2["projects · tasks · worklogs ..."]
        M3["dashboard · notifications · meetings"]
        M4["uploads · agent · agent_audit"]
    end
    MODULES <-->|query / rows| PG[("PostgreSQL")]
    M4 <-->|upload / URL| MINIO[("MinIO")]

    classDef m fill:#e7f7ec,stroke:#2e9e54;
    class M1,M2,M3,M4 m;
```

- **Chiều phản hồi:** module trả Pydantic model → FastAPI serialize JSON + status; lỗi nghiệp vụ ném `HTTPException` → client nhận status + `detail`.

- Auth: JWT (`user_id, email, role`); service-to-service cho agent qua header `X-Agent-Token`.
- Phân quyền 2 lớp: theo **vai trò** (ADMIN/MANAGER/MEMBER/VIEWER) và theo **membership dự án**.

---

## 4. Lớp AI Agent — luồng xử lý 1 tin nhắn Gapo

### 4.1. Các điểm gác (gate) trong `GapoAdapter.handle_event` — TRƯỚC khi vào router

> Một tin nhắn phải vượt qua **6 cửa kiểm tra tuần tự** trong [gapo_adapter.py](../backend/gapo/gapo_adapter.py). Mỗi cửa có thể trả lời ngay và **dừng luồng** — chỉ tin nào lọt hết mới tới `AgentMessageRouter`. Đây là phần luồng quan trọng nhất và là nơi sinh ra các hành vi "lệnh không nhận diện" / "tin bị nuốt".

```mermaid
flowchart TB
    START["POST /webhook/gapo<br/>GapoAdapter.handle_event"] --> G0

    G0{"verify_signature<br/>HMAC-SHA256?"}
    G0 -->|sai chữ ký| R0["❌ invalid_signature"]
    G0 -->|hợp lệ / dev| G1

    G1{"event == message_created<br/>& có message?"}
    G1 -->|thread_created / khác| R1["⏭️ ignored"]
    G1 -->|ok| G2

    G2{"_extract_user_text<br/>có nội dung text?"}
    G2 -->|rỗng (sticker/ảnh/<br/>attachment)| R2["💬 'Mình chưa đọc được<br/>nội dung tin nhắn này.'"]
    G2 -->|có text| G3

    G3{"message_type ∈<br/>text/quick_reply/menu?"}
    G3 -->|loại khác| R3["💬 'Chỉ hỗ trợ tin nhắn văn bản.'"]
    G3 -->|ok| G4

    G4{"text bắt đầu '/link'?"}
    G4 -->|có| R4["🔗 _handle_link_command<br/>(tự liên kết tài khoản)"]
    G4 -->|không| G5

    G5{"_lookup_gapo_user<br/>đã map & active?"}
    G5 -->|chưa map| R5["🚫 'Tài khoản chưa được<br/>liên kết với hệ thống.'"]
    G5 -->|đã map| CK

    CK["CheckinFlowService.handle_message<br/>(chặn trước router)"]
    CK --> CKD{"trả về?"}
    CKD -->|str ≠ ''| RCK["✅ gửi reply check-in"]
    CKD -->|'' (đã gửi menu)| RCK2["✅ đã gửi qua send_menu"]
    CKD -->|None (không liên quan)| RT["➡️ AgentMessageRouter.handle_message"]

    classDef gate fill:#fff7e6,stroke:#d48806,color:#5c3a00;
    classDef stop fill:#fff1f0,stroke:#cf1322,color:#5c0011;
    classDef pass fill:#f6ffed,stroke:#389e0d,color:#135200;
    class G0,G1,G2,G3,G4,G5,CKD gate;
    class R0,R1,R2,R3,R5 stop;
    class R4,RCK,RCK2,RT,CK pass;
```

**⚠️ Hai điểm dễ gây bug đã xác nhận trong code:**
- **Checkin chặn trước router** ([gapo_adapter.py:185-194](../backend/gapo/gapo_adapter.py#L185-L194)): nếu user còn 1 *active check-in session*, MỌI tin (kể cả "cook") bị diễn giải thành thao tác trong flow check-in → không tới được agent LLM.
- **`/checkin` neo `$`** trong `CHECKIN_TRIGGER` ([constants.py:5](../backend/ai_agent/checkin/constants.py#L5)) — `^/?(checkin|check[\s\-]?in)$`: gõ thừa chữ ("/checkin đi") **không khớp** → lệnh không kích hoạt, rơi xuống LLM và bị "bịa" trả lời.

### 4.2. Bên trong `AgentMessageRouter` — phân loại, chạy song song, gộp

```mermaid
sequenceDiagram
    participant AD as GapoAdapter
    participant RT as AgentMessageRouter
    participant IR as PMMultiAgentRouter<br/>(intent · Gemini)
    participant MEM as Memory
    participant PRF as Profile
    participant AG as Agents (song song)
    participant L9 as Gemini API (qua env)
    participant DB as PostgreSQL
    participant GMNI as Gemini API (trực tiếp)

    AD->>RT: handle_message(message, user_id, conv_id, db)

    par Nạp song song (asyncio.gather — giảm trễ)
        RT->>IR: selected_agents(text)
        IR->>GMNI: classify intent (reasoning_effort=none)
        GMNI-->>IR: ["text2sql","report",...]
        IR-->>RT: list tên agent (đã validate VALID_AGENTS)
    and
        RT->>MEM: load_memory (≤5 lượt + tóm tắt)
    and
        RT->>PRF: load_user_profile (tên, role, dự án, task quá hạn)
    end

    RT->>RT: _fallback_agent_for_message<br/>(ép task_update nếu 'xong rồi/done';<br/>cứu intent bằng từ khoá nếu LLM = ['conversation'];<br/>loại 'conversation' thừa khi có agent nghiệp vụ)

    RT->>AG: asyncio.gather(return_exceptions=True)<br/>chạy mọi agent đã chọn
    Note over AG,L9: report/planning/notification/<br/>conversation/task_update → Gemini (env)
    Note over AG,DB: text2sql/report/task_update → pool read-only<br/>(DB_AGENT_USER, chỉ SELECT/WITH, timeout 5s)
    AG-->>RT: kết quả từng agent (lỗi 1 agent không làm hỏng reply)

    RT->>RT: _combine_results<br/>(1 agent → trả thẳng; ≥2 → nối bằng dòng trống,<br/>KHÔNG gọi LLM lần nữa)
    RT-->>AD: AgentReply(answer, agent="text2sql+report", metadata)

    AD->>DB: save_memory (nếu agent ≠ 'error')
    AD-->>AD: send_text_with_response_time → Gapo
```

**Lưu ý:** mọi agent đều gọi **Gemini API**. Khác biệt là các agent nghiệp vụ đọc `MODEL_NAME`/`BASE_URL`/`API_KEY` từ **env**, còn intent router (`PMMultiAgentRouter`) **hardcode** `gemini-2.5-flash` + base_url + **API key ngay trong source** ([router.py:38-46](../backend/ai_agent/router/router.py#L38-L46)). ⚠️ Cần đưa key này về env.

### Các agent chuyên biệt

```mermaid
flowchart TB
    IR["PMMultiAgentRouter<br/>phân loại intent → MẢNG agent<br/>(Gemini trực tiếp; fallback từ khóa ở AgentMessageRouter)"]
    IR --> A1["conversation<br/>chào hỏi, trợ giúp (fast-path)"]
    IR --> A2["text2sql<br/>sinh SQL chỉ-đọc, diễn giải VI"]
    IR --> A3["report<br/>template SQL viết sẵn + fallback LLM"]
    IR --> A4["planning<br/>≤3 milestone, ≤2 task/milestone"]
    IR --> A5["notification<br/>nhắc deadline (template tất định dự phòng)"]
    IR --> A6["task_update<br/>xác nhận 'xong rồi/done' → verify DB<br/>(xác minh quyền + audit)"]

    A1 -->|chào hỏi có ngữ cảnh| L9["Gemini API"]
    A2 -->|pool read-only<br/>chỉ SELECT/WITH, timeout 5s| PG[("PostgreSQL")]
    A2 -->|cache SQL TTL~1h| REDIS[("Redis")]
    A2 -->|diễn giải kết quả VI| L9
    A3 -->|template SQL| PG
    A3 -->|fallback diễn giải| L9
    A4 -->|with_structured_output| L9
    A5 -->|sinh nội dung nhắc| L9
    A5 -->|tra deadline| PG
    A6 -->|kiểm follow-up + cập nhật| PG

    classDef a fill:#f3e8ff,stroke:#8a4ad0;
    class A1,A2,A3,A4,A5,A6 a;
```

> Lưu ý cấu hình LLM: tất cả agent gọi **Gemini API**. 6 agent nghiệp vụ lấy model/key từ **env** (đổi model 1 chỗ); riêng **intent router** đang **hardcode** model + API key trong source — nên đưa về env trong lần refactor tới.

---

## 5. Scheduler & tích hợp Gapo outbound

```mermaid
flowchart TB
    SCHED["APScheduler<br/>(PostgreSQL advisory lock, T2–T6, Asia/HCM)"]
    SCHED --> J1["Check-in 11:50 / 17:50<br/>+ nhắc người chưa check-in"]
    SCHED --> J2["Nhắc deadline 9:00 / 14:00<br/>(correlation_id chống trùng)"]
    J1 --> FSM["Check-in FSM<br/>chọn dự án→task→giờ→xác nhận"]
    FSM -->|LLM bóc tách giờ+mô tả| L9["Gemini API"]
    J1 --> GC["GapoClient.send_message<br/>(outbound)"]
    J2 --> GC
    FSM --> GC
    GC --> GAPO["📱 Gapo"]

    classDef s fill:#fdeef0,stroke:#c4485e;
    class J1,J2,FSM,GC s;
```

---

## 6. Tóm tắt tầng lưu trữ & bảo mật

| Thành phần | Vai trò | Bảo mật |
|---|---|---|
| **PostgreSQL 16** | Dữ liệu chính + `agent_memory`, `agent_audit_log` | App dùng pool thường; **agent dùng role read-only riêng** (`DB_AGENT_USER`) |
| **Redis 7** | Cache SQL sinh ra (TTL ~1h), state | bỏ cache cho câu hỏi thời gian tương đối |
| **MinIO (S3)** | Ảnh avatar / upload | giới hạn loại + 2MB |
| **Gemini API** | LLM cho mọi agent | cấu hình qua env (intent router còn hardcode — cần sửa) |
| **JWT** | Auth user | bcrypt password; endpoint nghiệp vụ cần token |
| **HMAC-SHA256** | Xác thực webhook Gapo | `GAPO_WEBHOOK_SECRET` |
| **X-Agent-Token** | Service-to-service (agent → API) | — |

---

## 7. Phần kiến trúc CHƯA có (gap so với requirement)

> 2 mảnh của sơ đồ luồng 4 giai đoạn chưa nằm trong kiến trúc hiện tại — xem [timeline-cai-tien-1-tuan.md](timeline-cai-tien-1-tuan.md):

- **FR-17 (Giai đoạn 1 — Giao việc):** chưa có nhánh `tạo task → assignment_notifier → Gapo DM/thread`.
- **FR-18 (Giai đoạn 4 — Rủi ro):** chưa có `risk_scanner job → risk_alerts → PM duyệt (human-in-the-loop) → push`.

```mermaid
flowchart LR
    NT["create_task / materialize plan"] -.->|FR-17 (chưa có)| NOTI["assignment_notifier → Gapo"]
    RS["risk_scanner job"] -.->|FR-18 (chưa có)| RA["risk_alerts (PENDING)"] -.->|PM duyệt| PUSH["push/đổi trạng thái"]
    classDef gap fill:#fff,stroke:#c44,stroke-dasharray:5 5;
    class NT,NOTI,RS,RA,PUSH gap;
```
