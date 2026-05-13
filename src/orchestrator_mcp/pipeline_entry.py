"""PipelineEntryMixin — HTTP endpoint, pipeline runners, and exception handling."""
from __future__ import annotations

import asyncio
import logging
import traceback
import uuid

import httpx
from aiohttp import web

from src.shared.audit_log import audit
from src.shared.models import WorkflowState, WorkflowStatus
from src.shared.resilience import handle_agent_failure, trigger_global_fallback
from src.notification_mcp.slack_notifier import send_slack_pipeline_started
from src.orchestrator_mcp.pipeline_helpers import extract_failed_files
from src.orchestrator_mcp.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 300.0


class PipelineEntryMixin:
    """HTTP entry point, sync/background runners, and exception handling."""

    async def handle_build_failure(self, request: web.Request) -> web.Response:
        """POST /tools/handle_build_failure — start the auto-heal pipeline.

        Returns 202 immediately and runs in background by default.
        Pass ``"sync": true`` to block until the pipeline finishes.
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

    async def _run_pipeline_sync(
        self, build_id: str, raw_log: str, repo: str, correlation_id: str,
    ) -> web.Response:
        """Synchronous run — blocks until the pipeline finishes (used by tests and sync=true)."""
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
