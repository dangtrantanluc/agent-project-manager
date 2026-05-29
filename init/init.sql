-- =============================================================================
-- BB-PM — Database Schema  (source of truth cho LLM / AI agent)
-- Cập nhật: 2026-05-25
-- =============================================================================
-- TỔNG QUAN MÔ HÌNH DỮ LIỆU
-- =============================================================================
-- Hệ thống quản lý dự án nội bộ (BB Project Management).
--
-- Luồng dữ liệu chính:
--   1. User đăng nhập → nhận JWT access token
--   2. User tạo / tham gia Projects
--   3. Projects có Tasks, Milestones, Members
--   4. Members log giờ làm qua Worklogs
--   5. Members log giờ làm qua Worklogs
--   6. AI agent ghi nhớ hội thoại vào agent_memory, trigger automation
--   7. Bot Gapo nhận check-in từ member qua gapo_user_maps / checkin_sessions
--
-- Quy ước:
--   · updated_at: bắt buộc NOT NULL, app luôn set = NOW() khi write
--   · counter fields (task_count, total_hours...): denormalized, app cập nhật
--     mỗi khi có INSERT/DELETE trên bảng con tương ứng
--   · ON DELETE CASCADE:  row con tự xoá khi row cha bị xoá
--   · ON DELETE RESTRICT: phải xoá/chuyển row con trước khi xoá row cha
--   · ON DELETE SET NULL: giữ row con, chỉ set FK = NULL
--
-- Danh sách bảng chính:
--   companies, users, projects, members, milestones,
--   task_status, tasks, worklogs,
--   gapo_user_maps, checkin_sessions, agent_memory, automations
-- =============================================================================


-- =============================================================================
-- ENUMS
-- =============================================================================

-- Vai trò toàn cục của user trong hệ thống:
--   ADMIN   → toàn quyền cấu hình, xem mọi dữ liệu
--   MANAGER → tạo/sửa project, phê duyệt worklog
--   MEMBER  → chỉ xem project mình tham gia, tự log công việc
CREATE TYPE "Role" AS ENUM ('ADMIN', 'MANAGER', 'MEMBER');

-- Vòng đời của một project:
--   PLANNED → PENDING → IN_PROGRESS → DONE | CANCELLED
CREATE TYPE "ProjectStatus" AS ENUM (
    'PLANNED', 'PENDING', 'IN_PROGRESS', 'DONE', 'CANCELLED'
);

-- Mức độ ưu tiên — dùng chung cho project và task
CREATE TYPE "Priority" AS ENUM ('LOW', 'MEDIUM', 'HIGH', 'URGENT');

-- Trạng thái kỹ thuật của task — dùng cho filter/rule backend.
-- Phân biệt: tasks.status là enum kỹ thuật; bảng task_status là lookup hiển thị UI.
CREATE TYPE "TaskStatus" AS ENUM (
    'TODO', 'IN_PROGRESS', 'DONE', 'CANCELLED'
);

-- Các bước của luồng check-in qua bot Gapo (máy trạng thái FSM):
--   IDLE → AWAITING_PROJECT → AWAITING_TASK → AWAITING_HOURS → CONFIRMING
--   Sau khi user confirm → bot tạo worklog → reset về IDLE
CREATE TYPE "CheckinState" AS ENUM (
    'IDLE', 'AWAITING_PROJECT', 'AWAITING_TASK', 'AWAITING_HOURS', 'CONFIRMING'
);

-- Nguồn trigger của AI agent (để audit/trace):
CREATE TYPE "AgentAuditSource" AS ENUM ('chat', 'cron', 'cli', 'other');


-- =============================================================================
-- NHÓM 1: CÔNG TY & NGƯỜI DÙNG
-- =============================================================================

CREATE TABLE companies (
    id          serial PRIMARY KEY,
    name        text NOT NULL,
    code        text,
    created_at  timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  timestamp(3) without time zone NOT NULL
);
CREATE UNIQUE INDEX companies_code_key ON companies USING btree (code);

-- ---------------------------------------------------------------------------
-- users — Tài khoản người dùng
-- ---------------------------------------------------------------------------
-- Thực thể trung tâm — mọi hành động đều gắn với user.
-- Quan hệ đi ra (user là "cha"):
--   · projects.owner_id / account_manager_id → người chịu trách nhiệm project
--   · members.user_id             → user tham gia project
--   · tasks.assignee_id           → user được giao task
--   · worklogs.user_id            → user log giờ làm
--   · gapo_user_maps.user_id      → tài khoản Gapo Work tương ứng
--   · checkin_sessions.user_id    → phiên check-in đang mở
--   · automations.owner_id        → user tạo automation
-- company_id: công ty chủ quản của user
-- company_name: cache tên công ty để tương thích UI cũ
-- is_admin: true = super-admin, vượt qua role check, xem mọi dữ liệu
-- active: false = tài khoản bị khoá, không thể đăng nhập
CREATE TABLE users (
    id              serial       PRIMARY KEY,
    email           text         NOT NULL,                        -- username đăng nhập, duy nhất
    password_hash   text         NOT NULL,                        -- bcrypt hash
    full_name       text         NOT NULL,
    company_id      integer      NOT NULL DEFAULT 1 REFERENCES companies(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    company_name    text         NOT NULL DEFAULT 'BBSW Software',
    avatar_url      text,
    lang            text         NOT NULL DEFAULT 'vi_VN',        -- vi_VN | en_US
    timezone        text         NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
    role            "Role"       NOT NULL DEFAULT 'MEMBER',
    department      text,
    position        text,
    active          boolean      NOT NULL DEFAULT true,
    is_admin        boolean      NOT NULL DEFAULT false,
    last_login_at   timestamp(3) without time zone,
    created_at      timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      timestamp(3) without time zone NOT NULL
);
CREATE UNIQUE INDEX users_email_key ON users USING btree (email);


-- =============================================================================
-- NHÓM 2: DỰ ÁN (projects, members, milestones)
-- =============================================================================

-- ---------------------------------------------------------------------------
-- projects — Dự án
-- ---------------------------------------------------------------------------
-- Thực thể nghiệp vụ trung tâm. Mọi task, worklog, milestone đều thuộc project.
-- Quan hệ:
--   · owner_id           → users.id  RESTRICT: chuyển owner trước khi xoá user
--   · account_manager_id → users.id  SET NULL: AM nghỉ → project vẫn tồn tại
-- Tiền tệ (inline — không dùng bảng currencies riêng):
--   currency_code   → mã ISO: VND, USD, EUR
--   currency_symbol → ký hiệu hiển thị: ₫, $, €
-- Khách hàng (inline — không dùng bảng customers riêng):
--   customer_name → tên khách hàng, dùng để phân loại và báo cáo
-- Counter fields (denormalized để tránh COUNT(*) mỗi lần load dashboard):
--   task_count, member_count, worklog_count, scope_count, milestone_count
--   → app cập nhật mỗi khi có INSERT/DELETE trên bảng con tương ứng
-- Tổng hợp:
--   total_hours      → tổng giờ thực tế
CREATE TABLE projects (
    id                  serial          PRIMARY KEY,
    name                text            NOT NULL,
    code                text,                                    -- mã ngắn duy nhất, VD "BB-001"
    status              "ProjectStatus" NOT NULL DEFAULT 'PLANNED',
    priority            "Priority"      NOT NULL DEFAULT 'MEDIUM',
    start_date          date,
    end_date            date,
    description         text,
    total_hours         double precision NOT NULL DEFAULT 0,
    task_count          integer          NOT NULL DEFAULT 0,
    member_count        integer          NOT NULL DEFAULT 0,
    worklog_count       integer          NOT NULL DEFAULT 0,
    scope_count         integer          NOT NULL DEFAULT 0,
    milestone_count     integer          NOT NULL DEFAULT 0,
    currency_code       text             NOT NULL DEFAULT 'VND',  -- mã tiền tệ: VND, USD, EUR
    currency_symbol     text             NOT NULL DEFAULT '₫',    -- ký hiệu hiển thị
    customer_name       text,
    company_id          integer          NOT NULL DEFAULT 1 REFERENCES companies(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    owner_id            integer          NOT NULL REFERENCES users(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    account_manager_id  integer                   REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at          timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          timestamp(3) without time zone NOT NULL
);
CREATE UNIQUE INDEX projects_code_key          ON projects USING btree (code);
CREATE INDEX        projects_status_idx        ON projects USING btree (status);
CREATE INDEX        projects_company_id_status_idx ON projects USING btree (company_id, status);
CREATE INDEX        projects_customer_name_idx ON projects USING btree (customer_name);


-- ---------------------------------------------------------------------------
-- members — Thành viên trong project
-- ---------------------------------------------------------------------------
-- Bảng nối nhiều-nhiều giữa users và projects.
-- Quan hệ:
--   · project_id → projects.id  CASCADE: project xoá → records thành viên xoá theo
--   · user_id    → users.id     RESTRICT: phải xoá khỏi project trước khi xoá user
-- UNIQUE (project_id, user_id): mỗi user chỉ join một project đúng một lần.
-- role: vai trò trong project (free text): "dev", "designer", "PM", "QA"...
--       Khác với users.role là enum toàn hệ thống.
CREATE TABLE members (
    id          serial  PRIMARY KEY,
    project_id  integer NOT NULL REFERENCES projects(id) ON UPDATE CASCADE ON DELETE CASCADE,
    user_id     integer NOT NULL REFERENCES users(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    role        text,
    joined_at   timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at  timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  timestamp(3) without time zone NOT NULL
);
CREATE UNIQUE INDEX members_project_id_user_id_key ON members USING btree (project_id, user_id);
CREATE INDEX        members_user_id_idx            ON members USING btree (user_id);


-- ---------------------------------------------------------------------------
-- milestones — Cột mốc / giai đoạn của project
-- ---------------------------------------------------------------------------
-- Chia project thành các giai đoạn có deadline riêng.
-- Quan hệ:
--   · project_id → projects.id  CASCADE: project xoá → milestones xoá theo
-- Quan hệ ngược:
--   · tasks.milestone_id → SET NULL: milestone xoá → task vẫn tồn tại
-- Counter fields (app cập nhật mỗi khi task status thay đổi):
--   task_count     → tổng số task gắn với milestone
--   done_count     → số task đã DONE
--   completion_pct → done_count * 100 / task_count (0–100)
CREATE TABLE milestones (
    id              serial  PRIMARY KEY,
    name            text    NOT NULL,
    status          text,                     -- "active", "completed", "delayed" (free text)
    due_date        date,
    description     text,
    task_count      integer NOT NULL DEFAULT 0,
    done_count      integer NOT NULL DEFAULT 0,
    completion_pct  integer NOT NULL DEFAULT 0,
    project_id      integer NOT NULL REFERENCES projects(id) ON UPDATE CASCADE ON DELETE CASCADE,
    created_at      timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      timestamp(3) without time zone NOT NULL
);
CREATE INDEX milestones_project_id_idx ON milestones USING btree (project_id);


-- =============================================================================
-- NHÓM 3: CÔNG VIỆC (task_status, tasks)
-- =============================================================================

-- ---------------------------------------------------------------------------
-- task_status — Bảng lookup trạng thái hiển thị của task
-- ---------------------------------------------------------------------------
-- Tách biệt trạng thái UI khỏi enum kỹ thuật "TaskStatus".
-- Không có FK đến tasks — app tự map code → label khi render Kanban/dropdown.
-- Lý do tách: thay đổi label, color, thứ tự mà không cần migration enum.
-- Mapping ngầm:
--   planned → PLANNED        in_progress → IN_PROGRESS        done → DONE
CREATE TABLE task_status (
    id          serial  PRIMARY KEY,
    code        text    NOT NULL,            -- key: planned, in_progress, done
    label       text    NOT NULL,            -- nhãn hiển thị trên UI
    color       text,                        -- hex color cho badge/chip
    sort_order  integer NOT NULL DEFAULT 0,  -- thứ tự cột Kanban
    is_active   boolean NOT NULL DEFAULT true
);
CREATE UNIQUE INDEX task_status_code_key ON task_status USING btree (code);

INSERT INTO task_status (code, label, color, sort_order) VALUES
    ('todo',        'Todo',        '#94a3b8', 1),
    ('in_progress', 'In Progress', '#3b82f6', 2),
    ('done',        'Done',        '#22c55e', 3),
    ('cancelled',   'Cancelled',   '#ef4444', 4);


-- ---------------------------------------------------------------------------
-- tasks — Công việc / hạng mục
-- ---------------------------------------------------------------------------
-- Đơn vị công việc được giao cho thành viên trong project.
-- Quan hệ:
--   · project_id   → projects.id    CASCADE: project xoá → tasks xoá theo
--   · assignee_id  → users.id       SET NULL: user nghỉ → task không người nhận
--   · milestone_id → milestones.id  SET NULL: milestone xoá → task vẫn tồn tại
-- Tiền tệ (inline — kế thừa từ project tại thời điểm tạo):
--   currency_code, currency_symbol
-- Thời gian:
--   deadline → ngày phải hoàn thành (dùng để cảnh báo AI agent)
--   end_at   → ngày thực tế kết thúc (app set khi status → DONE)
-- Tổng hợp (app cập nhật mỗi khi worklog thay đổi):
--   total_hours → SUM(worklogs.hours WHERE task_id = id)
CREATE TABLE tasks (
    id              serial           PRIMARY KEY,
    name            text             NOT NULL,
    status          "TaskStatus"     NOT NULL DEFAULT 'TODO',
    priority        "Priority"       NOT NULL DEFAULT 'MEDIUM',
    deadline        date,
    end_at          date,
    description     text,
    result          text,            -- mô tả kết quả khi hoàn thành
    issues          text,            -- ghi chú vấn đề / blockers
    total_cost      numeric(18,2)    NOT NULL DEFAULT 0,
    total_hours     double precision NOT NULL DEFAULT 0,
    currency_code   text             NOT NULL DEFAULT 'VND',
    currency_symbol text             NOT NULL DEFAULT '₫',
    project_id      integer          NOT NULL REFERENCES projects(id) ON UPDATE CASCADE ON DELETE CASCADE,
    company_id      integer          NOT NULL DEFAULT 1 REFERENCES companies(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    assignee_id     integer                   REFERENCES users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    milestone_id    integer                   REFERENCES milestones(id) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at      timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      timestamp(3) without time zone NOT NULL
);
CREATE INDEX tasks_project_id_status_idx  ON tasks USING btree (project_id, status);
CREATE INDEX tasks_company_id_status_idx  ON tasks USING btree (company_id, status);
CREATE INDEX tasks_assignee_id_status_idx ON tasks USING btree (assignee_id, status);
CREATE INDEX tasks_deadline_status_idx    ON tasks USING btree (deadline, status);
CREATE INDEX tasks_milestone_id_idx       ON tasks USING btree (milestone_id);
CREATE INDEX tasks_updated_at_idx         ON tasks USING btree (updated_at);


-- =============================================================================
-- NHÓM 4: NHẬT KÝ GIỜ LÀM
-- =============================================================================

-- ---------------------------------------------------------------------------
-- worklogs — Nhật ký giờ làm việc
-- ---------------------------------------------------------------------------
-- Nguồn dữ liệu gốc để tính tổng giờ thực tế của project và task.
-- Quan hệ:
--   · user_id    → users.id     RESTRICT: không xoá user còn worklog lịch sử
--   · project_id → projects.id  RESTRICT: không xoá project còn worklog
--   · task_id    → tasks.id     SET NULL: task xoá → worklog vẫn giữ, thuộc project
CREATE TABLE worklogs (
    id           serial       PRIMARY KEY,
    work_date    date         NOT NULL,
    description  text,
    hours        numeric(6,2) NOT NULL,        -- VD: 2.5 = 2 giờ 30 phút
    task_id      integer               REFERENCES tasks(id) ON UPDATE CASCADE ON DELETE SET NULL,
    project_id   integer      NOT NULL REFERENCES projects(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    company_id   integer      NOT NULL DEFAULT 1 REFERENCES companies(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    user_id      integer      NOT NULL REFERENCES users(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    created_at   timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   timestamp(3) without time zone NOT NULL
);
CREATE INDEX worklogs_project_id_work_date_idx ON worklogs USING btree (project_id, work_date);
CREATE INDEX worklogs_company_id_work_date_idx ON worklogs USING btree (company_id, work_date);
CREATE INDEX worklogs_user_id_work_date_idx    ON worklogs USING btree (user_id, work_date);


-- =============================================================================
-- NHÓM 5: AI AGENT & BOT
-- =============================================================================

-- ---------------------------------------------------------------------------
-- gapo_user_maps — Liên kết tài khoản Gapo Work ↔ users
-- ---------------------------------------------------------------------------
-- Khi bot nhận tin nhắn từ Gapo, tra bảng này để biết gapo_user_id
-- tương ứng với user nội bộ nào.
-- Quan hệ:
--   · user_id → users.id  CASCADE: xoá user → map xoá theo
-- UNIQUE user_id: mỗi internal user chỉ liên kết đúng một tài khoản Gapo.
-- gapo_thread_id: ID luồng chat riêng với bot (để bot reply đúng thread)
-- gapo_full_name: cache tên hiển thị trên Gapo (để debug, không dùng để auth)
CREATE TABLE gapo_user_maps (
    id              serial  PRIMARY KEY,
    user_id         integer NOT NULL REFERENCES users(id) ON UPDATE CASCADE ON DELETE CASCADE,
    gapo_user_id    bigint  NOT NULL,
    gapo_thread_id  bigint  NOT NULL,
    gapo_full_name  text,
    last_seen_at    timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at      timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX gapo_user_maps_user_id_key      ON gapo_user_maps USING btree (user_id);
CREATE INDEX        gapo_user_maps_gapo_user_id_idx ON gapo_user_maps USING btree (gapo_user_id);


-- ---------------------------------------------------------------------------
-- checkin_sessions — Phiên check-in qua bot Gapo (FSM)
-- ---------------------------------------------------------------------------
-- Lưu trạng thái cuộc hội thoại check-in đang dở dang.
-- Bot tra bảng này để biết đang hỏi user đến bước nào và dữ liệu đã thu thập.
-- Quan hệ:
--   · user_id → users.id  CASCADE: xoá user → session xoá theo
-- UNIQUE user_id: mỗi user chỉ có một session active cùng lúc.
-- Luồng FSM (máy trạng thái):
--   IDLE → AWAITING_PROJECT → AWAITING_TASK → AWAITING_HOURS → CONFIRMING
--   Sau khi user confirm → tạo worklog mới → set completed_at = NOW() → về IDLE
-- expires_at: session tự hết hạn sau 30 phút không phản hồi
-- pending_parsed: jsonb kết quả NLP: {hours, project_name, task_name, work_date...}
CREATE TABLE checkin_sessions (
    id                  serial         PRIMARY KEY,
    user_id             integer        NOT NULL REFERENCES users(id) ON UPDATE CASCADE ON DELETE CASCADE,
    gapo_user_id        text           NOT NULL,   -- cache để tra nhanh không qua JOIN
    thread_id           text           NOT NULL,   -- ID thread Gapo cần reply
    current_project_id  integer,                   -- dữ liệu đã thu thập trong session
    current_task_id     integer,
    state               "CheckinState" NOT NULL DEFAULT 'IDLE',
    expires_at          timestamp(3) without time zone NOT NULL,
    last_message_id     text,          -- ID tin nhắn bot cuối (để edit/delete trên Gapo)
    pending_text        text,          -- tin nhắn thô cuối của user
    pending_parsed      jsonb,         -- kết quả parse NLP
    completed_at        timestamp(3) without time zone,
    created_at          timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          timestamp(3) without time zone NOT NULL
);
CREATE UNIQUE INDEX checkin_sessions_user_id_key          ON checkin_sessions USING btree (user_id);
CREATE INDEX        checkin_sessions_state_expires_at_idx ON checkin_sessions USING btree (state, expires_at);


-- ---------------------------------------------------------------------------
-- agent_memory — Bộ nhớ hội thoại của AI agent
-- ---------------------------------------------------------------------------
-- Lưu lịch sử hội thoại giữa user và AI agent để agent có context
-- khi trả lời các câu hỏi tiếp theo (short-term memory / RAG).
-- Không còn phân vùng theo company_id vì hệ thống hiện chạy single-company.
-- project_ids, task_ids: integer[] không có FK để tránh dependency cứng khi
--   entity bị xoá sau này (audit log cần giữ dù entity không còn).
-- Các trường quan trọng:
--   user_text      → câu hỏi / lệnh của user
--   reply_text     → câu trả lời của agent
--   summary        → tóm tắt ngắn (dùng để embed vector search trong RAG)
--   tools_used     → danh sách tool agent đã gọi: ["get_tasks", "create_worklog"]
--   correlation_id → trace chuỗi hội thoại liên tiếp (cùng conversation)
CREATE TABLE agent_memory (
    id               serial             PRIMARY KEY,
    conversation_id  text,                         -- nhóm các turn trong một cuộc hội thoại
    source           "AgentAuditSource" NOT NULL DEFAULT 'chat',
    user_text        text               NOT NULL,
    reply_text       text               NOT NULL,
    summary          text               NOT NULL,
    tools_used       jsonb              NOT NULL DEFAULT '[]',
    project_ids      integer[],
    task_ids         integer[],
    correlation_id   text,
    created_at       timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX agent_memory_created_at_idx            ON agent_memory USING btree (created_at);
CREATE INDEX agent_memory_conversation_id_idx       ON agent_memory USING btree (conversation_id);


-- ---------------------------------------------------------------------------
-- automations — Tác vụ tự động định kỳ
-- ---------------------------------------------------------------------------
-- Lưu cấu hình các job tự động: gửi báo cáo tuần, nhắc deadline...
-- Quan hệ:
--   · owner_id → users.id  RESTRICT: chuyển owner trước khi xoá user
-- Lịch chạy:
--   schedule → cron expression, VD "0 8 * * 1-5" (8h mỗi ngày làm việc)
--   workflow → tên handler cần thực thi (key mapping trong code)
--   inputs   → tham số JSON truyền vào workflow
--   target   → kênh/user nhận kết quả (VD "gapo:user_id=123")
-- Giám sát:
--   consecutive_fails → tự động disable khi vượt ngưỡng (thường >= 5)
--   last_run_status   → "success" | "failed"
CREATE TABLE automations (
    id                serial  PRIMARY KEY,
    name              text    NOT NULL,
    workflow          text    NOT NULL,
    schedule          text    NOT NULL,              -- cron expression
    inputs            jsonb   NOT NULL DEFAULT '{}',
    target            text,
    active            boolean NOT NULL DEFAULT true,
    owner_id          integer NOT NULL REFERENCES users(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    created_at        timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        timestamp(3) without time zone NOT NULL,
    last_run_at       timestamp(3) without time zone,
    last_run_status   text,
    last_run_error    text,
    consecutive_fails integer NOT NULL DEFAULT 0
);
CREATE INDEX automations_active_schedule_idx ON automations USING btree (active, schedule);


-- =============================================================================
-- TÓM TẮT MỐI QUAN HỆ (dành cho LLM)
-- =============================================================================
--
-- Graph quan hệ theo chiều "cha → con":
--
--   companies ──► users ──┬──► projects ──┬──► members
--           │               ├──► milestones
--           │               ├──► tasks ──► (worklogs)
--           │               └──► worklogs
--           ├──► gapo_user_maps
--           ├──► checkin_sessions
--           └──► automations
--
--   task_status ─── (lookup table, không FK đến tasks)
--   agent_memory ── (bộ nhớ hội thoại single-company)
--
-- Các câu hỏi thường gặp và bảng liên quan:
--
--   "Task nào đang overdue?"
--     → tasks WHERE deadline < CURRENT_DATE AND status <> 'DONE'
--
--   "Tổng giờ làm của user X trong tháng Y?"
--     → worklogs WHERE user_id = X AND work_date BETWEEN ... GROUP BY user_id
--
--   "Tiến độ milestone M?"
--     → milestones.completion_pct hoặc COUNT tasks WHERE milestone_id = M
--
--   "User X thuộc project nào?"
--     → members WHERE user_id = X → JOIN projects
-- =============================================================================
