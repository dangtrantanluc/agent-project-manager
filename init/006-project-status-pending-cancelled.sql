-- Expand project status to the product workflow:
-- PLANNED, PENDING, IN_PROGRESS, DONE, CANCELLED.
-- This migration is intentionally non-destructive for live databases that may
-- still contain legacy ON_HOLD / COMPLETED values.

DO $$
BEGIN
    ALTER TYPE public."ProjectStatus" ADD VALUE IF NOT EXISTS 'PENDING';
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    ALTER TYPE public."ProjectStatus" ADD VALUE IF NOT EXISTS 'DONE';
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    ALTER TYPE public."ProjectStatus" ADD VALUE IF NOT EXISTS 'CANCELLED';
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

UPDATE public.projects
SET status = 'DONE'::public."ProjectStatus"
WHERE status::text = 'COMPLETED';

UPDATE public.projects
SET status = 'PENDING'::public."ProjectStatus"
WHERE status::text = 'ON_HOLD';
