# Agent 2: Task Inspector + Scheduler
# Implementeras i Sprint 4 — se .agents/workflows/sprint-4-integration.md
#
# Filer att skapa:
#   task_classifier.py — TaskClassifier (classify A / B / YELLOW)
#   monitor.py         — ScheduledMonitor (polls every 15 min)
#   issue_tracker.py   — fetch/update tasks (GitHub Issues / Jira)
#
# State ut: { build_id, scenario: A|B|YELLOW }
