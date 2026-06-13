-- ─────────────────────────────────────────────────────────────────────────────
-- AI-PM agent features (sơ đồ luồng): cập nhật tiến độ %, giao việc vào group,
-- và cảnh báo rủi ro có PM phê duyệt (human-in-the-loop).
--
-- Idempotent migration: an toàn chạy lại trên DB đang chạy lẫn deploy mới.
-- Phản chiếu các thay đổi cần thêm vào init.sql để fresh deploy và DB cũ đồng bộ.
-- ─────────────────────────────────────────────────────────────────────────────

-- (Luồng 3) Tiến độ % của task. status vẫn là enum rời rạc; progress bổ sung
-- mức hoàn thành 0–100 do thành viên báo qua chat ("đã xong 80%").
ALTER TABLE public.tasks
    ADD COLUMN IF NOT EXISTS progress smallint NOT NULL DEFAULT 0;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.constraint_column_usage
        WHERE table_name = 'tasks' AND constraint_name = 'tasks_progress_range'
    ) THEN
        ALTER TABLE public.tasks
            ADD CONSTRAINT tasks_progress_range CHECK (progress BETWEEN 0 AND 100);
    END IF;
END $$;

-- (Luồng 1) Thread group dự án trên GapoWork để bot đăng tin giao việc cho cả nhóm.
ALTER TABLE public.projects
    ADD COLUMN IF NOT EXISTS gapo_thread_id text;

-- (Luồng 4) Cảnh báo rủi ro dự thảo, chờ PM phê duyệt trước khi chốt/broadcast.
-- Dùng text + CHECK thay vì enum mới để migration idempotent dễ dàng.
CREATE TABLE IF NOT EXISTS public.risk_alerts (
    id            serial PRIMARY KEY,
    project_id    integer NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    pm_user_id    integer NOT NULL,            -- người nhận cảnh báo (owner/account_manager)
    risk_score    integer NOT NULL DEFAULT 0,
    risk_level    text    NOT NULL DEFAULT 'MEDIUM',
    reasons       jsonb   NOT NULL DEFAULT '[]'::jsonb,   -- danh sách lý do at-risk (để LLM/template soạn)
    draft_message text    NOT NULL,             -- nội dung cảnh báo + đề xuất dự thảo
    status        text    NOT NULL DEFAULT 'PENDING_PM_CONFIRMATION'
        CHECK (status IN ('PENDING_PM_CONFIRMATION','APPROVED','DISMISSED','EXPIRED')),
    thread_id     text,                         -- thread DM với PM (để map câu trả lời xác nhận)
    correlation_id text,                        -- dedup theo project + ngày
    decided_at    timestamp(3) without time zone,
    decision_note text,
    created_at    timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at    timestamp(3) without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Tra cứu nhanh cảnh báo đang chờ PM này trả lời (state-gate ở message router).
CREATE INDEX IF NOT EXISTS risk_alerts_pm_pending_idx
    ON public.risk_alerts (pm_user_id, thread_id)
    WHERE status = 'PENDING_PM_CONFIRMATION';

-- Dedup: 1 cảnh báo / project / ngày.
CREATE INDEX IF NOT EXISTS risk_alerts_corr_idx
    ON public.risk_alerts (correlation_id);
