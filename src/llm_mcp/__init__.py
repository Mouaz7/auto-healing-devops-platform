# Agent 5: Code Repairer — Port 8086
# Implementeras i Sprint 3 — se .agents/workflows/sprint-3-intelligence.md
#
# Filer att skapa:
#   prompt_templates.py — SYSTEM_PROMPT, SCENARIO_A/B templates, few-shot examples
#   fix_generator.py    — FixGenerator (fallback chain, max 50 lines, 2 retries, 60s timeout)
#   quality_check.py    — run Bandit+Pylint before fix is submitted
#   summary_writer.py   — generate_summary()
#   server.py           — LLMMCPServer
#   tools.py            — MCP tool definitions
#
# State ut: { build_id, fix_patch, lint_ok, test_ok }
