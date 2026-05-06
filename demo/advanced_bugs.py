"""Advanced demo bugs for auto-healing demonstration.

Five real-world bug patterns that require deeper reasoning than simple
syntax fixes. Each function has one intentional bug.

Bug inventory:
  fibonacci       — wrong base case (n==1 misses n=0 → RecursionError)
  Node.find       — missing `return` on recursive call → AttributeError NoneType
  fib_memo        — KeyError: reads memo[n] before writing it
  binary_search   — low=mid / high=mid never advances → infinite loop
  add_to_list     — mutable default argument shared across calls → silent bug
"""
from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Bug 1 — Wrong base case (RecursionError)
# ---------------------------------------------------------------------------

def fibonacci(n: int) -> int:
    """Return the nth Fibonacci number (0-indexed).

    BUG: base case is `n == 1` — misses n=0.
    fibonacci(0) → fibonacci(-1) → fibonacci(-2) → ... → RecursionError
    FIX: change to `if n <= 1: return n`
    """
    if n == 1:          # BUG: should be n <= 1
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)


# ---------------------------------------------------------------------------
# Bug 2 — Missing return on recursive call (AttributeError: NoneType)
# ---------------------------------------------------------------------------

class Node:
    """Singly-linked list node."""

    def __init__(self, val: int, nxt: Optional["Node"] = None) -> None:
        self.val = val
        self.next = nxt

    def find(self, target: int) -> Optional["Node"]:
        """Return the node whose val == target, or None.

        BUG: recursive call result is not returned.
        `self.next.find(target)` discards the found node → returns None →
        caller tries `.val` on None → AttributeError
        FIX: `return self.next.find(target)`
        """
        if self.val == target:
            return self
        if self.next:
            self.next.find(target)   # BUG: missing return
        return None


# ---------------------------------------------------------------------------
# Bug 3 — KeyError: reading cache before writing it
# ---------------------------------------------------------------------------

def fib_memo(n: int, memo: dict | None = None) -> int:
    """Return the nth Fibonacci number using memoization.

    BUG: `memo[n]` is read BEFORE checking whether n is in memo.
    First call with n=5 → KeyError: 5
    FIX: check `if n in memo: return memo[n]` before computing.
    """
    if memo is None:
        memo = {}
    if n <= 1:
        return n
    result = memo[n]          # BUG: KeyError — n not yet stored
    if result is None:
        memo[n] = fib_memo(n - 1, memo) + fib_memo(n - 2, memo)
    return memo[n]


# ---------------------------------------------------------------------------
# Bug 4 — Binary search infinite loop (low/high never advance past mid)
# ---------------------------------------------------------------------------

def binary_search(arr: list[int], target: int) -> int:
    """Return index of target in sorted arr, or -1 if absent.

    BUG: `low = mid` and `high = mid` — when arr[mid] != target the
    search window never shrinks. With arr=[1,2,3], target=3:
      low=0 high=2 mid=1 → low stays 1, high stays 1 → mid=1 forever
    FIX: `low = mid + 1` and `high = mid - 1`
    """
    low, high = 0, len(arr) - 1
    while low <= high:
        mid = (low + high) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            low = mid        # BUG: should be mid + 1
        else:
            high = mid       # BUG: should be mid - 1
    return -1


# ---------------------------------------------------------------------------
# Bug 5 — Mutable default argument (silent state leak across calls)
# ---------------------------------------------------------------------------

def add_to_list(item: int, collection: list | None = None) -> list:
    """Append item to collection and return it.

    The CORRECT version uses `collection=None` and initialises inside.
    This buggy version uses `collection=[]` — the SAME list object is
    shared across every call, so results from call N leak into call N+1.

    BUG: `def add_to_list(item, collection=[]):`
    FIX: `def add_to_list(item, collection=None):` then
         `collection = [] if collection is None else collection`
    """
    if collection is None:
        collection = []
    collection.append(item)
    return collection
