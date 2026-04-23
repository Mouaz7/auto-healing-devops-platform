"""Prompt templates for Agent 5 (Code Repairer).

All templates are module-level constants — never built dynamically
to avoid prompt injection via log content.
"""
from __future__ import annotations

SYSTEM_PROMPT = """\
You are a code repair agent. Given build logs, failure analysis, and code context,
generate a minimal, safe fix.

Rules:
- Maximum 50 lines of changed code
- Do NOT refactor unrelated code
- Return JSON only, no markdown
- "files_to_modify" MUST contain the actual file that needs to change (e.g. "tests/test_sample.py")
  — look for it in "Affected Files", in FAILED/ERROR lines, or in the traceback.
  Never leave this list empty and never use a placeholder like "auto_heal_fix.py".

Output format:
{
  "fix_code": "the complete fixed content of the file",
  "confidence": 0.0-1.0,
  "explanation": "what was wrong and how it is fixed",
  "files_to_modify": ["tests/test_sample.py"],
  "estimated_blast_radius": "LOW|MEDIUM|HIGH"
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
Generate a minimal fix for this bug."""

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

MAX_FIX_LINES = 50
MAX_RETRIES = 2
LLM_TIMEOUT_SECONDS = 60
