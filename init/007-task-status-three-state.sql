-- Ensure task status uses the product four-state workflow.

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

        ALTER TYPE public."TaskStatus" RENAME TO "TaskStatus_legacy";
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
        DROP TYPE public."TaskStatus_legacy";
    END IF;
END $$;

TRUNCATE TABLE public.task_status RESTART IDENTITY;
INSERT INTO public.task_status (code, label, color, sort_order) VALUES
    ('todo',        'Todo',        '#94a3b8', 1),
    ('in_progress', 'In Progress', '#3b82f6', 2),
    ('done',        'Done',        '#22c55e', 3),
    ('cancelled',   'Cancelled',   '#ef4444', 4);
