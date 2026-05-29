-- BB-PM Database Schema
-- Generated from schema.dbml 2026-05-23

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

-- ─── EXTENSIONS ───────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;

-- ─── ENUMS ────────────────────────────────────────────────────────────────────

CREATE TYPE public."Role" AS ENUM ('ADMIN', 'MANAGER', 'MEMBER');

CREATE TYPE public."ProjectStatus" AS ENUM (
    'PLANNED', 'PENDING', 'IN_PROGRESS', 'DONE', 'CANCELLED'
);

CREATE TYPE public."Priority" AS ENUM ('LOW', 'MEDIUM', 'HIGH', 'URGENT');

CREATE TYPE public."TaskStatus" AS ENUM (
    'TODO', 'IN_PROGRESS', 'DONE', 'CANCELLED'
);

CREATE TYPE public."CheckinState" AS ENUM (
    'IDLE', 'AWAITING_PROJECT', 'AWAITING_TASK', 'AWAITING_HOURS', 'CONFIRMING'
);

CREATE TYPE public."ChannelKind" AS ENUM (
    'gapo', 'slack', 'zalo', 'zalouser', 'telegram', 'email', 'sms'
);

CREATE TYPE public."AgentAuditSource" AS ENUM ('chat', 'cron', 'cli', 'other');

-- ─── CORE ─────────────────────────────────────────────────────────────────────

CREATE TABLE public.currencies (
    id      serial PRIMARY KEY,
    code    text           NOT NULL,
    symbol  text           NOT NULL,
    rate    numeric(20,6)  NOT NULL DEFAULT 1.0
);

CREATE UNIQUE INDEX currencies_code_key ON public.currencies USING btree (code);

CREATE TABLE public.companies (
    id          serial PRIMARY KEY,
    name        text                            NOT NULL,
    code        text,
    created_at  timestamp(3) without time zone  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  timestamp(3) without time zone  NOT NULL
);

CREATE UNIQUE INDEX companies_code_key ON public.companies USING btree (code);


CREATE TABLE public.users (
    id              serial PRIMARY KEY,
    email           text                            NOT NULL,
    password_hash   text                            NOT NULL,
    full_name       text                            NOT NULL,
    company_id      integer                         NOT NULL DEFAULT 1 REFERENCES public.companies(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    company_name    text                            NOT NULL DEFAULT 'BBSW Software',
    avatar_url      text,
    lang            text                            NOT NULL DEFAULT 'vi_VN',
    timezone        text                            NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
    role            public."Role"                   NOT NULL DEFAULT 'MEMBER',
    department      text,
    position        text,
    active          boolean                         NOT NULL DEFAULT true,
    is_admin        boolean                         NOT NULL DEFAULT false,
    last_login_at   timestamp(3) without time zone,
    created_at      timestamp(3) without time zone  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      timestamp(3) without time zone  NOT NULL
);

CREATE UNIQUE INDEX users_email_key ON public.users USING btree (email);


-- ─── PROJECTS ─────────────────────────────────────────────────────────────────

CREATE TABLE public.projects (
    id                  serial PRIMARY KEY,
    name                text                            NOT NULL,
    code                text,
    status              public."ProjectStatus"          NOT NULL DEFAULT 'PLANNED',
    priority            public."Priority"               NOT NULL DEFAULT 'MEDIUM',
    start_date          date,
    end_date            date,
    description         text,
    total_hours         double precision                NOT NULL DEFAULT 0,
    task_count          integer                         NOT NULL DEFAULT 0,
    member_count        integer                         NOT NULL DEFAULT 0,
    worklog_count       integer                         NOT NULL DEFAULT 0,
    scope_count         integer                         NOT NULL DEFAULT 0,
    milestone_count     integer                         NOT NULL DEFAULT 0,
    customer_name       text,
    company_id          integer                         NOT NULL DEFAULT 1 REFERENCES public.companies(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    owner_id            integer                         NOT NULL REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    account_manager_id  integer                         REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    currency_id         integer                         REFERENCES public.currencies(id) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at          timestamp(3) without time zone  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          timestamp(3) without time zone  NOT NULL
);

CREATE UNIQUE INDEX projects_code_key ON public.projects USING btree (code);
CREATE INDEX projects_status_idx ON public.projects USING btree (status);
CREATE INDEX projects_company_id_status_idx ON public.projects USING btree (company_id, status);
CREATE INDEX projects_customer_name_idx ON public.projects USING btree (customer_name);


CREATE TABLE public.members (
    id          serial PRIMARY KEY,
    project_id  integer                         NOT NULL REFERENCES public.projects(id) ON UPDATE CASCADE ON DELETE CASCADE,
    user_id     integer                         NOT NULL REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    role        text,
    joined_at   timestamp(3) without time zone  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at  timestamp(3) without time zone  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  timestamp(3) without time zone  NOT NULL
);

CREATE UNIQUE INDEX members_project_id_user_id_key ON public.members USING btree (project_id, user_id);
CREATE INDEX members_user_id_idx ON public.members USING btree (user_id);


CREATE TABLE public.milestones (
    id              serial PRIMARY KEY,
    name            text                            NOT NULL,
    status          text,
    due_date        date,
    description     text,
    task_count      integer                         NOT NULL DEFAULT 0,
    done_count      integer                         NOT NULL DEFAULT 0,
    completion_pct  integer                         NOT NULL DEFAULT 0,
    project_id      integer                         NOT NULL REFERENCES public.projects(id) ON UPDATE CASCADE ON DELETE CASCADE,
    created_at      timestamp(3) without time zone  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      timestamp(3) without time zone  NOT NULL
);

CREATE INDEX milestones_project_id_idx ON public.milestones USING btree (project_id);


-- ─── TASK STATUS ──────────────────────────────────────────────────────────────

CREATE TABLE public.task_status (
    id          serial PRIMARY KEY,
    code        text     NOT NULL,
    label       text     NOT NULL,
    color       text,
    sort_order  integer  NOT NULL DEFAULT 0,
    is_active   boolean  NOT NULL DEFAULT true
);

CREATE UNIQUE INDEX task_status_code_key ON public.task_status USING btree (code);

INSERT INTO public.task_status (code, label, color, sort_order) VALUES
    ('todo',        'Todo',        '#94a3b8', 1),
    ('in_progress', 'In Progress', '#3b82f6', 2),
    ('done',        'Done',        '#22c55e', 3),
    ('cancelled',   'Cancelled',   '#ef4444', 4);


-- ─── TASKS ────────────────────────────────────────────────────────────────────

CREATE TABLE public.tasks (
    id           serial PRIMARY KEY,
    name         text                            NOT NULL,
    status       public."TaskStatus"             NOT NULL DEFAULT 'TODO',
    priority     public."Priority"               NOT NULL DEFAULT 'MEDIUM',
    deadline     date,
    end_at       date,
    description  text,
    result       text,
    issues       text,
    total_hours  double precision                NOT NULL DEFAULT 0,
    project_id   integer                         NOT NULL REFERENCES public.projects(id) ON UPDATE CASCADE ON DELETE CASCADE,
    company_id   integer                         NOT NULL DEFAULT 1 REFERENCES public.companies(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    assignee_id  integer                         REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE SET NULL,
    milestone_id integer                         REFERENCES public.milestones(id) ON UPDATE CASCADE ON DELETE SET NULL,
    currency_id  integer                         REFERENCES public.currencies(id) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at   timestamp(3) without time zone  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   timestamp(3) without time zone  NOT NULL
);

CREATE INDEX tasks_project_id_status_idx ON public.tasks USING btree (project_id, status);
CREATE INDEX tasks_company_id_status_idx ON public.tasks USING btree (company_id, status);
CREATE INDEX tasks_assignee_id_status_idx ON public.tasks USING btree (assignee_id, status);
CREATE INDEX tasks_deadline_status_idx ON public.tasks USING btree (deadline, status);
CREATE INDEX tasks_milestone_id_idx ON public.tasks USING btree (milestone_id);
CREATE INDEX tasks_updated_at_idx ON public.tasks USING btree (updated_at);


-- ─── WORKLOGS ─────────────────────────────────────────────────────────────────

CREATE TABLE public.worklogs (
    id           serial PRIMARY KEY,
    work_date    date                            NOT NULL,
    description  text,
    hours        numeric(6,2)                    NOT NULL,
    task_id      integer                         REFERENCES public.tasks(id) ON UPDATE CASCADE ON DELETE SET NULL,
    project_id   integer                         NOT NULL REFERENCES public.projects(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    company_id   integer                         NOT NULL DEFAULT 1 REFERENCES public.companies(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    user_id      integer                         NOT NULL REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    created_at   timestamp(3) without time zone  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   timestamp(3) without time zone  NOT NULL
);

CREATE INDEX worklogs_project_id_work_date_idx ON public.worklogs USING btree (project_id, work_date);
CREATE INDEX worklogs_company_id_work_date_idx ON public.worklogs USING btree (company_id, work_date);
CREATE INDEX worklogs_user_id_work_date_idx ON public.worklogs USING btree (user_id, work_date);


-- ─── AI AGENT ─────────────────────────────────────────────────────────────────

CREATE TABLE public.gapo_user_maps (
    id              serial PRIMARY KEY,
    user_id         integer                         NOT NULL REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE CASCADE,
    gapo_user_id    bigint                          NOT NULL,
    gapo_thread_id  bigint                          NOT NULL,
    gapo_full_name  text,
    last_seen_at    timestamp(3) without time zone  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at      timestamp(3) without time zone  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX gapo_user_maps_user_id_key ON public.gapo_user_maps USING btree (user_id);
CREATE INDEX gapo_user_maps_gapo_user_id_idx ON public.gapo_user_maps USING btree (gapo_user_id);


CREATE TABLE public.channel_identities (
    id              serial PRIMARY KEY,
    user_id         integer                         NOT NULL REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE CASCADE,
    channel         public."ChannelKind"             NOT NULL,
    external_id     text                            NOT NULL,
    external_name   text,
    thread_id       text,
    preferred       boolean                         NOT NULL DEFAULT false,
    last_seen_at    timestamp(3) without time zone  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at      timestamp(3) without time zone  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      timestamp(3) without time zone  NOT NULL
);

CREATE UNIQUE INDEX channel_identities_channel_external_id_key ON public.channel_identities USING btree (channel, external_id);
CREATE INDEX channel_identities_user_id_channel_preferred_idx ON public.channel_identities USING btree (user_id, channel, preferred);


CREATE TABLE public.checkin_sessions (
    id                  serial PRIMARY KEY,
    user_id             integer                         NOT NULL REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE CASCADE,
    gapo_user_id        text                            NOT NULL,
    thread_id           text                            NOT NULL,
    current_project_id  integer,
    current_task_id     integer,
    state               public."CheckinState"           NOT NULL DEFAULT 'IDLE',
    expires_at          timestamp(3) without time zone  NOT NULL,
    last_message_id     text,
    pending_text        text,
    pending_parsed      jsonb,
    completed_at        timestamp(3) without time zone,
    created_at          timestamp(3) without time zone  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          timestamp(3) without time zone  NOT NULL
);

CREATE UNIQUE INDEX checkin_sessions_user_id_key ON public.checkin_sessions USING btree (user_id);
CREATE INDEX checkin_sessions_state_expires_at_idx ON public.checkin_sessions USING btree (state, expires_at);


CREATE TABLE public.agent_memory (
    id               serial PRIMARY KEY,
    conversation_id  text,
    source           public."AgentAuditSource"        NOT NULL DEFAULT 'chat',
    user_text        text                            NOT NULL,
    reply_text       text                            NOT NULL,
    summary          text                            NOT NULL,
    tools_used       jsonb                           NOT NULL DEFAULT '[]',
    project_ids      integer[],
    task_ids         integer[],
    correlation_id   text,
    created_at       timestamp(3) without time zone  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX agent_memory_created_at_idx ON public.agent_memory USING btree (created_at);
CREATE INDEX agent_memory_conversation_id_idx ON public.agent_memory USING btree (conversation_id);


CREATE TABLE public.automations (
    id                serial PRIMARY KEY,
    name              text                            NOT NULL,
    workflow          text                            NOT NULL,
    schedule          text                            NOT NULL,
    inputs            jsonb                           NOT NULL DEFAULT '{}',
    target            text,
    active            boolean                         NOT NULL DEFAULT true,
    owner_id          integer                         NOT NULL REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    created_at        timestamp(3) without time zone  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        timestamp(3) without time zone  NOT NULL,
    last_run_at       timestamp(3) without time zone,
    last_run_status   text,
    last_run_error    text,
    consecutive_fails integer                         NOT NULL DEFAULT 0
);

CREATE INDEX automations_active_schedule_idx ON public.automations USING btree (active, schedule);
