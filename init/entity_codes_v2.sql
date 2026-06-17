-- ─────────────────────────────────────────────────────────────────────────────
-- Entity codes v2 — short per-project prefix + 4-digit seq + worklog codes
--
-- Đổi format mã từ <project.code>-T001 (3 số, prefix = cả code) sang:
--     <PREFIX>-T0001  (task)
--     <PREFIX>-M0001  (milestone)
--     <PREFIX>-W0001  (worklog)
-- PREFIX = 3 ký tự A-Z đầu của projects.code, làm DUY NHẤT toàn cục bằng cách
-- thêm số khi trùng (BB, BB2, BB3...). Lưu vào projects.entity_prefix.
-- Số thứ tự (seq) đếm theo TỪNG dự án, cấp nguyên tử qua project_counters.
--
-- Idempotent: chạy lại cho ra cùng kết quả (recompute toàn bộ theo id/seq ổn định).
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. Cột mới ─────────────────────────────────────────────────────────────────
ALTER TABLE public.projects        ADD COLUMN IF NOT EXISTS entity_prefix text;
ALTER TABLE public.worklogs        ADD COLUMN IF NOT EXISTS seq  integer;
ALTER TABLE public.worklogs        ADD COLUMN IF NOT EXISTS code text;
ALTER TABLE public.project_counters ADD COLUMN IF NOT EXISTS next_wl_seq integer NOT NULL DEFAULT 1;

-- 2. entity_prefix per dự án: 3 ký tự A-Z đầu của code, làm duy nhất (BB, BB2…)
--    Thứ tự ưu tiên theo id (ổn định) -> chạy lại cho cùng kết quả.
WITH base AS (
    SELECT id,
           COALESCE(NULLIF(upper(left(regexp_replace(code, '[^A-Za-z]', '', 'g'), 3)), ''), 'PRJ') AS p
    FROM public.projects
),
numbered AS (
    SELECT id, p, row_number() OVER (PARTITION BY p ORDER BY id) AS rn FROM base
)
UPDATE public.projects pr
SET    entity_prefix = CASE WHEN n.rn = 1 THEN n.p ELSE n.p || n.rn::text END
FROM   numbered n
WHERE  pr.id = n.id;

CREATE UNIQUE INDEX IF NOT EXISTS projects_entity_prefix_key ON public.projects (entity_prefix);

-- 3. Recompute mã (FORCE toàn bộ, không chỉ NULL) sang format mới ───────────────
-- 3a. Tasks: giữ thứ tự seq cũ nếu có, else theo created_at; đánh số 4 chữ số.
WITH ranked AS (
    SELECT t.id, t.project_id,
           row_number() OVER (
               PARTITION BY t.project_id
               ORDER BY COALESCE(t.seq, 2147483647), t.created_at, t.id
           ) AS rn
    FROM public.tasks t
)
UPDATE public.tasks t
SET    seq  = r.rn,
       code = p.entity_prefix || '-T' || lpad(r.rn::text, 4, '0')
FROM   ranked r
JOIN   public.projects p ON p.id = r.project_id
WHERE  t.id = r.id;

-- 3b. Milestones.
WITH ranked AS (
    SELECT m.id, m.project_id,
           row_number() OVER (
               PARTITION BY m.project_id
               ORDER BY COALESCE(m.seq, 2147483647), m.created_at, m.id
           ) AS rn
    FROM public.milestones m
)
UPDATE public.milestones m
SET    seq  = r.rn,
       code = p.entity_prefix || '-M' || lpad(r.rn::text, 4, '0')
FROM   ranked r
JOIN   public.projects p ON p.id = r.project_id
WHERE  m.id = r.id;

-- 3c. Worklogs (mới): đánh số theo dự án, cũ nhất trước.
WITH ranked AS (
    SELECT w.id, w.project_id,
           row_number() OVER (
               PARTITION BY w.project_id
               ORDER BY w.work_date, w.created_at, w.id
           ) AS rn
    FROM public.worklogs w
)
UPDATE public.worklogs w
SET    seq  = r.rn,
       code = p.entity_prefix || '-W' || lpad(r.rn::text, 4, '0')
FROM   ranked r
JOIN   public.projects p ON p.id = r.project_id
WHERE  w.id = r.id;

-- 4. Re-seed counters từ max seq hiện tại (gồm worklog) ──────────────────────────
INSERT INTO public.project_counters (project_id, next_task_seq, next_ms_seq, next_wl_seq)
SELECT p.id,
       COALESCE((SELECT MAX(t.seq) FROM public.tasks t      WHERE t.project_id = p.id), 0) + 1,
       COALESCE((SELECT MAX(m.seq) FROM public.milestones m WHERE m.project_id = p.id), 0) + 1,
       COALESCE((SELECT MAX(w.seq) FROM public.worklogs w   WHERE w.project_id = p.id), 0) + 1
FROM   public.projects p
ON CONFLICT (project_id) DO UPDATE
    SET next_task_seq = EXCLUDED.next_task_seq,
        next_ms_seq   = EXCLUDED.next_ms_seq,
        next_wl_seq   = EXCLUDED.next_wl_seq;

-- 5. Ràng buộc cho worklog code (thêm sau backfill) ──────────────────────────────
DO $$ BEGIN
    ALTER TABLE public.worklogs ADD CONSTRAINT worklogs_project_seq_key UNIQUE (project_id, seq);
EXCEPTION WHEN duplicate_table THEN NULL; WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    ALTER TABLE public.worklogs ADD CONSTRAINT worklogs_code_key UNIQUE (code);
EXCEPTION WHEN duplicate_table THEN NULL; WHEN duplicate_object THEN NULL; END $$;
