import time
from collections import deque
from typing import Tuple


LIMITS = {
    "search": (20, 60),
    "write_file": (20, 60),
    "create_issue": (5, 60),
    "comment_on_issue": (5, 60),
    "list_notifications": (15, 60),
}
DEFAULT = (30, 60)

_history: dict = {}


def check_rate(tool: str) -> Tuple[bool, str]:
    max_calls, window = LIMITS.get(tool, DEFAULT)
    now = time.time()
    q = _history.setdefault(tool, deque())
    while q and q[0] < now - window:
        q.popleft()
    if len(q) >= max_calls:
        return False, f"rate limit ({max_calls}/{window}s)"
    q.append(now)
    return True, ""