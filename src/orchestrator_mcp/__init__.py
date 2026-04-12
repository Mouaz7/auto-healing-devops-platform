# Orchestrator MCP — Port 8085 — Central workflow coordinator
# Sprint 2: skeleton (Agent 1+3 chain)
# Sprint 3: full pipeline (Agent 1->3->4->5->6)
# Sprint 4: scenarios A/B + global fallback
# Se .agents/workflows/sprint-2-core-services.md
#
# Filer att skapa:
#   workflow.py        — WorkflowEngine (state machine, VALID_TRANSITIONS)
#   traffic_light.py   — placeholder Sprint 2, full in Sprint 3
#   scenario_router.py — ScenarioRouter (Scenario A/B/YELLOW)
#   server.py          — OrchestratorMCPServer
#   tools.py           — MCP tool definitions
