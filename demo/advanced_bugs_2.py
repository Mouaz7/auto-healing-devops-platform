"""Advanced demo bugs — batch 2. Five real-world Python bug patterns.

Bug inventory:
  graph_bfs          — missing visited set causes infinite loop on cycles
  calculate_grade    — UnboundLocalError: variable used before assignment
  word_count         — RuntimeError: dict changed size during iteration
  flatten            — TypeError: NoneType is not iterable (missing return)
  binary_search_v2   — returns wrong result due to `is` vs `==` comparison
"""
from __future__ import annotations

from collections import deque


# ---------------------------------------------------------------------------
# Bug 1 — Missing visited set → infinite loop on cyclic graph
# ---------------------------------------------------------------------------

def graph_bfs(graph: dict[str, list[str]], start: str) -> list[str]:
    """Return all nodes reachable from start via BFS.

    BUG: no visited set — revisiting already-seen nodes creates an
    infinite loop when the graph has a cycle.
    FIX: add `visited = set()` and skip nodes already in visited.
    """
    result: list[str] = []
    queue: deque[str] = deque([start])
    # BUG: missing visited = set()
    while queue:
        node = queue.popleft()
        # BUG: missing `if node in visited: continue` + `visited.add(node)`
        result.append(node)
        for neighbour in graph.get(node, []):
            queue.append(neighbour)
    return result


# ---------------------------------------------------------------------------
# Bug 2 — UnboundLocalError: grade assigned only in some branches
# ---------------------------------------------------------------------------

def calculate_grade(score: int) -> str:
    """Return letter grade for a numeric score.

    BUG: `grade` is not assigned when score < 0 or score > 100.
    Any out-of-range input raises UnboundLocalError: local variable
    'grade' referenced before assignment.
    FIX: add `grade = "INVALID"` before the if-chain, or add an else branch.
    """
    if score >= 90:
        grade = "A"
    elif score >= 80:
        grade = "B"
    elif score >= 70:
        grade = "C"
    elif score >= 60:
        grade = "D"
    elif score >= 0:
        grade = "F"
    # BUG: no else branch — grade is unbound for score < 0 or score > 100
    return grade   # UnboundLocalError if score = -1 or score = 101


# ---------------------------------------------------------------------------
# Bug 3 — RuntimeError: dict changed size during iteration
# ---------------------------------------------------------------------------

def remove_low_scores(scores: dict[str, int], threshold: int) -> dict[str, int]:
    """Remove all entries with score < threshold. Returns the same dict.

    BUG: `del scores[name]` modifies the dict while iterating over it.
    Python raises RuntimeError: dictionary changed size during iteration.
    FIX: iterate over `list(scores.items())` to snapshot before mutating.
    """
    for name, score in scores.items():   # BUG: should be list(scores.items())
        if score < threshold:
            del scores[name]
    return scores


# ---------------------------------------------------------------------------
# Bug 4 — TypeError: NoneType is not iterable (missing return in recursive fn)
# ---------------------------------------------------------------------------

def flatten(nested: list) -> list:
    """Recursively flatten a nested list into a flat list.

    BUG: the recursive call result is not returned — it is discarded.
    `result.extend(flatten(item))` receives None (the implicit return
    of the function) → TypeError: 'NoneType' object is not iterable.
    FIX: add `return result` at the end of the function.
    """
    result: list = []
    for item in nested:
        if isinstance(item, list):
            result.extend(flatten(item))
        else:
            result.append(item)
    # BUG: missing return result


# ---------------------------------------------------------------------------
# Bug 5 — `is` vs `==` gives wrong result for non-singleton integers
# ---------------------------------------------------------------------------

def find_first_zero(numbers: list[int]) -> int:
    """Return index of the first zero in numbers, or -1 if none found.

    BUG: `num is 0` uses identity comparison. For large integers Python
    does not guarantee object reuse, so `is` may return False even when
    the value is 0. Works by accident for small ints (-5..256) but fails
    for values like `int('0')` created at runtime.
    FIX: use `num == 0`.
    """
    for i, num in enumerate(numbers):
        if num is 0:          # BUG: should be `num == 0`  # noqa: E712
            return i
    return -1
