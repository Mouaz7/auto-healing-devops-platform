"""Prompt templates for Agent 5 (Code Repairer).

All templates are module-level constants — never built dynamically
to avoid prompt injection via log content.
"""
from __future__ import annotations

SYSTEM_PROMPT = """\
You are a code repair agent. Fix bugs by specifying EXACT line-level edits —
never rewrite entire files or functions.

PRIMARY OUTPUT: `changed_lines` — a map of line numbers to new content.
The system will apply these edits to the original file. Everything else stays identical.

Rules:
- SURGICAL: modify only the broken line(s), typically 1–3 lines
- Line numbers are 1-based (first line of file = 1)
- Do NOT rename variables, reformat, refactor, or "improve" anything
- Do NOT change logic unrelated to the error
- "files_to_modify" MUST name the actual file from the error log

Output JSON:
{
  "changed_lines": {"14": "      right = mid - 1"},
  "fix_code": "(full file content — only used if changed_lines is empty)",
  "confidence": 0.0-1.0,
  "explanation": "One sentence: what was broken and what you changed",
  "files_to_modify": ["tests/test_sample.py"],
  "estimated_blast_radius": "LOW|MEDIUM|HIGH"
}

EXAMPLE — bug: `right = left + -1` on line 14 should be `right = mid - 1`:
{
  "changed_lines": {"14": "      right = mid - 1"},
  "explanation": "Line 14 used 'left + -1' which excludes mid from the search range; changed to 'mid - 1'",
  "files_to_modify": ["tests/test_kram.py"],
  "confidence": 0.92,
  "estimated_blast_radius": "LOW"
}"""

SCENARIO_A_TEMPLATE = """\
Error Analysis:
- Error Type: {error_type}
- Root Cause: {root_cause}
- Affected Files: {affected_files}

Cleaned Build Logs:
{cleaned_logs}

Code Context:
{code_context}
{memory_context}

CRITICAL: Generate ONLY the minimal fix. Do NOT:
  ✗ Rename variables
  ✗ Refactor logic
  ✗ Add new functions
  ✗ Rewrite docstrings
  ✗ Change indentation unnecessarily
  ✗ Optimize unrelated code

DO:
  ✓ Fix the specific error (typo, wrong operator, missing colon, etc)
  ✓ Change ONLY the broken lines
  ✓ Keep everything else exactly as-is"""

SCENARIO_B_TEMPLATE = """\
Task Description:
{task_description}

Existing Code Context:
{code_context}

Generate code to implement this feature. Keep it minimal."""

# Few-shot examples prepended to the user message for context calibration
FEW_SHOT_EXAMPLES: list[dict[str, str]] = [
    {
        "error": "ImportError: cannot import name 'Validator' from 'utils'",
        "context": "# utils.py\nclass InputValidator:\n    pass",
        "fix": "from utils import InputValidator  # Was: from utils import Validator",
    },
    {
        "error": "SyntaxError: expected ':'",
        "context": "def process(data: str) -> dict\n    return {}",
        "fix": "def process(data: str) -> dict:\n    return {}",
    },
]

MAX_FIX_LINES = 20  # Strict limit: most bug fixes are 1-5 lines, 20 is already generous
MAX_RETRIES = 2
LLM_TIMEOUT_SECONDS = 60
