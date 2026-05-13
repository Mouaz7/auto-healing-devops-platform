"""PipelineStepsMixin — individual agent steps, diff engine, and regression guard."""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

from src.shared.audit_log import audit
from src.shared import config as _config
from src.shared.config import GERRIT_FETCH_TIMEOUT, LLM_FIX_TIMEOUT
from src.shared.heal_verifier import heal_verifier
from src.shared.models import WorkflowStatus
from src.notification_mcp.slack_notifier import send_slack_notification
from src.orchestrator_mcp.deduplication import dedup_cache
from src.orchestrator_mcp.pipeline_helpers import (
    build_minimal_analysis,
    extract_code_from_log,
    extract_failed_files,
)

logger = logging.getLogger(__name__)


class PipelineStepsMixin:
    """Agent steps (clean → analyse → fetch → generate → notify), diff engine, regression guard."""

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

        from src.shared.architecture_classifier import classify as _classify_layer
        layer_result = _classify_layer(
            affected_files=analysis.get("affected_files", []),
            code_context=code_context,
            error_message=cleaned or str(analysis.get("root_cause", "") or ""),
        )
        analysis["arch_layer"]        = layer_result.layer.value
        analysis["arch_confidence"]   = layer_result.confidence
        analysis["arch_risk_note"]    = layer_result.risk_note
        analysis["arch_fix_hint"]     = layer_result.fix_hint
        analysis["arch_sub_layer"]    = layer_result.sub_layer
        analysis["arch_framework"]    = layer_result.framework
        analysis["arch_language"]     = layer_result.language
        analysis["arch_runtime"]      = layer_result.runtime
        analysis["arch_cross_layers"] = layer_result.cross_layers or []
        analysis["arch_tags"]         = layer_result.tags or []
        analysis["arch_severity"]     = layer_result.severity_boost
        logger.info(
            "arch_layer_classified build_id=%s layer=%s sub=%s framework=%s confidence=%.2f",
            build_id, layer_result.layer.value, layer_result.sub_layer,
            layer_result.framework, layer_result.confidence,
        )

        fix = await self._step_generate_fix(
            client, build_id, analysis, cleaned, code_context, headers,
        )
        if fix is None:
            elapsed_s = round(time.monotonic() - started_at)
            files_str = ", ".join(analysis.get("affected_files", []))
            asyncio.create_task(send_slack_notification(
                "RED", build_id, 0.0,
                "Fix generation rejected (422) — change is too complex or structurally "
                "unrecoverable. Manual intervention required.",
                files_str, elapsed_s=elapsed_s,
            ))
            return self._blocked_result(build_id, "fix_rejected", "Fix generation rejected")

        # Override bugs_found and changed_lines with the diff-based authoritative versions.
        # Both are keyed by ORIGINAL line numbers so they stay aligned in the PR report.
        diff_bugs, diff_changed_lines = self._compute_diff_bugs(
            code_context, fix.get("fix_patch", "")
        )
        if diff_bugs:
            fix["bugs_found"]     = diff_bugs
            fix["changed_lines"]  = diff_changed_lines

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
            client, build_id, repo, analysis, fix, verdict,
            elapsed_s=elapsed_s, original_code=code_context,
        )

    # ------------------------------------------------------------------
    # Individual agent steps
    # ------------------------------------------------------------------

    async def _step_clean_logs(self, client, build_id, raw_log, headers) -> dict:
        """Agent 3 — clean logs. Falls back to raw log on failure."""
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

    async def _step_analyse(self, client, build_id, raw_log, cleaned, headers) -> dict:
        """Agent 4 — analyse failure. Falls back to log-extracted analysis on failure."""
        try:
            resp = await client.post(
                f"{_config.SERVICE_URLS['knowledge_graph']}/tools/analyze_failure",
                json={"build_id": build_id, "cleaned_logs": cleaned["cleaned_logs"]},
                headers=headers,
                timeout=120.0,
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

        if not analysis["affected_files"]:
            extra = extract_failed_files(raw_log)
            if extra:
                analysis["affected_files"].extend(extra)
                logger.info(
                    "affected_files_from_log build_id=%s files=%s",
                    build_id, analysis["affected_files"],
                )
        return analysis

    async def _step_fetch_context(self, client, repo: str, analysis: dict, raw_log: str) -> str:
        """Fetch code context from GitHub (max 3 files, in parallel)."""
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
                    continue
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
                "arch_layer":     analysis.get("arch_layer", "UNKNOWN"),
                "arch_fix_hint":  analysis.get("arch_fix_hint", ""),
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
                "bugs_found":     fix.get("bugs_found", []),
                "elapsed_s":      elapsed_s,
            },
            headers=headers,
        )
        resp.raise_for_status()
        verdict = resp.json()
        if "status" not in verdict:
            raise ValueError(f"Agent 6 response missing 'status': {verdict}")
        return verdict

    # ------------------------------------------------------------------
    # Diff engine
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_diff_bugs(
        original_code: str, fix_patch: str
    ) -> tuple[list[str], dict[str, str]]:
        """Compute the authoritative bug list — one entry per changed line.

        Returns:
            bugs          — descriptions keyed to ORIGINAL line numbers.
            changed_lines — str(orig_lineno) → cleaned fixed line, aligned with bugs.
        """
        if not original_code or not fix_patch:
            return [], {}
        import re as _re_d
        import difflib as _difflib
        _autoheal_strip = _re_d.compile(r"\s*#\s*AUTO-HEAL:\s*(.*)$")

        def _norm(ln: str) -> str:
            return _re_d.sub(r"\s+", " ", ln.strip())

        def _tokenize(ln: str) -> list[str]:
            return _re_d.findall(r"\w+|[^\w\s]", ln)

        orig_raw = original_code.splitlines()
        fix_raw  = fix_patch.splitlines()

        fix_norm_to_raw: dict[str, str] = {}
        autoheal_map: dict[str, str] = {}
        fix_norm_all: list[str] = []
        for ln in fix_raw:
            ah_m  = _autoheal_strip.search(ln)
            clean = _autoheal_strip.sub("", ln).strip()
            n     = _norm(clean)
            if n:
                fix_norm_all.append(n)
                if n not in fix_norm_to_raw:
                    fix_norm_to_raw[n] = clean
                if ah_m:
                    autoheal_map[n] = ah_m.group(1).strip()
        fix_norm_set = set(fix_norm_all)

        bugs: list[str] = []
        changed_lines: dict[str, str] = {}

        for orig_lineno, orig_line in enumerate(orig_raw, 1):
            if not orig_line.strip():
                continue
            orig_n = _norm(orig_line)
            if orig_n in fix_norm_set:
                continue

            matches   = _difflib.get_close_matches(orig_n, fix_norm_all, n=1, cutoff=0.3)
            best_norm = matches[0] if matches else ""
            fixed_display = fix_norm_to_raw.get(best_norm, "")

            orig_tokens = _tokenize(orig_line.strip())
            fix_tokens  = _tokenize(best_norm)
            sm = _difflib.SequenceMatcher(None, orig_tokens, fix_tokens)
            token_bugs = sum(1 for tag, *_ in sm.get_opcodes() if tag != "equal") or 1

            stripped = orig_line.strip()
            desc = autoheal_map.get(best_norm, "")
            if not desc:
                orig_tok_set = {t for t in _tokenize(stripped) if len(t) > 2}
                for ah_norm, ah_desc in autoheal_map.items():
                    ah_tok_set = {t for t in _tokenize(ah_desc) if len(t) > 2}
                    if len(orig_tok_set & ah_tok_set) >= 2:
                        desc = ah_desc
                        break
            if not desc:
                desc = f"changed: `{stripped[:80]}`"

            suffix = f" ({token_bugs} changes)" if token_bugs > 1 else ""
            bugs.append(f"Line {orig_lineno}{suffix}: {desc[:160]}")
            changed_lines[str(orig_lineno)] = fixed_display or "_(see fixed file)_"

        return bugs, changed_lines

    # ------------------------------------------------------------------
    # Regression guard
    # ------------------------------------------------------------------

    def _check_regression(self, build_id: str, analysis: dict) -> bool:
        """Return True when a regression loop is detected and the pipeline must stop."""
        regression = heal_verifier.check_regression(build_id, analysis["affected_files"])
        if not regression:
            return False

        original_error = regression.get("error_type", "")
        new_error      = str(analysis.get("error_type", ""))
        retry_count    = regression.get("retry_count", 0)

        if original_error and original_error == new_error and retry_count == 0:
            heal_verifier.increment_retry(regression["original_build_id"])
            logger.info(
                "regression_retry_allowed build_id=%s original=%s error_type=%s",
                build_id, regression["original_build_id"], new_error,
            )
            audit.log(
                "regression_retry_allowed",
                build_id=build_id,
                original_build=regression["original_build_id"],
                error_type=new_error,
                age_minutes=regression["age_minutes"],
            )
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
