# Auto-Healing AI DevOps Platform
[![Built with Claude Code](https://img.shields.io/badge/Built%20with-Claude%20Code-orange?logo=anthropic)](https://claude.ai/code)

> Automated Remediation in CI/CD: Design and Control of an AI-based Code Repair Agent

## Vision

Transform CI/CD build failures from developer interruptions into autonomous, AI-driven resolutions — using a pipeline of 6 specialised AI agents with built-in safety, fallback logic, and token budget control.

## 6-Agent Pipeline Architecture

```
CI/CD Webhook (Jenkins/GitHub Actions)
       │
       ▼
┌──────────────────┐
│ Agent 1:          │
│ Pipeline Monitor  │──→ Dubblettfiltrering via set(build_id)
└────────┬─────────┘
         ▼
┌──────────────────┐
│ Agent 2:          │
│ Task Inspector    │──→ Scenario A (bugg) / B (feature) / YELLOW (manuell)
└────────┬─────────┘
         ▼
┌──────────────────┐
│ Agent 3:          │
│ Log Analyst       │──→ 97% logg-reduktion (regex + LLM fallback)
└────────┬─────────┘
         ▼
┌──────────────────┐
│ Agent 4:          │
│ Error Analyst     │──→ Feltyp + blast radius (LOW/MEDIUM/HIGH)
└────────┬─────────┘
         ▼
┌──────────────────┐
│ Agent 5:          │
│ Code Repairer     │──→ Kodfix + Pylint/Bandit check
└────────┬─────────┘
         ▼
┌──────────────────┐
│ Agent 6:          │
│ Review & Notify   │──→ Traffic Light (GREEN/YELLOW/RED) + notifiering
└──────────────────┘
```

### Agent Overview

| # | Agent | MCP Service | Port | Token Limit/req |
|---|-------|-------------|------|-----------------|
| 1 | Pipeline Monitor | jenkins-mcp | 8082 | 500 |
| 2 | Task Inspector | scheduler | — | 1 000 |
| 3 | Log Analyst | log-cleaner-mcp | 8081 | 2 000 |
| 4 | Error Analyst | knowledge-graph-mcp | 8084 | 3 000 |
| 5 | Code Repairer | llm-mcp | 8086 | 4 000 |
| 6 | Review & Notify | notification-mcp | 8087 | 2 000 |

### Fallback & Resilience

- **Modell-fallback:** Varje agent har 4 modellslots (primär + 3 reserv). Om primär modell misslyckas → automatisk fallback.
- **Token-budget:** Max tokens per request och per timme per agent. Varning vid 80%, hård stopp vid 100%.
- **Global fallback:** Om NÅGON agent kraschar → hela pipelinen sätts till RED → Agent 6 notifierar → människa tar över.

### Traffic Light Safety System

| Colour | Threshold | Action |
|--------|-----------|--------|
| GREEN | >= 85% | Auto-merge |
| YELLOW | 60-84% | Human review required |
| RED | < 60% | Blocked |

**Safety Override:** blast_radius == HIGH → alltid RED, oavsett score.

## Technology Stack

- **Language:** Python 3.11+
- **Protocol:** MCP (Model Context Protocol)
- **HTTP:** httpx (async client), aiohttp (async server)
- **Data Models:** Pydantic v2
- **Quality:** Pylint, Bandit, Black, isort
- **Testing:** pytest, pytest-asyncio
- **Containers:** Docker, Docker Compose
- **Monitoring:** Prometheus, structlog
- **Token Counting:** tiktoken

## Setup

```bash
# Clone the repository
git clone <repo-url>
cd Exsamen

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies (dev mode)
pip install -e ".[dev]"

# Copy and configure environment
cp .env.example .env
# Edit .env with your model choices and API keys

# Run tests
python -m pytest tests/ -v

# Run linting
pylint src/
bandit -r src/

# Run all services
docker compose up --build

# Run demo (requires services running)
python scripts/demo.py

# Expose orchestrator publicly via ngrok (required for GitHub Actions)
# Terminal 1: keep docker compose running
# Terminal 2: run ngrok
ngrok http --url=washhouse-shopper-retry.ngrok-free.dev 8085
# Public URL: https://washhouse-shopper-retry.ngrok-free.dev
```

## Project Structure

```
Exsamen/
├── pyproject.toml              # Python build config + dependencies
├── Dockerfile                  # Multi-stage Docker build
├── docker-compose.yml          # All 7 services + scheduler
├── .env.example                # Environment template (model config + token limits)
├── .gitignore
├── .pre-commit-config.yaml
│
├── src/
│   ├── shared/                 # Shared infrastructure
│   │   ├── models.py           # Domain models (BuildEvent, TrafficLightResult, etc.)
│   │   ├── config.py           # Agent model config + token limits
│   │   ├── mcp_base.py         # Base MCP server class
│   │   ├── model_fallback.py   # Fallback logic (primary → FB1 → FB2 → FB3)
│   │   ├── token_tracker.py    # Token counting per agent per hour
│   │   ├── resilience.py       # Circuit breaker + global fallback
│   │   ├── quality_gates.py    # Bandit + Pylint runners
│   │   ├── logging_setup.py    # Structured logging + correlation IDs
│   │   └── metrics.py          # Prometheus metrics
│   │
│   ├── jenkins_mcp/            # Agent 1: Pipeline Monitor (port 8082)
│   ├── log_cleaner_mcp/        # Agent 3: Log Analyst (port 8081)
│   │   └── filters/            # Regex filter pipeline
│   ├── knowledge_graph_mcp/    # Agent 4: Error Analyst (port 8084)
│   ├── llm_mcp/                # Agent 5: Code Repairer (port 8086)
│   ├── notification_mcp/       # Agent 6: Review & Notify (port 8087)
│   ├── gerrit_mcp/             # Code fetch + patch submit (port 8083)
│   ├── orchestrator_mcp/       # Central workflow (port 8085)
│   │   ├── workflow.py         # State machine
│   │   ├── traffic_light.py    # Confidence scoring
│   │   ├── scenario_router.py  # Scenario A/B routing
│   │   └── task_inspector.py   # Agent 2: Task classification
│   └── scheduler/              # Cron-based monitoring
│
├── tests/
│   ├── conftest.py             # Shared fixtures
│   ├── fixtures/               # Sample Jenkins logs
│   ├── unit/                   # Per-agent unit tests
│   └── integration/            # End-to-end pipeline tests
│
├── docs/
│   ├── architecture/           # arc42, C4, ADRs
│   ├── thesis/chapters/        # Thesis chapters (MD)
│   └── interviews/             # Interview guide + transcripts
│
├── scripts/                    # Demo + utility scripts
└── .agents/workflows/          # Sprint plans + agent plan
```

## Authors

- Ahmad Darwich (ahda23@student.bth.se)
- Mouaz Naji (moap23@student.bth.se)

## Supervisor

Ahmad Nauman Ghazi (nauman.ghazi@bth.se)

## Licence

This project is part of a bachelor thesis at Blekinge Tekniska Hogskola (BTH).
