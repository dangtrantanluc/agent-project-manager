import httpx
import logging
import os

log = logging.getLogger(__name__)

class GapoClient:
    def __init__(self):
        self.url = os.getenv("GAPO_API_URL") or os.getenv("GAPO_URL", "")
        self.api_key = os.getenv("GAPO_BOT_TOKEN") or os.getenv("GAPO_API_KEY", "")
        self.bot_id = os.getenv("GAPO_BOT_ID") or os.getenv("BOT_ID", "")
        self.dry_run = os.getenv("GAPO_DRY_RUN", "false").lower() in {"1", "true", "yes", "on"}
    
    async def _post_body(self, thread_id: int | str, bot_id: int | str | None, body: dict):
        if self.dry_run or not self.url or not self.api_key:
            log.warning("Gapo client is not configured. Reply to thread_id=%s: %s", thread_id, body)
            return {"ok": True, "dry_run": True}

        resolved_bot_id = self.bot_id or bot_id
        payload = {
            "thread_id": int(thread_id) if str(thread_id).isdigit() else thread_id,
            "bot_id": int(resolved_bot_id) if str(resolved_bot_id).isdigit() else resolved_bot_id,
            "body": body,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self.url,
                headers={
                    "x-gapo-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        log.debug("Gapo API response: %s - %s", response.status_code, response.text)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            log.error(
                "Gapo API rejected message status=%s response=%s payload=%s",
                response.status_code,
                response.text,
                payload,
            )
            raise

        if response.text:
            return response.json()

        return {"ok": True}

    async def send_text(self, thread_id: int | str, bot_id: int | str | None, text: str, is_markdown: bool = True):
        return await self._post_body(
            thread_id,
            bot_id,
            {
                "type": "text",
                "text": text,
                "is_markdown_text": is_markdown,
            },
        )

    async def send_message(self, thread_id: int | str, text: str, is_markdown: bool = True):
        return await self.send_text(thread_id=thread_id, bot_id=self.bot_id, text=text, is_markdown=is_markdown)

    async def send_menu(self, thread_id: int | str, title: str, actions: list[dict]):
        return await self._post_body(
            thread_id,
            self.bot_id,
            {
                "type": "quick_replies",
                "text": title,
                "metadata": {
                    "options": [
                        {"title": item["label"], "payload": item["payload"]}
                        for item in actions[:15]
                    ],
                },
            },
        )
