"""AdminMixin — stats, retry, and AI code review endpoints."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid

import httpx
from aiohttp import web

from src.shared.adaptive_thresholds import adaptive_thresholds
from src.shared.audit_log import audit
from src.shared.cost_tracker import cost_tracker
from src.shared.fix_memory import fix_memory
from src.shared.heal_verifier import heal_verifier
from src.shared.models import WorkflowState, WorkflowStatus
from src.shared.token_tracker import token_tracker
from src.orchestrator_mcp.deduplication import dedup_cache
from src.orchestrator_mcp.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)
_HTTP_TIMEOUT = 300.0


_REVIEW_SYSTEM_PROMPT = (
    "You are an expert Python code reviewer specializing in logic bugs that do NOT cause "
    "crashes or test failures but produce wrong behaviour.\n\n"
    "Carefully check every line for:\n"
    "1. SELF-COMPARISON: a variable compared to itself, e.g. `if x < x`, `if n == n` "
    "   — always true/false, kills loops or recursion silently.\n"
    "2. WRONG VARIABLE: using the wrong variable name in a condition or expression, "
    "   e.g. `if low < high` written as `if high < high`.\n"
    "3. OFF-BY-ONE: loop bounds, index +1/-1 mistakes.\n"
    "4. INFINITE LOOP: loop condition that never changes.\n"
    "5. DEAD CODE: branch that can never execute.\n"
    "6. WRONG OPERATOR: `<` vs `<=`, `and` vs `or`, `=` vs `==`.\n"
    "7. WRONG RETURN: function returns wrong variable or constant.\n"
    "8. SWAPPED ARGUMENTS: arguments passed in wrong order.\n\n"
    "For EVERY condition (`if`, `while`, `for`) ask yourself: "
    "'Can this ever be True AND False, or is one side always the same as the other?'\n\n"
    "Respond with JSON only — no text outside the JSON:\n"
    '{"has_bug": true|false, "error_type": "SELF_COMPARISON|WRONG_VAR|OFF_BY_ONE|'
    'INFINITE_LOOP|DEAD_CODE|WRONG_OPERATOR|WRONG_RETURN|SWAPPED_ARGS|OTHER", '
    '"description": "exact bug description with line number and what it should be", '
    '"line": <line_number>, "fix": "the corrected line of code"}'
)


class AdminMixin:
    """Stats, retry, and AI code review endpoints."""

    async def get_stats(self, _request: web.Request) -> web.Response:
        """System-wide statistics for monitoring and thesis evaluation."""
        workflow_counts = self.engine.stats()
        prune_result = self.engine.prune_stale()
        return web.json_response({
            "workflows": {
                "by_status":        workflow_counts,
                "total":            sum(workflow_counts.values()),
                "active":           len(self.engine.list_active()),
                "pruned_this_call": prune_result,
            },
            "tokens_used_this_hour": token_tracker.usage_snapshot(),
            "cost":                  cost_tracker.session_summary(),
            "deduplication":         {"cache_size":   dedup_cache.size()},
            "rate_limiter":          {"active_keys":  rate_limiter.stats()},
            "audit_log": {
                "event_counts":  audit.summary(),
                "recent_events": audit.tail(n=10),
            },
            "regression_monitor":    {"active_fix_watches": heal_verifier.active_fixes()},
            "adaptive_thresholds":   adaptive_thresholds.summary(),
        })

    async def retry_build(self, request: web.Request) -> web.Response:
        """Re-submit a previously failed build through the pipeline.

        Looks up the original log from fix_memory and queues a new build_id.
        """
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)
        build_id = data.get("build_id", "")
        if not build_id:
            return web.json_response({"error": "build_id required"}, status=400)

        all_records = fix_memory._load_records()  # pylint: disable=protected-access
        original = next(
            (r for r in reversed(all_records)
             if r.get("build_id") == build_id and not r.get("_update")),
            None,
        )
        if not original:
            return web.json_response(
                {"error": f"No fix record found for build_id={build_id}"},
                status=404,
            )

        new_build_id = f"{build_id}-retry-{uuid.uuid4().int % 10000:04d}"
        audit.log("pipeline_retry", original_build_id=build_id, new_build_id=new_build_id)
        logger.info("retry_build original=%s new=%s", build_id, new_build_id)
        return web.json_response({
            "original_build_id": build_id,
            "new_build_id":      new_build_id,
            "status":            "QUEUED",
            "message":           (f"Build {new_build_id} queued. "
                                  "Submit new raw_log via /tools/handle_build_failure to re-run."),
        }, status=202)

    async def review_code(self, request: web.Request) -> web.Response:
        """AI-powered code review for logic bugs — no crash needed to trigger healing.

        POST /tools/review_code  body: {"file_path", "code", "repo", "build_id"}
        If the LLM finds a bug, kicks off the full healing pipeline.
        """
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)

        file_path = data.get("file_path", "")
        code = data.get("code", "")
        repo = data.get("repo", "")
        build_id = data.get("build_id", str(uuid.uuid4())[:8])
        if not code or not file_path:
            return web.json_response({"error": "file_path and code required"}, status=400)

        user_prompt = (
            f"File: {file_path}\n\n"
            "IMPORTANT: Look especially for self-comparisons like `if x < x` or `if x == x` "
            "which are always False/True and make algorithms do nothing.\n\n"
            f"```python\n{code}\n```"
        )

        try:
            from src.shared.nim_client import NimClient
            nim = NimClient(agent_name="code_repairer", agent_env_prefix="CODE_REPAIRER")
            raw = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: nim.complete([
                    {"role": "system", "content": _REVIEW_SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ]),
            )
            json_match = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
            if json_match:
                review = json.loads(json_match.group())
                has_bug = bool(review.get("has_bug", False))
                bug_description = review.get("description", "")
            else:
                bug_keywords = ["wrong", "incorrect", "error", "bug",
                                "should be", "infinite loop"]
                has_bug = any(kw in raw.lower() for kw in bug_keywords)
                bug_description = raw[:300]
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("review_code llm_failed file=%s err=%s", file_path, exc)
            return web.json_response({"has_bug": False, "reason": "llm unavailable"})

        if not has_bug:
            return web.json_response({"has_bug": False, "file": file_path})

        logger.info("review_code bug_found file=%s desc=%s", file_path, bug_description)
        audit.log("code_review_bug_found", file=file_path, description=bug_description)

        synthetic_log = (
            f"FAILED_FILE: {file_path}\n"
            f"ERROR_TYPE: LOGIC_ERROR\n"
            f"AI Code Review detected a bug: {bug_description}\n\n"
            f"FILE_CONTENT_START: {file_path}\n{code}\nFILE_CONTENT_END"
        )

        asyncio.create_task(self._trigger_healing_for_review(
            build_id=f"review-{build_id}", repo=repo, raw_log=synthetic_log,
        ))
        return web.json_response({
            "has_bug": True,
            "file": file_path,
            "description": bug_description,
            "healing_triggered": True,
        })

    async def _trigger_healing_for_review(
        self, build_id: str, repo: str, raw_log: str,
    ) -> None:
        """Submit a code-review-detected bug to the main healing pipeline.

        Runs `_run_pipeline` directly (not via HTTP self-call) — a self-POST
        used to race the orchestrator's own outer timeout against the LLM-mcp
        timeout, producing misleading ReadTimeouts.
        """
        state = WorkflowState(build_id=build_id, status=WorkflowStatus.PENDING)
        try:
            self.engine.register(state)
        except ValueError:
            logger.info("review_healing_already_registered build_id=%s", build_id)
            return

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                result = await self._run_pipeline(
                    client, build_id, raw_log, repo, str(uuid.uuid4())
                )
            logger.info(
                "review_healing_trigger_done build_id=%s status=%s",
                build_id, result.get("status"),
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.error(
                "review_healing_trigger_failed build_id=%s err=%r type=%s",
                build_id, exc, type(exc).__name__,
            )
            self._safe_fail(build_id, str(exc) or repr(exc))
