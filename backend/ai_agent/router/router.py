import asyncio
import json
import logging
import os
import re
import time
from typing import List

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()
logger = logging.getLogger(__name__)

# Tên agent hợp lệ — dùng để validate output của LLM, tránh agent "ảo".
VALID_AGENTS = {
    "report",
    "text2sql",
    "planning",
    "conversation",
    "notification",
    "task_update",
    "create_task",
    "add_member",
}
DEFAULT_AGENT = "conversation"


class PMMultiAgentRouter:
    def __init__(self):
        """Khởi tạo bộ định tuyến đa tác nhân cho các câu hỏi quản lý dự án.

        Router dùng model nhẹ để phân loại intent (fail-fast). Credentials/model
        đọc từ env chung (như các agent khác) — KHÔNG hardcode.
        """
        self.llm = ChatOpenAI(
            timeout=10,
            max_retries=1,
            model=os.getenv("MODEL_NAME_ROUTER") or os.getenv("MODEL_NAME"),
            api_key=os.getenv("API_KEY_ROUTER") or os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL_ROUTER") or os.getenv("BASE_URL"),
            # Phân loại intent là tác vụ đơn giản, không cần thinking.
            reasoning_effort="none",
        )
        logger.info("PMMultiAgentRouter initialized with LLM: %s", self.llm.model_name)

    def _parse_agent_list(self, raw_output: str) -> List[str]:
        """Parse output LLM thành list tên agent đã validate & khử trùng lặp.

        Chấp nhận cả khi LLM bọc trong ```json fence hoặc kèm văn bản thừa.
        Mọi tên không thuộc VALID_AGENTS đều bị loại bỏ.
        """
        cleaned = re.sub(r"```(?:json)?", "", raw_output).replace("```", "").strip()

        names: List[str] = []
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, list):
                    names = [str(x).strip().lower() for x in parsed]
            except json.JSONDecodeError:
                logger.warning("Không parse được JSON array, fallback quét tên: %r", raw_output)

        # Fallback: output bị cắt cụt / sai định dạng → quét tên agent trong text thô.
        if not names:
            lowered = cleaned.lower()
            names = [name for name in VALID_AGENTS if name in lowered]

        # Giữ thứ tự xuất hiện, khử trùng lặp, chỉ giữ tên hợp lệ.
        seen = set()
        result: List[str] = []
        for name in names:
            if name in VALID_AGENTS and name not in seen:
                seen.add(name)
                result.append(name)

        if not result:
            logger.error("Không trích xuất được agent nào — raw_output: %r", raw_output)
        return result

    async def _classify(self, question: str) -> List[str]:
        """Gọi LLM phân loại ý định, trả về list tên agent."""
        # LƯU Ý: ví dụ JSON trong prompt dùng dấu ngoặc vuông [] nên an toàn với
        # f-string. TUYỆT ĐỐI KHÔNG đặt ví dụ chứa {} trong f-string của prompt
        # (gây lỗi runtime "Invalid format specifier").
        prompt = f"""Bạn là bộ phân loại ý định. Hãy phân loại câu hỏi của người dùng vào MỘT hoặc NHIỀU danh mục dưới đây.

Danh mục:
- report: báo cáo dự án, tiến độ, thống kê tổng hợp.
- text2sql: lấy dữ liệu cụ thể từ cơ sở dữ liệu (đếm, liệt kê, tra cứu task/dự án/người).
- planning: lập kế hoạch dự án, phân chia công việc, milestone, quản lý thời gian.
- conversation: chào hỏi, giao tiếp, cảm xúc, câu hỏi chung chung không thuộc nhóm trên.
- notification: tạo nội dung thông báo, nhắc nhở, reminder.
- task_update: người dùng KHẲNG ĐỊNH đã làm xong / đã cập nhật một task đã nhắc trước đó (vd: "tôi update rồi", "xong rồi", "done", "đã hoàn thành", "task X xong 80%").
- create_task: người dùng GIAO VIỆC / tạo task MỚI cho người khác (vd: "giao task X cho Thảo deadline mai", "tạo task ... cho Nam"). Khác task_update (báo task cũ) và notification (chỉ nhắc, không tạo).
- add_member: người dùng THÊM THÀNH VIÊN vào DỰ ÁN (vd: "thêm Thảo vào dự án Logistics", "add Nam vào project CRM vai trò dev"). KHÁC create_task: add_member gắn người vào DỰ ÁN (không tạo task); create_task tạo CÔNG VIỆC giao cho người.

Quy tắc:
- CHỈ trả về một JSON array các tên danh mục, KHÔNG giải thích, KHÔNG markdown.
- Nếu câu hỏi vừa cần lấy dữ liệu vừa cần báo cáo, trả về nhiều danh mục.
- Nếu không chắc, trả về ["conversation"].

Câu hỏi: {question}

Trả về (ví dụ: ["text2sql"] hoặc ["report", "planning"]):"""

        raw = await self.llm.ainvoke(prompt)
        return self._parse_agent_list(raw.content)

    async def selected_agents(self, question: str) -> List[str]:
        """Phân loại và trả về list tên agent. Luôn trả ít nhất 1 phần tử.

        Args:
            question: Câu hỏi đầu vào từ người dùng.
        Returns:
            List[str]: Danh sách tên agent được chọn (theo thứ tự ưu tiên của LLM).
        """
        t = time.perf_counter()
        try:
            agents = await self._classify(question)
        except Exception as e:
            # Fail-fast: LLM lỗi/timeout → để tầng trên fallback bằng từ khoá.
            logger.error("Phân loại ý định thất bại: %s", e)
            agents = []
        logger.info(
            "Phân loại agents=%s elapsed_ms=%.0f",
            agents, (time.perf_counter() - t) * 1000,
        )
        return agents or [DEFAULT_AGENT]


async def main():
    router = PMMultiAgentRouter()
    questions = [
        "Dự án X có bao nhiêu task đã hoàn thành và tiến độ tổng thể là gì?",
        "Hôm nay tôi muốn biết dự án X đang ở giai đoạn nào và có những rủi ro gì?",
        "Hello b",
        "Tôi muốn lập kế hoạch cho dự án Y, bạn có thể giúp tôi không?",
        "Tôi muốn tạo một thông báo nhắc nhở cho task ABC.",
        "Tôi update task ABC rồi nhé",
    ]
    for q in questions:
        print(f"\nQuestion: {q}")
        print(f"Selected agents: {await router.selected_agents(q)}")


if __name__ == "__main__":
    asyncio.run(main())
