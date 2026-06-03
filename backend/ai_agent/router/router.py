import asyncio
import uuid
import json
import re
from datetime import datetime
from typing import Any, Dict, List
from attr import dataclass
from fastapi import APIRouter, BackgroundTasks, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os
import time
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from ai_agent.coversation.conversation import ConversationAgent
from ai_agent.planning.planning_agent import PlanningAgent
from ai_agent.report_generator.report_agent import ReportAgent
from ai_agent.text_to_sql.text2sql import Text2SQLAgent
from ai_agent.notification.notification_agent import NotificationAgent

router = APIRouter(prefix="/api/agent")
load_dotenv()
logger = logging.getLogger(__name__)

@dataclass
class Agent:
    name: str
    description: str
    threshold: float # confidence threshold để quyết định fallback sql_query
    confidence: float = 0.0
    selected: bool = False

class PMMultiAgentRouter:
    def __init__(self):
        """
        Khởi tạo bộ định tuyến đa tác nhân cho các câu hỏi liên quan đến quản lý dự án.
        """
        self.llm = ChatOpenAI(
            model="gemini-2.5-flash",
            timeout=10,
            max_tokens=100,
            max_retries=0,
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL"),
        )
        logger.info("PMMultiAgentRouter initialized with LLM: %s", self.llm.model_name)
        self.agents = [
            Agent(
                name="report",
                description="Chuyên xử lý các câu hỏi liên quan đến báo cáo dự án, tiến độ, và thống kê.",
                threshold=0.6,
            ),
            Agent(
                name="text2sql",
                description="Chuyên chuyển đổi các câu hỏi về dự án, task thành SQL để truy vấn cơ sở dữ liệu",
                threshold=0.2,
            ),
            Agent(
                name="planning",
                description="Chuyên xử lý các câu hỏi liên quan đến lập kế hoạch dự án.",
                threshold=0.7,
            ),
            Agent(
                name="conversation",
                description="xử lý các câu hỏi tương tác giao tiếp và lời chào.",
                threshold=0.2,
            ),
            Agent(
                name="notification",
                description="Chuyên xử lý các câu hỏi liên quan đến tạo nội dung thông báo, nhắc nhở.",
                threshold=0.5,
            )
        ]

    def parse_confidence_json(self, raw_output: str) -> dict[str, float]:
        """
        Phân tích JSON chứa điểm tin cậy từ đầu ra của LLM.
        
        Args:
            raw_output (str): Đầu ra thô từ LLM
        Returns:
            Dict chứa điểm tin cậy cho từng tác nhân
        """
        json_match = re.search(r"\{.*\}", raw_output, re.DOTALL)
        if not json_match:
            try:
                logger.warning(f"Không tìm thấy JSON trong output: {raw_output}")
                return json.loads(raw_output)
            except json.JSONDecodeError as e:
                logger.error(f"JSON không hợp lệ: {e} — raw_output: {raw_output}")
                return {}
        
        # Loại bỏ markdown nếu có và parse JSON
        # clean_output = raw_output.replace('```json', '').replace('```', '').strip()
        try:
            return json.loads(json_match.group(0))
        except:
            logger.warning(f"Không thể phân tích JSON: {raw_output}")
            confidence_dict = {agent.name: 0.0 for agent in self.agents}
            logger.info(f"Trả về điểm tin cậy mặc định: {confidence_dict}")
            
            for agent in self.agents:
                match = re.search(rf'{agent.name}["\']?\s*:\s*(\d+\.?\d*)', raw_output)
                if match:
                    try:
                        confidence_dict[agent.name] = float(match.group(1))
                    except ValueError:
                        logger.warning(f"Không thể chuyển đổi điểm tin cậy thành float cho {agent.name}: {match.group(1)}")
            logger.info(f"Điểm tin cậy sau khi phân tích thủ công: {confidence_dict}")
            return confidence_dict
        
    async def calculate_confidence(self, message: str) -> List[Agent]:
        """Tính toán điểm tin cậy cho từng tác nhân dựa trên câu hỏi đầu vào.
        Args:
            message (str): Câu hỏi đầu vào từ người dùng
        Returns:
            List[Agent]: Danh sách các tác nhân với điểm tin cậy đã được tính toán
        """
        try:
            time_es = time.perf_counter()
            agents = await self._llm_intent_classification(message)
            elapsed = time.perf_counter() - time_es
            logger.info(f"Phân loại ý định mất {elapsed:.3f} giây")
            
            logger.info(f"Điểm tin cậy sau khi phân loại: {[f'{agent.name}: {agent.confidence}' for agent in agents]}")
            return agents
        except Exception as e:
            logger.error(f"Phân loại ý định thất bại: {e}")
            for agent in self.agents:
                agent.confidence = 0.0
                agent.selected = False
            return self.agents
        
    async def _llm_intent_classification(self, question: str) -> List[Agent]:
        """Sử dụng LLM để phân loại ý định của câu hỏi.
        Args:
            question (str): Câu hỏi đầu vào từ người dùng
        Returns:
            List[Agent]: Danh sách các tác nhân với điểm tin cậy đã được tính toán
        """

        prompt=f"""
        Phân loại câu hỏi vào một hoặc nhiều danh mục sau:
        1. report: liên quan đến báo cáo dự án, tiến độ, thống kê.
        2. text2sql: liên quan đến chuyển đổi câu hỏi thành SQL để truy vấn cơ sở dữ liệu.
        3. planning: liên quan đến lập kế hoạch dự án.
        4. conversation: liên quan đến tương tác giao tiếp và lời chào.
        5. notification: liên quan đến tạo nội dung thông báo, nhắc nhở.

        Câu hỏi: {question}
        Hãy xem xét kỹ độ phù hợp câu hỏi với từng danh mục. Đặc biệt lưu ý:
        - Nếu câu hỏi liên quan đến việc lấy dữ liệu cụ thể từ cơ sở dữ liệu, thì sẽ dùng text2sql.
        - Nếu câu hỏi liên quan đến việc tạo báo cáo, hoặc thống kê, thì sẽ thuộc report,
        - Nếu câu hỏi liên quan đến việc lập kế hoạch, phân chia công việc, hoặc quản lý thời gian, ưu tiên planning.
        - Nếu câu hỏi mang tính chất giao tiếp, chào hỏi, cảm xúc, hãy ưu tiên conversation.
        - Nếu câu hỏi liên quan đến việc tạo nội dung thông báo, nhắc nhở, hãy ưu tiên notification.
        Trả về JSON với điểm tin cậy cho mỗi danh mục, tổng bằng 1.0.
        Ví dụ: {{"report": 0.3, "text2sql": 0.2, "planning": 0.4, "conversation": 0.1, "notification": 0.0}}

        """
        raw_output = await self.llm.ainvoke(prompt)
        confidence_dict = self.parse_confidence_json(raw_output.content)

        for agent in self.agents:
            agent.confidence = confidence_dict.get(agent.name, 0.0)
            logger.info(f"Agent '{agent.name}': confidence={agent.confidence}, threshold={agent.threshold}")
            agent.selected = agent.confidence >= agent.threshold
            logger.info(f"Agent '{agent.name}': confidence={agent.confidence}, selected={agent.selected}")
        
        return self.agents

    async def selected_agents(self, question: str) -> List[Agent]:
        """Trả về danh sách các tác nhân được chọn dựa trên điểm tin cậy và ngưỡng đã định.
        Args:
            question (str): Câu hỏi đầu vào từ người dùng
        Returns:
            List[Agent]: Danh sách các tác nhân được chọn
        """
        await self.calculate_confidence(question)
        start = time.perf_counter()
        selected = [agent for agent in self.agents if agent.selected]
        elapsed = time.perf_counter() - start
        logger.info(f"Lựa chọn tác nhân mất {elapsed:.3f} giây")
        logger.info(f"Tác nhân được chọn: {[agent.name for agent in selected]}")
        if selected:
            return selected
        # Mặc định chọn conversation nếu không có tác nhân nào đạt ngưỡng
        fallback = next((a for a in self.agents if a.name == "conversation"), None)
        return [fallback] if fallback is not None else []

    async def detail_agents(self, question: str) -> Dict[str, Any]:
        """Trả về chi tiết điểm tin cậy và trạng thái của tất cả các tác nhân.
        Args:
            question (str): Câu hỏi đầu vào từ người dùng
        Returns:
            Dict[str, Any]: Chi tiết về điểm tin cậy và trạng thái của tất cả các tác nhân
        """
        await self.calculate_confidence(question)

        details = {
            agent.name: {
                "confidence": agent.confidence,
                "threshold": agent.threshold,
                "selected": agent.selected,
                "description": agent.description,
            }
            for agent in self.agents
        }
        logger.info(f"Chi tiết tác nhân: {details}")
        return details
    
    async def timed(name: str, coro):
        start = time.perf_counter()
        try:
            result = await coro
            elapsed = time.perf_counter() - start
            print(f"[TIMER] {name}: {elapsed:.3f}s", flush=True)
            return result
        except Exception as exc:
            elapsed = time.perf_counter() - start
            print(f"[TIMER] {name} FAILED after {elapsed:.3f}s — {exc}", flush=True)
            raise


async def main():
    router = PMMultiAgentRouter()
    questions = ["Dự án X có bao nhiêu task đã hoàn thành và tiến độ tổng thể là gì?",
                "Hôm nay tôi muốn biết dự án X đang ở giai đoạn nào và có những rủi ro gì?",
                "Hello b",
                "Tôi muốn lập kế hoạch cho dự án Y, bạn có thể giúp tôi không?",
                "Tôi muốn tạo một thông báo nhắc nhở cho task ABC."]

    for q in questions:
        print(f"\nQuestion: {q}")
        details = await router.detail_agents(q)
        print(f"Routing result: {details}")
        selected_agents = await router.selected_agents(q)
        print(f"Selected agents: {selected_agents}")

if __name__ == "__main__":
    asyncio.run(main())
