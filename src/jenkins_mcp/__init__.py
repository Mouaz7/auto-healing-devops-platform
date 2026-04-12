# Agent 1: Pipeline Monitor — Port 8082
# Implementeras i Sprint 2 — se .agents/workflows/sprint-2-core-services.md
#
# Filer att skapa:
#   webhook_handler.py  — WebhookHandler (dedup via set(build_id))
#   log_fetcher.py      — LogFetcher (mock mode + real Jenkins API)
#   server.py           — JenkinsMCPServer
#   tools.py            — MCP tool definitions
#
# State ut: { build_id, repo, branch, timestamp }
