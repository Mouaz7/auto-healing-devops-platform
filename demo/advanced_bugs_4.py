"""Advanced demo bugs — batch 4. Ten bugs covering the 30 new patterns.

Bug inventory:
  build_grid           — list_multiply_shared_refs: [[0]] * 3 (shared inner lists)
  EventBus.__init__    — class_mutable_attribute + missing_super_init
  top_scores           — max_min_without_guard: max(scores) on possibly-empty list
  merge_sorted         — assert_tuple: assert (condition, msg) always passes
  encode_ids           — join_non_string_elements: join([1,2,3]) TypeError
  flatten_deep         — recursive_mutable_default: result=[] accumulates across calls
  search_sorted        — range_excludes_last_element + return_first_iteration
  cleanup_data         — wrong_exception_reraise: raise Exception(e)
  schedule_task        — callable_default_arg: def f(t=datetime.now())
  count_words          — sort_returns_none + while_condition_unchanged
"""
from __future__ import annotations

import datetime


# ---------------------------------------------------------------------------
# Bug 1 — list_multiply_shared_refs
# ---------------------------------------------------------------------------

def build_grid(rows: int, cols: int) -> list[list[int]]:
    """Return a rows × cols grid initialised to 0.

    BUG: [[0]] * rows creates `rows` references to THE SAME inner list.
    Writing to grid[0][1] also changes grid[1][1], grid[2][1], etc.
    FIX: [[0] * cols for _ in range(rows)]
    """
    return [[0] * cols] * rows   # BUG: shared inner lists


# ---------------------------------------------------------------------------
# Bug 2 — class_mutable_attribute + missing_super_init
# ---------------------------------------------------------------------------

class Publisher:
    def __init__(self, name: str) -> None:
        self.name = name


class EventBus(Publisher):
    """A simple publish/subscribe bus.

    BUG 1: `listeners = []` is a CLASS attribute — all EventBus instances
    share the same list. Adding a listener on one bus adds it to all buses.
    FIX: Move `self.listeners = []` into __init__.

    BUG 2: __init__ does not call `super().__init__(name)`, so
    `self.name` is never set (AttributeError on `self.name`).
    FIX: Add `super().__init__(name)`.
    """
    listeners = []    # BUG 1: class-level mutable attribute

    def __init__(self, name: str) -> None:
        # BUG 2: missing super().__init__(name)
        pass

    def subscribe(self, fn) -> None:
        self.listeners.append(fn)

    def publish(self, event) -> None:
        for fn in self.listeners:
            fn(event)


# ---------------------------------------------------------------------------
# Bug 3 — max_min_without_guard
# ---------------------------------------------------------------------------

def top_scores(scores: list[int]) -> int:
    """Return the highest score.

    BUG: max(scores) raises ValueError: max() arg is an empty sequence
    when scores is empty.
    FIX: if not scores: return 0
    """
    return max(scores)   # BUG: no empty guard


# ---------------------------------------------------------------------------
# Bug 4 — assert_tuple always truthy
# ---------------------------------------------------------------------------

def merge_sorted(a: list, b: list) -> list:
    """Merge two sorted lists into a sorted result.

    BUG: `assert (a is not None, "a cannot be None")` passes a 2-element
    tuple as the test — a non-empty tuple is ALWAYS True.
    The assertion NEVER fails, even when a is None.
    FIX: assert a is not None, "a cannot be None"
    """
    assert (a is not None, "a cannot be None")   # BUG: tuple always True  # noqa: F631
    assert (b is not None, "b cannot be None")   # BUG: same
    result = []
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            result.append(a[i]); i += 1
        else:
            result.append(b[j]); j += 1
    result.extend(a[i:]); result.extend(b[j:])
    return result


# ---------------------------------------------------------------------------
# Bug 5 — join_non_string_elements
# ---------------------------------------------------------------------------

def encode_ids(ids: list[int]) -> str:
    """Return a comma-separated string of integer IDs.

    BUG: str.join() requires all elements to be strings.
    Passing ints raises TypeError: sequence item 0: expected str, got int.
    FIX: ", ".join(str(i) for i in ids)
    """
    return ", ".join(ids)    # BUG: ids contains ints, not strings


# ---------------------------------------------------------------------------
# Bug 6 — recursive_mutable_default accumulates across calls
# ---------------------------------------------------------------------------

def flatten_deep(nested: list, result: list = []) -> list:   # BUG: mutable default  # noqa: B006
    """Recursively flatten a nested list.

    BUG: `result=[]` is evaluated ONCE. Every call to flatten_deep() shares
    the same result list. The second call appends to leftovers from the first.
    FIX: use `result=None` and set `if result is None: result = []` inside.
    """
    for item in nested:
        if isinstance(item, list):
            flatten_deep(item, result)
        else:
            result.append(item)
    return result


# ---------------------------------------------------------------------------
# Bug 7 — range_excludes_last + return_first_iteration
# ---------------------------------------------------------------------------

def search_sorted(arr: list[int], target: int) -> int:
    """Return index of target in sorted arr, or -1.

    BUG 1: range(len(arr) - 1) never checks the last element.
    BUG 2: return i is unconditional — exits on the FIRST element always.
    FIX: for i in range(len(arr)):  AND  if arr[i] == target: return i
    """
    for i in range(len(arr) - 1):   # BUG 1: misses last element
        return i                     # BUG 2: always exits on first iteration
    return -1


# ---------------------------------------------------------------------------
# Bug 8 — wrong_exception_reraise (loses traceback)
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    """Load JSON config from path.

    BUG: `raise Exception(e)` wraps the original exception in a new one,
    discarding the original traceback and chaining information.
    FIX: use bare `raise` to re-raise with full context preserved.
    """
    try:
        with open(path) as f:
            import json
            return json.load(f)
    except Exception as e:
        raise Exception(e)    # BUG: should be bare `raise`


# ---------------------------------------------------------------------------
# Bug 9 — callable_default_arg (timestamp frozen at import time)
# ---------------------------------------------------------------------------

def create_event(
    name: str,
    timestamp: datetime.datetime = datetime.datetime.now(),  # BUG: evaluated once
) -> dict:
    """Create a timestamped event dict.

    BUG: `datetime.datetime.now()` is evaluated ONCE when the module is
    imported. Every call to create_event() gets the SAME timestamp.
    FIX: use `timestamp=None` and set `if timestamp is None: timestamp = datetime.datetime.now()`
    """
    return {"name": name, "timestamp": timestamp}


# ---------------------------------------------------------------------------
# Bug 10 — sort_returns_none + while_condition_unchanged
# ---------------------------------------------------------------------------

def get_top_n(items: list[int], n: int) -> list[int]:
    """Return the n largest items, sorted descending.

    BUG 1: `result = sorted_items.sort()` — sort() returns None,
    so result is always None.
    BUG 2: `while processing:` — processing is never changed inside
    the loop body (would be an infinite loop if ever reached).
    FIX: result = sorted(items, reverse=True)[:n]
    """
    sorted_items = list(items)
    result = sorted_items.sort(reverse=True)   # BUG 1: sort() returns None
    processing = True
    while processing:                           # BUG 2: never modified → infinite
        return (result or [])[:n]
