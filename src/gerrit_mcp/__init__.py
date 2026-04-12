# Gerrit/GitHub MCP — Port 8083 — Code fetch + patch submit
# Implementeras i Sprint 4 — se .agents/workflows/sprint-4-integration.md
#
# Filer att skapa:
#   code_fetcher.py    — CodeFetcher (local / github / gerrit mode)
#   patch_submitter.py — PatchSubmitter (retry 3x, delays 1s/2s/4s)
#   server.py          — GerritMCPServer
#   tools.py           — MCP tool definitions
