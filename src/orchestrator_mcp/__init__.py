# Orchestrator MCP — Port 8085 — Central workflow coordinator
#
# Modules:
#   server.py             — OrchestratorMCPServer (thin shell + lifecycle)
#   pipeline_mixin.py     — handle_build_failure + Agent 3→4→5→6 pipeline
#   pipeline_helpers.py   — pure helpers (FAILED_FILE regex, ERROR_TYPE map)
#   github_mixin.py       — PR creation, auto-merge, GitHub webhook
#   slack_mixin.py        — Slack interactive Approve / Reject
#   workflow_api_mixin.py — REST CRUD for workflows
#   admin_mixin.py        — stats, retry, AI code review
#   workflow.py           — WorkflowEngine (state machine, transitions)
#   deduplication.py      — repeat-error guard
#   rate_limiter.py       — per-IP throttle
#   traffic_light.py      — GREEN / YELLOW / RED verdict
#   tools.py              — MCP tool definitions
