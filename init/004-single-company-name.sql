-- Align the live database with the single-company model.
-- The application stores only a plain company name on users.

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS company_name text NOT NULL DEFAULT 'BBSW Software';

DO $$
BEGIN
    IF to_regclass('public.companies') IS NOT NULL
       AND EXISTS (
           SELECT 1
           FROM information_schema.columns
           WHERE table_schema = 'public'
             AND table_name = 'users'
             AND column_name = 'company_id'
       )
    THEN
        UPDATE public.users u
        SET company_name = COALESCE(c.name, u.company_name, 'BBSW Software')
        FROM public.companies c
        WHERE u.company_id = c.id;
    END IF;
END $$;

ALTER TABLE public.users
    DROP CONSTRAINT IF EXISTS users_company_id_fkey,
    DROP COLUMN IF EXISTS company_id;

DROP INDEX IF EXISTS public.users_company_id_idx;

DROP INDEX IF EXISTS public.agent_memory_company_id_created_at_idx;

ALTER TABLE public.agent_memory
    DROP COLUMN IF EXISTS company_id;

CREATE INDEX IF NOT EXISTS agent_memory_created_at_idx
    ON public.agent_memory USING btree (created_at);

DROP TABLE IF EXISTS public.companies;
