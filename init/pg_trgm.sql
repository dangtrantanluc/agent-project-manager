-- Bật pg_trgm cho khớp tên gần-đúng (entity_resolver.resolve_tasks fallback mờ,
-- name_resolver trigram). Trước đây code đã gọi similarity()/word_similarity()
-- nhưng extension chưa được provision -> nhánh mờ luôn im lặng bỏ qua, nên
-- "mẫu mail" không bắc cầu được sang "Mẫu Email & WhatsApp".
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Index trigram để word_similarity(:ref, t.name) không phải quét toàn bảng.
CREATE INDEX IF NOT EXISTS idx_tasks_name_trgm
    ON tasks USING gin (lower(name) gin_trgm_ops);
