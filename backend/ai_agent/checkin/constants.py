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
P_DONE      = "checkin:done"

CHECKIN_PREFIX = "checkin:"

SLOT_EXPIRE_TIME = {
    CheckinSlot.LUNCH:   "14:00",
    CheckinSlot.END_DAY: "21:00",
}
MANUAL_EXPIRE_DELTA = timedelta(hours=2)

ADVISORY_LOCK_KEY = 20260523

REMINDER_COOLDOWN_MINUTES = 20
MAX_REMINDERS_PER_SLOT = 2
