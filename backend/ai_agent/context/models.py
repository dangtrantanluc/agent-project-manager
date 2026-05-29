from pydantic import BaseModel
from typing import Optional


class LastProject(BaseModel):
    id: int
    name: str
    code: Optional[str] = None


class LastTask(BaseModel):
    id: int
    title: str
    project_id: int


class LastUser(BaseModel):
    id: int
    name: str


class ConversationState(BaseModel):
    # Single most-recent entity (backward compat)
    last_project: Optional[LastProject] = None
    last_task: Optional[LastTask] = None
    last_user: Optional[LastUser] = None

    # Multi-entity lists (populated by list queries)
    last_projects: list[LastProject] = []
    last_tasks: list[LastTask] = []

    # Query context for disambiguation
    last_filters: dict = {}
    last_date_range: Optional[str] = None
    last_query_type: Optional[str] = None       # "project_list"|"project_progress"|"list_tasks"|...
    last_result_summary: Optional[str] = None   # brief human-readable summary of last result

    last_intent: Optional[str] = None
    updated_at: Optional[str] = None            # ISO string (UTC)


class ResolvedEntities(BaseModel):
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    task_id: Optional[int] = None
    task_title: Optional[str] = None
    needs_clarification: bool = False
    clarification_hint: str = ""


def merge_state_from_result(state: ConversationState, entities: dict) -> ConversationState:
    """
    Return a new ConversationState updated with entities from a FastPathResult or LLM result.
    Used for in-memory turn_context chaining between sub-queries.
    """
    new = state.model_copy(deep=True)

    if "last_project" in entities and entities["last_project"]:
        new.last_project = LastProject(**entities["last_project"])

    if "last_projects" in entities:
        new.last_projects = [LastProject(**p) for p in entities["last_projects"]]
        # Convenience shortcut: first project becomes last_project if not already set
        if new.last_projects and not entities.get("last_project"):
            new.last_project = new.last_projects[0]

    if "last_task" in entities and entities["last_task"]:
        new.last_task = LastTask(**entities["last_task"])

    if "last_tasks" in entities:
        new.last_tasks = [LastTask(**t) for t in entities["last_tasks"]]

    if "last_query_type" in entities:
        new.last_query_type = entities["last_query_type"]

    if "last_result_summary" in entities:
        new.last_result_summary = entities["last_result_summary"]

    if "last_filters" in entities:
        new.last_filters = entities["last_filters"]

    if "last_date_range" in entities:
        new.last_date_range = entities["last_date_range"]

    return new
