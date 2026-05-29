import re
from ai_agent.context.models import ConversationState, ResolvedEntities

# Project reference: "dự án đó/này", "project đó/này", "bên đó"
_PROJECT_REF = re.compile(
    r"\b(dự\s*án|du\s*an|project)\s*(đó|do|này|nay)\b"
    r"|\b(bên\s*(đó|do))\b",
    re.IGNORECASE,
)

# Task reference: "task đó/này", "công việc đó/này"
_TASK_REF = re.compile(
    r"\b(task|công\s*việc|cong\s*viec|việc|viec)\s*(đó|do|này|nay)\b",
    re.IGNORECASE,
)

# Ambiguous "nó" pronoun — standalone, not part of a larger word
_AMBIGUOUS = re.compile(r"(?<!\w)(nó|no)\b", re.IGNORECASE)

# Semantic cues that indicate the referent is a PROJECT
_PROJECT_CUES = re.compile(
    r"\b(bao\s*nhiêu\s*task|team\s*mấy\s*người|tiến\s*độ|"
    r"member|owner|phụ\s*trách|tổng\s*task|thành\s*viên|tổng\s*giờ)\b",
    re.IGNORECASE,
)

# Semantic cues that indicate the referent is a TASK
_TASK_CUES = re.compile(
    r"\b(xong\s*chưa|done\s*chưa|overdue|trễ\s*chưa|ai\s*làm|"
    r"estimate|giao\s*cho|assigned|assignee|deadline\s*khi\s*nào)\b",
    re.IGNORECASE,
)

_PROJECT_QUERY_TYPES = frozenset({
    "project_list", "project_progress", "project_detail", "project_owner", "PROJECT_LIST",
    "PROJECT_PROGRESS", "PROJECT_OWNER",
})
_TASK_QUERY_TYPES = frozenset({
    "list_tasks", "task_detail", "project_tasks", "PROJECT_TASKS",
})


def resolve_references(message: str, state: ConversationState) -> ResolvedEntities:
    """
    Detect pronoun references in message and resolve to entity IDs from state.
    Pure sync — no DB, no LLM.
    """
    msg = message.lower()
    has_project_ref = bool(_PROJECT_REF.search(msg))
    has_task_ref = bool(_TASK_REF.search(msg))
    has_ambiguous = bool(_AMBIGUOUS.search(msg))

    if has_project_ref:
        if state.last_project:
            return ResolvedEntities(
                project_id=state.last_project.id,
                project_name=state.last_project.name,
            )
        # Check last_projects list (from a prior PROJECT_LIST result)
        if state.last_projects:
            p = state.last_projects[0]
            return ResolvedEntities(project_id=p.id, project_name=p.name)
        return ResolvedEntities(needs_clarification=True, clarification_hint="project")

    if has_task_ref:
        if state.last_task:
            return ResolvedEntities(
                task_id=state.last_task.id,
                task_title=state.last_task.title,
            )
        if state.last_tasks:
            t = state.last_tasks[0]
            return ResolvedEntities(task_id=t.id, task_title=t.title)
        return ResolvedEntities(needs_clarification=True, clarification_hint="task")

    if has_ambiguous:
        return _resolve_ambiguous_no(message, state)

    return ResolvedEntities()


def _resolve_ambiguous_no(message: str, state: ConversationState) -> ResolvedEntities:
    """
    Disambiguate standalone 'nó' using semantic cues in the message and
    last_query_type from state. Avoids the fragile task > project priority fallback.
    """
    has_project_cue = bool(_PROJECT_CUES.search(message))
    has_task_cue = bool(_TASK_CUES.search(message))

    # Clear semantic signal in the message
    if has_project_cue and not has_task_cue:
        if state.last_project:
            return ResolvedEntities(project_id=state.last_project.id,
                                    project_name=state.last_project.name)
    elif has_task_cue and not has_project_cue:
        if state.last_task:
            return ResolvedEntities(task_id=state.last_task.id,
                                    task_title=state.last_task.title)

    # Use last_query_type to disambiguate
    lqt = state.last_query_type or state.last_intent or ""
    if lqt in _TASK_QUERY_TYPES:
        if state.last_task:
            return ResolvedEntities(task_id=state.last_task.id,
                                    task_title=state.last_task.title)
        if state.last_tasks:
            t = state.last_tasks[0]
            return ResolvedEntities(task_id=t.id, task_title=t.title)
    elif lqt in _PROJECT_QUERY_TYPES:
        if state.last_project:
            return ResolvedEntities(project_id=state.last_project.id,
                                    project_name=state.last_project.name)
        if state.last_projects:
            p = state.last_projects[0]
            return ResolvedEntities(project_id=p.id, project_name=p.name)

    # Final fallback: prefer project over task (less ambiguous in PM context)
    if state.last_project:
        return ResolvedEntities(project_id=state.last_project.id,
                                project_name=state.last_project.name)
    if state.last_task:
        return ResolvedEntities(task_id=state.last_task.id,
                                task_title=state.last_task.title)

    return ResolvedEntities(needs_clarification=True, clarification_hint="nó")


def build_clarification_message(hint: str) -> str:
    if hint == "project":
        return "Bạn đang nhắc đến dự án nào? Mình chưa có ngữ cảnh về dự án trước đó."
    if hint == "task":
        return "Bạn đang nhắc đến task nào? Mình chưa có ngữ cảnh về task trước đó."
    return "Bạn đang nhắc đến 'đó/nó' là gì? Bạn có thể nói rõ tên dự án hoặc task không?"
