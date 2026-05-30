-- =============================================================================
-- BB-PM — Database Schema (CONSOLIDATED, source of truth cho backend & AI agent)
-- =============================================================================
-- File schema HỢP NHẤT, chạy được từ đầu trên Postgres rỗng. Thay thế cho chuỗi
-- migration cũ (schema.sql + 002..009) vốn không compose được từ scratch.
--
-- Nội dung = trạng thái cuối của: schema.sql + 003-align-live-backend-schema
--            + 005..009 (status enums). Khớp đúng các cột/bảng mà backend FastAPI
--            đang query (users.is_super_admin, currencies, scopes, backlogs,
--            meetings, agent_audit_log, worklogs.slot/source..., checkin slot...).
--
-- Quy ước: KHÔNG chứa data. Toàn bộ seed (currencies, task_status, company, users,
--          demo) nằm ở seed.sql. Init chỉ chạy khi volume Postgres còn rỗng.
-- =============================================================================

--
-- PostgreSQL database dump
--


-- Dumped from database version 16.13 (Debian 16.13-1.pgdg13+1)
-- Dumped by pg_dump version 16.13 (Debian 16.13-1.pgdg13+1)

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

--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: AgentAuditSource; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."AgentAuditSource" AS ENUM (
    'chat',
    'cron',
    'cli',
    'other'
);


--
-- Name: BacklogSource; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."BacklogSource" AS ENUM (
    'manual',
    'checkin',
    'import'
);


--
-- Name: BacklogStatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."BacklogStatus" AS ENUM (
    'PENDING',
    'APPROVED',
    'REJECTED'
);


--
-- Name: BlockerSeverity; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."BlockerSeverity" AS ENUM (
    'LOW',
    'MED',
    'HIGH',
    'CRITICAL'
);


--
-- Name: ChannelKind; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."ChannelKind" AS ENUM (
    'gapo',
    'slack',
    'zalo',
    'zalouser',
    'telegram',
    'email',
    'sms'
);


--
-- Name: CheckinState; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."CheckinState" AS ENUM (
    'IDLE',
    'AWAITING_PROJECT',
    'AWAITING_TASK',
    'AWAITING_HOURS',
    'CONFIRMING',
    'AWAITING_UPDATE',
    'AWAITING_TASK_CONFIRM',
    'COMPLETED',
    'CANCELLED',
    'EXPIRED',
    'MISSED'
);


--
-- Name: FollowUpStatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."FollowUpStatus" AS ENUM (
    'PENDING',
    'REPLIED',
    'EXPIRED'
);


--
-- Name: MeetingItemStatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."MeetingItemStatus" AS ENUM (
    'DRAFT',
    'APPROVED',
    'REJECTED'
);


--
-- Name: Priority; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."Priority" AS ENUM (
    'LOW',
    'MEDIUM',
    'HIGH',
    'URGENT'
);


--
-- Name: ProjectStatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."ProjectStatus" AS ENUM (
    'PLANNED',
    'PENDING',
    'IN_PROGRESS',
    'DONE',
    'CANCELLED'
);


--
-- Name: Role; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."Role" AS ENUM (
    'ADMIN',
    'MANAGER',
    'MEMBER',
    'VIEWER',
    'SUPER_ADMIN'
);


--
-- Name: TaskStatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public."TaskStatus" AS ENUM (
    'TODO',
    'IN_PROGRESS',
    'DONE',
    'CANCELLED'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agent_audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_audit_log (
    id integer NOT NULL,
    tool text NOT NULL,
    args_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    result_json jsonb,
    error_message text,
    duration_ms integer,
    correlation_id text,
    source public."AgentAuditSource" DEFAULT 'other'::public."AgentAuditSource" NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: agent_audit_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_audit_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_audit_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_audit_log_id_seq OWNED BY public.agent_audit_log.id;


--
-- Name: agent_follow_ups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_follow_ups (
    id integer NOT NULL,
    task_id integer NOT NULL,
    user_id integer NOT NULL,
    channel public."ChannelKind" DEFAULT 'gapo'::public."ChannelKind" NOT NULL,
    thread_id text,
    question text NOT NULL,
    status public."FollowUpStatus" DEFAULT 'PENDING'::public."FollowUpStatus" NOT NULL,
    asked_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    replied_at timestamp(3) without time zone,
    reply_text text,
    correlation_id text,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: agent_follow_ups_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_follow_ups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_follow_ups_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_follow_ups_id_seq OWNED BY public.agent_follow_ups.id;


--
-- Name: agent_memory; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.agent_memory (
    id integer NOT NULL,
    conversation_id text,
    source public."AgentAuditSource" DEFAULT 'chat'::public."AgentAuditSource" NOT NULL,
    user_text text NOT NULL,
    reply_text text NOT NULL,
    summary text NOT NULL,
    tools_used jsonb DEFAULT '[]'::jsonb NOT NULL,
    project_ids integer[],
    task_ids integer[],
    correlation_id text,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: agent_memory_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.agent_memory_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_memory_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.agent_memory_id_seq OWNED BY public.agent_memory.id;


--
-- Name: automations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.automations (
    id integer NOT NULL,
    name text NOT NULL,
    workflow text NOT NULL,
    schedule text NOT NULL,
    inputs jsonb DEFAULT '{}'::jsonb NOT NULL,
    target text,
    active boolean DEFAULT true NOT NULL,
    owner_id integer NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    last_run_at timestamp(3) without time zone,
    last_run_status text,
    last_run_error text,
    consecutive_fails integer DEFAULT 0 NOT NULL,
    company_id integer NOT NULL
);


--
-- Name: automations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.automations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: automations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.automations_id_seq OWNED BY public.automations.id;


--
-- Name: backlogs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backlogs (
    id integer NOT NULL,
    status public."BacklogStatus" DEFAULT 'PENDING'::public."BacklogStatus" NOT NULL,
    source public."BacklogSource" DEFAULT 'manual'::public."BacklogSource" NOT NULL,
    work_date date NOT NULL,
    description text,
    hours numeric(6,2) NOT NULL,
    task_id integer,
    project_id integer NOT NULL,
    company_id integer NOT NULL,
    user_id integer NOT NULL,
    currency_id integer,
    approver_id integer,
    approved_at timestamp(3) without time zone,
    rejected_reason text,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: backlogs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.backlogs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: backlogs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.backlogs_id_seq OWNED BY public.backlogs.id;


--
-- Name: channel_identities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.channel_identities (
    id integer NOT NULL,
    user_id integer NOT NULL,
    channel public."ChannelKind" NOT NULL,
    external_id text NOT NULL,
    external_name text,
    thread_id text,
    preferred boolean DEFAULT false NOT NULL,
    last_seen_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL
);


--
-- Name: channel_identities_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.channel_identities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: channel_identities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.channel_identities_id_seq OWNED BY public.channel_identities.id;


--
-- Name: checkin_sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.checkin_sessions (
    id integer NOT NULL,
    user_id integer NOT NULL,
    gapo_user_id text NOT NULL,
    thread_id text NOT NULL,
    current_project_id integer,
    current_task_id integer,
    state public."CheckinState" DEFAULT 'IDLE'::public."CheckinState" NOT NULL,
    expires_at timestamp(3) without time zone NOT NULL,
    last_message_id text,
    pending_text text,
    pending_parsed jsonb,
    completed_at timestamp(3) without time zone,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    company_id integer NOT NULL,
    work_date date NOT NULL,
    slot text NOT NULL,
    reminder_count integer DEFAULT 0 NOT NULL,
    last_reminded_at timestamp(3) without time zone,
    missed_at timestamp(3) without time zone
);


--
-- Name: checkin_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.checkin_sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: checkin_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.checkin_sessions_id_seq OWNED BY public.checkin_sessions.id;


--
-- Name: companies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.companies (
    id integer NOT NULL,
    name text NOT NULL,
    code text,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    currency_id integer
);


--
-- Name: companies_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.companies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: companies_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.companies_id_seq OWNED BY public.companies.id;


--
-- Name: currencies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.currencies (
    id integer NOT NULL,
    code text NOT NULL,
    symbol text NOT NULL,
    rate numeric(20,6) DEFAULT 1.0 NOT NULL
);


--
-- Name: currencies_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.currencies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: currencies_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.currencies_id_seq OWNED BY public.currencies.id;


--
-- Name: gapo_user_maps; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.gapo_user_maps (
    id integer NOT NULL,
    user_id integer NOT NULL,
    gapo_user_id bigint NOT NULL,
    gapo_thread_id bigint NOT NULL,
    gapo_full_name text,
    last_seen_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: gapo_user_maps_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.gapo_user_maps_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: gapo_user_maps_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.gapo_user_maps_id_seq OWNED BY public.gapo_user_maps.id;


--
-- Name: meeting_action_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.meeting_action_items (
    id integer NOT NULL,
    meeting_id integer NOT NULL,
    title text NOT NULL,
    description text,
    owner_name text,
    owner_user_id integer,
    due_date date,
    priority public."Priority" DEFAULT 'MEDIUM'::public."Priority" NOT NULL,
    status public."MeetingItemStatus" DEFAULT 'DRAFT'::public."MeetingItemStatus" NOT NULL,
    created_task_id integer,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: meeting_action_items_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.meeting_action_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: meeting_action_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.meeting_action_items_id_seq OWNED BY public.meeting_action_items.id;


--
-- Name: meetings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.meetings (
    id integer NOT NULL,
    company_id integer NOT NULL,
    project_id integer,
    title text,
    held_at timestamp with time zone DEFAULT now() NOT NULL,
    transcript text NOT NULL,
    summary text,
    decisions jsonb DEFAULT '[]'::jsonb NOT NULL,
    participants text[] DEFAULT '{}'::text[] NOT NULL,
    created_by_id integer,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: meetings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.meetings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: meetings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.meetings_id_seq OWNED BY public.meetings.id;


--
-- Name: members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.members (
    id integer NOT NULL,
    project_id integer NOT NULL,
    user_id integer NOT NULL,
    role text,
    joined_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL
);


--
-- Name: members_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.members_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: members_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.members_id_seq OWNED BY public.members.id;


--
-- Name: milestones; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.milestones (
    id integer NOT NULL,
    name text NOT NULL,
    status text,
    due_date date,
    description text,
    task_count integer DEFAULT 0 NOT NULL,
    done_count integer DEFAULT 0 NOT NULL,
    completion_pct integer DEFAULT 0 NOT NULL,
    project_id integer NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL
);


--
-- Name: milestones_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.milestones_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: milestones_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.milestones_id_seq OWNED BY public.milestones.id;


--
-- Name: projects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.projects (
    id integer NOT NULL,
    name text NOT NULL,
    code text,
    status public."ProjectStatus" DEFAULT 'PLANNED'::public."ProjectStatus" NOT NULL,
    priority public."Priority" DEFAULT 'MEDIUM'::public."Priority" NOT NULL,
    start_date date,
    end_date date,
    description text,
    total_hours double precision DEFAULT 0 NOT NULL,
    task_count integer DEFAULT 0 NOT NULL,
    member_count integer DEFAULT 0 NOT NULL,
    worklog_count integer DEFAULT 0 NOT NULL,
    scope_count integer DEFAULT 0 NOT NULL,
    milestone_count integer DEFAULT 0 NOT NULL,
    customer_name text,
    company_id integer DEFAULT 1 NOT NULL,
    owner_id integer NOT NULL,
    account_manager_id integer,
    currency_id integer,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL
);


--
-- Name: projects_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.projects_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: projects_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.projects_id_seq OWNED BY public.projects.id;


--
-- Name: scopes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scopes (
    id integer NOT NULL,
    sequence integer DEFAULT 10 NOT NULL,
    name text NOT NULL,
    notes text,
    estimated_hours numeric(12,2),
    project_id integer NOT NULL,
    task_id integer,
    assignee_id integer,
    currency_id integer,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: scopes_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scopes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scopes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scopes_id_seq OWNED BY public.scopes.id;


--
-- Name: task_blockers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_blockers (
    id integer NOT NULL,
    task_id integer NOT NULL,
    severity public."BlockerSeverity" DEFAULT 'MED'::public."BlockerSeverity" NOT NULL,
    description text NOT NULL,
    resolved_at timestamp(3) without time zone,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: task_blockers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.task_blockers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: task_blockers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.task_blockers_id_seq OWNED BY public.task_blockers.id;


--
-- Name: task_status; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.task_status (
    id integer NOT NULL,
    code text NOT NULL,
    label text NOT NULL,
    color text,
    sort_order integer DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL
);


--
-- Name: task_status_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.task_status_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: task_status_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.task_status_id_seq OWNED BY public.task_status.id;


--
-- Name: tasks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tasks (
    id integer NOT NULL,
    name text NOT NULL,
    status public."TaskStatus" DEFAULT 'TODO'::public."TaskStatus" NOT NULL,
    priority public."Priority" DEFAULT 'MEDIUM'::public."Priority" NOT NULL,
    deadline date,
    end_at date,
    description text,
    result text,
    issues text,
    total_hours double precision DEFAULT 0 NOT NULL,
    project_id integer NOT NULL,
    company_id integer DEFAULT 1 NOT NULL,
    assignee_id integer,
    milestone_id integer,
    currency_id integer,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL
);


--
-- Name: tasks_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tasks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tasks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tasks_id_seq OWNED BY public.tasks.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id integer NOT NULL,
    email text NOT NULL,
    password_hash text NOT NULL,
    full_name text NOT NULL,
    company_id integer DEFAULT 1 NOT NULL,
    company_name text DEFAULT 'BBSW Software'::text NOT NULL,
    avatar_url text,
    lang text DEFAULT 'vi_VN'::text NOT NULL,
    timezone text DEFAULT 'Asia/Ho_Chi_Minh'::text NOT NULL,
    role public."Role" DEFAULT 'MEMBER'::public."Role" NOT NULL,
    department text,
    "position" text,
    active boolean DEFAULT true NOT NULL,
    is_admin boolean DEFAULT false NOT NULL,
    last_login_at timestamp(3) without time zone,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    is_super_admin boolean DEFAULT false NOT NULL
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: worklogs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.worklogs (
    id integer NOT NULL,
    work_date date NOT NULL,
    description text,
    hours numeric(6,2) NOT NULL,
    task_id integer,
    project_id integer NOT NULL,
    company_id integer DEFAULT 1 NOT NULL,
    user_id integer NOT NULL,
    created_at timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp(3) without time zone NOT NULL,
    source text,
    raw_message text,
    parsed_json jsonb,
    checkin_session_id integer,
    slot text
);


--
-- Name: worklogs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.worklogs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: worklogs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.worklogs_id_seq OWNED BY public.worklogs.id;


--
-- Name: agent_audit_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_audit_log ALTER COLUMN id SET DEFAULT nextval('public.agent_audit_log_id_seq'::regclass);


--
-- Name: agent_follow_ups id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_follow_ups ALTER COLUMN id SET DEFAULT nextval('public.agent_follow_ups_id_seq'::regclass);


--
-- Name: agent_memory id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_memory ALTER COLUMN id SET DEFAULT nextval('public.agent_memory_id_seq'::regclass);


--
-- Name: automations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automations ALTER COLUMN id SET DEFAULT nextval('public.automations_id_seq'::regclass);


--
-- Name: backlogs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backlogs ALTER COLUMN id SET DEFAULT nextval('public.backlogs_id_seq'::regclass);


--
-- Name: channel_identities id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel_identities ALTER COLUMN id SET DEFAULT nextval('public.channel_identities_id_seq'::regclass);


--
-- Name: checkin_sessions id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.checkin_sessions ALTER COLUMN id SET DEFAULT nextval('public.checkin_sessions_id_seq'::regclass);


--
-- Name: companies id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.companies ALTER COLUMN id SET DEFAULT nextval('public.companies_id_seq'::regclass);


--
-- Name: currencies id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.currencies ALTER COLUMN id SET DEFAULT nextval('public.currencies_id_seq'::regclass);


--
-- Name: gapo_user_maps id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gapo_user_maps ALTER COLUMN id SET DEFAULT nextval('public.gapo_user_maps_id_seq'::regclass);


--
-- Name: meeting_action_items id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meeting_action_items ALTER COLUMN id SET DEFAULT nextval('public.meeting_action_items_id_seq'::regclass);


--
-- Name: meetings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meetings ALTER COLUMN id SET DEFAULT nextval('public.meetings_id_seq'::regclass);


--
-- Name: members id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.members ALTER COLUMN id SET DEFAULT nextval('public.members_id_seq'::regclass);


--
-- Name: milestones id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.milestones ALTER COLUMN id SET DEFAULT nextval('public.milestones_id_seq'::regclass);


--
-- Name: projects id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects ALTER COLUMN id SET DEFAULT nextval('public.projects_id_seq'::regclass);


--
-- Name: scopes id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scopes ALTER COLUMN id SET DEFAULT nextval('public.scopes_id_seq'::regclass);


--
-- Name: task_blockers id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_blockers ALTER COLUMN id SET DEFAULT nextval('public.task_blockers_id_seq'::regclass);


--
-- Name: task_status id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_status ALTER COLUMN id SET DEFAULT nextval('public.task_status_id_seq'::regclass);


--
-- Name: tasks id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks ALTER COLUMN id SET DEFAULT nextval('public.tasks_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: worklogs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.worklogs ALTER COLUMN id SET DEFAULT nextval('public.worklogs_id_seq'::regclass);


--
-- Name: agent_audit_log agent_audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_audit_log
    ADD CONSTRAINT agent_audit_log_pkey PRIMARY KEY (id);


--
-- Name: agent_follow_ups agent_follow_ups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_follow_ups
    ADD CONSTRAINT agent_follow_ups_pkey PRIMARY KEY (id);


--
-- Name: agent_memory agent_memory_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_memory
    ADD CONSTRAINT agent_memory_pkey PRIMARY KEY (id);


--
-- Name: automations automations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automations
    ADD CONSTRAINT automations_pkey PRIMARY KEY (id);


--
-- Name: backlogs backlogs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backlogs
    ADD CONSTRAINT backlogs_pkey PRIMARY KEY (id);


--
-- Name: channel_identities channel_identities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel_identities
    ADD CONSTRAINT channel_identities_pkey PRIMARY KEY (id);


--
-- Name: checkin_sessions checkin_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.checkin_sessions
    ADD CONSTRAINT checkin_sessions_pkey PRIMARY KEY (id);


--
-- Name: companies companies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.companies
    ADD CONSTRAINT companies_pkey PRIMARY KEY (id);


--
-- Name: currencies currencies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.currencies
    ADD CONSTRAINT currencies_pkey PRIMARY KEY (id);


--
-- Name: gapo_user_maps gapo_user_maps_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gapo_user_maps
    ADD CONSTRAINT gapo_user_maps_pkey PRIMARY KEY (id);


--
-- Name: meeting_action_items meeting_action_items_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meeting_action_items
    ADD CONSTRAINT meeting_action_items_pkey PRIMARY KEY (id);


--
-- Name: meetings meetings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meetings
    ADD CONSTRAINT meetings_pkey PRIMARY KEY (id);


--
-- Name: members members_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.members
    ADD CONSTRAINT members_pkey PRIMARY KEY (id);


--
-- Name: milestones milestones_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.milestones
    ADD CONSTRAINT milestones_pkey PRIMARY KEY (id);


--
-- Name: projects projects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);


--
-- Name: scopes scopes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scopes
    ADD CONSTRAINT scopes_pkey PRIMARY KEY (id);


--
-- Name: task_blockers task_blockers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_blockers
    ADD CONSTRAINT task_blockers_pkey PRIMARY KEY (id);


--
-- Name: task_status task_status_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_status
    ADD CONSTRAINT task_status_pkey PRIMARY KEY (id);


--
-- Name: tasks tasks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: worklogs worklogs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.worklogs
    ADD CONSTRAINT worklogs_pkey PRIMARY KEY (id);


--
-- Name: agent_audit_log_correlation_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX agent_audit_log_correlation_id_idx ON public.agent_audit_log USING btree (correlation_id);


--
-- Name: agent_audit_log_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX agent_audit_log_created_at_idx ON public.agent_audit_log USING btree (created_at DESC);


--
-- Name: agent_follow_ups_task_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX agent_follow_ups_task_status_idx ON public.agent_follow_ups USING btree (task_id, status, created_at DESC);


--
-- Name: agent_follow_ups_user_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX agent_follow_ups_user_status_idx ON public.agent_follow_ups USING btree (user_id, status, created_at DESC);


--
-- Name: agent_memory_conversation_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX agent_memory_conversation_id_idx ON public.agent_memory USING btree (conversation_id);


--
-- Name: agent_memory_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX agent_memory_created_at_idx ON public.agent_memory USING btree (created_at);


--
-- Name: automations_active_schedule_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX automations_active_schedule_idx ON public.automations USING btree (active, schedule);


--
-- Name: automations_company_active_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX automations_company_active_idx ON public.automations USING btree (company_id, active);


--
-- Name: backlogs_company_status_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX backlogs_company_status_date_idx ON public.backlogs USING btree (company_id, status, work_date);


--
-- Name: backlogs_project_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX backlogs_project_id_idx ON public.backlogs USING btree (project_id);


--
-- Name: channel_identities_channel_external_id_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX channel_identities_channel_external_id_key ON public.channel_identities USING btree (channel, external_id);


--
-- Name: channel_identities_user_id_channel_preferred_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX channel_identities_user_id_channel_preferred_idx ON public.channel_identities USING btree (user_id, channel, preferred);


--
-- Name: checkin_sessions_company_state_expires_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX checkin_sessions_company_state_expires_idx ON public.checkin_sessions USING btree (company_id, state, expires_at);


--
-- Name: checkin_sessions_slot_reminder_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX checkin_sessions_slot_reminder_idx ON public.checkin_sessions USING btree (slot, state, expires_at, reminder_count);


--
-- Name: checkin_sessions_state_expires_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX checkin_sessions_state_expires_at_idx ON public.checkin_sessions USING btree (state, expires_at);


--
-- Name: checkin_sessions_user_date_slot_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX checkin_sessions_user_date_slot_idx ON public.checkin_sessions USING btree (user_id, work_date, slot);


--
-- Name: companies_code_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX companies_code_key ON public.companies USING btree (code);


--
-- Name: currencies_code_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX currencies_code_key ON public.currencies USING btree (code);


--
-- Name: gapo_user_maps_gapo_user_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX gapo_user_maps_gapo_user_id_idx ON public.gapo_user_maps USING btree (gapo_user_id);


--
-- Name: gapo_user_maps_user_id_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX gapo_user_maps_user_id_key ON public.gapo_user_maps USING btree (user_id);


--
-- Name: meeting_action_items_meeting_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX meeting_action_items_meeting_id_idx ON public.meeting_action_items USING btree (meeting_id);


--
-- Name: meetings_company_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX meetings_company_created_at_idx ON public.meetings USING btree (company_id, created_at);


--
-- Name: members_project_id_user_id_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX members_project_id_user_id_key ON public.members USING btree (project_id, user_id);


--
-- Name: members_user_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX members_user_id_idx ON public.members USING btree (user_id);


--
-- Name: milestones_project_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX milestones_project_id_idx ON public.milestones USING btree (project_id);


--
-- Name: projects_code_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX projects_code_key ON public.projects USING btree (code);


--
-- Name: projects_company_id_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX projects_company_id_status_idx ON public.projects USING btree (company_id, status);


--
-- Name: projects_customer_name_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX projects_customer_name_idx ON public.projects USING btree (customer_name);


--
-- Name: projects_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX projects_status_idx ON public.projects USING btree (status);


--
-- Name: scopes_project_id_sequence_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX scopes_project_id_sequence_idx ON public.scopes USING btree (project_id, sequence);


--
-- Name: task_blockers_task_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX task_blockers_task_id_idx ON public.task_blockers USING btree (task_id);


--
-- Name: task_status_code_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX task_status_code_key ON public.task_status USING btree (code);


--
-- Name: tasks_assignee_id_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX tasks_assignee_id_status_idx ON public.tasks USING btree (assignee_id, status);


--
-- Name: tasks_company_id_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX tasks_company_id_status_idx ON public.tasks USING btree (company_id, status);


--
-- Name: tasks_deadline_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX tasks_deadline_status_idx ON public.tasks USING btree (deadline, status);


--
-- Name: tasks_milestone_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX tasks_milestone_id_idx ON public.tasks USING btree (milestone_id);


--
-- Name: tasks_project_id_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX tasks_project_id_status_idx ON public.tasks USING btree (project_id, status);


--
-- Name: tasks_updated_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX tasks_updated_at_idx ON public.tasks USING btree (updated_at);


--
-- Name: users_company_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX users_company_id_idx ON public.users USING btree (company_id);


--
-- Name: users_email_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX users_email_key ON public.users USING btree (email);


--
-- Name: worklogs_checkin_session_id_raw_message_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX worklogs_checkin_session_id_raw_message_idx ON public.worklogs USING btree (checkin_session_id, raw_message);


--
-- Name: worklogs_company_id_work_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX worklogs_company_id_work_date_idx ON public.worklogs USING btree (company_id, work_date);


--
-- Name: worklogs_project_id_work_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX worklogs_project_id_work_date_idx ON public.worklogs USING btree (project_id, work_date);


--
-- Name: worklogs_user_id_work_date_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX worklogs_user_id_work_date_idx ON public.worklogs USING btree (user_id, work_date);


--
-- Name: agent_follow_ups agent_follow_ups_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_follow_ups
    ADD CONSTRAINT agent_follow_ups_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: agent_follow_ups agent_follow_ups_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.agent_follow_ups
    ADD CONSTRAINT agent_follow_ups_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: automations automations_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automations
    ADD CONSTRAINT automations_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: backlogs backlogs_approver_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backlogs
    ADD CONSTRAINT backlogs_approver_id_fkey FOREIGN KEY (approver_id) REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: backlogs backlogs_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backlogs
    ADD CONSTRAINT backlogs_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: backlogs backlogs_currency_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backlogs
    ADD CONSTRAINT backlogs_currency_id_fkey FOREIGN KEY (currency_id) REFERENCES public.currencies(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: backlogs backlogs_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backlogs
    ADD CONSTRAINT backlogs_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: backlogs backlogs_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backlogs
    ADD CONSTRAINT backlogs_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: backlogs backlogs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backlogs
    ADD CONSTRAINT backlogs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: channel_identities channel_identities_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel_identities
    ADD CONSTRAINT channel_identities_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: checkin_sessions checkin_sessions_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.checkin_sessions
    ADD CONSTRAINT checkin_sessions_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: checkin_sessions checkin_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.checkin_sessions
    ADD CONSTRAINT checkin_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: companies companies_currency_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.companies
    ADD CONSTRAINT companies_currency_id_fkey FOREIGN KEY (currency_id) REFERENCES public.currencies(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: gapo_user_maps gapo_user_maps_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gapo_user_maps
    ADD CONSTRAINT gapo_user_maps_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: meeting_action_items meeting_action_items_created_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meeting_action_items
    ADD CONSTRAINT meeting_action_items_created_task_id_fkey FOREIGN KEY (created_task_id) REFERENCES public.tasks(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: meeting_action_items meeting_action_items_meeting_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meeting_action_items
    ADD CONSTRAINT meeting_action_items_meeting_id_fkey FOREIGN KEY (meeting_id) REFERENCES public.meetings(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: meeting_action_items meeting_action_items_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meeting_action_items
    ADD CONSTRAINT meeting_action_items_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: meetings meetings_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meetings
    ADD CONSTRAINT meetings_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: meetings meetings_created_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meetings
    ADD CONSTRAINT meetings_created_by_id_fkey FOREIGN KEY (created_by_id) REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: meetings meetings_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.meetings
    ADD CONSTRAINT meetings_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: members members_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.members
    ADD CONSTRAINT members_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: members members_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.members
    ADD CONSTRAINT members_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: milestones milestones_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.milestones
    ADD CONSTRAINT milestones_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: projects projects_account_manager_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_account_manager_id_fkey FOREIGN KEY (account_manager_id) REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: projects projects_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: projects projects_currency_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_currency_id_fkey FOREIGN KEY (currency_id) REFERENCES public.currencies(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: projects projects_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: scopes scopes_assignee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scopes
    ADD CONSTRAINT scopes_assignee_id_fkey FOREIGN KEY (assignee_id) REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: scopes scopes_currency_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scopes
    ADD CONSTRAINT scopes_currency_id_fkey FOREIGN KEY (currency_id) REFERENCES public.currencies(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: scopes scopes_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scopes
    ADD CONSTRAINT scopes_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: scopes scopes_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scopes
    ADD CONSTRAINT scopes_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: task_blockers task_blockers_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.task_blockers
    ADD CONSTRAINT task_blockers_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: tasks tasks_assignee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_assignee_id_fkey FOREIGN KEY (assignee_id) REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: tasks tasks_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: tasks tasks_currency_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_currency_id_fkey FOREIGN KEY (currency_id) REFERENCES public.currencies(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: tasks tasks_milestone_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_milestone_id_fkey FOREIGN KEY (milestone_id) REFERENCES public.milestones(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: tasks tasks_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tasks
    ADD CONSTRAINT tasks_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- Name: users users_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: worklogs worklogs_checkin_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.worklogs
    ADD CONSTRAINT worklogs_checkin_session_id_fkey FOREIGN KEY (checkin_session_id) REFERENCES public.checkin_sessions(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: worklogs worklogs_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.worklogs
    ADD CONSTRAINT worklogs_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: worklogs worklogs_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.worklogs
    ADD CONSTRAINT worklogs_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- Name: worklogs worklogs_task_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.worklogs
    ADD CONSTRAINT worklogs_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id) ON UPDATE CASCADE ON DELETE SET NULL;


--
-- Name: worklogs worklogs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.worklogs
    ADD CONSTRAINT worklogs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- PostgreSQL database dump complete
--


