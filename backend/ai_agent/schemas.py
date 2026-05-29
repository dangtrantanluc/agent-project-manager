from __future__ import annotations
from enum import Enum
from pydantic import BaseModel
from typing import Optional, Any
from datetime import date


class IntentType(str, Enum):
    SQL_QUERY = "SQL_QUERY"
    LOG_WORK = "LOG_WORK"
    GENERATE_REPORT = "GENERATE_REPORT"
    GREETING = "GREETING"
    SMALL_TALK = "SMALL_TALK"
    UNKNOWN = "UNKNOWN"
    # Fast-path PM intents (deterministic SQL, no LLM)
    PROJECT_LIST = "PROJECT_LIST"
    PROJECT_OWNER = "PROJECT_OWNER"
    PROJECT_TASKS = "PROJECT_TASKS"
    PROJECT_PROGRESS = "PROJECT_PROGRESS"


class GapoMessageContent(BaseModel):
    text: str = ""
    id: Optional[str] = None


class GapoSender(BaseModel):
    id: str  # gapo_user_id dạng string


class GapoWebhookPayload(BaseModel):
    type: str
    sender: GapoSender
    conversation_id: str
    thread_id: Optional[str] = None
    message: GapoMessageContent
    timestamp: Optional[int] = None


class AgentContext(BaseModel):
    user_id: int
    company_id: int
    gapo_user_id: str
    conversation_id: str
    memory_summary: str = ""
    recent_turns: list[dict] = []
    conversation_state: Optional[Any] = None   # ConversationState at runtime
    resolved_entities: Optional[Any] = None    # ResolvedEntities at runtime


class IntentResult(BaseModel):
    intent: IntentType
    entities: dict[str, Any] = {}


class DevChatRequest(BaseModel):
    message: str
    user_id: int = 1
    company_id: Optional[int] = None
    conversation_id: str = "dev-session"


class WorklogEntities(BaseModel):
    hours: float
    project_name: Optional[str] = None
    task_name: Optional[str] = None
    work_date: date
    description: Optional[str] = None


class SubQuery(BaseModel):
    """A single decomposed intent from a (potentially compound) user message."""
    type: str                       # "project_list"|"project_progress"|"project_owner"|
                                    # "project_tasks"|"sql_query"|"log_work"|
                                    # "generate_report"|"small_talk"|"unknown"
    raw_text: str = ""              # the sub-message text for this sub-query
    entities: dict = {}             # extracted entities: {"project_name": "ABC", ...}
    needs_context: bool = False     # True if sub-query uses a pronoun reference (đó/này/nó)
    reference: Optional[str] = None # "that_project"|"those_projects"|"that_task"|None
    confidence: float = 1.0         # 0.0–1.0; below threshold → fallback to Text2SQL


class QueryPlan(BaseModel):
    """Parsed representation of a user message, possibly decomposed into sub-queries."""
    is_compound: bool = False
    sub_queries: list[SubQuery] = []
