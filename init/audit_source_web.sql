-- Thêm nguồn 'web' cho AgentAuditSource — để audit đổi status từ UI (transition_task)
-- hiện đúng nguồn trong Lịch sử task (TaskActivityTimeline). Idempotent (PG12+).
ALTER TYPE public."AgentAuditSource" ADD VALUE IF NOT EXISTS 'web';
