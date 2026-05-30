import os
import asyncio
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableSequence
import time
from datetime import datetime
from dotenv import load_dotenv
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv()

DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"

def _now_in_timezone(timezone_name: str | None = None) -> datetime:
    try:
        return datetime.now(ZoneInfo(timezone_name or DEFAULT_TIMEZONE))
    except ZoneInfoNotFoundError:
        return datetime.now(ZoneInfo(DEFAULT_TIMEZONE))

class ConversationAgent:
    def __init__(self, llm: ChatAnthropic | None = None):
        """Khởi tạo agent xử lý giao tiếp và lời chào."""
        load_dotenv()
        
        # Khởi tạo LLM
        self.llm = ChatAnthropic(
            model=os.getenv("MODEL_NAME"),
            api_key=os.getenv("API_KEY"),
            base_url=os.getenv("BASE_URL"),
        ) if llm is None else llm
        # Đặt các tham số
        self.max_retries = 3
        # Tạo prompt cho cuộc trò chuyện
        self.conversation_prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                """
        Bạn là trợ lý thông tin dự án, task, milestone, worklog.

        Hãy phản hồi:
        - lịch sự
        - chuyên nghiệp
        - đúng trọng tâm
        - bằng tiếng Việt

        Thông tin người dùng:
        {user_context}
        """
            ),

            (
                "human",
                """
        Tin nhắn người dùng:
        {input}
        """
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
    
    def get_standard_response(self, message, timezone_name: str | None = None):
        """Trả về phản hồi chuẩn cho các trường hợp thông thường."""
        message = message.lower()
        
        if self.is_greeting(message):
            current_hour = _now_in_timezone(timezone_name).hour
            
            if 5 <= current_hour < 12:
                greeting = "Chào buổi sáng"
            elif 12 <= current_hour < 18:
                greeting = "Chào buổi chiều"
            else:
                greeting = "Chào buổi tối"
                
            return {
                "type": "greeting",
                "message": f"{greeting}! Tôi là trợ lý thông tin dự án. Tôi có thể giúp gì cho bạn về thông tin dự án, task, milestone, hoặc worklog?"
            }
        
        elif self.is_help_request(message):
            return {
                "type": "help",
                "message": """Tôi có thể giúp bạn:
                1. Tìm kiếm thông tin dự án và task
                2. Tra cứu milestone và worklog
                3. Truy vấn cơ sở dữ liệu về thông tin dự án và lịch sử công việc
                4. Trả lời các câu hỏi chung về quản lý dự án và công việc

                Bạn có thể hỏi những câu như:
                - "Hiện tại có bao nhiêu dự án?"
                - "Cho tôi thông tin về task X!"
                - "Thông tin về project Y?"
                """
            }
        
        return None

    async def process_message_async(self, message, user_context=None, timezone_name: str | None = None):
        """
        Xử lý tin nhắn của người dùng và trả về phản hồi bằng cách bất đồng bộ.
        
        Args:
            message (str): Tin nhắn của người dùng
            user_context (str, optional): Thông tin ngữ cảnh của người dùng
        Returns:
            Dict chứa loại và nội dung phản hồi
        """
        # Hàm chạy các tác vụ chặn trong thread riêng
        async def run_in_executor(func, *args, **kwargs):
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
        
        # Kiểm tra các trường hợp chuẩn trước
        standard_response = await run_in_executor(self.get_standard_response, message, timezone_name)
        if standard_response:
            return standard_response
        
        # Xử lý với LLM nếu không phải trường hợp chuẩn
        retries = 0
        while retries < self.max_retries:
            try:
                user_context_str = user_context if user_context else "Không có thông tin ngữ cảnh."
                
                # Sử dụng invoke trong thread riêng để không chặn event loop
                response = await run_in_executor(
                    self.chain.invoke,
                    {"input": message, "user_context": user_context_str}
                )
                
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
        standard_response = self.get_standard_response(message, timezone_name)
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
