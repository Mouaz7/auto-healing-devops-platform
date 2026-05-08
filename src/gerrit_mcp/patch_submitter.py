"""Create GitHub pull requests for auto-generated fixes.

Flow:
  1. Get the current SHA of the target file on the base branch.
  2. Create a new branch  ``auto-heal/{build_id}``.
  3. Commit the fixed file content to that branch.
  4. Open a PR against the base branch.

The branch name encodes the build_id so the orchestrator's GitHub webhook
can recover the build_id when the PR is merged/approved.

Rate-limit handling:
  When GitHub returns 403 with a Retry-After or X-RateLimit-Reset header,
  the client waits the indicated seconds before retrying (capped at 60 s).
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os

import httpx

from src.gerrit_mcp.gerrit_helpers import (
    GITHUB_API,
    MAX_RETRIES,
    RETRY_DELAYS,
    rate_limit_wait,
    sanitize_files,
)

logger = logging.getLogger(__name__)

# Backwards-compat aliases for tests / legacy callers
_GITHUB_API = GITHUB_API
_MAX_RETRIES = MAX_RETRIES
_RETRY_DELAYS = RETRY_DELAYS
_sanitize_files = sanitize_files
_rate_limit_wait = rate_limit_wait


class PatchSubmitter:
    """Submit a code fix as a GitHub pull request."""

    def __init__(self) -> None:
        self._token = os.getenv("GITHUB_TOKEN", "")

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"token {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def create_pr(
        self,
        repo: str,
        build_id: str,
        patch: str,
        affected_files: list[str],
        title: str = "",
        base_branch: str = "main",
        report_data: dict | None = None,
    ) -> dict[str, object]:
        """Create a GitHub PR with the fix.

        Args:
            repo: ``owner/repo`` format.
            build_id: Used as the branch name suffix.
            patch: Fixed file content (output from Agent 5).
            affected_files: Files changed by the fix.
            title: PR title (auto-generated if empty).
            base_branch: Target branch for the PR.

        Returns:
            ``{"pr_url": str, "pr_number": int, "branch": str}``
        """
        if not self._token:
            logger.warning("create_pr skipped — GITHUB_TOKEN not set")
            return {"pr_url": "", "pr_number": 0, "branch": ""}

        branch = f"auto-heal/{build_id}"
        pr_title = title or f"[auto-heal] Fix for build {build_id}"

        # Filter out hallucinated filenames like "<unknown>" that LLMs emit when
        # they can't name a real file. Without this the branch would literally
        # contain a file called "<unknown>".
        sanitized = _sanitize_files(affected_files)
        if not sanitized:
            logger.error(
                "create_pr rejected — no valid affected files (build_id=%s input=%s)",
                build_id, affected_files,
            )
            return {"pr_url": "", "pr_number": 0, "branch": "", "error": "no_target_file"}

        file_path = sanitized[0]
        affected_files = sanitized

        for attempt in range(_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(
                    timeout=15, headers=self._headers
                ) as client:
                    base_sha = await self._get_base_sha(client, repo, base_branch)
                    await self._create_branch(client, repo, branch, base_sha)
                    await self._commit_file(
                        client, repo, branch, file_path, patch,
                        f"auto-heal: fix for build {build_id}",
                    )
                    pr = await self._open_pr(
                        client, repo, pr_title, branch, base_branch,
                        build_id, affected_files, patch, report_data=report_data,
                    )
                    logger.info(
                        "pr_created repo=%s build_id=%s pr_number=%d url=%s",
                        repo, build_id, pr["number"], pr["html_url"],
                    )
                    return {
                        "pr_url":    pr["html_url"],
                        "pr_number": pr["number"],
                        "branch":    branch,
                    }
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 422:
                    # Branch already exists — find the existing PR instead of
                    # returning empty data which would break the Slack buttons
                    logger.warning("branch_exists build_id=%s attempt=%d", build_id, attempt)
                    existing = await self._find_existing_pr(repo, branch, base_branch)
                    return existing or {"pr_url": "", "pr_number": 0, "branch": branch}
                if status in (403, 429):
                    # GitHub rate limit — respect the Retry-After / X-RateLimit-Reset header
                    wait = _rate_limit_wait(exc.response)
                    logger.warning(
                        "github_rate_limited build_id=%s status=%d wait=%.1fs",
                        build_id, status, wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(_RETRY_DELAYS[attempt])
                else:
                    raise

        raise RuntimeError("create_pr: max retries exhausted")

    # ------------------------------------------------------------------
    # Private GitHub API helpers
    # ------------------------------------------------------------------

    async def _find_existing_pr(
        self,
        repo: str,
        head_branch: str,
        base_branch: str,
    ) -> dict | None:
        """Look up an open PR for *head_branch* → *base_branch*.

        Called when branch creation returns 422 (branch already exists) so we
        can return real PR data instead of an empty dict.
        """
        try:
            async with httpx.AsyncClient(timeout=10, headers=self._headers) as client:
                resp = await client.get(
                    f"{_GITHUB_API}/repos/{repo}/pulls",
                    params={"head": f"{repo.split('/')[0]}:{head_branch}", "base": base_branch, "state": "open"},
                )
                if resp.status_code == 200:
                    pulls = resp.json()
                    if pulls:
                        pr = pulls[0]
                        return {
                            "pr_url":    pr["html_url"],
                            "pr_number": pr["number"],
                            "branch":    head_branch,
                        }
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        return None

    async def _get_base_sha(
        self, client: httpx.AsyncClient, repo: str, branch: str
    ) -> str:
        resp = await client.get(
            f"{_GITHUB_API}/repos/{repo}/git/ref/heads/{branch}"
        )
        resp.raise_for_status()
        return str(resp.json()["object"]["sha"])

    async def _create_branch(
        self, client: httpx.AsyncClient, repo: str, branch: str, sha: str
    ) -> None:
        resp = await client.post(
            f"{_GITHUB_API}/repos/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        resp.raise_for_status()

    async def _commit_file(
        self,
        client: httpx.AsyncClient,
        repo: str,
        branch: str,
        file_path: str,
        content: str,
        message: str,
    ) -> None:
        # Get current file SHA (needed for update)
        current_sha = ""
        check = await client.get(
            f"{_GITHUB_API}/repos/{repo}/contents/{file_path}",
            params={"ref": branch},
        )
        if check.status_code == 200:
            current_sha = check.json().get("sha", "")

        body: dict[str, object] = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch":  branch,
        }
        if current_sha:
            body["sha"] = current_sha

        resp = await client.put(
            f"{_GITHUB_API}/repos/{repo}/contents/{file_path}", json=body
        )
        resp.raise_for_status()

    async def _open_pr(
        self,
        client: httpx.AsyncClient,
        repo: str,
        title: str,
        head: str,
        base: str,
        build_id: str,
        affected_files: list[str],
        patch: str,
        report_data: dict | None = None,
    ) -> dict:
        import base64 as _b64

        rd = report_data or {}
        colour        = rd.get("colour", "")
        score         = round(float(rd.get("confidence", 0)) * 100)
        elapsed       = rd.get("elapsed_s", 0)
        error_t       = rd.get("error_type", "")
        blast         = rd.get("blast_radius", "")
        root_c        = rd.get("root_cause", "")
        expl          = rd.get("explanation", "")
        fix_strategy  = rd.get("fix_strategy", "")
        bug_list      = rd.get("bug_list", [])
        scan_findings = rd.get("scan_findings", [])
        bug_count     = rd.get("bug_count", 0) or len(scan_findings) or len(bug_list)
        attempts      = rd.get("attempts", 1)
        model_used    = rd.get("model_used", "AI model")
        bandit_issues = rd.get("bandit_issues", [])
        regression    = rd.get("regression_risk", "")
        test_hints    = rd.get("test_hints", [])
        complexity    = rd.get("complexity", "")
        all_files     = rd.get("all_affected_files", affected_files)
        original_code = rd.get("original_code", "")

        # Fetch original code from GitHub base branch if not already in report_data
        if not original_code and affected_files and self._token:
            try:
                check = await client.get(
                    f"{_GITHUB_API}/repos/{repo}/contents/{affected_files[0]}",
                    params={"ref": base},
                )
                if check.status_code == 200:
                    raw_b64 = check.json().get("content", "").replace("\n", "")
                    original_code = _b64.b64decode(raw_b64).decode("utf-8", errors="replace")
            except Exception:  # pylint: disable=broad-exception-caught
                pass

        dur = f"{elapsed // 60}m {elapsed % 60}s" if elapsed >= 60 else (f"{elapsed}s" if elapsed else "—")
        emoji_map = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}
        emoji = emoji_map.get(colour, "🤖")
        colour_label = {
            "GREEN":  "GREEN — High Confidence",
            "YELLOW": "YELLOW — Manual Review Required",
            "RED":    "RED — Blocked",
        }.get(colour, colour)

        confidence_bar = "█" * (score // 10) + "░" * (10 - score // 10)
        files_str      = "\n".join(f"  - `{f}`" for f in all_files) or "  - _(unknown)_"
        bandit_str     = "\n".join(f"  - {b}" for b in bandit_issues) if bandit_issues else "  ✅ No security issues found"
        test_str       = "\n".join(f"  - {t}" for t in test_hints) if test_hints else "  _(no specific test hints)_"

        # --- Bug table with line numbers and solutions ---
        orig_lines_list = original_code.splitlines() if original_code else []

        if scan_findings:
            sev_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "INFO": "🔵"}
            table_rows = ["| # | Severity | Line | Bug Pattern | Description | Fix |",
                          "|---|----------|------|-------------|-------------|-----|"]
            detail_blocks = []
            for i, f in enumerate(scan_findings, 1):
                icon    = sev_icon.get(f.get("severity", "HIGH"), "🔴")
                sev     = f.get("severity", "HIGH")
                lineno  = f["line"]
                pattern = f["pattern"]
                msg     = f["message"][:80]
                fix_hint= f.get("suggestion", "—")[:80]
                table_rows.append(f"| {i} | {icon} {sev} | `{lineno}` | `{pattern}` | {msg} | {fix_hint} |")

                # Per-bug detail block with actual buggy line of code
                buggy_line_code = ""
                if orig_lines_list and 0 <= lineno - 1 < len(orig_lines_list):
                    buggy_line_code = orig_lines_list[lineno - 1].strip()

                detail_blocks.append(
                    f"**{i}. {icon} Line {lineno} — `{pattern}`** ({sev})\n"
                    f"> {f['message']}\n"
                    + (f"> 💡 **Fix:** {f['suggestion']}\n" if f.get('suggestion') else "")
                    + (f"\n```python\n# Line {lineno} (buggy):\n{buggy_line_code}\n```" if buggy_line_code else "")
                )
            bug_table_str   = "\n".join(table_rows)
            bug_details_str = "\n\n".join(detail_blocks)
        elif bug_list:
            table_rows = ["| # | Description |", "|---|-------------|"]
            table_rows += [f"| {i+1} | {b} |" for i, b in enumerate(bug_list)]
            bug_table_str   = "\n".join(table_rows)
            bug_details_str = ""
        else:
            bug_table_str   = "_No bugs identified by static scanner._"
            bug_details_str = ""

        # --- Before / After code ---
        if orig_lines_list:
            orig_preview = "\n".join(orig_lines_list[:80])
            if len(orig_lines_list) > 80:
                orig_preview += f"\n# ... ({len(orig_lines_list) - 80} more lines)"
        else:
            orig_preview = ""

        patch_lines_all = patch.splitlines()
        new_preview     = "\n".join(patch_lines_all[:80])
        if len(patch_lines_all) > 80:
            new_preview += f"\n# ... ({len(patch_lines_all) - 80} more lines)"

        body = (
            f"{emoji} **Auto-Heal Fix** — build `{build_id}`\n\n"
            f"> **Status:** {colour_label} | **Confidence:** {score}% `{confidence_bar}`\n\n"
            f"---\n\n"

            f"## 📊 Summary\n\n"
            f"| Field | Value |\n"
            f"|-------|-------|\n"
            f"| **Build ID** | `{build_id}` |\n"
            f"| **Confidence Score** | {score}% |\n"
            f"| **Traffic Light** | {emoji} {colour_label} |\n"
            f"| **Error Type** | `{error_t}` |\n"
            f"| **Blast Radius** | `{blast or '—'}` |\n"
            f"| **Complexity** | {complexity or '—'} |\n"
            f"| **Bugs Found** | {bug_count} |\n"
            f"| **AI Attempts** | {attempts} |\n"
            f"| **Model** | `{model_used}` |\n"
            f"| **Time to Fix** | {dur} |\n\n"

            f"---\n\n"
            f"## 🔍 Error Analysis\n\n"
            f"### Root Cause\n"
            f"{root_c or '_(root cause not identified)_'}\n\n"
            f"### Error Type Detail\n"
            f"Error classified as **`{error_t}`**. "
            f"Blast radius (system impact): **{blast or 'unknown'}**.\n\n"

            f"---\n\n"
            f"## 🐛 Bug Report — {bug_count} bug(s) found with exact line numbers\n\n"
            f"{bug_table_str}\n\n"
            + (f"### Detailed Bug Analysis\n\n{bug_details_str}\n\n" if bug_details_str else "")

            + f"---\n\n"
            f"## 🛠️ Fix Strategy & Explanation\n\n"
            f"{fix_strategy or expl or '_(no strategy provided)_'}\n\n"
            f"### Detailed Explanation\n"
            f"{expl or '_(no explanation)_'}\n\n"

            f"---\n\n"
            f"## 📁 Affected Files\n\n"
            f"{files_str}\n\n"

            f"---\n\n"
            f"## 🔄 Code — Before vs After\n\n"
            f"<details><summary>▶ Show ORIGINAL (buggy) code</summary>\n\n"
            f"```python\n{orig_preview if orig_preview else '# (original code unavailable — file may be new or not yet pushed)'}\n```\n"
            f"</details>\n\n"
            f"<details><summary>▶ Show FIXED code</summary>\n\n"
            f"```python\n{new_preview}\n```\n"
            f"</details>\n\n"

            f"---\n\n"
            f"## 🔒 Security Analysis (Bandit)\n\n"
            f"{bandit_str}\n\n"

            f"---\n\n"
            f"## ⚠️ Regression Risk\n\n"
            f"{regression or '_(no regression risk identified)_'}\n\n"

            f"---\n\n"
            f"## 🧪 Test Recommendations\n\n"
            f"{test_str}\n\n"

            f"---\n\n"
            f"## 🤖 Agent Pipeline\n\n"
            f"```\n"
            f"log-cleaner → error-analyst → llm (code-repairer) → notification\n"
            f"     ↓              ↓                  ↓                  ↓\n"
            f"  Cleans        Analyses         Generates fix      Notifies\n"
            f"  logs          root cause       ({attempts} attempt(s))   Slack/GitHub\n"
            f"```\n\n"

            f"---\n\n"
            f"## 📝 Full Patch\n\n"
            f"<details><summary>▶ Show full patch ({len(patch)} chars)</summary>\n\n"
            f"```python\n{patch[:8000]}\n```\n"
            f"{'> _(patch truncated — view file directly for full version)_' if len(patch) > 8000 else ''}"
            f"\n</details>\n\n"

            f"---\n\n"
            f"> 📋 Full report available in `AUTO_HEAL_REPORT.md` in this PR.\n\n"
            f"_Generated by **Auto-Healing AI DevOps Platform** • Build `{build_id}` • Time: {dur}_"
        )
        resp = await client.post(
            f"{_GITHUB_API}/repos/{repo}/pulls",
            json={"title": title, "body": body, "head": head, "base": base},
        )
        resp.raise_for_status()
        return dict(resp.json())
