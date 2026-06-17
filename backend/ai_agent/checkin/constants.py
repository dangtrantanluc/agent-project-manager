import re
from datetime import timedelta

# Matches "checkin", "/checkin", "check-in", "/check in" etc.
CHECKIN_TRIGGER = re.compile(r"^/?(checkin|check[\s\-]?in)$", re.IGNORECASE)


class CheckinState:
    IDLE              = "IDLE"
    AWAITING_PROJECT  = "AWAITING_PROJECT"
    AWAITING_TASK     = "AWAITING_TASK"
    AWAITING_UPDATE   = "AWAITING_UPDATE"
    CONFIRMING        = "AWAITING_TASK_CONFIRM"  # post-worklog: waiting for add_more or done
    AWAITING_EDIT     = "AWAITING_EDIT"          # user bấm "Sửa": chờ nhập lại nội dung worklog
    COMPLETED         = "COMPLETED"
    EXPIRED           = "EXPIRED"
    CANCELLED         = "CANCELLED"
    MISSED            = "MISSED"

    TERMINAL = {"COMPLETED", "CANCELLED", "EXPIRED", "MISSED"}


class CheckinSlot:
    LUNCH   = "lunch"
    END_DAY = "end_day"
    MANUAL  = "manual"


P_PROJECT   = "checkin:project:"
P_TASK      = "checkin:task:"
P_SKIP_TASK = "checkin:skip_task"
P_CANCEL    = "checkin:cancel"
P_ADD_MORE  = "checkin:add_more"
P_EDIT      = "checkin:edit"
P_DONE      = "checkin:done"

CHECKIN_PREFIX = "checkin:"

SLOT_EXPIRE_TIME = {
    CheckinSlot.LUNCH:   "14:00",
    CheckinSlot.END_DAY: "21:00",
}
MANUAL_EXPIRE_DELTA = timedelta(hours=2)

ADVISORY_LOCK_KEY = 20260523  # giữ cho tương thích ngược (default)

# Lock key RIÊNG cho từng loại job: tránh job chạy lâu (vd risk_scan) chiếm lock
# chung làm các job khác cùng khung giờ (vd deadline_notifications) bị skip cả ngày.
LOCK_CHECKIN       = 20260524
LOCK_REMINDER      = 20260525
LOCK_MISSING       = 20260526
LOCK_EXPIRE_STALE  = 20260527
LOCK_RISK_SCAN     = 20260528
LOCK_DEADLINE      = 20260529

REMINDER_COOLDOWN_MINUTES = 20
MAX_REMINDERS_PER_SLOT = 2
