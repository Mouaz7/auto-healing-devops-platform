# arc42 Architecture Documentation
## Auto-Healing AI DevOps Platform

---

## 1. Introduction and Goals

**System:** Auto-Healing AI DevOps Platform
**Version:** 1.0.0 (PoC)
**Course:** PA2534 — Kandidatarbete i Programvaruteknik (BTH)

### Purpose
Automatisera CI/CD-buggreparationer med en pipeline av 6 specialiserade AI-agenter. Systemet tar emot build-failures via webhook, analyserar felet, genererar en kodfix, och lämnar in den för granskning — allt utan manuell inblandning.

### Quality Goals

| Prioritet | Mål | Mätvärde |
|-----------|-----|----------|
| 1 | Säkerhet | HIGH blast radius → alltid RED. Människa godkänner alltid merge. |
| 2 | Resilience | Fallback-kedja per agent (4 modellslots). Global fallback vid crash. |
| 3 | Kostnadseffektivitet | Token-budget per agent per timme. Varning 80%, stopp 100%. |
| 4 | Observability | Prometheus metrics + strukturerad logging på alla agenter. |
| 5 | Korrekthet | Pylint + Bandit på varje genererad fix innan inlämning. |

### Stakeholders

| Roll | Intresse |
|------|---------|
| Utvecklare | Snabb bugg-fix utan att avbryta arbetsflödet |
| DevOps-ingenjör | Pålitlig pipeline, inga falska positiver |
| Handledare (BTH) | Vetenskapligt bidrag, reproducerbart PoC |

---

## 2. Constraints

| Typ | Constraint |
|-----|-----------|
| Teknik | Python 3.11+, MCP-protokollet, Docker Compose |
| Modell | Inga modellnamn hårdkodas — konfigureras via `.env` |
| Scope | Bara Python-projekt i PoC. Inga produktionsmiljöer. |
| Säkerhet | Inga API-nycklar i källkod. Allt via environment variables. |
| Tid | 7 sprints (Mar 27 – May 14, 2026) |

---

## 3. Context and Scope

### Systemgränser

```
Externt: Jenkins, GitHub/Gerrit, LLM API, Teams/Slack, Issue Tracker
Internt: 6 AI-agenter + Orchestrator + Gerrit MCP + Scheduler
```

Se C4 Level 1 diagram i [c4-diagrams.md](c4-diagrams.md#1-level-1--system-context).

### Kommunikation

| Gränssnitt | Protokoll | Riktning |
|-----------|-----------|---------|
| Jenkins → Platform | HTTP POST webhook | In |
| Platform → GitHub | HTTPS REST API | Ut |
| Platform → LLM API | HTTPS REST API | Ut |
| Platform → Teams/Slack | HTTPS webhook | Ut |
| Interna agenter | HTTP (docker network) | Intern |

---

## 4. Solution Strategy

### Nyckelarkitekturval

| Beslut | Val | Motivering |
|--------|-----|-----------|
| Kommunikationsprotokoll | MCP (Model Context Protocol) | Standardiserat AI-tool interface, lätt att byta ut enskilda agenter |
| Arkitekturmönster | Event-driven pipeline | Webhook triggar kedja, varje agent är oberoende |
| Säkerhetsmodell | Traffic Light (GREEN/YELLOW/RED) | Graderad autonomi baserat på confidence score |
| Resilience | Modell-fallback (4 slots/agent) | Oberoende av specifik modell |
| Kostnadskontroll | Token-budget per agent/timme | Förhindrar okontrollerade LLM-kostnader |
| Kodhälsa | Pylint + Bandit på genererad kod | Säkerhet och kvalitet innan inlämning |

### Arkitekturprinciper

1. **Varje agent har ett ansvar** — ingen agent gör mer än en sak
2. **Inga modellnamn i kod** — modeller väljs via `.env`
3. **Fail-safe** — vid tvivel → RED → människa
4. **Observable** — alla agenter exponerar `/metrics` och `/health`

---

## 5. Building Block View

### Level 1 — Systemöversikt

```
Auto-Healing Platform
├── Agent 1: Pipeline Monitor    (src/jenkins_mcp/)
├── Agent 2: Task Inspector      (src/scheduler/task_classifier.py)
├── Agent 3: Log Analyst         (src/log_cleaner_mcp/)
├── Agent 4: Error Analyst       (src/knowledge_graph_mcp/)
├── Agent 5: Code Repairer       (src/llm_mcp/)
├── Agent 6: Review & Notify     (src/notification_mcp/)
├── Orchestrator                 (src/orchestrator_mcp/)
├── Gerrit/GitHub MCP            (src/gerrit_mcp/)
├── Scheduler                    (src/scheduler/monitor.py)
└── Shared Infrastructure        (src/shared/)
    ├── models.py                 Domain models
    ├── config.py                 Agent config + token limits
    ├── model_fallback.py         Fallback-kedja primär→FB3
    ├── token_tracker.py          Token-budget per agent
    ├── resilience.py             CircuitBreaker + global fallback
    ├── quality_gates.py          Bandit + Pylint runners
    ├── mcp_base.py               /health + /metrics base
    ├── logging_setup.py          Structured logging
    └── metrics.py                Prometheus metrics
```

### Level 2 — Agent-detaljer

| Agent | MCP Service | Port | Nyckelklasser |
|-------|-------------|------|---------------|
| 1 | jenkins_mcp | 8082 | `WebhookHandler`, `LogFetcher` |
| 2 | scheduler | — | `TaskClassifier` |
| 3 | log_cleaner_mcp | 8081 | `clean_logs()`, 5 filter-klasser |
| 4 | knowledge_graph_mcp | 8084 | `FailureAnalyser`, `DependencyTracker` |
| 5 | llm_mcp | 8086 | `FixGenerator`, `quality_check.py` |
| 6 | notification_mcp | 8087 | `evaluate_traffic_light()`, `TeamsNotifier`, `SlackNotifier` |
| — | orchestrator_mcp | 8085 | `WorkflowEngine`, `ScenarioRouter` |
| — | gerrit_mcp | 8083 | `CodeFetcher`, `PatchSubmitter` |

Se detaljerade C4 Level 3 diagram i [c4-diagrams.md](c4-diagrams.md#3-level-3--orchestrator-components).

---

## 6. Runtime View

### Scenario A: Bug Fix (Happy Path)

```
Jenkins webhook → Agent 1 (dedup) → Orchestrator
→ Agent 3 (clean logs, 97% reduction)
→ Agent 4 (detect: IMPORT_ERROR, blast_radius: LOW)
→ Gerrit MCP (fetch affected file)
→ Agent 5 (LLM fix + Bandit/Pylint → confidence: 0.92)
→ Agent 6 (score: 0.92×0.6 + 1.0×0.4 = 0.952 → GREEN)
→ Gerrit MCP (submit patch as PR)
→ Teams/Slack: "✅ Auto-fix Applied"
```

### Scenario B: Feature (Autonomous Development)

```
Scheduler polls issues → Agent 2 (classify: SCENARIO_B)
→ Orchestrator
→ Agent 5 (generate from description → confidence: 0.75)
→ Agent 6 (score: 0.75×0.6 + 1.0×0.4 = 0.85 → GREEN/YELLOW borderline)
→ Likely YELLOW → human review
```

### Global Fallback

```
Any agent crashes/AllModelsFailed
→ Orchestrator catches exception
→ resilience.trigger_global_fallback(failed_agent, build_id, reason)
→ Agent 6 called directly with {status: RED, reason: agent_failure}
→ Teams/Slack: "🛑 Agent N crashed — manual intervention"
→ WorkflowState → FAILED
```

Se sequence-diagram i [c4-diagrams.md](c4-diagrams.md#8-scenario-a--happy-path-green).

---

## 7. Deployment View

### PoC: Docker Compose

Alla 8 containers på samma Docker-nätverk (`agent-network`). Konfigureras via `.env` (baserat på `.env.example`).

```bash
docker-compose up --build   # Startar alla 7 MCP-tjänster + scheduler
```

Portar: 8081–8087 (se docker-compose.yml).

### Production (framtida)

- Kubernetes med KEDA (event-driven autoscaling)
- Separata namespaces per agent
- Secrets via Kubernetes Secrets / HashiCorp Vault
- Se ADR-005: KEDA Scaling

---

## 8. Cross-cutting Concepts

### Fallback-kedja

Varje agent: primär modell → fallback 1 → fallback 2 → fallback 3 → `AllModelsFailed` → global fallback.
Implementation: `src/shared/model_fallback.py` — `ModelFallbackManager`.

### Token-budget

Per agent per timme. Varning vid 80%. Hård stopp vid 100% → byt till nästa modell.
Implementation: `src/shared/token_tracker.py` — `TokenTracker`.

### Structured Logging

Alla agenter använder `structlog` med JSON-format och correlation ID (`build_id`).
Implementation: `src/shared/logging_setup.py`.

### Prometheus Metrics

Alla agenter exponerar `/metrics`. Nyckelmetrics:
- `agent_tokens_used` (gauge per agent)
- `auto_healer_confidence_score` (histogram per traffic light)
- `agent_model_switch_total` (counter per agent)
- `auto_healer_quality_gate_results` (counter per gate)

Implementation: `src/shared/metrics.py`.

### Circuit Breaker

För externa API-anrop (LLM, GitHub, Jenkins). 5 failures / 60s → OPEN. 30s cooldown → HALF_OPEN.
Implementation: `src/shared/resilience.py` — `CircuitBreaker`.

---

## 9. Architecture Decisions

| ADR | Beslut |
|-----|--------|
| [ADR-001](adr/001-mcp-protocol.md) | MCP over direct REST APIs |
| [ADR-002](adr/002-python-stack.md) | Python for all services |
| [ADR-003](adr/003-event-driven.md) | Event-driven over request-response |
| [ADR-004](adr/004-traffic-light.md) | Confidence-based safety gates |
| [ADR-005](adr/005-keda-scaling.md) | KEDA for production scaling |
| [ADR-006](adr/006-orchestrator-mcp.md) | Orchestrator as central coordinator |
| [ADR-007](adr/007-log-pipeline.md) | Filter pipeline for log reduction |
| [ADR-008](adr/008-knowledge-graph.md) | Knowledge graph for failure analysis |
| [ADR-009](adr/009-agent-fallback.md) | 4-slot model fallback per agent |
| [ADR-010](adr/010-token-limits.md) | Token budget per agent per hour |

---

## 10. Quality Requirements

| Kvalitetsmål | Scenario | Mätvärde | Mål |
|-------------|---------|---------|-----|
| Säkerhet | HIGH blast radius | Traffic light result | Alltid RED |
| Precision | ImportError i logg | Error type detection | > 90% korrekt |
| Logg-reduktion | 10 000-raders Jenkins-logg | reduction_pct | > 90% |
| Resilience | Primär modell nere | Fallback aktivering | < 5s delay |
| Kostnadskontroll | Agent når 80% budget | Varning loggad | Inom 1 min |
| Kodkvalitet | LLM-genererad kod | Bandit HIGH issues | 0 accepteras |

---

## 11. Risks and Technical Debt

| Risk | Sannolikhet | Påverkan | Åtgärd |
|------|-------------|---------|--------|
| LLM ger felaktig fix | Medium | Hög | Quality gates + human review |
| Token-kostnader skenar | Låg | Medium | Token-budget per agent |
| Alla 4 modeller nere | Låg | Hög | Global fallback → RED |
| False negative i Traffic Light | Medium | Hög | Safety override för HIGH blast radius |
| Jenkins-logg format ändras | Låg | Medium | Regex fallback bevarar Error-rader |

**Teknisk skuld (PoC-scope):**
- `WebhookHandler._seen_builds` töms vid omstart — inte persistent
- `FixGenerator._call_llm()` är `NotImplementedError` — implementeras med faktisk SDK
- `PatchSubmitter._do_submit()` är placeholder — GitHub/Gerrit API krävs
- `ScheduledMonitor._fetch_open_tasks()` returnerar tom lista — GitHub Issues API krävs

---

## 12. Glossary

| Term | Definition |
|------|-----------|
| Agent | En specialiserad AI-tjänst med ett specifikt ansvar i pipelinen |
| MCP | Model Context Protocol — standardiserat gränssnitt för AI-tool interaction |
| Blast Radius | Hur många filer ett fel påverkar: LOW (1), MEDIUM (2-5), HIGH (6+) |
| Traffic Light | GREEN/YELLOW/RED-klassificering baserat på confidence score |
| Fallback Chain | Primär modell + 3 reservmodeller per agent |
| Token Budget | Max antal LLM-tokens per agent per timme |
| Circuit Breaker | Mekanism som blockerar anrop till en tjänst som upprepade gånger misslyckas |
| Global Fallback | Om en agent kraschar → hela flödet → RED → Agent 6 notifierar |
| Scenario A | Bug-fix-flöde: baserat på felrapport i issue-kommentar |
| Scenario B | Feature-flöde: ny kod genereras från task-beskrivning |
| YELLOW (manual) | Blandad task-beskrivning → människa klassificerar manuellt |
