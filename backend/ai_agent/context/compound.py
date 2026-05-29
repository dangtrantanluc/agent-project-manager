import re

# Pronouns that indicate a sub-query depends on a prior result
_PRONOUN_REFS = re.compile(
    r'\b(dự\s*án|project|task|công\s*việc)\s*(đó|do|này|nay)\b'
    r'|\bnó\b|\bchúng\b',
    re.IGNORECASE,
)


def decompose_message(message: str) -> list[str]:
    """
    Split a compound message into individual sub-queries.

    Only splits when ALL conditions hold:
    1. Message contains multiple ?-terminated clauses
    2. At least one clause uses a pronoun reference (đó/này/nó/chúng)
       — indicating one part depends on the result of a prior part

    If there are multiple ?-clauses but NO pronoun reference, the whole
    message is passed to Text2SQL as one unit (it handles the join itself).
    """
    parts = [p.strip() for p in re.split(r'\?', message) if p.strip()]
    if len(parts) <= 1:
        return [message]
    if not _PRONOUN_REFS.search(message):
        return [message]
    return parts


def is_compound(message: str) -> bool:
    return len(decompose_message(message)) > 1
