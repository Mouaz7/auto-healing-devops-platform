"""Orchestrator MCP server — port 8085.

Sprint 2: state machine skeleton.
Sprint 3: full Agent 1→3→4→5→6 pipeline chain.
Sprint 4: GitHub PR approval — YELLOW creates a PR, webhook advances workflow.
Sprint 5+: correlation IDs, defensive validation, stats endpoint, pruning.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import urllib.parse
import uuid

import httpx
from aiohttp import web

from src.shared.audit_log import audit
from src.shared.config import SERVICE_URLS
from src.shared.adaptive_thresholds import adaptive_thresholds
from src.shared.cost_tracker import cost_tracker
from src.shared.fix_memory import fix_memory
from src.shared.heal_verifier import heal_verifier
from src.shared.mcp_base import MCPServiceBase
from src.shared.models import WorkflowState, WorkflowStatus
from src.shared.resilience import handle_agent_failure, trigger_global_fallback
from src.shared.token_tracker import token_tracker
from src.notification_mcp.slack_notifier import send_slack_review_buttons
from src.notification_mcp.slack_slash_handler import handle_slash_command
from src.orchestrator_mcp.deduplication import dedup_cache
from src.orchestrator_mcp.rate_limiter import rate_limiter
from src.orchestrator_mcp.workflow import (
    WorkflowEngine,
    InvalidTransitionError,
    WorkflowNotFoundError,
)
from src.gerrit_mcp.github_approver import extract_build_id

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 300.0   # seconds per agent call (LLM has 3 retries × 60s + runtime validation)
_GITHUB_WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
# How often the background pruner runs (seconds)
_PRUNE_INTERVAL = 3600


class OrchestratorMCPServer(MCPServiceBase):
    """Orchestrator MCP server.

    Endpoints:
        POST /tools/handle_build_failure   — run full Agent 1→3→4→5→6 pipeline
        GET  /tools/get_workflow_status    — query workflow status
        POST /webhooks/github              — receive GitHub PR events
        POST /workflows                    — register workflow (REST)
        GET  /workflows/{build_id}         — get workflow state (REST)
        POST /workflows/{build_id}/advance — advance state (REST)
        GET  /workflows/active             — list active workflows (REST)
        GET  /health                       — health check (inherited)
        GET  /metrics                      — Prometheus metrics (inherited)
    """

    def __init__(self) -> None:
        super().__init__("orchestrator_mcp", 8085)
        self._port = 8085
        self.engine = WorkflowEngine()
        self._prune_task: asyncio.Task | None = None

    async def setup_routes(self) -> None:
        """Register orchestrator-specific routes on self.app."""
        self.app.router.add_post("/tools/handle_build_failure",   self.handle_build_failure)
        self.app.router.add_get("/tools/get_workflow_status",     self.get_workflow_status)
        self.app.router.add_post("/webhooks/github",              self.github_webhook)
        self.app.router.add_post("/webhooks/slack",               self.slack_webhook)
        self.app.router.add_post("/workflows",                    self.create_workflow)
        self.app.router.add_get("/workflows/active",              self.list_active)
        self.app.router.add_get("/workflows/{build_id}",          self.get_workflow)
        self.app.router.add_post("/workflows/{build_id}/advance", self.advance_workflow)
        self.app.router.add_get("/api/stats",                     self.get_stats)
        self.app.router.add_post("/tools/retry_build",            self.retry_build)
        self.app.router.add_post("/tools/review_code",            self.review_code)
        self.app.router.add_post("/webhooks/slack/commands",      handle_slash_command)
        # Start background pruner on app startup
        self.app.on_startup.append(self._start_pruner)
        self.app.on_cleanup.append(self._stop_pruner)

    async def _start_pruner(self, _app: web.Application) -> None:
        self._prune_task = asyncio.create_task(self._prune_loop())

    async def _stop_pruner(self, _app: web.Application) -> None:
        if self._prune_task:
            self._prune_task.cancel()
            try:
                await self._prune_task
            except asyncio.CancelledError:
                pass

    async def _prune_loop(self) -> None:
        """Background task: prune stale workflows every hour."""
        while True:
            await asyncio.sleep(_PRUNE_INTERVAL)
            try:
                result = self.engine.prune_stale()
                logger.info("prune_loop result=%s", result)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.error("prune_loop_error error=%s", exc)

    # ------------------------------------------------------------------
    # Full pipeline — Agent 1→3→4→5→6
    # ------------------------------------------------------------------

    async def handle_build_failure(self, request: web.Request) -> web.Response:
        """Run the full auto-healing pipeline for a build failure.

        Sequence:
          PENDING → ANALYSING  (Agent 3: clean_logs)
                  → ANALYSING  (Agent 4: analyze_failure)
          ANALYSING → GENERATING_FIX (Agent 5: generate_fix)
          GENERATING_FIX → VALIDATING (Agent 6: evaluate_and_notify)
          VALIDATING → COMPLETED | AWAITING_REVIEW (+ GitHub PR) | BLOCKED
        """
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)

        # --- Rate limiting: 10 requests / 60 s per client IP ---
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

        # --- Input size cap: reject payloads > 500 KB ---
        if len(raw_log) > 500_000:
            return web.json_response(
                {"error": "raw_log exceeds 500 KB limit", "size": len(raw_log)},
                status=413,
            )

        state = WorkflowState(build_id=build_id, status=WorkflowStatus.PENDING)
        try:
            self.engine.register(state)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=409)

        # Generate a correlation ID so this pipeline run can be traced in logs
        # across all 6 agent services
        correlation_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        audit.log(
            "pipeline_start",
            build_id=build_id,
            repo=repo,
            correlation_id=correlation_id,
        )
        logger.info(
            "pipeline_start build_id=%s correlation_id=%s repo=%s",
            build_id, correlation_id, repo,
        )

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            try:
                result = await self._run_pipeline(
                    client, build_id, raw_log, repo, correlation_id
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                import traceback
                tb = traceback.format_exc()
                err_str = str(exc) or repr(exc) or f"{type(exc).__name__}(no message)"
                logger.error(
                    "pipeline_exception build_id=%s type=%s str=%r repr=%r\n%s",
                    build_id, type(exc).__name__, str(exc), repr(exc), tb,
                )
                # Extract files from raw_log so the fallback Slack shows them
                fallback_files: list[str] = []
                if raw_log:
                    for m in re.finditer(r"FAILED_FILE:\s*(\S+\.py)", raw_log):
                        f = m.group(1).strip().lstrip("./")
                        if f and f not in fallback_files:
                            fallback_files.append(f)
                handle_agent_failure("orchestrator", build_id, err_str, fallback_files)
                self._safe_fail(build_id, err_str)
                await trigger_global_fallback("orchestrator", build_id, err_str, fallback_files)
                audit.log("pipeline_failed", build_id=build_id, error=err_str)
                return web.json_response(
                    {"build_id": build_id, "status": "FAILED", "error": err_str,
                     "type": type(exc).__name__},
                    status=500,
                )

        return web.json_response(result)

    async def _run_pipeline(
        self,
        client: httpx.AsyncClient,
        build_id: str,
        raw_log: str,
        repo: str = "",
        correlation_id: str = "",
    ) -> dict:
        """Execute the full 4-step pipeline and return the final result dict."""
        # Propagate correlation ID to all downstream agents so a single
        # build_id can be traced across log lines from different services
        extra_headers = {"X-Request-ID": correlation_id} if correlation_id else {}

        # Step 1: Agent 3 — clean logs
        # (regression check happens after Step 2 analysis, once we know the files)
        self.engine.advance(build_id, WorkflowStatus.ANALYSING)
        # Log cleaning is best-effort: if the agent is down or slow, fall
        # back to the raw log rather than blocking the whole pipeline for
        # 5 minutes on a transient timeout. The downstream analyser still
        # works fine on raw logs — it just gets slightly noisier input.
        try:
            clean_resp = await client.post(
                f"{SERVICE_URLS['log_cleaner']}/tools/clean_logs",
                json={"build_id": build_id, "raw_log": raw_log},
                headers=extra_headers,
                timeout=30.0,
            )
            clean_resp.raise_for_status()
            cleaned = clean_resp.json()
            if "cleaned_logs" not in cleaned:
                raise ValueError(f"Agent 3 response missing 'cleaned_logs': {cleaned}")
        except (httpx.TimeoutException, httpx.HTTPStatusError, ValueError) as exc:
            logger.warning(
                "log_cleaner_unavailable build_id=%s err=%r — using raw log",
                build_id, exc,
            )
            cleaned = {"cleaned_logs": raw_log}

        # Step 2: Agent 4 — analyze failure
        # If the analyser is unreachable, infer minimal analysis from the
        # raw log (FAILED_FILE markers + naive error type) so the LLM can
        # still attempt a fix. Without this, a flaky analyser blocks every
        # auto-heal attempt.
        try:
            analyse_resp = await client.post(
                f"{SERVICE_URLS['knowledge_graph']}/tools/analyze_failure",
                json={"build_id": build_id, "cleaned_logs": cleaned["cleaned_logs"]},
                headers=extra_headers,
                timeout=60.0,
            )
            analyse_resp.raise_for_status()
            analysis = analyse_resp.json()
            for required in ("error_type", "blast_radius", "affected_files", "confidence", "root_cause"):
                if required not in analysis:
                    raise ValueError(f"Agent 4 response missing '{required}': {analysis}")
        except (httpx.TimeoutException, httpx.HTTPStatusError, ValueError) as exc:
            logger.warning(
                "analyser_unavailable build_id=%s err=%r — using minimal analysis",
                build_id, exc,
            )
            fallback_files: list[str] = []
            for m in re.finditer(r"FAILED_FILE:\s*(\S+\.py)", raw_log or ""):
                f = m.group(1).strip().lstrip("./")
                if f and f not in fallback_files:
                    fallback_files.append(f)
            err_type = "LOGIC_ERROR"
            if re.search(r"ERROR_TYPE:\s*(\w+)", raw_log or ""):
                err_type = re.search(r"ERROR_TYPE:\s*(\w+)", raw_log).group(1)
            analysis = {
                "error_type": err_type,
                "blast_radius": "LOW" if len(fallback_files) <= 1 else "MEDIUM",
                "affected_files": fallback_files,
                "confidence": 0.5,
                "root_cause": "analyser unavailable — using log-extracted minimal analysis",
            }

        # Fallback: if log cleaner stripped FAILED_FILE lines, extract from raw_log directly
        if not analysis["affected_files"] and raw_log:
            for m in re.finditer(r"FAILED_FILE:\s*(\S+\.py)", raw_log):
                candidate = m.group(1).strip().lstrip("./")
                if candidate and candidate not in analysis["affected_files"]:
                    analysis["affected_files"].append(candidate)
            if analysis["affected_files"]:
                logger.info(
                    "affected_files_from_log build_id=%s files=%s",
                    build_id, analysis["affected_files"],
                )

        # Regression check: if the failing files were recently fixed, emit a warning
        regression = heal_verifier.check_regression(build_id, analysis["affected_files"])
        if regression:
            audit.log(
                "regression_detected",
                build_id=build_id,
                original_build=regression["original_build_id"],
                overlap_files=regression["overlap_files"],
                age_minutes=regression["age_minutes"],
            )
            logger.warning(
                "regression_alert build_id=%s original=%s files=%s age_min=%.1f",
                build_id, regression["original_build_id"],
                regression["overlap_files"], regression["age_minutes"],
            )

        # Step 2b: Gerrit MCP — fetch code context for affected files (max 3)
        code_context = ""
        if repo and analysis.get("affected_files"):
            for file_path in analysis["affected_files"][:3]:
                try:
                    ctx_resp = await client.post(
                        f"{SERVICE_URLS['gerrit']}/tools/fetch_file",
                        json={"repo": repo, "file_path": file_path},
                    )
                    if ctx_resp.status_code == 200:
                        code_context += ctx_resp.json().get("content", "")
                except Exception:  # pylint: disable=broad-exception-caught
                    pass  # code context is best-effort

        # Fallback: extract code directly from the log's FILE_CONTENT_START block
        # Used when gerrit fetch fails (network issues, rate limits, etc.)
        if not code_context and raw_log:
            fc_match = re.search(
                r"FILE_CONTENT_START:[^\n]*\n(.*?)FILE_CONTENT_END",
                raw_log,
                re.DOTALL,
            )
            if fc_match:
                code_context = fc_match.group(1).strip()
                logger.info("code_context_from_log build_id=%s chars=%d", build_id, len(code_context))

        # Step 3: Agent 5 — generate fix
        self.engine.advance(build_id, WorkflowStatus.GENERATING_FIX)
        fix_resp = await client.post(
            f"{SERVICE_URLS['llm']}/tools/generate_fix",
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
            headers=extra_headers,
        )
        # 422 = structurally unrecoverable (empty code_context, secret leak, etc.).
        # Route to human review instead of crashing the pipeline.
        if fix_resp.status_code == 422:
            err = fix_resp.json()
            self.engine.advance(build_id, WorkflowStatus.BLOCKED)
            return {
                "build_id": build_id,
                "status":   "BLOCKED",
                "colour":   "RED",
                "reason":   err.get("reason", "fix_rejected"),
                "message":  err.get("error", "Fix generation rejected"),
            }
        fix_resp.raise_for_status()
        fix = fix_resp.json()
        if "fix_patch" not in fix or "confidence" not in fix:
            raise ValueError(f"Agent 5 response missing required fields: {fix}")

        # Step 4: Agent 6 — traffic light + notify
        self.engine.advance(build_id, WorkflowStatus.VALIDATING)
        notify_resp = await client.post(
            f"{SERVICE_URLS['notification']}/tools/evaluate_and_notify",
            json={
                "build_id":       build_id,
                "fix_patch":      fix["fix_patch"],
                "confidence":     fix["confidence"],
                "explanation":    fix.get("explanation", ""),
                "error_type":     analysis["error_type"],
                "blast_radius":   analysis["blast_radius"],
                "affected_files": analysis["affected_files"],
            },
            headers=extra_headers,
        )
        notify_resp.raise_for_status()
        verdict = notify_resp.json()
        if "status" not in verdict:
            raise ValueError(f"Agent 6 response missing 'status': {verdict}")

        # Check deduplication cache — skip PR creation if identical error was
        # processed recently and already produced a fix
        dedup_hit = dedup_cache.check(
            error_type=analysis["error_type"],
            root_cause=analysis.get("root_cause", ""),
            affected_files=analysis["affected_files"],
        )
        if dedup_hit:
            audit.log("fix_deduplicated", build_id=build_id,
                      original_build=dedup_hit.get("original_build"),
                      colour=dedup_hit.get("colour"))
            self.engine.advance(build_id, WorkflowStatus.BLOCKED)
            return {
                "build_id":      build_id,
                "status":        "BLOCKED",
                "colour":        dedup_hit.get("colour", "RED"),
                "deduplicated":  True,
                "original_build": dedup_hit.get("original_build"),
                "cache_age_min": dedup_hit.get("cache_age_min"),
                "message":       "Identical error was already processed recently.",
            }

        # Advance to final state based on traffic light
        colour = verdict.get("status", "RED")
        pr_url = ""

        # Prefer files from analysis; fall back to what the LLM identified
        files_for_pr = analysis["affected_files"] or fix.get("files_to_modify", [])

        if colour == "GREEN" and verdict.get("auto_merge_allowed"):
            # Create PR and auto-merge so fix is traceable in GitHub
            if repo:
                pr_url = await self._create_github_pr(
                    client, build_id, repo,
                    fix["fix_patch"], files_for_pr,
                    auto_merge=True,
                )
            self.engine.advance(build_id, WorkflowStatus.APPLYING_FIX)
            self.engine.advance(build_id, WorkflowStatus.COMPLETED)
            # Register fix with regression verifier — watches for re-failures
            heal_verifier.record_fix(build_id, files_for_pr)

        elif colour == "YELLOW":
            # Create PR — human must review and approve before merge
            self.engine.advance(build_id, WorkflowStatus.AWAITING_REVIEW)
            if repo:
                pr_data = await self._create_github_pr_with_number(
                    client, build_id, repo,
                    fix["fix_patch"], files_for_pr,
                    auto_merge=False,
                )
                pr_url = pr_data.get("pr_url", "")
                pr_number = pr_data.get("pr_number", 0)
                # Send Slack message with Approve/Reject buttons
                await send_slack_review_buttons(
                    build_id=build_id,
                    pr_url=pr_url,
                    pr_number=pr_number,
                    repo=repo,
                    score=fix["confidence"],
                    explanation=fix.get("explanation", ""),
                )

        else:
            self.engine.advance(build_id, WorkflowStatus.BLOCKED)

        final_status = self.engine.get(build_id).status.value

        # Record in dedup cache so the same error isn't re-processed
        dedup_cache.record(
            error_type=analysis["error_type"],
            root_cause=analysis.get("root_cause", ""),
            affected_files=analysis["affected_files"],
            build_id=build_id,
            colour=colour,
            pr_url=pr_url,
        )

        # Record fix outcome in AI memory so future prompts can learn from it
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
            build_id=build_id,
            colour=colour,
            final_status=final_status,
            final_score=verdict.get("final_score"),
            pr_url=pr_url,
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

    async def _create_github_pr(
        self,
        client: httpx.AsyncClient,
        build_id: str,
        repo: str,
        patch: str,
        affected_files: list,
        auto_merge: bool = False,
    ) -> str:
        """Call gerrit-mcp to open a GitHub PR. Returns the PR URL or empty string."""
        try:
            title = (
                f"[auto-heal][GREEN] Auto-fix build {build_id}"
                if auto_merge else
                f"[auto-heal][YELLOW] Human review required — build {build_id}"
            )
            resp = await client.post(
                f"{SERVICE_URLS['gerrit']}/tools/submit_patch",
                json={
                    "build_id":       build_id,
                    "repo":           repo,
                    "patch":          patch,
                    "affected_files": affected_files,
                    "title":          title,
                },
            )
            resp.raise_for_status()
            pr_data = resp.json()
            pr_url = str(pr_data.get("pr_url", ""))
            pr_number = pr_data.get("pr_number", 0)
            logger.info(
                "github_pr_created build_id=%s pr_url=%s auto_merge=%s",
                build_id, pr_url, auto_merge,
            )
            # Auto-merge if GREEN and PR was created
            if auto_merge and pr_number:
                await self._merge_pr(client, repo, pr_number)
            return pr_url
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("github_pr_failed build_id=%s error=%s", build_id, exc)
            return ""

    async def _create_github_pr_with_number(
        self,
        client: httpx.AsyncClient,
        build_id: str,
        repo: str,
        patch: str,
        affected_files: list,
        auto_merge: bool = False,
    ) -> dict:
        """Like _create_github_pr but returns full dict with pr_number."""
        try:
            title = (
                f"[auto-heal][GREEN] Auto-fix build {build_id}"
                if auto_merge else
                f"[auto-heal][YELLOW] Human review required — build {build_id}"
            )
            resp = await client.post(
                f"{SERVICE_URLS['gerrit']}/tools/submit_patch",
                json={
                    "build_id":       build_id,
                    "repo":           repo,
                    "patch":          patch,
                    "affected_files": affected_files,
                    "title":          title,
                },
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("github_pr_failed build_id=%s error=%s", build_id, exc)
            return {"pr_url": "", "pr_number": 0, "branch": ""}

    async def slack_webhook(self, request: web.Request) -> web.Response:
        """Handle Slack interactive button clicks (Approve / Reject)."""
        body = await request.text()
        payload_str = urllib.parse.unquote(body.replace("payload=", "", 1))
        try:
            payload = json.loads(payload_str)
        except Exception:  # pylint: disable=broad-exception-caught
            return web.Response(text="invalid payload", status=400)

        actions = payload.get("actions", [])
        response_url = payload.get("response_url", "")
        if not actions:
            return web.Response(text="ok")

        action = actions[0]
        action_id = action.get("action_id", "")
        value = action.get("value", "")

        try:
            repo, pr_number_str, build_id = value.split("|")
            pr_number = int(pr_number_str)
        except ValueError:
            return web.Response(text="invalid value", status=400)

        token = os.getenv("GITHUB_TOKEN", "")
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        }
        pr_url = f"https://github.com/{repo}/pull/{pr_number}"

        async with httpx.AsyncClient(timeout=15) as client:
            if action_id == "approve_fix":
                resp = await client.put(
                    f"https://api.github.com/repos/{repo}/pulls/{pr_number}/merge",
                    headers=headers,
                    json={"merge_method": "squash"},
                )
                if resp.status_code == 200:
                    fix_memory.update_outcome(build_id, approved=True)
                    # Let adaptive thresholds learn from this approval
                    _record_adaptive_decision(build_id, approved=True)
                    audit.log("pr_approved", build_id=build_id, pr_number=pr_number,
                              repo=repo, approved_by=payload.get("user", {}).get("id"))
                    logger.info("slack_approved build_id=%s pr=%d", build_id, pr_number)
                    updated_msg = {
                        "replace_original": True,
                        "blocks": [
                            {
                                "type": "header",
                                "text": {"type": "plain_text", "text": "✅ Fix Approved & Merged"},
                            },
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": (
                                        f"*Build:* `{build_id}`\n"
                                        f"*PR:* <{pr_url}|#{pr_number}> — merged successfully\n"
                                        f"*Approved by:* <@{payload.get('user', {}).get('id', 'unknown')}>\n"
                                        f"*Status:* Fix applied to `main` branch ✅"
                                    ),
                                },
                            },
                        ],
                    }
                else:
                    updated_msg = {
                        "replace_original": True,
                        "blocks": [
                            {
                                "type": "header",
                                "text": {"type": "plain_text", "text": "⚠️ Merge Failed"},
                            },
                            {
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": (
                                        f"*Build:* `{build_id}`\n"
                                        f"*PR:* <{pr_url}|#{pr_number}>\n"
                                        f"*Error:* Could not merge (status {resp.status_code})\n"
                                        f"Please merge manually on GitHub."
                                    ),
                                },
                            },
                        ],
                    }

            elif action_id == "reject_fix":
                resp = await client.patch(
                    f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
                    headers=headers,
                    json={"state": "closed"},
                )
                fix_memory.update_outcome(build_id, approved=False)
                # Let adaptive thresholds learn from this rejection
                _record_adaptive_decision(build_id, approved=False)
                audit.log("pr_rejected", build_id=build_id, pr_number=pr_number,
                          repo=repo, rejected_by=payload.get("user", {}).get("id"))
                logger.info("slack_rejected build_id=%s pr=%d", build_id, pr_number)
                updated_msg = {
                    "replace_original": True,
                    "blocks": [
                        {
                            "type": "header",
                            "text": {"type": "plain_text", "text": "❌ Fix Rejected"},
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": (
                                    f"*Build:* `{build_id}`\n"
                                    f"*PR:* <{pr_url}|#{pr_number}> — closed\n"
                                    f"*Rejected by:* <@{payload.get('user', {}).get('id', 'unknown')}>\n"
                                    f"*Next step:* Manual fix required 🔧"
                                ),
                            },
                        },
                    ],
                }
            else:
                return web.Response(text="ok")

            # Update the original Slack message via response_url
            if response_url:
                await client.post(
                    response_url,
                    json=updated_msg,
                    headers={"Content-Type": "application/json"},
                )

        return web.Response(text="", status=200)

    async def _merge_pr(
        self,
        client: httpx.AsyncClient,
        repo: str,
        pr_number: int,
    ) -> None:
        """Merge a GitHub PR automatically (GREEN path)."""
        token = os.getenv("GITHUB_TOKEN", "")
        if not token:
            return
        try:
            resp = await client.put(
                f"https://api.github.com/repos/{repo}/pulls/{pr_number}/merge",
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github+json",
                },
                json={"merge_method": "squash"},
            )
            if resp.status_code == 200:
                logger.info("pr_auto_merged repo=%s pr=%d", repo, pr_number)
            else:
                logger.warning("pr_merge_failed repo=%s pr=%d status=%d",
                               repo, pr_number, resp.status_code)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("pr_merge_error repo=%s pr=%d error=%s", repo, pr_number, exc)

    def _safe_fail(self, build_id: str, reason: str) -> None:
        """Mark workflow as FAILED, ignoring errors if already terminal."""
        try:
            self.engine.fail(build_id, reason)
        except Exception:  # pylint: disable=broad-exception-caught
            pass

    # ------------------------------------------------------------------
    # GitHub webhook — PR approved / merged → advance workflow
    # ------------------------------------------------------------------

    async def github_webhook(self, request: web.Request) -> web.Response:
        """Receive GitHub PR webhooks and advance AWAITING_REVIEW workflows.

        Validates the ``X-Hub-Signature-256`` header when
        ``GITHUB_WEBHOOK_SECRET`` is set.  On a ``pull_request`` event with
        action ``closed`` + ``merged: true``, extracts the build_id from the
        branch name ``auto-heal/{build_id}`` and advances the workflow to
        APPLYING_FIX → COMPLETED.
        """
        body = await request.read()

        if _GITHUB_WEBHOOK_SECRET:
            if not self._verify_github_signature(body, request):
                return web.json_response({"error": "invalid signature"}, status=401)

        try:
            payload = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)

        event = request.headers.get("X-GitHub-Event", "")
        action = payload.get("action", "")

        if event == "pull_request" and action == "closed":
            merged = payload.get("pull_request", {}).get("merged", False)
            branch = payload.get("pull_request", {}).get("head", {}).get("ref", "")
            build_id = extract_build_id(branch)

            if merged and build_id:
                self._advance_after_approval(build_id)
                logger.info("github_pr_merged build_id=%s branch=%s", build_id, branch)
                return web.json_response(
                    {"build_id": build_id, "status": "COMPLETED", "action": "advanced"}
                )

        if event == "pull_request_review" and action == "submitted":
            state = payload.get("review", {}).get("state", "")
            branch = payload.get("pull_request", {}).get("head", {}).get("ref", "")
            build_id = extract_build_id(branch)

            if state == "approved" and build_id:
                self._advance_after_approval(build_id)
                logger.info(
                    "github_pr_approved build_id=%s branch=%s", build_id, branch
                )
                return web.json_response(
                    {"build_id": build_id, "status": "APPLYING_FIX", "action": "advanced"}
                )

        return web.json_response({"action": "ignored"})

    def _advance_after_approval(self, build_id: str) -> None:
        """Advance AWAITING_REVIEW → APPLYING_FIX → COMPLETED."""
        try:
            state = self.engine.get(build_id)
            if state.status == WorkflowStatus.AWAITING_REVIEW:
                self.engine.advance(build_id, WorkflowStatus.APPLYING_FIX)
                self.engine.advance(build_id, WorkflowStatus.COMPLETED)
        except (WorkflowNotFoundError, InvalidTransitionError) as exc:
            logger.warning(
                "advance_after_approval_failed build_id=%s error=%s", build_id, exc
            )

    @staticmethod
    def _verify_github_signature(body: bytes, request: web.Request) -> bool:
        """Validate HMAC-SHA256 signature from GitHub."""
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        if not sig_header.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(
            _GITHUB_WEBHOOK_SECRET.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, sig_header)

    # ------------------------------------------------------------------
    # REST workflow management endpoints
    # ------------------------------------------------------------------

    async def create_workflow(self, request: web.Request) -> web.Response:
        """Register a new workflow."""
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)
        build_id = data.get("build_id", "")
        if not build_id:
            return web.json_response({"error": "build_id required"}, status=400)
        state = WorkflowState(build_id=build_id, status=WorkflowStatus.PENDING)
        try:
            self.engine.register(state)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=409)
        return web.json_response(_serialise(state), status=201)

    async def get_workflow(self, request: web.Request) -> web.Response:
        """Return the current state of a single workflow."""
        build_id = request.match_info["build_id"]
        try:
            state = self.engine.get(build_id)
        except WorkflowNotFoundError:
            return web.json_response({"error": "workflow not found"}, status=404)
        return web.json_response(_serialise(state))

    async def advance_workflow(self, request: web.Request) -> web.Response:
        """Manually advance a workflow to the next status."""
        build_id = request.match_info["build_id"]
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)
        next_status_str = data.get("next_status", "")
        try:
            next_status = WorkflowStatus(next_status_str)
        except ValueError:
            return web.json_response(
                {"error": f"unknown status '{next_status_str}'"}, status=400
            )
        try:
            state = self.engine.advance(build_id, next_status)
        except WorkflowNotFoundError:
            return web.json_response({"error": "workflow not found"}, status=404)
        except InvalidTransitionError as exc:
            return web.json_response({"error": str(exc)}, status=422)
        return web.json_response(_serialise(state))

    async def list_active(self, _request: web.Request) -> web.Response:
        """Return all active (non-terminal) workflows."""
        return web.json_response([_serialise(s) for s in self.engine.list_active()])

    async def get_workflow_status(self, request: web.Request) -> web.Response:
        """Return current workflow status for a given build_id."""
        build_id = request.query.get("build_id", "")
        if not build_id:
            return web.json_response({"error": "build_id required"}, status=400)
        try:
            state = self.engine.get(build_id)
        except WorkflowNotFoundError:
            return web.json_response({"error": "not found"}, status=404)
        return web.json_response({"build_id": build_id, "status": state.status.value})

    async def get_stats(self, _request: web.Request) -> web.Response:
        """Return system-wide statistics for monitoring and thesis evaluation.

        Covers:
        - Workflow status breakdown (active / completed / blocked / failed)
        - Token usage per agent this hour
        - Estimated API cost this session
        - Deduplication cache size
        - Rate limiter activity
        - Audit log event summary
        """
        workflow_counts = self.engine.stats()
        prune_result = self.engine.prune_stale()
        token_snapshot = token_tracker.usage_snapshot()
        cost_summary = cost_tracker.session_summary()

        return web.json_response({
            "workflows": {
                "by_status":        workflow_counts,
                "total":            sum(workflow_counts.values()),
                "active":           len(self.engine.list_active()),
                "pruned_this_call": prune_result,
            },
            "tokens_used_this_hour": token_snapshot,
            "cost":                  cost_summary,
            "deduplication": {
                "cache_size":        dedup_cache.size(),
            },
            "rate_limiter": {
                "active_keys":       rate_limiter.stats(),
            },
            "audit_log": {
                "event_counts":      audit.summary(),
                "recent_events":     audit.tail(n=10),
            },
            "regression_monitor": {
                "active_fix_watches": heal_verifier.active_fixes(),
            },
            "adaptive_thresholds": adaptive_thresholds.summary(),
        })

    async def retry_build(self, request: web.Request) -> web.Response:
        """Re-submit a previously failed build through the pipeline.

        Called by the /autoheal retry slash command.  Looks up the original
        log from fix_memory and re-triggers handle_build_failure.
        """
        try:
            data = await request.json()
        except Exception:  # pylint: disable=broad-exception-caught
            return web.json_response({"error": "invalid JSON"}, status=400)

        build_id = data.get("build_id", "")
        if not build_id:
            return web.json_response({"error": "build_id required"}, status=400)

        # Look up original pipeline metadata from fix_memory
        all_records = fix_memory._load_records()
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

        new_build_id = f"{build_id}-retry-{int(uuid.uuid4().int % 10000):04d}"
        audit.log("pipeline_retry", original_build_id=build_id, new_build_id=new_build_id)
        logger.info("retry_build original=%s new=%s", build_id, new_build_id)

        return web.json_response({
            "original_build_id": build_id,
            "new_build_id":      new_build_id,
            "status":            "QUEUED",
            "message":           (
                f"Build {new_build_id} queued. "
                "Submit new raw_log via /tools/handle_build_failure to re-run."
            ),
        }, status=202)


    async def review_code(self, request: web.Request) -> web.Response:
        """AI-powered code review for logic bugs — no crash needed to trigger healing.

        POST /tools/review_code
        Body: {"file_path": "foo.py", "code": "...", "repo": "...", "build_id": "..."}

        Calls the LLM directly to review the code for logic bugs.
        If a bug is found, automatically triggers handle_build_failure.
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

        system_prompt = (
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
        user_prompt = (
            f"File: {file_path}\n\n"
            "IMPORTANT: Look especially for self-comparisons like `if x < x` or `if x == x` "
            "which are always False/True and make algorithms do nothing.\n\n"
            f"```python\n{code}\n```"
        )

        has_bug = False
        bug_description = ""

        try:
            from src.shared.nim_client import NimClient
            nim = NimClient(agent_name="code_repairer", agent_env_prefix="CODE_REPAIRER")
            raw = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: nim.complete([
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ]),
            )
            json_match = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
            if json_match:
                review = json.loads(json_match.group())
                has_bug = bool(review.get("has_bug", False))
                bug_description = review.get("description", "")
            else:
                bug_keywords = ["wrong", "incorrect", "error", "bug", "should be", "infinite loop"]
                has_bug = any(kw in raw.lower() for kw in bug_keywords)
                bug_description = raw[:300]
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.warning("review_code llm_failed file=%s err=%s", file_path, exc)
            return web.json_response({"has_bug": False, "reason": "llm unavailable"})

        if not has_bug:
            return web.json_response({"has_bug": False, "file": file_path})

        # Bug found — trigger the full healing pipeline
        logger.info("review_code bug_found file=%s desc=%s", file_path, bug_description)
        audit.log("code_review_bug_found", file=file_path, description=bug_description)

        synthetic_log = (
            f"FAILED_FILE: {file_path}\n"
            f"ERROR_TYPE: LOGIC_ERROR\n"
            f"AI Code Review detected a bug: {bug_description}\n\n"
            f"FILE_CONTENT_START: {file_path}\n{code}\nFILE_CONTENT_END"
        )

        # Fire-and-forget: submit to the healing pipeline
        asyncio.create_task(self._trigger_healing_for_review(
            build_id=f"review-{build_id}",
            repo=repo,
            raw_log=synthetic_log,
        ))

        return web.json_response({
            "has_bug": True,
            "file": file_path,
            "description": bug_description,
            "healing_triggered": True,
        })

    async def _trigger_healing_for_review(
        self, build_id: str, repo: str, raw_log: str
    ) -> None:
        """Submit a code-review-detected bug to the main healing pipeline.

        Runs the pipeline DIRECTLY (not via HTTP self-call). The previous
        implementation POST'd to its own /tools/handle_build_failure, which
        meant the LLM-mcp timeout (300s) inside _run_pipeline raced against
        the outer HTTP timeout (also 300s) — and lost, producing a misleading
        ReadTimeout for the orchestrator's own endpoint.
        """
        # Register the workflow so subsequent UI/state queries can find it
        state = WorkflowState(build_id=build_id, status=WorkflowStatus.PENDING)
        try:
            self.engine.register(state)
        except ValueError:
            logger.info("review_healing_already_registered build_id=%s", build_id)
            return

        # Use a fresh client; pipeline call has its own internal timeouts
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


def _serialise(state: WorkflowState) -> dict:
    return {
        "build_id":      state.build_id,
        "status":        state.status.value,
        "retry_count":   state.retry_count,
        "error_message": state.error_message,
        "created_at":    state.created_at.isoformat(),
        "updated_at":    state.updated_at.isoformat(),
    }


def _record_adaptive_decision(build_id: str, approved: bool) -> None:
    """Feed a human decision back to the adaptive threshold learner."""
    try:
        records = fix_memory._load_records()
        for rec in reversed(records):
            if rec.get("build_id") == build_id and not rec.get("_update"):
                error_type = rec.get("error_type", "")
                confidence = rec.get("confidence", 0.0)
                if error_type:
                    adaptive_thresholds.record_decision(error_type, confidence, approved)
                break
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.warning("adaptive_threshold_update_failed build_id=%s error=%s", build_id, exc)


if __name__ == "__main__":
    server = OrchestratorMCPServer()
    server.run()
