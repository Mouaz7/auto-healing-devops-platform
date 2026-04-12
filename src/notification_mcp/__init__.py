# Agent 6: Review & Notify — Port 8087
# Implementeras i Sprint 3 — se .agents/workflows/sprint-3-intelligence.md
#
# Filer att skapa:
#   traffic_light_evaluator.py — evaluate_traffic_light() (score formula + safety override)
#   teams_notifier.py          — send_teams_notification() (fixed Adaptive Card templates)
#   slack_notifier.py          — send_slack_notification() (fixed Block Kit templates)
#   server.py                  — NotificationMCPServer
#   tools.py                   — MCP tool definitions
#
# State ut: { build_id, status: GREEN|YELLOW|RED, notified: true }
