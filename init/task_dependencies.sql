-- ─────────────────────────────────────────────────────────────────────────────
-- Task dependencies (phụ thuộc công việc)
--
-- "A phụ thuộc B" => task_dependencies(blocked_task_id=A, depends_on_task_id=B):
-- A chỉ làm được sau khi B (depends_on) DONE. Người dùng set thủ công; agent quét
-- để cảnh báo "A đang chờ B chưa xong" / "B xong, A đã sẵn sàng".
--
-- Idempotent migration: an toàn chạy lại. Mirror vào init.sql cho deploy mới.
-- Chống chu trình (A->B->A) kiểm ở tầng app (recursive CTE), DB chỉ chặn self + trùng.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.task_dependencies (
    id                 serial PRIMARY KEY,
    blocked_task_id    integer NOT NULL REFERENCES public.tasks(id) ON DELETE CASCADE,
    depends_on_task_id integer NOT NULL REFERENCES public.tasks(id) ON DELETE CASCADE,
    created_by         integer REFERENCES public.users(id),
    created_at         timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT task_dependencies_no_self CHECK (blocked_task_id <> depends_on_task_id),
    CONSTRAINT task_dependencies_unique UNIQUE (blocked_task_id, depends_on_task_id)
);

CREATE INDEX IF NOT EXISTS task_dependencies_blocked_idx
    ON public.task_dependencies (blocked_task_id);
CREATE INDEX IF NOT EXISTS task_dependencies_depends_on_idx
    ON public.task_dependencies (depends_on_task_id);
