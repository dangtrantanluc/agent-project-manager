import os
import asyncio
import time
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from datetime import datetime
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv()

DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"

# Số lần thử lại tối đa khi LLM lỗi/timeout trước khi trả câu xin lỗi.
DEFAULT_MAX_RETRIES = 3

def _tone_context(timezone_name: str | None = None) -> str:
    try:
        now = datetime.now(ZoneInfo(timezone_name or DEFAULT_TIMEZONE))
    except ZoneInfoNotFoundError:
        now = datetime.now(ZoneInfo(DEFAULT_TIMEZONE))
    hour = now.hour
    if 5 <= hour < 12:
        return "Hiện đang buổi sáng."
    if 12 <= hour < 18:
        return "Hiện đang buổi chiều."
    return "Hiện đang buổi tối."


def _now_in_timezone(timezone_name: str | None = None) -> datetime:
    try:
        return datetime.now(ZoneInfo(timezone_name or DEFAULT_TIMEZONE))
    except ZoneInfoNotFoundError:
        return datetime.now(ZoneInfo(DEFAULT_TIMEZONE))

class ConversationAgent:
    def __init__(self, llm: ChatOpenAI | None = None):
        """Khởi tạo agent xử lý giao tiếp và lời chào."""
        load_dotenv()

        self.llm = ChatOpenAI(
            model=os.getenv("MODEL_NAME"),
            temperature=0.7,
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL"),
        ) if llm is None else llm
        # Đặt các tham số
        self.max_retries = DEFAULT_MAX_RETRIES
        # Tạo prompt cho cuộc trò chuyện
        self.conversation_prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                """Bạn là PM-Bot, trợ lý quản lý dự án của team.

Phong cách:
- Gọi user bằng tên nếu biết (ví dụ "anh Luc", "chị Mai") — dùng tên cuối trong tiếng Việt
- Thân thiện, ngắn gọn, đúng trọng tâm — không dài dòng
- Khi trả lời số liệu: nhận xét ngắn thay vì chỉ liệt kê (ví dụ "tiến độ tốt" hay "đang chậm")
- Nếu trong context có task quá hạn hoặc deadline gần, chủ động đề cập cuối câu
- Không dùng bullet list cho câu trả lời ngắn — viết tự nhiên như người thật
- Luôn dùng tiếng Việt

{tone_context}

Thông tin người dùng:
{user_context}"""
            ),
            (
                "human",
                "{input}"
            )
        ])
        # Sử dụng RunnableSequence thay vì LLMChain
        self.chain = self.conversation_prompt | self.llm
        
        # Danh sách lời chào và câu hỏi thông thường
        self.greetings = [
            "xin chào", "chào", "hello", "hi", "hey", "alo", "chào bạn", 
            "chào buổi sáng", "chào buổi chiều", "chào buổi tối"
        ]
        
        self.common_questions = [
            "bạn là ai", "bạn có thể làm gì", "giúp tôi", "trợ giúp", 
            "hướng dẫn", "khả năng", "chức năng"
        ]

    def is_greeting(self, message):
        """Kiểm tra xem tin nhắn có phải là lời chào không."""
        message = message.lower()
        return any(greeting in message for greeting in self.greetings)
    
    def is_help_request(self, message):
        """Kiểm tra xem tin nhắn có phải là yêu cầu trợ giúp không."""
        message = message.lower()
        return any(question in message for question in self.common_questions)
    
    def _greeting_word(self, timezone_name: str | None = None) -> str:
        hour = _now_in_timezone(timezone_name).hour
        if 5 <= hour < 12:
            return "Chào buổi sáng"
        if 12 <= hour < 18:
            return "Chào buổi chiều"
        return "Chào buổi tối"

    def _first_name(self, full_name: str) -> str:
        parts = full_name.strip().split()
        return parts[-1] if parts else ""

    def get_standard_response(self, message, user_profile: dict | None = None, timezone_name: str | None = None):
        lowered = message.lower()

        if self.is_greeting(lowered):
            profile = user_profile or {}
            name = self._first_name(profile.get("full_name", ""))
            greeting = self._greeting_word(timezone_name)
            name_part = f" {name}" if name else ""

            overdue = profile.get("overdue_count", 0)
            nearest_task = profile.get("nearest_task")
            nearest_deadline = profile.get("nearest_deadline")

            if overdue > 0:
                hint = f" Hiện có {overdue} task quá hạn đang chờ."
            elif nearest_task and nearest_deadline:
                hint = f" Deadline gần nhất: '{nearest_task}' ({nearest_deadline})."
            else:
                hint = ""

            return {
                "type": "greeting",
                "message": f"{greeting}{name_part}!{hint} Mình có thể giúp gì không?",
            }

        if self.is_help_request(lowered):
            return {
                "type": "help",
                "message": (
                    "Mình có thể giúp bạn:\n"
                    "• Tra cứu thông tin dự án, task, milestone, worklog\n"
                    "• Tạo báo cáo tiến độ\n"
                    "• Lập kế hoạch và phân chia công việc\n"
                    "• Trả lời câu hỏi bằng ngôn ngữ tự nhiên (không cần biết SQL)"
                ),
            }

        return None

    async def process_message_async(self, message, user_context=None, user_profile=None, timezone_name: str | None = None):
        standard_response = self.get_standard_response(message, user_profile=user_profile, timezone_name=timezone_name)
        if standard_response:
            return standard_response

        retries = 0
        while retries < self.max_retries:
            try:
                response = await self.chain.ainvoke({
                    "input": message,
                    "user_context": user_context or "Không có thông tin ngữ cảnh.",
                    "tone_context": _tone_context(timezone_name),
                })
                return {"type": "conversation", "message": response.content.strip()}
            except Exception as e:
                retries += 1
                if retries == self.max_retries:
                    return {
                        "type": "error",
                        "message": "Xin lỗi, tôi đang gặp vấn đề kỹ thuật. Vui lòng thử lại sau."
                    }
                await asyncio.sleep(1)

    def process_message(self, message, user_context=None, timezone_name: str | None = None):
        """
        Xử lý tin nhắn của người dùng và trả về phản hồi.
        
        Args:
            message (str): Tin nhắn của người dùng
            user_context (str, optional): Thông tin ngữ cảnh của người dùng
        Returns:
            Dict chứa loại và nội dung phản hồi
        """
        # Kiểm tra các trường hợp chuẩn trước
        standard_response = self.get_standard_response(message, timezone_name=timezone_name)
        if standard_response:
            return standard_response
        
        # Xử lý với LLM nếu không phải trường hợp chuẩn
        retries = 0
        while retries < self.max_retries:
            try:
                user_context_str = user_context if user_context else "Không có thông tin ngữ cảnh."
                
                # Sử dụng invoke thay vì run
                response = self.chain.invoke({"input": message, "user_context": user_context_str})
                
                return {
                    "type": "conversation",
                    "message": response.content.strip()
                }
            
            except Exception as e:
                retries += 1
                print(f"Lỗi (thử lại {retries}/{self.max_retries}): {str(e)}")
                if retries == self.max_retries:
                    return {
                        "type": "error",
                        "message": "Xin lỗi, tôi đang gặp vấn đề kỹ thuật. Vui lòng thử lại sau."
                    }
                time.sleep(1)

# Ví dụ sử dụng
if __name__ == "__main__":
    agent = ConversationAgent()
    
    # Danh sách các ví dụ để kiểm tra
    test_messages = [
        "mày biết bố m là ai không?"
    ]
    
    for message in test_messages:
        print(f"\nNgười dùng: {message}")
        start_time = time.perf_counter()
        response = agent.process_message(message)
        elapsed_time = time.perf_counter() - start_time
        print(f"Phản hồi nhận được sau {elapsed_time:.2f} giây:")
        print(f"Trợ lý ({response['type']}): {response['message']}")
