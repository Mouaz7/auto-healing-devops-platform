"""PR body builder — assembles the full GitHub PR markdown from report_data."""
from __future__ import annotations

from src.gerrit_mcp.pr_bug_table import annotate_original, build_bug_table

_ARCH_LAYER_LABEL: dict[str, str] = {
    "FRONTEND": "🎨 Frontend",
    "BACKEND":  "⚙️ Backend",
    "DATABASE": "🗄️ Database",
    "INFRA":    "🐳 Infra",
    "TESTS":    "🧪 Tests",
    "MOBILE":   "📱 Mobile",
    "DATA_ML":  "🧠 Data/ML",
    "UNKNOWN":  "❓ Unknown",
}


def build_pr_body(
    rd: dict,
    patch: str,
    build_id: str,
    affected_files: list[str],
    original_code: str = "",
) -> str:
    """Return the full GitHub PR body as a markdown string."""
    colour        = rd.get("colour", "")
    score         = round(float(rd.get("confidence", 0)) * 100)
    elapsed       = rd.get("elapsed_s", 0)
    error_t       = rd.get("error_type", "")
    blast         = rd.get("blast_radius", "")
    root_c        = rd.get("root_cause", "")
    expl          = rd.get("explanation", "")
    fix_strategy  = rd.get("fix_strategy", "")
    scan_findings = rd.get("scan_findings", [])
    parse_error   = rd.get("parse_error", "")
    attempts      = rd.get("attempts", 1)
    model_used    = rd.get("model_used", "AI model")
    bandit_issues = rd.get("bandit_issues", [])
    regression    = rd.get("regression_risk", "")
    test_hints    = rd.get("test_hints", [])
    all_files     = rd.get("all_affected_files", affected_files)
    changed_lines = rd.get("changed_lines", {})
    bugs_found    = rd.get("bugs_found", [])
    bug_count     = (
        rd.get("bug_count", 0)
        or len(bugs_found)
        or len(scan_findings)
        or len(changed_lines)
        or len(rd.get("bug_list", []))
    )

    dur            = f"{elapsed // 60}m {elapsed % 60}s" if elapsed >= 60 else (f"{elapsed}s" if elapsed else "—")
    emoji          = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(colour, "🤖")
    colour_label   = {
        "GREEN":  "GREEN — High Confidence",
        "YELLOW": "YELLOW — Manual Review Required",
        "RED":    "RED — Blocked",
    }.get(colour, colour)
    bar_fill       = {"GREEN": "🟩", "YELLOW": "🟨", "RED": "🟥"}.get(colour, "🟩")
    confidence_bar = bar_fill * (score // 10) + "⬜" * (10 - score // 10)
    files_str      = "\n".join(f"  - `{f}`" for f in all_files) or "  - _(unknown)_"
    bandit_str     = "\n".join(f"  - {b}" for b in bandit_issues) if bandit_issues else "  ✅ No security issues found"
    test_str       = "\n".join(f"  - {t}" for t in test_hints) if test_hints else "  _(no specific test hints)_"

    arch_label = _ARCH_LAYER_LABEL.get(rd.get("arch_layer", "UNKNOWN"), "❓ Unknown")
    arch_line  = (
        f"{arch_label} ({int(rd.get('arch_confidence', 0) * 100)}% conf)"
        + (f" · {rd['arch_sub_layer']}"                            if rd.get("arch_sub_layer")   else "")
        + (f" · {rd['arch_framework']}"                            if rd.get("arch_framework")   else "")
        + (f" · {rd['arch_language']}"                             if rd.get("arch_language")    else "")
        + (f" on {rd['arch_runtime']}"                             if rd.get("arch_runtime")     else "")
        + (f" · 🔗 also: {', '.join(rd['arch_cross_layers'])}"    if rd.get("arch_cross_layers") else "")
        + (f" · ⚠️ +{int(rd['arch_severity'] * 100)}% risk"       if rd.get("arch_severity", 0) >= 0.15 else "")
    )

    orig_lines_list = original_code.splitlines() if original_code else []
    bug_table_str, bug_details_str = build_bug_table(
        changed_lines, scan_findings, bugs_found, orig_lines_list, parse_error, root_c,
    )

    orig_full       = annotate_original(orig_lines_list, patch) if orig_lines_list else "# (original code unavailable)"
    patch_lines_all = patch.splitlines()
    patch_full      = "\n".join(patch_lines_all[:80])
    if len(patch_lines_all) > 80:
        patch_full += f"\n# ... ({len(patch_lines_all) - 80} more lines)"

    return (
        f"{emoji} **Auto-Heal Fix** — build `{build_id}`\n\n"
        f"> **Status:** {colour_label} | **Confidence:** {score}% `{confidence_bar}`\n\n"
        f"---\n\n"

        f"## 📊 Summary\n\n"
        f"| Field | Value |\n"
        f"|-------|-------|\n"
        f"| **Build ID** | `{build_id}` |\n"
        f"| **Traffic Light** | {emoji} {colour_label} |\n"
        f"| **Confidence Score** | {score}% {confidence_bar} |\n"
        f"| **Decision Reason** | {rd.get('verdict_reason') or '—'} |\n"
        f"| **Architecture Layer** | {arch_line} |\n"
        f"| **Error Type** | `{error_t}` |\n"
        f"| **Blast Radius** | `{blast or '—'}` |\n"
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
        f"## 🐛 Bug Report — {bug_count} bug(s) with exact line numbers\n\n"
        f"{bug_table_str}\n\n"

        + (
            f"---\n\n"
            f"## 🔄 Bug Details — What Changed (Bug → Fix per line)\n\n"
            f"{bug_details_str}\n\n"
            if bug_details_str else ""
        )

        + f"---\n\n"
        f"## 🛠️ Fix Strategy & Explanation\n\n"
        f"{fix_strategy or expl or '_(no strategy provided)_'}\n\n"
        f"### Detailed Explanation\n"
        f"{expl or '_(no explanation)_'}\n\n"

        f"---\n\n"
        f"## 📁 Affected Files\n\n"
        f"{files_str}\n\n"

        f"---\n\n"
        f"## 🔄 Full File — Before vs After\n\n"
        f"<details><summary>▶ Show ORIGINAL (buggy) file</summary>\n\n"
        f"```python\n{orig_full}\n```\n"
        f"</details>\n\n"
        f"<details><summary>▶ Show FIXED file</summary>\n\n"
        f"```python\n{patch_full}\n```\n"
        f"</details>\n\n"

        f"---\n\n"
        f"## 🔒 Security Analysis (Bandit)\n\n"
        f"{bandit_str}\n\n"

        f"---\n\n"
        f"## ⚠️ Regression Risk\n\n"
        f"{regression or rd.get('arch_risk_note') or '_(no regression risk identified)_'}\n\n"

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
