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

    async def _post(self, target: dict, body: dict, bot_id: int | str | None = None):
        """Gửi một message tới Gapo. ``target`` là đúng MỘT trong:
        {"thread_id": ...} | {"receiver_id": ...} | {"collab_id": ...}
        (docs Bảng 4a: request body chỉ tồn tại 1 trong 3 khóa này).
        """
        if self.dry_run or not self.url or not self.api_key:
            log.warning("Gapo client is not configured. Send to target=%s: %s", target, body)
            return {"ok": True, "dry_run": True}

        resolved_bot_id = self.bot_id or bot_id
        payload = {
            **{k: int(v) if str(v).isdigit() else v for k, v in target.items()},
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
        # Quan sát giao DM: ghi rõ target + body phản hồi (cắt ngắn) ở mức INFO để
        # xác nhận tin có được Gapo tạo (message_id) hay không, không cần bật DEBUG.
        log.info("Gapo send target=%s status=%s resp=%s",
                 target, response.status_code, (response.text or "")[:300])
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

    async def _post_body(self, thread_id: int | str, bot_id: int | str | None, body: dict):
        return await self._post({"thread_id": thread_id}, body, bot_id=bot_id)

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

    async def send_to_user(self, receiver_id: int | str, text: str, is_markdown: bool = True):
        """DM chủ động theo gapo_user_id (receiver_id) — không cần thread_id."""
        return await self._post(
            {"receiver_id": receiver_id},
            {"type": "text", "text": text, "is_markdown_text": is_markdown},
        )

    async def send_text_with_mention(
        self,
        thread_id: int | str,
        text: str,
        mention_user_id: int | str,
        mention_name: str | None,
        is_markdown: bool = True,
    ):
        """Trả lời trong group kèm mention người hỏi để họ nhận thông báo.

        Format mention theo docs 4.1.1: text chứa
        "[@Tên](https://www.gapowork.vn/profile/<id>)" + metadata.mentions.
        Thiếu tên hoặc id không phải số thì rơi về gửi text thường.
        """
        if not mention_name or not str(mention_user_id).isdigit():
            return await self.send_text(thread_id, self.bot_id, text, is_markdown=is_markdown)

        prefix = f"[@{mention_name}](https://www.gapowork.vn/profile/{mention_user_id}) "
        return await self._post_body(
            thread_id,
            self.bot_id,
            {
                "type": "text",
                "text": prefix + text,
                "tmp_text": f"@{mention_name} {text}",
                "metadata": {"mentions": [{"target": int(mention_user_id), "length": 0, "offset": 0}]},
                "is_markdown_text": is_markdown,
            },
        )

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
                        for item in actions[:10]  # Gapo render tốt ~vài nút; backstop 10
                    ],
                },
            },
        )
