-- ─────────────────────────────────────────────────────────────────────────────
-- Nút bấm nhanh trong tin nhắc deadline: snooze (hoãn nhắc 1 ngày).
-- Idempotent: an toàn chạy lại trên DB đang chạy lẫn deploy mới.
-- ─────────────────────────────────────────────────────────────────────────────

-- snooze_reminder_until: nếu >= hôm nay thì BỎ QUA task này khi nhắc deadline
-- (user bấm "😴 Hoãn nhắc 1 ngày" -> set = CURRENT_DATE + 1, skip đúng ngày mai).
ALTER TABLE public.tasks
    ADD COLUMN IF NOT EXISTS snooze_reminder_until date;
