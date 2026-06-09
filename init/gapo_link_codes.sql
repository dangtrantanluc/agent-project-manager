-- ─────────────────────────────────────────────────────────────────────────────
-- Gapo self-service linking codes
--
-- Short-lived, single-use codes that let a new employee link their own Gapo
-- account to an internal user without an admin running manual SQL. An admin
-- generates a code for a user; the employee messages the bot "/link <code>";
-- the webhook then knows the real gapo_user_id + gapo_thread_id and writes the
-- permanent row into gapo_user_maps.
--
-- This table holds only the transient code (the "ticket"), never the mapping
-- itself — gapo_user_maps stays the source of truth for completed links.
--
-- Idempotent migration: safe to run on an existing database without resetting.
-- Mirrors the definition added to init.sql so fresh deploys and existing
-- databases stay in sync.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.gapo_link_codes (
    id                   serial PRIMARY KEY,
    code                 text NOT NULL UNIQUE,
    user_id              integer NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    expires_at           timestamp(3) without time zone NOT NULL,
    used_at              timestamp(3) without time zone,
    used_by_gapo_user_id bigint,
    created_by           integer REFERENCES public.users(id) ON DELETE SET NULL,
    created_at           timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Lookup all codes for a user (admin UI).
CREATE INDEX IF NOT EXISTS gapo_link_codes_user_id_idx
    ON public.gapo_link_codes (user_id);

-- At most one *active* (unused) code per user. Used codes are kept for audit.
CREATE UNIQUE INDEX IF NOT EXISTS gapo_link_codes_active_uq
    ON public.gapo_link_codes (user_id) WHERE used_at IS NULL;
