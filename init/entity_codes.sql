-- ─────────────────────────────────────────────────────────────────────────────
-- Human-readable entity codes (Jira-style) for tasks & milestones
--
-- Project keeps its existing `code` column (used as the prefix, e.g. MTL).
-- Tasks/milestones get a per-project running `seq` and a full `code`:
--     Task:      <PREFIX>-T001, -T002, ...
--     Milestone: <PREFIX>-M001, -M002, ...
-- A `project_counters` table hands out the next seq atomically.
--
-- Idempotent migration: safe to run on an existing database without resetting.
-- Mirrors the columns/table added to init.sql so fresh deploys and existing
-- databases stay in sync.
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. New columns ──────────────────────────────────────────────────────────────
ALTER TABLE public.tasks      ADD COLUMN IF NOT EXISTS seq  integer;
ALTER TABLE public.tasks      ADD COLUMN IF NOT EXISTS code text;
ALTER TABLE public.milestones ADD COLUMN IF NOT EXISTS seq  integer;
ALTER TABLE public.milestones ADD COLUMN IF NOT EXISTS code text;

-- 2. Per-project counter table ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.project_counters (
    project_id    integer PRIMARY KEY REFERENCES public.projects(id) ON DELETE CASCADE,
    next_task_seq integer NOT NULL DEFAULT 1,
    next_ms_seq   integer NOT NULL DEFAULT 1
);

-- 3. Backfill ───────────────────────────────────────────────────────────────────
-- 3a. Projects missing a code: derive a prefix from the name.
--     Take the initials of each word; if a single word, take its first 3 letters.
--     Strip to A-Z, uppercase. Collisions get a numeric suffix below.
WITH base AS (
    SELECT
        p.id,
        CASE
            WHEN array_length(regexp_split_to_array(trim(p.name), '\s+'), 1) > 1
            THEN upper(regexp_replace(
                     string_agg(left(w, 1), '' ORDER BY ord), '[^A-Za-z]', '', 'g'))
            ELSE upper(left(regexp_replace(trim(p.name), '[^A-Za-z]', '', 'g'), 3))
        END AS raw_prefix
    FROM public.projects p,
         LATERAL unnest(regexp_split_to_array(trim(p.name), '\s+')) WITH ORDINALITY AS t(w, ord)
    WHERE p.code IS NULL OR p.code = ''
    GROUP BY p.id, p.name
),
cleaned AS (
    SELECT id, NULLIF(left(raw_prefix, 8), '') AS prefix FROM base
),
-- Disambiguate within the batch AND against existing codes.
numbered AS (
    SELECT
        c.id,
        COALESCE(c.prefix, 'PRJ') AS prefix,
        row_number() OVER (PARTITION BY COALESCE(c.prefix, 'PRJ') ORDER BY c.id) AS rn
    FROM cleaned c
),
final AS (
    SELECT
        n.id,
        CASE WHEN n.rn = 1 AND NOT EXISTS (
                  SELECT 1 FROM public.projects p2 WHERE p2.code = n.prefix)
             THEN n.prefix
             ELSE n.prefix || (n.rn + 1)::text
        END AS code
    FROM numbered n
)
UPDATE public.projects p
SET    code = f.code
FROM   final f
WHERE  p.id = f.id;

-- 3b. Tasks: assign seq per project (oldest first) + full code.
WITH ranked AS (
    SELECT t.id, t.project_id,
           row_number() OVER (PARTITION BY t.project_id ORDER BY t.created_at, t.id) AS rn
    FROM public.tasks t
    WHERE t.seq IS NULL
)
UPDATE public.tasks t
SET    seq  = r.rn,
       code = p.code || '-T' || lpad(r.rn::text, 3, '0')
FROM   ranked r
JOIN   public.projects p ON p.id = r.project_id
WHERE  t.id = r.id;

-- 3c. Milestones: same per-project numbering.
WITH ranked AS (
    SELECT m.id, m.project_id,
           row_number() OVER (PARTITION BY m.project_id ORDER BY m.created_at, m.id) AS rn
    FROM public.milestones m
    WHERE m.seq IS NULL
)
UPDATE public.milestones m
SET    seq  = r.rn,
       code = p.code || '-M' || lpad(r.rn::text, 3, '0')
FROM   ranked r
JOIN   public.projects p ON p.id = r.project_id
WHERE  m.id = r.id;

-- 3d. Seed counters from current max seq per project.
INSERT INTO public.project_counters (project_id, next_task_seq, next_ms_seq)
SELECT p.id,
       COALESCE((SELECT MAX(t.seq) FROM public.tasks t      WHERE t.project_id = p.id), 0) + 1,
       COALESCE((SELECT MAX(m.seq) FROM public.milestones m WHERE m.project_id = p.id), 0) + 1
FROM   public.projects p
ON CONFLICT (project_id) DO UPDATE
    SET next_task_seq = EXCLUDED.next_task_seq,
        next_ms_seq   = EXCLUDED.next_ms_seq;

-- 4. Constraints (added after backfill so existing rows don't violate them) ──────
-- Unique seq within a project (safety net against concurrent allocation races).
DO $$ BEGIN
    ALTER TABLE public.tasks      ADD CONSTRAINT tasks_project_seq_key      UNIQUE (project_id, seq);
EXCEPTION WHEN duplicate_table THEN NULL; WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    ALTER TABLE public.milestones ADD CONSTRAINT milestones_project_seq_key UNIQUE (project_id, seq);
EXCEPTION WHEN duplicate_table THEN NULL; WHEN duplicate_object THEN NULL; END $$;
-- Full code is globally unique.
DO $$ BEGIN
    ALTER TABLE public.tasks      ADD CONSTRAINT tasks_code_key      UNIQUE (code);
EXCEPTION WHEN duplicate_table THEN NULL; WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    ALTER TABLE public.milestones ADD CONSTRAINT milestones_code_key UNIQUE (code);
EXCEPTION WHEN duplicate_table THEN NULL; WHEN duplicate_object THEN NULL; END $$;
