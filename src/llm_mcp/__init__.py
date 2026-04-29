# Agent 5: Code Repairer — Port 8086
#
# Modules:
#   prompt_templates.py — SYSTEM_PROMPT, SCENARIO_A_TEMPLATE, COMPLEX_REPAIR_TEMPLATE
#   fix_generator.py    — FixGenerator (NIM fallback chain, dynamic retry budget)
#   fix_validators.py   — syntax + runtime checks (AST, subprocess sandbox)
#   fix_prompts.py      — retry-prompt builder, bug-list extractor
#   fix_parsers.py      — surgical patch + JSON response parser
#   quality_check.py    — Bandit + Pylint run before fix is submitted
#   server.py           — LLMMCPServer
#   tools.py            — MCP tool definitions
#
# Output: { build_id, fix_patch, files_to_modify, confidence, lint_ok, test_ok }
