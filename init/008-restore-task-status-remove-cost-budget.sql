-- Restore four-state task workflow and remove cost/budget fields.

DO $$
DECLARE
    labels text[];
BEGIN
    SELECT array_agg(e.enumlabel ORDER BY e.enumsortorder)
    INTO labels
    FROM pg_type t
    JOIN pg_enum e ON e.enumtypid = t.oid
    WHERE t.typname = 'TaskStatus';

    IF labels IS DISTINCT FROM ARRAY['TODO', 'IN_PROGRESS', 'DONE', 'CANCELLED'] THEN
        ALTER TABLE public.tasks ALTER COLUMN status DROP DEFAULT;

        ALTER TYPE public."TaskStatus" RENAME TO "TaskStatus_previous";
        CREATE TYPE public."TaskStatus" AS ENUM ('TODO', 'IN_PROGRESS', 'DONE', 'CANCELLED');

        ALTER TABLE public.tasks
            ALTER COLUMN status TYPE public."TaskStatus"
            USING (
                CASE status::text
                    WHEN 'PLANNED' THEN 'TODO'
                    WHEN 'IN_REVIEW' THEN 'DONE'
                    ELSE status::text
                END
            )::public."TaskStatus";

        ALTER TABLE public.tasks ALTER COLUMN status SET DEFAULT 'TODO';
        DROP TYPE public."TaskStatus_previous";
    END IF;
END $$;

TRUNCATE TABLE public.task_status RESTART IDENTITY;
INSERT INTO public.task_status (code, label, color, sort_order) VALUES
    ('todo',        'Todo',        '#94a3b8', 1),
    ('in_progress', 'In Progress', '#3b82f6', 2),
    ('done',        'Done',        '#22c55e', 3),
    ('cancelled',   'Cancelled',   '#ef4444', 4);

ALTER TABLE public.projects
    DROP COLUMN IF EXISTS budget,
    DROP COLUMN IF EXISTS estimated_total_cost,
    DROP COLUMN IF EXISTS total_cost,
    DROP COLUMN IF EXISTS budget_remaining;

ALTER TABLE public.tasks
    DROP COLUMN IF EXISTS total_cost;

ALTER TABLE public.scopes
    DROP COLUMN IF EXISTS estimated_rate,
    DROP COLUMN IF EXISTS estimated_cost;

ALTER TABLE public.backlogs
    DROP COLUMN IF EXISTS cost_per_hour_snapshot,
    DROP COLUMN IF EXISTS total_cost_snapshot;

DROP TABLE IF EXISTS public.member_rates;
