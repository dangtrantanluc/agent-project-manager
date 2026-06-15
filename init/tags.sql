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
    -- Tag CÁ NHÂN: NULL = tag chung công ty (mọi người thấy); có giá trị = tag
    -- riêng của user đó (chỉ chủ thấy/gắn/sửa). Xoá user -> xoá tag riêng của họ.
    owner_user_id integer REFERENCES public.users(id) ON DELETE CASCADE,
    created_at  timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at  timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Cột owner_user_id cho DB đã tạo bảng trước đó (idempotent).
ALTER TABLE public.tags ADD COLUMN IF NOT EXISTS owner_user_id integer
    REFERENCES public.users(id) ON DELETE CASCADE;

-- Tên tag duy nhất trong phạm vi (company + chủ sở hữu). COALESCE(...,0): tag
-- chung không trùng nhau; tag riêng chỉ không trùng trong chính chủ -> 2 người
-- được đặt tag riêng cùng tên ("việc gấp").
DROP INDEX IF EXISTS tags_company_name_uniq;
CREATE UNIQUE INDEX IF NOT EXISTS tags_company_owner_name_uniq
    ON public.tags (company_id, COALESCE(owner_user_id, 0), lower(name));

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
