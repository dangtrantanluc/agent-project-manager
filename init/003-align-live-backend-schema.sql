-- Align the live DB with the current backend contract.
-- This migration is intentionally idempotent and does not recreate customers/tags.

DO $$ BEGIN
    ALTER TYPE public."Role" ADD VALUE IF NOT EXISTS 'VIEWER';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TYPE public."Role" ADD VALUE IF NOT EXISTS 'SUPER_ADMIN';
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

DO $$ BEGIN
    CREATE TYPE public."FollowUpStatus" AS ENUM ('PENDING', 'REPLIED', 'EXPIRED');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TYPE public."ChannelKind" ADD VALUE IF NOT EXISTS 'zalo';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TYPE public."ChannelKind" ADD VALUE IF NOT EXISTS 'slack';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TYPE public."CheckinState" ADD VALUE IF NOT EXISTS 'AWAITING_UPDATE';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TYPE public."CheckinState" ADD VALUE IF NOT EXISTS 'AWAITING_TASK_CONFIRM';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TYPE public."CheckinState" ADD VALUE IF NOT EXISTS 'COMPLETED';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TYPE public."CheckinState" ADD VALUE IF NOT EXISTS 'CANCELLED';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TYPE public."CheckinState" ADD VALUE IF NOT EXISTS 'EXPIRED';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TYPE public."CheckinState" ADD VALUE IF NOT EXISTS 'MISSED';
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
FROM public.currencies
WHERE code = 'VND'
ON CONFLICT (code) DO NOTHING;

ALTER TABLE public.users ADD COLUMN IF NOT EXISTS company_id integer;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS is_super_admin boolean NOT NULL DEFAULT false;

UPDATE public.users
SET company_id = COALESCE(company_id, (SELECT id FROM public.companies ORDER BY id LIMIT 1));

ALTER TABLE public.users ALTER COLUMN company_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS users_company_id_idx ON public.users USING btree (company_id);

INSERT INTO public.users (
    email, password_hash, full_name, role, company_id, active, is_admin,
    is_super_admin, updated_at
)
SELECT
    'pm-agent@bluebolt.local',
    'agent-service-account',
    'PM Agent',
    'MANAGER'::public."Role",
    c.id,
    true,
    false,
    false,
    NOW()
FROM public.companies c
ORDER BY c.id
LIMIT 1
ON CONFLICT (email) DO NOTHING;

ALTER TABLE public.projects ADD COLUMN IF NOT EXISTS company_id integer;
ALTER TABLE public.projects ADD COLUMN IF NOT EXISTS estimated_total_cost numeric(18,2);
ALTER TABLE public.projects ADD COLUMN IF NOT EXISTS estimated_total_hours double precision;
ALTER TABLE public.projects ADD COLUMN IF NOT EXISTS customer_name text;
ALTER TABLE public.projects ADD COLUMN IF NOT EXISTS currency_id integer;

UPDATE public.projects p
SET company_id = COALESCE(p.company_id, u.company_id)
FROM public.users u
WHERE p.owner_id = u.id;

UPDATE public.projects
SET company_id = COALESCE(company_id, (SELECT id FROM public.companies ORDER BY id LIMIT 1));

UPDATE public.projects
SET currency_id = COALESCE(currency_id, (SELECT id FROM public.currencies WHERE code = 'VND' LIMIT 1));

ALTER TABLE public.projects ALTER COLUMN company_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS projects_company_id_status_idx ON public.projects USING btree (company_id, status);
CREATE INDEX IF NOT EXISTS projects_customer_name_idx ON public.projects USING btree (customer_name);

ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS company_id integer;
ALTER TABLE public.tasks ADD COLUMN IF NOT EXISTS currency_id integer;

UPDATE public.tasks t
SET company_id = COALESCE(t.company_id, p.company_id)
FROM public.projects p
WHERE t.project_id = p.id;

UPDATE public.tasks
SET company_id = COALESCE(company_id, (SELECT id FROM public.companies ORDER BY id LIMIT 1));

UPDATE public.tasks
SET currency_id = COALESCE(currency_id, (SELECT id FROM public.currencies WHERE code = 'VND' LIMIT 1));

ALTER TABLE public.tasks ALTER COLUMN company_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS tasks_company_id_status_idx ON public.tasks USING btree (company_id, status);

ALTER TABLE public.worklogs ADD COLUMN IF NOT EXISTS company_id integer;
ALTER TABLE public.worklogs ADD COLUMN IF NOT EXISTS source text;
ALTER TABLE public.worklogs ADD COLUMN IF NOT EXISTS raw_message text;
ALTER TABLE public.worklogs ADD COLUMN IF NOT EXISTS parsed_json jsonb;
ALTER TABLE public.worklogs ADD COLUMN IF NOT EXISTS checkin_session_id integer;
ALTER TABLE public.worklogs ADD COLUMN IF NOT EXISTS slot text;

UPDATE public.worklogs w
SET company_id = COALESCE(w.company_id, p.company_id)
FROM public.projects p
WHERE w.project_id = p.id;

UPDATE public.worklogs
SET company_id = COALESCE(company_id, (SELECT id FROM public.companies ORDER BY id LIMIT 1));

ALTER TABLE public.worklogs ALTER COLUMN company_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS worklogs_company_id_work_date_idx ON public.worklogs USING btree (company_id, work_date);
CREATE INDEX IF NOT EXISTS worklogs_checkin_session_id_raw_message_idx
    ON public.worklogs USING btree (checkin_session_id, raw_message);

ALTER TABLE public.checkin_sessions ADD COLUMN IF NOT EXISTS company_id integer;
ALTER TABLE public.checkin_sessions ADD COLUMN IF NOT EXISTS work_date date;
ALTER TABLE public.checkin_sessions ADD COLUMN IF NOT EXISTS slot text;
ALTER TABLE public.checkin_sessions ADD COLUMN IF NOT EXISTS reminder_count integer NOT NULL DEFAULT 0;
ALTER TABLE public.checkin_sessions ADD COLUMN IF NOT EXISTS last_reminded_at timestamp(3) without time zone;
ALTER TABLE public.checkin_sessions ADD COLUMN IF NOT EXISTS missed_at timestamp(3) without time zone;

UPDATE public.checkin_sessions cs
SET company_id = COALESCE(cs.company_id, u.company_id)
FROM public.users u
WHERE cs.user_id = u.id;

UPDATE public.checkin_sessions
SET company_id = COALESCE(company_id, (SELECT id FROM public.companies ORDER BY id LIMIT 1)),
    work_date = COALESCE(work_date, CURRENT_DATE),
    slot = COALESCE(slot, 'manual');

ALTER TABLE public.checkin_sessions ALTER COLUMN company_id SET NOT NULL;
ALTER TABLE public.checkin_sessions ALTER COLUMN work_date SET NOT NULL;
ALTER TABLE public.checkin_sessions ALTER COLUMN slot SET NOT NULL;

DROP INDEX IF EXISTS public.checkin_sessions_user_id_key;
CREATE INDEX IF NOT EXISTS checkin_sessions_user_date_slot_idx
    ON public.checkin_sessions USING btree (user_id, work_date, slot);
CREATE INDEX IF NOT EXISTS checkin_sessions_company_state_expires_idx
    ON public.checkin_sessions USING btree (company_id, state, expires_at);
CREATE INDEX IF NOT EXISTS checkin_sessions_slot_reminder_idx
    ON public.checkin_sessions USING btree (slot, state, expires_at, reminder_count);

CREATE TABLE IF NOT EXISTS public.scopes (
    id              serial PRIMARY KEY,
    sequence        integer NOT NULL DEFAULT 10,
    name            text NOT NULL,
    notes           text,
    estimated_hours numeric(12,2),
    estimated_rate  numeric(18,2),
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
    task_id                integer REFERENCES public.tasks(id) ON UPDATE CASCADE ON DELETE SET NULL,
    project_id             integer NOT NULL REFERENCES public.projects(id) ON UPDATE CASCADE ON DELETE CASCADE,
    company_id             integer NOT NULL REFERENCES public.companies(id) ON UPDATE CASCADE ON DELETE RESTRICT,
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
    company_id    integer NOT NULL REFERENCES public.companies(id) ON UPDATE CASCADE ON DELETE RESTRICT,
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

ALTER TABLE public.automations ADD COLUMN IF NOT EXISTS company_id integer;
UPDATE public.automations
SET company_id = COALESCE(company_id, (SELECT company_id FROM public.users WHERE users.id = automations.owner_id LIMIT 1));
UPDATE public.automations
SET company_id = COALESCE(company_id, (SELECT id FROM public.companies ORDER BY id LIMIT 1));
ALTER TABLE public.automations ALTER COLUMN company_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS automations_company_active_idx ON public.automations USING btree (company_id, active);

CREATE TABLE IF NOT EXISTS public.agent_follow_ups (
    id              serial PRIMARY KEY,
    task_id         integer NOT NULL REFERENCES public.tasks(id) ON UPDATE CASCADE ON DELETE CASCADE,
    user_id         integer NOT NULL REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE CASCADE,
    channel         public."ChannelKind" NOT NULL DEFAULT 'gapo',
    thread_id       text,
    question        text NOT NULL,
    status          public."FollowUpStatus" NOT NULL DEFAULT 'PENDING',
    asked_at        timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    replied_at      timestamp(3) without time zone,
    reply_text      text,
    correlation_id  text,
    created_at      timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      timestamp(3) without time zone NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS agent_follow_ups_user_status_idx ON public.agent_follow_ups USING btree (user_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS agent_follow_ups_task_status_idx ON public.agent_follow_ups USING btree (task_id, status, created_at DESC);

INSERT INTO public.channel_identities (
    user_id, channel, external_id, external_name, thread_id, preferred,
    last_seen_at, created_at, updated_at
)
SELECT
    user_id, 'gapo'::public."ChannelKind", gapo_user_id::text, gapo_full_name,
    gapo_thread_id::text, true, last_seen_at, created_at, NOW()
FROM public.gapo_user_maps
ON CONFLICT (channel, external_id) DO UPDATE SET
    user_id = EXCLUDED.user_id,
    external_name = EXCLUDED.external_name,
    thread_id = EXCLUDED.thread_id,
    preferred = true,
    last_seen_at = EXCLUDED.last_seen_at,
    updated_at = NOW();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'tasks_company_id_fkey'
          AND conrelid = 'public.tasks'::regclass
    ) THEN
        ALTER TABLE public.tasks
            ADD CONSTRAINT tasks_company_id_fkey
            FOREIGN KEY (company_id) REFERENCES public.companies(id)
            ON UPDATE CASCADE ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'worklogs_company_id_fkey'
          AND conrelid = 'public.worklogs'::regclass
    ) THEN
        ALTER TABLE public.worklogs
            ADD CONSTRAINT worklogs_company_id_fkey
            FOREIGN KEY (company_id) REFERENCES public.companies(id)
            ON UPDATE CASCADE ON DELETE RESTRICT;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'worklogs_checkin_session_id_fkey'
          AND conrelid = 'public.worklogs'::regclass
    ) THEN
        ALTER TABLE public.worklogs
            ADD CONSTRAINT worklogs_checkin_session_id_fkey
            FOREIGN KEY (checkin_session_id) REFERENCES public.checkin_sessions(id)
            ON UPDATE CASCADE ON DELETE SET NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'checkin_sessions_company_id_fkey'
          AND conrelid = 'public.checkin_sessions'::regclass
    ) THEN
        ALTER TABLE public.checkin_sessions
            ADD CONSTRAINT checkin_sessions_company_id_fkey
            FOREIGN KEY (company_id) REFERENCES public.companies(id)
            ON UPDATE CASCADE ON DELETE RESTRICT;
    END IF;
END $$;

DROP TABLE IF EXISTS public.task_tags CASCADE;
DROP TABLE IF EXISTS public.project_tags CASCADE;
DROP TABLE IF EXISTS public.tags CASCADE;
DROP TABLE IF EXISTS public.customers CASCADE;
ALTER TABLE public.projects DROP COLUMN IF EXISTS customer_id;
