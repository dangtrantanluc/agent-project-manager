-- ─────────────────────────────────────────────────────────────────────────────
-- agent_follow_ups.kind — phân loại follow-up để các luồng không nuốt reply của nhau
--
--   DEADLINE       — nhắc trước hạn (scheduler), reply -> cập nhật tiến độ
--   RESULT_ISSUES  — sau khi task DONE, reply -> ghi tasks.result/issues
--   BLOCKER_REASON — sau khi báo "đang kẹt", reply -> ghi task_blockers.description (+ issues)
--   GENERIC        — mặc định/khác
--
-- Idempotent.
-- ─────────────────────────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE TYPE public."FollowUpKind" AS ENUM ('DEADLINE', 'RESULT_ISSUES', 'BLOCKER_REASON', 'GENERIC');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

ALTER TABLE public.agent_follow_ups
    ADD COLUMN IF NOT EXISTS kind public."FollowUpKind" NOT NULL DEFAULT 'GENERIC';

-- Follow-up cũ (do scheduler nhắc deadline tạo) gắn nhãn DEADLINE cho đúng ngữ nghĩa.
-- Chỉ đụng các bản ghi GENERIC hiện có; an toàn chạy lại.
UPDATE public.agent_follow_ups SET kind = 'DEADLINE' WHERE kind = 'GENERIC';

-- Index phục vụ tra cứu follow-up PENDING theo user+thread+kind (seam B của outcome).
CREATE INDEX IF NOT EXISTS agent_follow_ups_user_thread_kind_idx
    ON public.agent_follow_ups (user_id, thread_id, kind, status);
