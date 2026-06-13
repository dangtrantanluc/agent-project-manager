-- ─────────────────────────────────────────────────────────────────────────────
-- Tags (nhãn) — quản lý task & project tự do theo nhãn người dùng tự tạo.
--
-- Idempotent migration: an toàn chạy lại trên DB đang chạy lẫn deploy mới.
-- Tag scope theo company; gắn nhiều-nhiều với task và project.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.tags (
    id          serial PRIMARY KEY,
    name        text    NOT NULL,
    color       text    NOT NULL DEFAULT '#3b82f6',   -- hex màu hiển thị chip
    company_id  integer NOT NULL,
    created_by  integer,
    created_at  timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at  timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Tên tag duy nhất (không phân biệt hoa/thường) trong cùng 1 company.
CREATE UNIQUE INDEX IF NOT EXISTS tags_company_name_uniq
    ON public.tags (company_id, lower(name));

-- Gắn tag cho TASK (nhiều-nhiều). Xoá task/tag -> tự gỡ liên kết.
CREATE TABLE IF NOT EXISTS public.task_tags (
    task_id integer NOT NULL REFERENCES public.tasks(id) ON DELETE CASCADE,
    tag_id  integer NOT NULL REFERENCES public.tags(id)  ON DELETE CASCADE,
    PRIMARY KEY (task_id, tag_id)
);
CREATE INDEX IF NOT EXISTS task_tags_tag_idx ON public.task_tags (tag_id);

-- Gắn tag cho PROJECT (nhiều-nhiều).
CREATE TABLE IF NOT EXISTS public.project_tags (
    project_id integer NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    tag_id     integer NOT NULL REFERENCES public.tags(id)     ON DELETE CASCADE,
    PRIMARY KEY (project_id, tag_id)
);
CREATE INDEX IF NOT EXISTS project_tags_tag_idx ON public.project_tags (tag_id);
