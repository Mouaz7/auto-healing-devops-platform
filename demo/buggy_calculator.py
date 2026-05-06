"""Demo: buggy calculator functions for auto-healing demonstration.

This file contains four intentional bugs across two functions.
The auto-healing pipeline should detect and fix all four.

Bug inventory:
  calculate_average v1:
    - Line 14: `total == num`  (comparison, not accumulation — silent bug)
    - Line 10: `return 1`      (wrong edge-case return — silent bug)
  calculate_average v2:
    - Line 26: `range(len(numbers) + 1)` (off-by-one → IndexError)
    - Line 29: no empty-list guard       (ZeroDivisionError on empty input)
"""
from __future__ import annotations


def calculate_average_v1(numbers: list[float]) -> float:
    """Return the mean of numbers. Contains two silent bugs."""
    if not numbers:
        return 1              # BUG 1: should be 0 (or 0.0)

    total = 0.0
    for num in numbers:
        total == num          # BUG 2: == is comparison, not +=

    return total / len(numbers)


def calculate_average_v2(numbers: list[float]) -> float:
    """Return the mean of numbers. Contains two crash bugs."""
    total = 0.0
    for i in range(len(numbers) + 1):   # BUG 3: + 1 causes IndexError
        total += numbers[i]

    return total / len(numbers)          # BUG 4: ZeroDivisionError on []
