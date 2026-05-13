"""PipelineFinaliseMixin — report_data assembly, PR creation, and result builders."""
from __future__ import annotations

import logging

from src.shared.audit_log import audit
from src.shared.fix_memory import fix_memory
from src.shared.heal_verifier import heal_verifier
from src.shared.models import WorkflowStatus
from src.notification_mcp.slack_notifier import send_slack_review_buttons
from src.orchestrator_mcp.deduplication import dedup_cache
from src.llm_mcp.bug_scanner import BugPatternScanner

logger = logging.getLogger(__name__)


class PipelineFinaliseMixin:
    """Assembles report_data, creates the GitHub PR, and returns the final result dict."""

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
        self,
        client,
        build_id: str,
        repo: str,
        analysis: dict,
        fix: dict,
        verdict: dict,
        elapsed_s: int = 0,
        original_code: str = "",
    ) -> dict:
        """Apply traffic-light decision: create PR, notify Slack, record memory."""
        colour       = verdict.get("status", "RED")
        pr_url       = ""
        files_for_pr = analysis["affected_files"] or fix.get("files_to_modify", [])

        scan_findings = []
        parse_error   = ""
        if original_code:
            scan_result = BugPatternScanner.scan(original_code)
            parse_error = scan_result.parse_error
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

        bugs_found_final = fix.get("bugs_found", [])
        if not bugs_found_final:
            if parse_error:
                import re as _re_pm
                line_m = _re_pm.search(r"line[:\s]+(\d+)", parse_error, _re_pm.IGNORECASE)
                line_hint = f" (line {line_m.group(1)})" if line_m else ""
                bugs_found_final = [f"Syntax error{line_hint}: {parse_error[:200]}"]
            elif analysis.get("root_cause"):
                bugs_found_final = [str(analysis["root_cause"])[:200]]
        diff_bug_count = len(bugs_found_final)

        report_data = {
            "colour":            colour,
            "confidence":        fix.get("confidence", 0.0),
            "elapsed_s":         elapsed_s,
            "error_type":        str(analysis.get("error_type", "")),
            "blast_radius":      str(analysis.get("blast_radius", "")),
            "root_cause":        analysis.get("root_cause", ""),
            "explanation":       fix.get("explanation", ""),
            "all_affected_files": analysis.get("affected_files", []),
            "fix_strategy":      fix.get("fix_strategy", ""),
            "bug_list":          fix.get("bug_list", []),
            "verdict_reason":    verdict.get("reason", ""),
            "final_score":       verdict.get("final_score", fix.get("confidence", 0.0)),
            "arch_layer":        analysis.get("arch_layer", "UNKNOWN"),
            "arch_confidence":   analysis.get("arch_confidence", 0.0),
            "arch_risk_note":    analysis.get("arch_risk_note", ""),
            "arch_sub_layer":    analysis.get("arch_sub_layer", ""),
            "arch_framework":    analysis.get("arch_framework", ""),
            "arch_language":     analysis.get("arch_language", ""),
            "arch_runtime":      analysis.get("arch_runtime", ""),
            "arch_cross_layers": analysis.get("arch_cross_layers", []),
            "arch_tags":         analysis.get("arch_tags", []),
            "arch_severity":     analysis.get("arch_severity", 0.0),
            "bug_count":         diff_bug_count or len(bugs_found_final),
            "attempts":          fix.get("attempts", 1),
            "model_used":        fix.get("model_used", ""),
            "bandit_issues":     fix.get("bandit_issues", []),
            "regression_risk":   fix.get("regression_risk", ""),
            "test_hints":        fix.get("test_hints", []),
            "complexity":        fix.get("complexity", ""),
            "original_code":     original_code,
            "scan_findings":     scan_findings,
            "parse_error":       parse_error,
            "cleaned_logs":      fix.get("cleaned_logs", analysis.get("root_cause", "")),
            "changed_lines":     fix.get("changed_lines", {}),
            "bugs_found":        bugs_found_final,
        }

        if colour in ("GREEN", "YELLOW"):
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
            heal_verifier.record_fix(
                build_id, files_for_pr,
                error_type=str(analysis.get("error_type", "")),
            )
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
