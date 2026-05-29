-- BB-PM UI/API compatibility migration.
-- Safe to run more than once on a database created from init/schema.sql.

DO $$ BEGIN
    ALTER TYPE public."Role" ADD VALUE IF NOT EXISTS 'VIEWER';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE public."BacklogStatus" AS ENUM ('PENDING', 'APPROVED', 'REJECTED');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE public."BacklogSource" AS ENUM ('manual', 'checkin', 'import');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE public."MeetingItemStatus" AS ENUM ('DRAFT', 'APPROVED', 'REJECTED');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE public."BlockerSeverity" AS ENUM ('LOW', 'MED', 'HIGH', 'CRITICAL');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS public.currencies (
    id      serial PRIMARY KEY,
    code    text NOT NULL,
    symbol  text NOT NULL,
    rate    numeric(20,6) NOT NULL DEFAULT 1.0
);
CREATE UNIQUE INDEX IF NOT EXISTS currencies_code_key ON public.currencies USING btree (code);

INSERT INTO public.currencies (code, symbol, rate)
VALUES ('VND', '₫', 1.0)
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.companies (
    id          serial PRIMARY KEY,
    name        text NOT NULL,
    code        text,
    currency_id integer REFERENCES public.currencies(id) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at  timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS companies_code_key ON public.companies USING btree (code);

INSERT INTO public.companies (name, code, currency_id, updated_at)
SELECT 'Bluebolt Software', 'BLUEBOLT', id, NOW()
FROM public.currencies WHERE code = 'VND'
ON CONFLICT (code) DO NOTHING;

ALTER TABLE public.users ADD COLUMN IF NOT EXISTS company_id integer;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS is_super_admin boolean NOT NULL DEFAULT false;
UPDATE public.users
SET company_id = COALESCE(company_id, (SELECT id FROM public.companies ORDER BY id LIMIT 1));
ALTER TABLE public.users ALTER COLUMN company_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS users_company_id_idx ON public.users USING btree (company_id);

ALTER TABLE public.projects ADD COLUMN IF NOT EXISTS company_id integer;
ALTER TABLE public.projects ADD COLUMN IF NOT EXISTS estimated_total_cost numeric(18,2);
ALTER TABLE public.projects ADD COLUMN IF NOT EXISTS estimated_total_hours double precision;
ALTER TABLE public.projects ADD COLUMN IF NOT EXISTS customer_name text;
ALTER TABLE public.projects ADD COLUMN IF NOT EXISTS currency_id integer;
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'projects'
          AND column_name = 'currency_code'
    ) THEN
        UPDATE public.projects
        SET currency_id = COALESCE(
            currency_id,
            (SELECT id FROM public.currencies WHERE code = currency_code LIMIT 1)
        );
    END IF;
END $$;
UPDATE public.projects p
SET company_id = COALESCE(p.company_id, u.company_id)
FROM public.users u
WHERE p.owner_id = u.id;
UPDATE public.projects
SET company_id = COALESCE(company_id, (SELECT id FROM public.companies ORDER BY id LIMIT 1));
ALTER TABLE public.projects ALTER COLUMN company_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS projects_company_id_status_idx ON public.projects USING btree (company_id, status);
CREATE INDEX IF NOT EXISTS projects_customer_name_idx ON public.projects USING btree (customer_name);
ALTER TABLE public.projects DROP COLUMN IF EXISTS customer_id;

ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS company_id integer;
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS currency_id integer;
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'tasks'
          AND column_name = 'currency_code'
    ) THEN
        UPDATE public.tasks
        SET currency_id = COALESCE(
            currency_id,
            (SELECT id FROM public.currencies WHERE code = currency_code LIMIT 1)
        );
    END IF;
END $$;
UPDATE public.tasks t
SET company_id = COALESCE(t.company_id, p.company_id)
FROM public.projects p
WHERE t.project_id = p.id;
ALTER TABLE public.tasks ALTER COLUMN company_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS tasks_company_id_status_idx ON public.tasks USING btree (company_id, status);

ALTER TABLE public.worklogs ADD COLUMN IF NOT EXISTS company_id integer;
UPDATE public.worklogs w
SET company_id = COALESCE(w.company_id, p.company_id)
FROM public.projects p
WHERE w.project_id = p.id;
ALTER TABLE public.worklogs ALTER COLUMN company_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS worklogs_company_id_work_date_idx ON public.worklogs USING btree (company_id, work_date);

ALTER TABLE public.member_rates ADD COLUMN IF NOT EXISTS currency_id integer;
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'member_rates'
          AND column_name = 'currency_code'
    ) THEN
        UPDATE public.member_rates
        SET currency_id = COALESCE(
            currency_id,
            (SELECT id FROM public.currencies WHERE code = currency_code LIMIT 1)
        );
    END IF;
END $$;

DROP TABLE IF EXISTS public.task_tags CASCADE;
DROP TABLE IF EXISTS public.project_tags CASCADE;
DROP TABLE IF EXISTS public.tags CASCADE;
DROP TABLE IF EXISTS public.customers CASCADE;

CREATE TABLE IF NOT EXISTS public.scopes (
    id              serial PRIMARY KEY,
    sequence        integer NOT NULL DEFAULT 10,
    name            text NOT NULL,
    notes           text,
    estimated_hours numeric(12,2),
    estimated_rate  numeric(18,2),
    estimated_cost  numeric(18,2),
    project_id      integer NOT NULL REFERENCES public.projects(id) ON UPDATE CASCADE ON DELETE CASCADE,
    task_id         integer REFERENCES public.tasks(id) ON UPDATE CASCADE ON DELETE SET NULL,
    assignee_id     integer REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    currency_id     integer REFERENCES public.currencies(id) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at      timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS scopes_project_id_sequence_idx ON public.scopes USING btree (project_id, sequence);

CREATE TABLE IF NOT EXISTS public.backlogs (
    id                     serial PRIMARY KEY,
    status                 public."BacklogStatus" NOT NULL DEFAULT 'PENDING',
    source                 public."BacklogSource" NOT NULL DEFAULT 'manual',
    work_date              date NOT NULL,
    description            text,
    hours                  numeric(6,2) NOT NULL,
    cost_per_hour_snapshot numeric(18,2),
    total_cost_snapshot    numeric(18,2),
    task_id                integer REFERENCES public.tasks(id) ON UPDATE CASCADE ON DELETE SET NULL,
    project_id             integer NOT NULL REFERENCES public.projects(id) ON UPDATE CASCADE ON DELETE CASCADE,
    company_id             integer NOT NULL,
    user_id                integer NOT NULL REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    currency_id            integer REFERENCES public.currencies(id) ON UPDATE CASCADE ON DELETE SET NULL,
    approver_id            integer REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    approved_at            timestamp(3) without time zone,
    rejected_reason        text,
    created_at             timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at             timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS backlogs_company_status_date_idx ON public.backlogs USING btree (company_id, status, work_date);
CREATE INDEX IF NOT EXISTS backlogs_project_id_idx ON public.backlogs USING btree (project_id);

CREATE TABLE IF NOT EXISTS public.task_blockers (
    id          serial PRIMARY KEY,
    task_id     integer NOT NULL REFERENCES public.tasks(id) ON UPDATE CASCADE ON DELETE CASCADE,
    severity    public."BlockerSeverity" NOT NULL DEFAULT 'MED',
    description text NOT NULL,
    resolved_at timestamp(3) without time zone,
    created_at  timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS task_blockers_task_id_idx ON public.task_blockers USING btree (task_id);

CREATE TABLE IF NOT EXISTS public.meetings (
    id            serial PRIMARY KEY,
    company_id    integer NOT NULL,
    project_id    integer REFERENCES public.projects(id) ON UPDATE CASCADE ON DELETE SET NULL,
    title         text,
    held_at       timestamp with time zone NOT NULL DEFAULT NOW(),
    transcript    text NOT NULL,
    summary       text,
    decisions     jsonb NOT NULL DEFAULT '[]',
    participants  text[] NOT NULL DEFAULT '{}',
    created_by_id integer REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at    timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS meetings_company_created_at_idx ON public.meetings USING btree (company_id, created_at);

CREATE TABLE IF NOT EXISTS public.meeting_action_items (
    id              serial PRIMARY KEY,
    meeting_id      integer NOT NULL REFERENCES public.meetings(id) ON UPDATE CASCADE ON DELETE CASCADE,
    title           text NOT NULL,
    description     text,
    owner_name      text,
    owner_user_id   integer REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    due_date        date,
    priority        public."Priority" NOT NULL DEFAULT 'MEDIUM',
    status          public."MeetingItemStatus" NOT NULL DEFAULT 'DRAFT',
    created_task_id integer REFERENCES public.tasks(id) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at      timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS meeting_action_items_meeting_id_idx ON public.meeting_action_items USING btree (meeting_id);

CREATE TABLE IF NOT EXISTS public.agent_audit_log (
    id             serial PRIMARY KEY,
    tool           text NOT NULL,
    args_json      jsonb NOT NULL DEFAULT '{}',
    result_json    jsonb,
    error_message  text,
    duration_ms    integer,
    correlation_id text,
    source         public."AgentAuditSource" NOT NULL DEFAULT 'other',
    created_at     timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS agent_audit_log_created_at_idx ON public.agent_audit_log USING btree (created_at DESC);
CREATE INDEX IF NOT EXISTS agent_audit_log_correlation_id_idx ON public.agent_audit_log USING btree (correlation_id);
