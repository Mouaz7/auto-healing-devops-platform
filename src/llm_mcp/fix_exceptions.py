"""Exception types raised by the fix-generation pipeline."""
from __future__ import annotations


class FixTooLongError(ValueError):
    """Raised when the generated fix exceeds MAX_FIX_LINES."""


class SecretLeakError(ValueError):
    """Raised when the generated fix contains hardcoded secrets."""


class FixStillBrokenError(ValueError):
    """LLM cannot produce a runtime-correct fix after retries.

    The fix compiled but still infinite-looped or crashed when executed.
    Routes to BLOCKED so a human can intervene.
    """


class NoCodeContextError(ValueError):
    """generate_fix called without real code_context.

    Without the actual source file, the LLM can only hallucinate. Better to
    fail loudly so the orchestrator routes the failure to human review.
    """


class SyntaxFixExhaustedError(ValueError):
    """Every retry produced fix_code that fails to compile.

    Treated as BLOCKED (HTTP 422), not 503 — more retries from the
    orchestrator will not help; the LLM kept producing invalid Python.
    """
