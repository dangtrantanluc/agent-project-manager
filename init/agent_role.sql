-- ============================================================================
-- Role read-only cho AI agent (text2sql / report).
--
-- Mục tiêu (defense-in-depth, lớp HẠ TẦNG — mạnh hơn regex is_safe_sql):
--   1. Agent chỉ ĐỌC, không bao giờ ghi (default_transaction_read_only).
--   2. KHÔNG đọc được cột nhạy cảm users.password_hash.
--   3. KHÔNG đọc được bảng nhạy cảm (audit log chứa args, channel_identities...).
--   4. statement_timeout chặn pg_sleep / query nặng làm cạn connection pool.
--
-- Cách dùng:
--   psql -U postgres -d agent_pm -f init/agent_role.sql
--   rồi đặt trong .env:
--     DB_AGENT_USER=pmbot_ro
--     DB_AGENT_PASSWORD=<đổi-mật-khẩu-này>
--
-- File idempotent: chạy lại nhiều lần an toàn.
-- ============================================================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pmbot_ro') THEN
        CREATE ROLE pmbot_ro LOGIN PASSWORD 'change-me-agent-ro-password';
    END IF;
END
$$;

-- Read-only tuyệt đối + timeout ở cấp role (áp cho mọi phiên của role này).
ALTER ROLE pmbot_ro SET default_transaction_read_only = on;
ALTER ROLE pmbot_ro SET statement_timeout = '5s';

-- Quyền schema.
GRANT USAGE ON SCHEMA public TO pmbot_ro;

-- Cấp SELECT trên tất cả bảng hiện có, rồi siết lại các bảng/cột nhạy cảm.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO pmbot_ro;

-- (1) Bảng nhạy cảm: thu hồi hoàn toàn.
REVOKE ALL ON public.agent_audit_log   FROM pmbot_ro;  -- chứa args/kết quả nội bộ
REVOKE ALL ON public.channel_identities FROM pmbot_ro;  -- định danh kênh
REVOKE ALL ON public.automations        FROM pmbot_ro;  -- cấu hình tự động hoá

-- (2) users: thu hồi rồi cấp lại CHỈ các cột an toàn (loại password_hash).
REVOKE ALL ON public.users FROM pmbot_ro;
GRANT SELECT (
    id, email, full_name, avatar_url, lang, timezone,
    role, department, "position", active, is_admin,
    last_login_at, created_at, updated_at, company_id, is_super_admin
) ON public.users TO pmbot_ro;

-- Bảng tạo trong tương lai cũng mặc định read-only cho role (do owner postgres tạo).
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT SELECT ON TABLES TO pmbot_ro;

-- Không cấp quyền trên sequences/functions → agent không gọi được hàm tuỳ ý.
