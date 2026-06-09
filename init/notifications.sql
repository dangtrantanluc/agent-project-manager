-- ─────────────────────────────────────────────────────────────────────────────
-- In-app notifications
--
-- Idempotent migration: safe to run on an existing database without resetting.
-- Mirrors the table definition added to init.sql so fresh deploys and existing
-- databases stay in sync.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.notifications (
    id          bigserial PRIMARY KEY,
    user_id     integer NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    type        text    NOT NULL DEFAULT 'general',
    title       text    NOT NULL,
    body        text,
    link        text,
    read_at     timestamp(3) without time zone,
    created_at  timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Unread lookups + badge count: hot path, filtered by user and read state.
CREATE INDEX IF NOT EXISTS notifications_user_unread_idx
    ON public.notifications (user_id, read_at);

-- Listing newest-first per user.
CREATE INDEX IF NOT EXISTS notifications_user_created_idx
    ON public.notifications (user_id, created_at DESC);
