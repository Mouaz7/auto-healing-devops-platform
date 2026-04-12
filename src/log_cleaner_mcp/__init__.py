# Agent 3: Log Analyst — Port 8081
# Implementeras i Sprint 2 — se .agents/workflows/sprint-2-core-services.md
#
# Filer att skapa:
#   filters/ansi_remover.py        — remove_ansi()
#   filters/timestamp_stripper.py  — strip_timestamps()
#   filters/noise_filter.py        — filter_noise()
#   filters/stack_trace_extractor.py — extract_relevant_lines()
#   filters/deduplicator.py        — deduplicate()
#   pipeline.py                    — clean_logs() -> (str, float)
#   server.py                      — LogCleanerMCPServer
#   tools.py                       — MCP tool definitions
#
# State ut: { build_id, cleaned_logs, reduction_pct }
