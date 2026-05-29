import datetime
import logging

from enum import Enum

logger = logging.getLogger(__name__)

class NotificationTrigger(str, Enum):
    CRON_JOB = "cron_job"
    MANUAL = "manual"

class NotificationAction(str, Enum):
    SEND_DEADLINE_REMINDER = "send_deadline_reminder"
    SEND_PROGRESS_PUSH = "send_progress_push"

class NotificationTool:
    def __init__(self, notification_agent, gapo_client):
        self.notification_agent = notification_agent
        self.gapo_client = gapo_client

    async def execute(
        self,
        *,
        trigger: NotificationTrigger,
        action: NotificationAction,
        target_user_id: str,
        target_thread_id: str,
        tasks: list[dict],
        raw_message: str | None = None,
        actor_user_id: str | None = None,
    ):
        if trigger == NotificationTrigger.CRON_JOB:
            message = await self.notification_agent.prepare_deadline_digest(
                recipient_name=None,
                notify_date=datetime.date.today(),
                tasks=tasks,
            )
            logger.info("Deadline digest prepared for user %s", target_user_id)

        elif trigger == NotificationTrigger.MANUAL:
            message = await self.notification_agent.prepare_notification(
                user_id=target_user_id,
                thread_id=target_thread_id,
                message=raw_message or "Nhắc cập nhật tiến độ task.",
            )
            message = message.message
            logger.info("Manual notification prepared for user %s", target_user_id)

        else:
            raise ValueError("Unknown notification trigger")

        send_result = await self.gapo_client.send_message(
            thread_id=target_thread_id,
            text=message,
        )

        return {
            "trigger": trigger,
            "action": action,
            "target_user_id": target_user_id,
            "actor_user_id": actor_user_id,
            "message": message,
            "send_result": send_result,
        }