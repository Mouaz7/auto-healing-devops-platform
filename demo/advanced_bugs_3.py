"""Advanced demo bugs — batch 3. Ten real-world Python bug patterns.

Bug inventory:
  calculate_stats    — wrong_accumulator_init: total = 1 (should be 0)
  calculate_stats    — loop_overwrites_accumulator: total = n (should be +=)
  build_config       — duplicate_dict_key: 'host' appears twice
  compute_product    — wrong_product_sentinel: product = 0 (should be 1)
  find_max           — wrong_sentinel: max_val = 0 (misses negative inputs)
  normalize          — augmented_subtract_in_sum: total -= x in avg function
  point_distance     — none_equality_check: result == None (use is None)
  Container.__init__ — forgot_self_dot: name = name (not self.name = name)
  load_data          — exception_swallowed: except ValueError: pass
  is_even            — redundant_bool_comparison: return x % 2 == 0 == True
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Bug 1 + 2 — wrong accumulator init AND loop overwrites
# ---------------------------------------------------------------------------

def calculate_stats(numbers: list[float]) -> dict:
    """Return {'sum': ..., 'count': ..., 'average': ...} for the list.

    BUG 1: total = 1 → first iteration adds 1 to every sum.
    BUG 2: total = n inside loop → each iteration replaces total with n,
           so total ends up as just the last element.
    FIX: total = 0  AND  total += n
    """
    if not numbers:
        return {"sum": 0, "count": 0, "average": 0.0}
    total = 1          # BUG 1: wrong init
    count = len(numbers)
    for n in numbers:
        total = n      # BUG 2: overwrites instead of accumulates
    return {"sum": total, "count": count, "average": total / count}


# ---------------------------------------------------------------------------
# Bug 3 — duplicate dict key
# ---------------------------------------------------------------------------

def build_config() -> dict:
    """Return database configuration dict.

    BUG: 'host' key appears twice — second value silently wins.
    FIX: Remove or rename the duplicate key.
    """
    return {
        "host": "localhost",   # BUG: first value ignored
        "port": 5432,
        "host": "db.prod.internal",  # BUG: second value wins silently  # noqa: F601
        "database": "app",
    }


# ---------------------------------------------------------------------------
# Bug 4 — wrong product sentinel
# ---------------------------------------------------------------------------

def compute_product(numbers: list[int]) -> int:
    """Return the product of all numbers.

    BUG: product = 0 → any number * 0 = 0. Result is always 0.
    FIX: product = 1 (identity element for multiplication)
    """
    product = 0   # BUG: should be 1
    for n in numbers:
        product *= n
    return product


# ---------------------------------------------------------------------------
# Bug 5 — wrong sentinel for max (misses negatives)
# ---------------------------------------------------------------------------

def find_max(numbers: list[float]) -> float:
    """Return the maximum value in the list.

    BUG: max_val = 0 — if all numbers are negative, returns 0 (wrong).
    FIX: max_val = numbers[0] or max_val = float('-inf')
    """
    if not numbers:
        return 0.0
    max_val = 0       # BUG: wrong sentinel — misses all-negative lists
    for n in numbers:
        if n > max_val:
            max_val = n
    return max_val


# ---------------------------------------------------------------------------
# Bug 6 — augmented subtract instead of add in average function
# ---------------------------------------------------------------------------

def normalize_average(values: list[float]) -> float:
    """Return the average of values.

    BUG: total -= v subtracts instead of adds — produces -(sum) / n.
    FIX: total += v
    """
    if not values:
        return 0.0
    total = 0.0
    for v in values:
        total -= v    # BUG: should be +=
    return total / len(values)


# ---------------------------------------------------------------------------
# Bug 7 — `== None` instead of `is None`
# ---------------------------------------------------------------------------

def point_distance(p1: tuple | None, p2: tuple | None) -> float:
    """Return Euclidean distance between two (x, y) points.

    BUG: `p1 == None` uses __eq__, not identity. Should be `is None`.
    FIX: if p1 is None or p2 is None
    """
    if p1 == None or p2 == None:    # BUG: use `is None`  # noqa: E711
        return 0.0
    return ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5


# ---------------------------------------------------------------------------
# Bug 8 — forgot self.  in __init__
# ---------------------------------------------------------------------------

class Container:
    """A named container with a max capacity.

    BUG: `name = name` and `capacity = capacity` assign to local variables,
    not to instance attributes. `self.name` and `self.capacity` are never set.
    FIX: `self.name = name` and `self.capacity = capacity`
    """
    def __init__(self, name: str, capacity: int) -> None:
        name = name            # BUG: should be self.name = name
        capacity = capacity    # BUG: should be self.capacity = capacity
        self.items: list = []

    def info(self) -> str:
        return f"{self.name}: {len(self.items)}/{self.capacity}"  # AttributeError


# ---------------------------------------------------------------------------
# Bug 9 — exception swallowed (except: pass)
# ---------------------------------------------------------------------------

def load_data(raw: str) -> int:
    """Parse raw string as integer, return -1 on failure.

    BUG: `except ValueError: pass` silently swallows bad input.
    After the except block, `value` is unbound → NameError.
    FIX: assign a default before the try, or return in the except.
    """
    try:
        value = int(raw)
    except ValueError:
        pass           # BUG: value never set — NameError follows
    return value       # NameError: local variable 'value' referenced before assignment


# ---------------------------------------------------------------------------
# Bug 10 — redundant bool comparison
# ---------------------------------------------------------------------------

def is_even(n: int) -> bool:
    """Return True if n is even.

    BUG: `return (n % 2 == 0) == True` — double comparison is redundant.
    `n % 2 == 0` already IS a bool.
    FIX: `return n % 2 == 0`
    """
    return (n % 2 == 0) == True    # BUG: redundant `== True`  # noqa: E712
