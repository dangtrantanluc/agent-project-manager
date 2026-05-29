-- Simplify project/task status, restore company table, remove project budget
-- fields, and remove member salary/rate history.

CREATE TABLE IF NOT EXISTS public.companies (
    id          serial PRIMARY KEY,
    name        text NOT NULL,
    code        text,
    created_at  timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS companies_code_key ON public.companies USING btree (code);

INSERT INTO public.companies (name, code, updated_at)
VALUES ('BBSW Software', 'BBSW', NOW())
ON CONFLICT (code) DO UPDATE
SET name = EXCLUDED.name,
    updated_at = NOW();

ALTER TABLE public.users ADD COLUMN IF NOT EXISTS company_id integer;
UPDATE public.users
SET company_id = COALESCE(company_id, (SELECT id FROM public.companies WHERE code = 'BBSW' LIMIT 1));
ALTER TABLE public.users ALTER COLUMN company_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_company_id_fkey'
    ) THEN
        ALTER TABLE public.users
            ADD CONSTRAINT users_company_id_fkey
            FOREIGN KEY (company_id) REFERENCES public.companies(id)
            ON UPDATE CASCADE ON DELETE RESTRICT;
    END IF;
END $$;

ALTER TABLE public.projects ADD COLUMN IF NOT EXISTS company_id integer;
UPDATE public.projects
SET company_id = COALESCE(
    company_id,
    (SELECT company_id FROM public.users WHERE users.id = projects.owner_id LIMIT 1),
    (SELECT id FROM public.companies WHERE code = 'BBSW' LIMIT 1)
);
ALTER TABLE public.projects ALTER COLUMN company_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'projects_company_id_fkey'
    ) THEN
        ALTER TABLE public.projects
            ADD CONSTRAINT projects_company_id_fkey
            FOREIGN KEY (company_id) REFERENCES public.companies(id)
            ON UPDATE CASCADE ON DELETE RESTRICT;
    END IF;
END $$;

ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS company_id integer;
UPDATE public.tasks t
SET company_id = COALESCE(t.company_id, p.company_id)
FROM public.projects p
WHERE p.id = t.project_id;
UPDATE public.tasks
SET company_id = COALESCE(company_id, (SELECT id FROM public.companies WHERE code = 'BBSW' LIMIT 1));
ALTER TABLE public.tasks ALTER COLUMN company_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'tasks_company_id_fkey'
    ) THEN
        ALTER TABLE public.tasks
            ADD CONSTRAINT tasks_company_id_fkey
            FOREIGN KEY (company_id) REFERENCES public.companies(id)
            ON UPDATE CASCADE ON DELETE RESTRICT;
    END IF;
END $$;

ALTER TABLE public.worklogs ADD COLUMN IF NOT EXISTS company_id integer;
UPDATE public.worklogs w
SET company_id = COALESCE(w.company_id, p.company_id)
FROM public.projects p
WHERE p.id = w.project_id;
UPDATE public.worklogs
SET company_id = COALESCE(company_id, (SELECT id FROM public.companies WHERE code = 'BBSW' LIMIT 1));
ALTER TABLE public.worklogs ALTER COLUMN company_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'worklogs_company_id_fkey'
    ) THEN
        ALTER TABLE public.worklogs
            ADD CONSTRAINT worklogs_company_id_fkey
            FOREIGN KEY (company_id) REFERENCES public.companies(id)
            ON UPDATE CASCADE ON DELETE RESTRICT;
    END IF;
END $$;

DROP INDEX IF EXISTS public.projects_company_id_status_idx;
CREATE INDEX IF NOT EXISTS projects_company_id_status_idx ON public.projects USING btree (company_id, status);
DROP INDEX IF EXISTS public.tasks_company_id_status_idx;
CREATE INDEX IF NOT EXISTS tasks_company_id_status_idx ON public.tasks USING btree (company_id, status);
DROP INDEX IF EXISTS public.worklogs_company_id_work_date_idx;
CREATE INDEX IF NOT EXISTS worklogs_company_id_work_date_idx ON public.worklogs USING btree (company_id, work_date);

DROP TABLE IF EXISTS public.member_rates;

ALTER TABLE public.projects
    DROP COLUMN IF EXISTS budget,
    DROP COLUMN IF EXISTS estimated_total_cost,
    DROP COLUMN IF EXISTS total_cost,
    DROP COLUMN IF EXISTS budget_remaining;

ALTER TABLE public.projects ALTER COLUMN status DROP DEFAULT;
ALTER TYPE public."ProjectStatus" RENAME TO "ProjectStatus_old";
CREATE TYPE public."ProjectStatus" AS ENUM ('PLANNED', 'PENDING', 'IN_PROGRESS', 'DONE', 'CANCELLED');
ALTER TABLE public.projects
    ALTER COLUMN status TYPE public."ProjectStatus"
    USING (
        CASE status::text
            WHEN 'COMPLETED' THEN 'DONE'
            WHEN 'ON_HOLD' THEN 'PENDING'
            ELSE status::text
        END
    )::public."ProjectStatus";
ALTER TABLE public.projects ALTER COLUMN status SET DEFAULT 'PLANNED';
DROP TYPE public."ProjectStatus_old";

ALTER TABLE public.tasks ALTER COLUMN status DROP DEFAULT;
ALTER TYPE public."TaskStatus" RENAME TO "TaskStatus_old";
CREATE TYPE public."TaskStatus" AS ENUM ('PLANNED', 'IN_PROGRESS', 'DONE');
ALTER TABLE public.tasks
    ALTER COLUMN status TYPE public."TaskStatus"
    USING (
        CASE status::text
            WHEN 'TODO' THEN 'PLANNED'
            WHEN 'IN_REVIEW' THEN 'DONE'
            WHEN 'CANCELLED' THEN 'DONE'
            ELSE status::text
        END
    )::public."TaskStatus";
ALTER TABLE public.tasks ALTER COLUMN status SET DEFAULT 'PLANNED';
DROP TYPE public."TaskStatus_old";

TRUNCATE TABLE public.task_status RESTART IDENTITY;
INSERT INTO public.task_status (code, label, color, sort_order) VALUES
    ('planned',     'Planned',     '#94a3b8', 1),
    ('in_progress', 'In Progress', '#3b82f6', 2),
    ('done',        'Done',        '#22c55e', 3);
