"""PipelineMixin — the Agent 1→3→4→5→6 auto-heal pipeline.

`_run_pipeline` is split into per-step coroutines so each step can be
read, tested, and debugged on its own. Public entry: `handle_build_failure`.
"""
from __future__ import annotations

import asyncio
import logging
import time
import traceback
import uuid

import httpx
from aiohttp import web

from src.shared.audit_log import audit
from src.shared import config as _config
from src.shared.config import GERRIT_FETCH_TIMEOUT, LLM_FIX_TIMEOUT
from src.shared.fix_memory import fix_memory
from src.shared.heal_verifier import heal_verifier
from src.shared.models import WorkflowState, WorkflowStatus
from src.shared.resilience import handle_agent_failure, trigger_global_fallback
from src.notification_mcp.slack_notifier import (
    send_slack_notification,
    send_slack_pipeline_started,
    send_slack_review_buttons,
)
from src.orchestrator_mcp.deduplication import dedup_cache
from src.orchestrator_mcp.pipeline_helpers import (
    build_minimal_analysis,
    extract_code_from_log,
    extract_failed_files,
)
from src.orchestrator_mcp.rate_limiter import rate_limiter
from src.llm_mcp.bug_scanner import BugPatternScanner

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 300.0  # default per-call; LLM_FIX_TIMEOUT overrides for generate_fix


class PipelineMixin:
    """Provides handle_build_failure + the 4-step pipeline."""

    # --- Entry point ---------------------------------------------------

    async def handle_build_failure(self, request: web.Request) -> web.Response:
        """POST /tools/handle_build_failure — start the auto-heal pipeline.

        Default mode: returns 202 immediately and runs the pipeline in
        background (high-bug-density files can legitimately take 5-10 min).
        Pass `"sync": true` to block until the pipeline finishes.
        """
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)

        client_ip = request.remote or "unknown"
        if not rate_limiter.is_allowed(client_ip):
            audit.log("rate_limit_blocked", client_ip=client_ip)
            return web.json_response(
                {"error": "rate_limit_exceeded", "retry_after_seconds": 60},
                status=429,
            )

        build_id = data.get("build_id", "")
        raw_log  = data.get("raw_log", "")
        repo     = data.get("repo", "")
        if not build_id or not raw_log:
            return web.json_response(
                {"error": "build_id and raw_log are required"}, status=400
            )
        if len(raw_log) > 500_000:
            return web.json_response(
                {"error": "raw_log exceeds 500 KB limit", "size": len(raw_log)},
                status=413,
            )

        state = WorkflowState(build_id=build_id, status=WorkflowStatus.PENDING)
        try:
            self.engine.register(state)
        except ValueError as exc:
            try:
                existing_status = self.engine.get(build_id).status.value
            except Exception:  # pylint: disable=broad-exception-caught
                existing_status = "UNKNOWN"
            logger.info(
                "duplicate_handle_build_failure build_id=%s existing_status=%s",
                build_id, existing_status,
            )
            return web.json_response(
                {
                    "build_id":        build_id,
                    "status":          "ALREADY_TRIGGERED",
                    "existing_status": existing_status,
                    "message":         str(exc),
                },
                status=200,
            )

        correlation_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        audit.log("pipeline_start", build_id=build_id, repo=repo,
                  correlation_id=correlation_id)
        logger.info("pipeline_start build_id=%s correlation_id=%s repo=%s",
                    build_id, correlation_id, repo)

        if data.get("sync") is True:
            return await self._run_pipeline_sync(build_id, raw_log, repo, correlation_id)

        # Fire-and-forget Slack ping so the user sees activity immediately.
        # The pipeline can take 5-20 min for hard cases; without this, the
        # next thing they'd see is the final GREEN/YELLOW/RED much later.
        asyncio.create_task(
            send_slack_pipeline_started(build_id, repo, extract_failed_files(raw_log))
        )
        asyncio.create_task(
            self._run_pipeline_background(build_id, raw_log, repo, correlation_id)
        )
        return web.json_response(
            {
                "build_id":       build_id,
                "status":         "ACCEPTED",
                "message":        "auto-heal pipeline started — poll /tools/get_workflow_state for progress",
                "correlation_id": correlation_id,
            },
            status=202,
        )

    # --- Pipeline runners ---------------------------------------------

    async def _run_pipeline_sync(
        self, build_id: str, raw_log: str, repo: str, correlation_id: str,
    ) -> web.Response:
        """Synchronous run — blocks until the pipeline finishes (tests, sync=true)."""
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            try:
                result = await self._run_pipeline(client, build_id, raw_log, repo, correlation_id)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                err_str = self._handle_pipeline_exception(build_id, raw_log, exc)
                return web.json_response(
                    {"build_id": build_id, "status": "FAILED",
                     "error": err_str, "type": type(exc).__name__},
                    status=500,
                )
        return web.json_response(result)

    async def _run_pipeline_background(
        self, build_id: str, raw_log: str, repo: str, correlation_id: str,
    ) -> None:
        """Background run — caller already got 202; failures go via fallback chain."""
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            try:
                await self._run_pipeline(client, build_id, raw_log, repo, correlation_id)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self._handle_pipeline_exception(build_id, raw_log, exc)

    def _handle_pipeline_exception(
        self, build_id: str, raw_log: str, exc: Exception,
    ) -> str:
        """Common exception handling for sync + background runs."""
        tb = traceback.format_exc()
        err_str = str(exc) or repr(exc) or f"{type(exc).__name__}(no message)"
        logger.error(
            "pipeline_exception build_id=%s type=%s str=%r repr=%r\n%s",
            build_id, type(exc).__name__, str(exc), repr(exc), tb,
        )
        fallback_files = extract_failed_files(raw_log)
        handle_agent_failure("orchestrator", build_id, err_str, fallback_files)
        self._safe_fail(build_id, err_str)
        asyncio.create_task(
            trigger_global_fallback("orchestrator", build_id, err_str, fallback_files)
        )
        audit.log("pipeline_failed", build_id=build_id, error=err_str)
        return err_str

    def _safe_fail(self, build_id: str, reason: str) -> None:
        """Mark workflow FAILED, ignoring errors if already terminal."""
        try:
            self.engine.fail(build_id, reason)
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    # --- The 4-step pipeline (split into helpers below) ---------------

    async def _run_pipeline(
        self,
        client: httpx.AsyncClient,
        build_id: str,
        raw_log: str,
        repo: str = "",
        correlation_id: str = "",
    ) -> dict:
        """Execute Agent 3→4→5→6 and return the final verdict dict."""
        headers = {"X-Request-ID": correlation_id} if correlation_id else {}

        started_at = time.monotonic()

        cleaned  = await self._step_clean_logs(client, build_id, raw_log, headers)
        analysis = await self._step_analyse(client, build_id, raw_log, cleaned, headers)
        if self._check_regression(build_id, analysis):
            elapsed_s = round(time.monotonic() - started_at)
            self.engine.advance(build_id, WorkflowStatus.BLOCKED)
            files_str = ", ".join(analysis.get("affected_files", []))
            asyncio.create_task(send_slack_notification(
                "RED", build_id, 0.0,
                "Regression loop detected — this file was recently fixed and failed again. "
                "Automatic repair blocked. Manual intervention required.",
                files_str, elapsed_s=elapsed_s,
            ))
            return self._blocked_result(
                build_id,
                "regression_loop",
                "Regression detected — the same file was recently fixed and failed again. "
                "Blocking to prevent an infinite repair loop. Manual review required.",
            )
        code_context = await self._step_fetch_context(client, repo, analysis, raw_log)
        fix = await self._step_generate_fix(
            client, build_id, analysis, cleaned, code_context, headers,
        )
        if fix is None:  # 422 — structurally unrecoverable
            elapsed_s = round(time.monotonic() - started_at)
            files_str = ", ".join(analysis.get("affected_files", []))
            asyncio.create_task(send_slack_notification(
                "RED", build_id, 0.0,
                "Fix generation rejected (422) — change is too complex or structurally "
                "unrecoverable. Manual intervention required.",
                files_str, elapsed_s=elapsed_s,
            ))
            return self._blocked_result(build_id, "fix_rejected", "Fix generation rejected")

        elapsed_s = round(time.monotonic() - started_at)
        verdict = await self._step_notify(
            client, build_id, fix, analysis, headers, elapsed_s=elapsed_s,
        )

        dedup_hit = dedup_cache.check(
            error_type=analysis["error_type"],
            root_cause=analysis.get("root_cause", ""),
            affected_files=analysis["affected_files"],
        )
        if dedup_hit:
            return self._dedup_result(build_id, dedup_hit)

        return await self._finalise(
            client, build_id, repo, analysis, fix, verdict, elapsed_s=elapsed_s,
            original_code=code_context,
        )

    # --- Pipeline steps -----------------------------------------------

    async def _step_clean_logs(
        self, client, build_id, raw_log, headers,
    ) -> dict:
        """Agent 3 — clean logs. Falls back to raw log on failure (best-effort)."""
        self.engine.advance(build_id, WorkflowStatus.ANALYSING)
        try:
            resp = await client.post(
                f"{_config.SERVICE_URLS['log_cleaner']}/tools/clean_logs",
                json={"build_id": build_id, "raw_log": raw_log},
                headers=headers,
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            if "cleaned_logs" not in data:
                raise ValueError(f"Agent 3 response missing 'cleaned_logs': {data}")
            return data
        except (httpx.TimeoutException, httpx.HTTPStatusError, ValueError) as exc:
            logger.warning(
                "log_cleaner_unavailable build_id=%s err=%r — using raw log",
                build_id, exc,
            )
            return {"cleaned_logs": raw_log}

    async def _step_analyse(
        self, client, build_id, raw_log, cleaned, headers,
    ) -> dict:
        """Agent 4 — analyse failure. Falls back to log-extracted analysis on failure."""
        try:
            resp = await client.post(
                f"{_config.SERVICE_URLS['knowledge_graph']}/tools/analyze_failure",
                json={"build_id": build_id, "cleaned_logs": cleaned["cleaned_logs"]},
                headers=headers,
                timeout=60.0,
            )
            resp.raise_for_status()
            analysis = resp.json()
            for required in ("error_type", "blast_radius", "affected_files",
                             "confidence", "root_cause"):
                if required not in analysis:
                    raise ValueError(f"Agent 4 response missing '{required}': {analysis}")
        except (httpx.TimeoutException, httpx.HTTPStatusError, ValueError) as exc:
            logger.warning(
                "analyser_unavailable build_id=%s err=%r — using minimal analysis",
                build_id, exc,
            )
            analysis = build_minimal_analysis(raw_log)

        # Backfill from raw log if cleaner stripped FAILED_FILE markers
        if not analysis["affected_files"]:
            extra = extract_failed_files(raw_log)
            if extra:
                analysis["affected_files"].extend(extra)
                logger.info(
                    "affected_files_from_log build_id=%s files=%s",
                    build_id, analysis["affected_files"],
                )
        return analysis

    def _check_regression(self, build_id: str, analysis: dict) -> bool:
        """Return True and log audit event if the failing files were recently fixed.

        A True return means the pipeline detected a regression loop and the
        caller must stop further processing to prevent an infinite repair cycle.
        """
        regression = heal_verifier.check_regression(build_id, analysis["affected_files"])
        if not regression:
            return False
        audit.log(
            "regression_detected",
            build_id=build_id,
            original_build=regression["original_build_id"],
            overlap_files=regression["overlap_files"],
            age_minutes=regression["age_minutes"],
        )
        logger.warning(
            "regression_loop_blocked build_id=%s original=%s files=%s age_min=%.1f",
            build_id, regression["original_build_id"],
            regression["overlap_files"], regression["age_minutes"],
        )
        return True

    async def _step_fetch_context(
        self, client, repo: str, analysis: dict, raw_log: str,
    ) -> str:
        """Step 2b — fetch code context from gerrit (max 3 files, in parallel)."""
        code_context = ""
        if repo and analysis.get("affected_files"):
            files = analysis["affected_files"][:3]
            tasks = [
                client.post(
                    f"{_config.SERVICE_URLS['gerrit']}/tools/fetch_file",
                    json={"repo": repo, "file_path": fp},
                    timeout=GERRIT_FETCH_TIMEOUT,
                )
                for fp in files
            ]
            for resp in await asyncio.gather(*tasks, return_exceptions=True):
                if isinstance(resp, Exception):
                    continue  # best-effort
                if resp.status_code == 200:
                    code_context += resp.json().get("content", "")

        if not code_context:
            code_context = extract_code_from_log(raw_log)
            if code_context:
                logger.info("code_context_from_log chars=%d", len(code_context))
        return code_context

    async def _step_generate_fix(
        self, client, build_id, analysis, cleaned, code_context, headers,
    ) -> dict | None:
        """Agent 5 — generate fix. Returns None on 422 (caller routes to BLOCKED)."""
        self.engine.advance(build_id, WorkflowStatus.GENERATING_FIX)
        resp = await client.post(
            f"{_config.SERVICE_URLS['llm']}/tools/generate_fix",
            json={
                "build_id":       build_id,
                "error_type":     analysis["error_type"],
                "blast_radius":   analysis["blast_radius"],
                "affected_files": analysis["affected_files"],
                "confidence":     analysis["confidence"],
                "root_cause":     analysis["root_cause"],
                "cleaned_logs":   cleaned["cleaned_logs"],
                "code_context":   code_context,
            },
            headers=headers,
            timeout=LLM_FIX_TIMEOUT,
        )
        if resp.status_code == 422:
            self.engine.advance(build_id, WorkflowStatus.BLOCKED)
            return None
        resp.raise_for_status()
        fix = resp.json()
        if "fix_patch" not in fix or "confidence" not in fix:
            raise ValueError(f"Agent 5 response missing required fields: {fix}")
        return fix

    async def _step_notify(
        self, client, build_id, fix, analysis, headers, elapsed_s: int = 0,
    ) -> dict:
        """Agent 6 — traffic-light verdict + notification."""
        self.engine.advance(build_id, WorkflowStatus.VALIDATING)
        resp = await client.post(
            f"{_config.SERVICE_URLS['notification']}/tools/evaluate_and_notify",
            json={
                "build_id":       build_id,
                "fix_patch":      fix["fix_patch"],
                "confidence":     fix["confidence"],
                "explanation":    fix.get("explanation", ""),
                "error_type":     analysis["error_type"],
                "blast_radius":   analysis["blast_radius"],
                "affected_files": analysis["affected_files"],
                "elapsed_s":      elapsed_s,
            },
            headers=headers,
        )
        resp.raise_for_status()
        verdict = resp.json()
        if "status" not in verdict:
            raise ValueError(f"Agent 6 response missing 'status': {verdict}")
        return verdict

    # --- Result builders ----------------------------------------------

    def _blocked_result(self, build_id: str, reason: str, message: str) -> dict:
        return {
            "build_id": build_id,
            "status":   "BLOCKED",
            "colour":   "RED",
            "reason":   reason,
            "message":  message,
        }

    def _dedup_result(self, build_id: str, dedup_hit: dict) -> dict:
        audit.log("fix_deduplicated", build_id=build_id,
                  original_build=dedup_hit.get("original_build"),
                  colour=dedup_hit.get("colour"))
        self.engine.advance(build_id, WorkflowStatus.BLOCKED)
        return {
            "build_id":       build_id,
            "status":         "BLOCKED",
            "colour":         dedup_hit.get("colour", "RED"),
            "deduplicated":   True,
            "original_build": dedup_hit.get("original_build"),
            "cache_age_min":  dedup_hit.get("cache_age_min"),
            "message":        "Identical error was already processed recently.",
        }

    async def _finalise(
        self, client, build_id, repo, analysis, fix, verdict, elapsed_s: int = 0,
        original_code: str = "",
    ) -> dict:
        """Apply traffic-light decision: PR + merge / PR + Slack / BLOCKED."""
        colour = verdict.get("status", "RED")
        pr_url = ""
        files_for_pr = analysis["affected_files"] or fix.get("files_to_modify", [])

        # Run static bug scanner on the original (buggy) code for detailed findings
        scan_findings = []
        parse_error   = ""
        if original_code:
            scan_result = BugPatternScanner.scan(original_code)
            parse_error = scan_result.parse_error  # non-empty when syntax error
            scan_findings = [
                {
                    "pattern":    f.pattern,
                    "line":       f.line,
                    "message":    f.message,
                    "severity":   f.severity,
                    "suggestion": f.suggestion,
                }
                for f in scan_result.findings
            ]

        report_data = {
            "colour":         colour,
            "confidence":     fix.get("confidence", 0.0),
            "elapsed_s":      elapsed_s,
            "error_type":     str(analysis.get("error_type", "")),
            "blast_radius":   str(analysis.get("blast_radius", "")),
            "root_cause":     analysis.get("root_cause", ""),
            "explanation":    fix.get("explanation", ""),
            "all_affected_files": analysis.get("affected_files", []),
            "fix_strategy":   fix.get("fix_strategy", ""),
            "bug_list":       fix.get("bug_list", []),
            "bug_count":      (
                len(fix.get("bugs_found", []))
                or len(fix.get("changed_lines", {}))
                or len(scan_findings)
                or fix.get("bug_count", 0)
            ),
            "attempts":       fix.get("attempts", 1),
            "model_used":     fix.get("model_used", ""),
            "bandit_issues":  fix.get("bandit_issues", []),
            "regression_risk": fix.get("regression_risk", ""),
            "test_hints":     fix.get("test_hints", []),
            "complexity":     fix.get("complexity", ""),
            "original_code":  original_code,
            "scan_findings":  scan_findings,
            "parse_error":    parse_error,
            "cleaned_logs":   fix.get("cleaned_logs", analysis.get("root_cause", "")),
            "changed_lines":  fix.get("changed_lines", {}),
            "bugs_found":     fix.get("bugs_found", []),
        }

        if colour in ("GREEN", "YELLOW"):
            # Human-in-the-Loop: both GREEN and YELLOW require explicit human
            # approval before merging. The colour signals review urgency, not
            # autonomous action — GREEN = fast-track review, YELLOW = careful review.
            self.engine.advance(build_id, WorkflowStatus.AWAITING_REVIEW)
            if repo:
                pr_data = await self._create_github_pr_with_number(
                    client, build_id, repo, fix["fix_patch"],
                    files_for_pr, auto_merge=False, report_data=report_data,
                )
                pr_url = pr_data.get("pr_url", "")
                await send_slack_review_buttons(
                    build_id=build_id,
                    pr_url=pr_url,
                    pr_number=pr_data.get("pr_number", 0),
                    repo=repo,
                    score=fix["confidence"],
                    explanation=fix.get("explanation", ""),
                    report_data={**report_data, "fix_patch": fix.get("fix_patch", "")},
                )
            heal_verifier.record_fix(build_id, files_for_pr)
        else:
            self.engine.advance(build_id, WorkflowStatus.BLOCKED)

        final_status = self.engine.get(build_id).status.value

        dedup_cache.record(
            error_type=analysis["error_type"],
            root_cause=analysis.get("root_cause", ""),
            affected_files=analysis["affected_files"],
            build_id=build_id,
            colour=colour,
            pr_url=pr_url,
        )

        try:
            fix_memory.record(
                error_type=analysis["error_type"],
                root_cause=analysis.get("root_cause", ""),
                affected_files=analysis["affected_files"],
                fix_patch=fix.get("fix_patch", ""),
                outcome=colour,
                confidence=fix.get("confidence", 0.0),
                explanation=fix.get("explanation", ""),
                build_id=build_id,
                pr_url=pr_url,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("fix_memory_record_failed build_id=%s error=%s", build_id, exc)

        audit.log(
            "pipeline_complete",
            build_id=build_id, colour=colour, final_status=final_status,
            final_score=verdict.get("final_score"), pr_url=pr_url,
            files=files_for_pr,
        )
        logger.info(
            "pipeline_complete build_id=%s verdict=%s final=%s pr_url=%s",
            build_id, colour, final_status, pr_url,
        )
        return {
            "build_id":    build_id,
            "status":      final_status,
            "colour":      colour,
            "final_score": verdict.get("final_score"),
            "notified":    verdict.get("notified", False),
            "pr_url":      pr_url,
        }
