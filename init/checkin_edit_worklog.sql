-- Cho phép sửa worklog vừa lưu trong luồng check-in.
-- Thêm state AWAITING_EDIT: user đã bấm "Sửa", đang chờ nhập lại nội dung worklog.
-- Idempotent (PG12+). Mirror vào init.sql cho deploy mới.
ALTER TYPE public."CheckinState" ADD VALUE IF NOT EXISTS 'AWAITING_EDIT';
