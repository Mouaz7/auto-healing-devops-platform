<div align="center">

# 🤖 Auto-Healing AI DevOps Platform

### Automated Remediation in CI/CD: Design and Control of an AI-based Code Repair Agent

[![Tests](https://img.shields.io/badge/tests-639%20passing-brightgreen?style=flat-square)](tests/)
[![HITL](https://img.shields.io/badge/HITL-enforced-critical?style=flat-square)](src/orchestrator_mcp/pipeline_mixin.py)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square)](https://python.org)
[![License](https://img.shields.io/badge/thesis-PA2534%20BTH%202026-lightgrey?style=flat-square)](https://www.bth.se)

**Bachelor Thesis · Blekinge Tekniska Högskola (BTH) · 2026**

*Ahmad Darwich · Mouaz Naji · Supervisor: Ahmad Nauman Ghazi*

</div>

---

## What is this?

A self-healing CI/CD system built in Python. When a build fails on GitHub, **6 AI agents** automatically analyse the error, generate a code fix, run security and quality scans, open a Pull Request — and notify a human for review. The system never merges without human approval.

Built as a research prototype (PoC) to answer three thesis research questions about trust, control mechanisms, and the design of autonomous agents in software engineering pipelines.

---

## 📋 Table of Contents

1. [Research Questions & Code Mapping](#1-research-questions--code-mapping)
2. [Architecture — The 6 Agents](#2-architecture--the-6-agents)
3. [Pipeline Flow](#3-pipeline-flow)
4. [Control Mechanisms (RQ2)](#4-control-mechanisms-rq2)
5. [Traffic Light Safety System](#5-traffic-light-safety-system)
6. [Architecture Layer Classifier](#6-architecture-layer-classifier)
7. [Workflow State Machine](#7-workflow-state-machine)
8. [AI Model System](#8-ai-model-system)
9. [AI Memory & Learning](#9-ai-memory--learning)
10. [Proactive Bug Scanner](#10-proactive-bug-scanner-agent-5)
11. [Log Processing Pipeline](#11-log-processing-pipeline)
12. [Observability & Monitoring](#12-observability--monitoring)
13. [GitHub PR Report](#13-github-pr-report)
14. [Slack Integration](#14-slack-integration)
15. [Test Suite](#15-test-suite)
16. [Installation & Setup](#16-installation--setup)
17. [Environment Variables](#17-environment-variables)
18. [Project Structure](#18-project-structure)
19. [Authors](#19-authors)

---

## 1. Research Questions & Code Mapping

> This codebase is the PoC artifact for thesis **PA2534**. Every research question maps directly to running code.

### RQ1 — How should an AI code repair agent be designed to detect and fix build failures from logs?

| Design Decision | Code Location |
|---|---|
| 6-agent system: monitor (1) → classify (2) → clean (3) → analyse (4) → repair (5) → notify (6) | `src/orchestrator_mcp/pipeline_mixin.py` |
| 5-stage log compression, ~90% token reduction before LLM | `src/log_cleaner_mcp/pipeline.py` |
| Regex + LLM fallback error analysis for 11 error types, blast radius | `src/knowledge_graph_mcp/failure_analyser.py` |
| Fix generation: retry loop 6–14 attempts, surgical patch or full rewrite | `src/llm_mcp/fix_generator.py` |
| Proactive AST bug scanner: 63 patterns injected into prompt before LLM sees traceback | `src/llm_mcp/bug_scanner.py` |
| 11 runtime error hints in retry prompts: TypeError, IndexError, KeyError, RecursionError, AttributeError, NameError, ValueError, ZeroDivisionError, SyntaxError, IndentationError, AssertionError | `src/llm_mcp/fix_prompts.py` |
| Stuck-loop pivot: identical error type twice → strategy change in prompt | `src/llm_mcp/fix_prompts.py:45` |
| 4-model fallback chain per agent, complexity-based model routing | `src/shared/nim_client.py`, `src/shared/task_complexity.py` |

### RQ2 — What control mechanisms are required to prevent unsafe changes or technical debt?

| Control Mechanism | What it does | Code Location |
|---|---|---|
| **Human-in-the-Loop (enforced)** | Auto-merge permanently **disabled** for all confidence levels. GREEN = fast-track review, YELLOW = careful review. Both send Slack Approve/Reject buttons. | `src/orchestrator_mcp/github_mixin.py:94` |
| **Traffic light (file + bug + confidence)** | 🟢 GREEN: 1–3 files, ≤30 bugs/file, confidence ≥60%. 🟡 YELLOW: 4–5 files. 🔴 RED: >5 files, >30 bugs/file, or confidence <60%. | `src/notification_mcp/traffic_light_evaluator.py` |
| **Architecture-aware fix strategy** | Classifies failing code into 7 layers (frontend/backend/database/infra/tests/mobile/data-ml) across 152 frameworks and 82 languages. Layer-specific guidance injected into the AI prompt. DB migrations get +30% severity, auth code +30%, K8s +20%. | `src/shared/architecture_classifier.py` |
| **BLOCKED-state notification** | Regression loops and 422-rejected fixes send Slack RED alert immediately — no silent failures. | `src/orchestrator_mcp/pipeline_mixin.py:200` |
| **Bandit security scan** | Scans every generated fix for HIGH-severity issues. Triggers LLM retry with feedback. | `src/shared/quality_gates.py` |
| **Pylint linting (real score)** | Real weighted score via `--output-format=json2`. Low score reduces confidence modifier (−0.20 or −0.40). | `src/shared/quality_gates.py` |
| **Secret scanner** | 11 regex patterns block hardcoded credentials before any GitHub push. | `src/shared/secret_scanner.py` |
| **Audit trail** | Append-only JSONL log — every pipeline event with UTC timestamp. | `src/shared/audit_log.py` |
| **Regression loop prevention** | Same files fail again after recent fix → workflow → BLOCKED + Slack RED. | `src/orchestrator_mcp/pipeline_mixin.py` |
| **Retry limits** | Max 6–14 attempts by bug complexity. `FixStillBrokenError` on exhaustion. | `src/llm_mcp/fix_generator.py:254` |
| **CI loop guard** | Auto-heal commits use branch prefix `auto-heal/<build_id>` and titles `[auto-heal][COLOUR]` so external CI can exclude them with branch-name or commit-message filters. | `src/gerrit_mcp/patch_submitter.py` |
| **Protected paths** | AI cannot modify `.github/`, `Dockerfile`, `pyproject.toml`, or infra files. | `src/gerrit_mcp/gerrit_helpers.py:is_protected_path` |
| **Deduplication** | MD5 fingerprint of error+files prevents re-processing the same failure for 24 h. | `src/orchestrator_mcp/deduplication.py` |

### RQ3 — What are the primary barriers to trust, and how does the design address them?

| Trust Barrier | Architectural Mitigation | Code Location |
|---|---|---|
| AI introduces security vulnerabilities | Bandit scan → retry or block | `src/shared/quality_gates.py` |
| AI produces low-quality code | Pylint real score → confidence penalty | `src/shared/quality_gates.py` |
| AI hallucinates wrong fixes | AST parse + sandboxed subprocess run + 11 runtime hints in retry prompt before accepting | `src/llm_mcp/fix_validators.py`, `src/llm_mcp/fix_prompts.py` |
| AI targets symptom not root cause | 63-pattern static scanner pre-annotates code with bug locations before LLM call | `src/llm_mcp/bug_scanner.py` |
| AI cannot be trusted to merge | **Auto-merge disabled** — human clicks Merge on GitHub | `src/orchestrator_mcp/github_mixin.py` |
| No accountability or traceability | Audit trail + PR body with confidence, root cause, elapsed time | `src/shared/audit_log.py` |
| System loops infinitely | Regression block + CI guard prevent infinite repair cycles | `src/orchestrator_mcp/pipeline_mixin.py` |
| Confidence score is opaque | Decision Reason shown in every notification: "1 file, 19 bugs, confidence 95%". `auto_merge_allowed` always `False`. | `src/notification_mcp/traffic_light_evaluator.py` |
| Thresholds don't fit the domain | Adaptive thresholds self-calibrate from human approve/reject decisions | `src/shared/adaptive_thresholds.py` |

---

## 2. Architecture — The 6 Agents

```
╔══════════════════════ TRIGGER AGENTS (run independently) ═══════════════════╗
║                                                                              ║
║  ┌──────────────────────┐         ┌──────────────────────────────┐         ║
║  │  Agent 1 — Jenkins   │         │   Agent 2 — Scheduler        │         ║
║  │  jenkins-mcp  :8082  │         │   scheduler (no port)        │         ║
║  │                      │         │                              │         ║
║  │  • Polls Jenkins     │         │  • Polls GitHub Issues/Jira  │         ║
║  │  • Fetches raw logs  │         │  • Classifies: A / B / YELLOW│         ║
║  │  • On failure → POST │         │  • Daily 08:00 UTC digest    │         ║
║  └──────────┬───────────┘         └──────────┬───────────────────┘         ║
║             │                                │                              ║
╚═════════════╪════════════════════════════════╪══════════════════════════════╝
              │                                │
              │  POST /tools/handle_build_failure
              ▼                                ▼
   ┌─────────────────────────────────────────────────────────┐
   │             ORCHESTRATOR — orchestrator-mcp :8085        │
   │     State machine · Dedup · Rate limit · Cost tracking  │
   └────────────────────────┬────────────────────────────────┘
                            │  (sequential pipeline)
                            │
                            ▼
   ┌─────────────────────────────────────────────────────────┐
   │ Agent 3 — Log Cleaner       (log-cleaner-mcp   :8081)   │
   │ 5-stage regex pipeline + LLM fallback  · ~95% reduction │
   └────────────────────────┬────────────────────────────────┘
                            ▼
   ┌─────────────────────────────────────────────────────────┐
   │ Agent 4 — Error Analyst     (knowledge-graph-mcp :8084) │
   │ Regex + LLM · 11 error types · blast radius             │
   └────────────────────────┬────────────────────────────────┘
                            ▼
   ┌─────────────────────────────────────────────────────────┐
   │ 🆕 Architecture Classifier  (in-process in orchestrator)│
   │ 7 layers · 152 frameworks · 82 languages · 55 sub-layers│
   └────────────────────────┬────────────────────────────────┘
                            ▼
   ┌─────────────────────────────────────────────────────────┐
   │       Gerrit MCP — fetch source file content :8083      │
   └────────────────────────┬────────────────────────────────┘
                            ▼
   ┌─────────────────────────────────────────────────────────┐
   │ Agent 5 — Code Repairer     (llm-mcp           :8086)   │
   │ 63-pattern bug scanner → LLM → AUTO-HEAL annotations    │
   │ Bandit + Pylint + secret scanner · 6–14 retry attempts  │
   └────────────────────────┬────────────────────────────────┘
                            ▼
   ┌─────────────────────────────────────────────────────────┐
   │ 🆕 Diff Bug Counter         (in-process in orchestrator)│
   │ Token-level diff · authoritative bug count              │
   └────────────────────────┬────────────────────────────────┘
                            ▼
   ┌─────────────────────────────────────────────────────────┐
   │ Agent 6 — Review & Notify   (notification-mcp  :8087)   │
   │ Traffic light (file + bug + confidence)                 │
   │ Slack (Block Kit) + Teams + 9 slash commands            │
   └────────────────────────┬────────────────────────────────┘
                            ▼
   ┌─────────────────────────────────────────────────────────┐
   │  Gerrit MCP — create GitHub PR with AUTO-HEAL patch     │
   │  (only on 🟢 GREEN or 🟡 YELLOW — HITL still required)  │
   └─────────────────────────────────────────────────────────┘
```

| # | Agent | Service | Port | Role |
|---|---|---|---|---|
| 1 | **Pipeline Monitor** | `jenkins-mcp` | `:8082` | Polls Jenkins for build failures, fetches raw logs |
| 2 | **Task Inspector** | `scheduler` | — | Polls GitHub Issues / Jira, classifies tasks (Scenario A/B/YELLOW) |
| 3 | **Log Analyst** | `log-cleaner-mcp` | `:8081` | 5-stage regex + LLM fallback log compression (~90% reduction) |
| 4 | **Error Analyst** | `knowledge-graph-mcp` | `:8084` | Regex + LLM analysis, 11 error types, blast radius, affected files |
| 5 | **Code Repairer** | `llm-mcp` | `:8086` | Fix generation with memory + architecture context, Bandit, Pylint, AUTO-HEAL annotations |
| 6 | **Review & Notify** | `notification-mcp` | `:8087` | File + bug + confidence traffic light, Slack/Teams notifications, slash commands |
| — | **Orchestrator** | `orchestrator-mcp` | `:8085` | Central pipeline, state machine, webhooks. Runs two in-process helpers between agents: 🆕 **Architecture Classifier** (after Agent 4) and 🆕 **Diff Bug Counter** (after Agent 5). |
| — | **PR Manager** | `gerrit-mcp` | `:8083` | Creates GitHub PRs with structured report, applies AUTO-HEAL patches, enforces protected paths |

> **Note on numbering:** Agents 1 and 2 are *trigger* agents that run independently — Agent 1 watches Jenkins, Agent 2 watches issue trackers. When either detects work, they hand off to the **Orchestrator**, which then runs the **in-pipeline agents 3 → 4 → 5 → 6** with two in-process helpers (Architecture Classifier, Diff Bug Counter) and a supporting service (Gerrit MCP for PR creation).

### Agents in Detail

#### 🔭 Agent 1 — Pipeline Monitor (`jenkins-mcp`)

**Purpose:** Watch Jenkins for failed builds and pull their raw logs.

| Aspect | Details |
|---|---|
| Code | `src/jenkins_mcp/server.py` (`JenkinsMCPServer`) |
| Endpoint | `GET /tools/fetch_log?job=<job>&build=<build>` |
| Trigger | Polled by orchestrator on every webhook hit, OR called directly when GitHub Actions sends a build failure |
| Output | Raw multi-MB build log → handed to Agent 3 (Log Analyst) |

#### 🧭 Agent 2 — Task Inspector (`scheduler`)

**Purpose:** Classify incoming tasks (GitHub Issues, Jira tickets, comments) into one of three scenarios so the orchestrator knows whether to route them to the bug-fix or feature-development path.

| Aspect | Details |
|---|---|
| Code | `src/scheduler/task_classifier.py` (`TaskClassifier`) + `src/scheduler/monitor.py` |
| Container | `scheduler` (defined in `docker-compose.yml`, runs `python -m src.scheduler.monitor`) |
| Polling | GitHub Issues / Jira every `SCHEDULE_INTERVAL_MINUTES` (default 15 min) |
| Strategy | 4-stage escalating latency: regex → primary LLM → fallback chain → YELLOW fallback |
| LLM | NIM PRIMARY = `gemma-4-31b-it`; fallback chain FB1 → FB2 → FB3 |

**Classification output:**

| Scenario | Trigger | Action |
|---|---|---|
| **A** = `BUG_FIX_FROM_COMMENT` | Error keywords (`Traceback`, `Error:`, `Exception`, `crash`, `fix`) or stack-trace patterns | Route to bug-fix pipeline |
| **B** = `AUTONOMOUS_DEVELOPMENT` | Feature keywords (`add`, `create`, `implement`, `enhancement`) without error signals | Route to feature pipeline |
| **YELLOW** = `YELLOW_MANUAL` | Ambiguous text or all LLM calls failed | Send to Slack for human classification |

**Also runs:** Daily Slack digest at 08:00 UTC (`src/scheduler/daily_digest.py`) — builds processed, success rates, top error types, troubled files, threshold adaptations, regression watch status.

#### 🧹 Agent 3 — Log Analyst (`log-cleaner-mcp`)

**Purpose:** Compress noisy multi-MB logs to ~2 KB before the LLM ever sees them.

| Aspect | Details |
|---|---|
| Code | `src/log_cleaner_mcp/pipeline.py` + `filters/` |
| Stages | 5-stage deterministic pipeline: ANSI → timestamps → dedup → noise → stack-trace extract |
| LLM fallback | If reduction < 50%, prompt LLM to summarise |
| Typical result | 40 KB log → ~2 KB (~95% reduction) |

#### 🧠 Agent 4 — Error Analyst (`knowledge-graph-mcp`)

**Purpose:** Identify what went wrong and which files are affected.

| Aspect | Details |
|---|---|
| Code | `src/knowledge_graph_mcp/failure_analyser.py` (`FailureAnalyser`) |
| Detection | Regex per error type (zero latency) → LLM fallback for unmatched cases |
| Error types | 11 (`SYNTAX_ERROR`, `TYPE_ERROR`, `IMPORT_ERROR`, `ASSERTION_ERROR`, `FILE_NOT_FOUND`, `ATTRIBUTE_ERROR`, `NAME_ERROR`, `VALUE_ERROR`, `KEY_ERROR`, `INDEX_ERROR`, `ZERO_DIVISION_ERROR`) + `UNKNOWN` |
| Blast radius | LOW (1 file) / MEDIUM (2–5) / HIGH (6+) |
| Output | `FailureAnalysis(error_type, blast_radius, affected_files, root_cause, confidence)` |

#### 🛠️ Agent 5 — Code Repairer (`llm-mcp`)

**Purpose:** Generate the actual fix.

| Aspect | Details |
|---|---|
| Code | `src/llm_mcp/fix_generator.py` (`FixGenerator`) |
| Pre-LLM | 63-pattern AST scanner (`bug_scanner.py`) annotates code with bug locations injected into the prompt |
| Strategy | Surgical patch (small fix) OR full rewrite (multi-bug) — chosen by complexity score |
| Retry budget | 6 attempts (≤2 bugs) · 8 (3–9) · 14 (10–40) — scales with bug density |
| Quality gates | Bandit (HIGH severity blocks) · Pylint (low score reduces confidence) · secret scanner (11 patterns) |
| AUTO-HEAL annotations | Every changed line gets `# AUTO-HEAL: was '...' (bug type) -> fix` inline |
| Output | `CodeFix(fix_patch, confidence, explanation, bugs_found, model_used, regression_risk, test_hints)` |

#### 📨 Agent 6 — Review & Notify (`notification-mcp`)

**Purpose:** Decide the traffic light, send notifications, handle slash commands.

| Aspect | Details |
|---|---|
| Code | `src/notification_mcp/traffic_light_evaluator.py` + `slack_notifier.py` + `slack_slash_handler.py` |
| Decision | File count + bugs/file + AI confidence (no opaque score formula) |
| Notifications | Slack (Block Kit with emoji bars 🟩🟨🟥) + Teams |
| Slash commands | 9 commands (`status`, `list`, `stats`, `retry`, `explain`, `rollback`, `history`, `top`, `thresholds`) + `help` fallback |
| Build-ID parsing | Strips `build`, `#`, `id:` prefixes so `/autoheal status build 12345` and `/autoheal status 12345` both work |

---

## 3. Pipeline Flow

```
POST /tools/handle_build_failure
  │
  ├─ Rate limit (10 req/60s)  ──────────────────────────► 429
  ├─ Payload size (> 500 KB)  ──────────────────────────► 413
  ├─ Duplicate build_id       ──────────────────────────► 200 ALREADY_TRIGGERED
  │
  ▼  [Agent 3]  Clean logs
     • Remove ANSI codes, timestamps, duplicate lines, noise
     • Extract stack traces  •  LLM fallback if < 50% reduction
  │
  ▼  [Agent 4]  Analyse failure
     • Regex → 11 error types  •  Blast radius (LOW / MEDIUM / HIGH)
     • Affected files from pytest output and tracebacks
  │
  ├─ Regression check ──────── same files recently fixed? ──► BLOCKED ⛔
  ├─ Deduplication ──────────── same error in 24 h?        ──► cached result
  │
  ▼  [Gerrit MCP]  Fetch file content (code context, max 3 files)
  │
  ▼  🆕 [Architecture Classifier]  Identify the architecture layer
     • Classify into 7 layers (frontend/backend/db/infra/tests/mobile/data-ml)
     • Detect framework (152 supported) · language (82) · runtime
     • Sub-layer (55 patterns: API endpoint, Migration, Auth, K8s workload, ...)
     • Severity boost for high-risk areas (Migration +30%, Auth +30%, K8s +20%)
     • Inject layer-specific guidance into the AI prompt
  │
  ▼  [Agent 5]  Generate fix
     • Inject fix memory (past 3 relevant outcomes) + architecture context
     • Complexity score → model tier (7 B / 32 B / 70 B+)
     • LLM call  →  parse  →  apply patch
     • Tier-0 AUTO-HEAL parsing: AI annotates every changed line with
       `# AUTO-HEAL: was '...' (bug type) -> fix`. Parsed back into the bug list.
     • Secret scan  •  Bandit  •  Pylint
     • Retry on security issues (up to budget)
  │
  ▼  🆕 [Diff Bug Counter]  Authoritative token-level diff
     • Walks original vs fix line by line
     • Counts each distinct token-group change as 1 bug
     • Same source feeds traffic-light, PR report, and Slack — they always agree
  │
  ▼  [Agent 6]  Evaluate & Notify
     • Traffic light based on: files affected + bugs per file + AI confidence
     • 🟢 GREEN:  1–3 files  AND  ≤30 bugs/file  AND  confidence ≥ 60%
     • 🟡 YELLOW: 4–5 files  AND  ≤30 bugs/file  AND  confidence ≥ 60%
     • 🔴 RED:    >5 files   OR   >30 bugs/file  OR   confidence < 60%
  │
  ├─── 🟢 GREEN  ──► PR opened · Slack Approve / Reject buttons (fast-track)
  │                  Decision Reason: "1 file, 19 bugs, confidence 95%"
  │                  Regression watch activated (60 min)
  │
  ├─── 🟡 YELLOW ──► PR opened · Slack Approve / Reject buttons (careful review)
  │                  Decision Reason: "4 files affected — careful review required (80%)"
  │                  Human decision feeds adaptive thresholds + fix memory
  │
  ├─── 🔴 RED    ──► No PR · BLOCKED · Slack RED alert sent immediately
  │                  Decision Reason: "Too many bugs per file (35 > 30)"
  │                  Manual intervention required
  │
  └─── ⛔ BLOCKED ─► Regression loop OR 422 too-complex
                     Smart retry: same error type → allow 1 extra attempt
                     Slack RED alert with reason · BLOCKED state in workflow
                     Audit event logged · no fix attempted
```

---

## 4. Control Mechanisms (RQ2)

### 🔒 Human-in-the-Loop — Always Enforced

Auto-merge is **permanently disabled** for all confidence levels. Every fix — even a GREEN fix at 99% confidence — requires explicit human approval before merging. The colour signals review urgency, not autonomous action:

| Colour | What it means for the reviewer |
|---|---|
| 🟢 GREEN | 1–3 files, ≤30 bugs/file, confidence ≥60% — **fast-track review** recommended. Check the diff briefly and merge if it looks right. |
| 🟡 YELLOW | 4–5 files, ≤30 bugs/file, confidence ≥60% — **careful review** required. Read the fix closely and consider testing locally. |
| 🔴 RED | >5 files, >30 bugs/file, or confidence <60% — **fix is blocked**, no PR created. Manual intervention required. |

The auto-merge code path is disabled at the source:

```python
# src/orchestrator_mcp/github_mixin.py
# Enforce Human-in-the-Loop: every PR must be reviewed by a human
# before merging, regardless of the AI confidence score.
# if auto_merge and pr_number:
#     await self._merge_pr(client, repo, pr_number)
```

`auto_merge_allowed` in `TrafficLightResult` always returns `False` — it is never consulted for merge decisions.

---

### 🛡️ Quality Gates — Run on Every Generated Fix

Both gates run inside Agent 5's retry loop **before** any fix is returned:

| Gate | Tool | Trigger | Consequence |
|---|---|---|---|
| **Security scan** | Bandit `--format json` | HIGH severity issue found | LLM retry with security feedback; budget exhausted → RED |
| **Linting** | Pylint `--output-format=json2` | Score < 6.0 / 4.0 | Confidence modifier −0.20 / −0.40 |

**Confidence modifier rules:**

```
Bandit HIGH issue      →  −0.30
Pylint score < 6.0     →  −0.20
Pylint score < 4.0     →  −0.40   (replaces −0.20)
Both bad               →  stacked, up to −0.70
All pass               →   0.00
```

Pylint uses the real weighted formula (`statistics.score` from `json2` output), not an approximation. Conventions and refactors are excluded (`--disable=C,R`) so missing docstrings in a patch don't inflate the penalty.

---

### 📋 Audit Trail

Every pipeline event is appended to an **append-only JSONL** file with UTC timestamp:

| Event | When logged |
|---|---|
| `pipeline_start` | Build failure received |
| `pipeline_complete` | Pipeline finished (any colour) |
| `pipeline_failed` | Unhandled exception in any agent |
| `regression_detected` | Same files fail again after recent fix |
| `fix_deduplicated` | Error fingerprint matched 24 h cache |
| `rate_limit_blocked` | IP exceeded rate limit |
| `pr_approved` | Human clicked Approve in Slack |
| `pr_rejected` | Human clicked Reject in Slack |

Example record:
```json
{"ts":"2026-04-23T12:00:00Z","event":"pipeline_start","build_id":"run-42","repo":"org/repo"}
```

---

### ♾️ Infinite Loop Prevention

Three complementary mechanisms:

1. **Regression blocking with smart retry** — `_check_regression()` watches affected files for 60 minutes. Behaviour:
   - Same file, **same** error type, first re-failure → **allow 1 retry** (AI may need another pass)
   - Same file, same error type, second re-failure → BLOCKED + Slack RED
   - Same file, **different** error type → BLOCKED (likely new bug introduced by the fix)
2. **CI guard** — GitHub Actions trigger steps require `!startsWith(head_commit.message, 'auto-heal')`, so healer commits never re-trigger the healer
3. **Protected paths** — AI cannot modify `.github/`, `Dockerfile`, `pyproject.toml`, `requirements.txt`, or any infra file

---

## 5. Traffic Light Safety System

### Decision Logic (file count + bugs/file + AI confidence)

The traffic light is computed from three concrete inputs — not an opaque weighted score.

```
Step 1 — RED overrides (any one triggers RED immediately):
  • > 30 bugs in any single file   → file too broken for reliable AI fix
  • > 5  files affected            → change scope too wide
  • AI confidence < 0.60           → AI itself is not sure

Step 2 — YELLOW:
  • 4–5 files affected, ≤ 30 bugs/file, confidence ≥ 0.60

Step 3 — GREEN:
  • 1–3 files, ≤ 30 bugs/file, confidence ≥ 0.60
```

### Decision Table

| Colour | Condition | Reason text shown in Slack & PR | Action |
|---|---|---|---|
| 🟢 **GREEN** | 1–3 files, ≤30 bugs/file, conf ≥60% | "High confidence fix — N file(s), M bug(s), confidence X%" | PR opened · Slack Approve/Reject (fast-track) · regression watch started |
| 🟡 **YELLOW** | 4–5 files, ≤30 bugs/file, conf ≥60% | "N files affected — careful review required (confidence X%)" | PR opened · Slack Approve/Reject (careful review) · 24 h window |
| 🔴 **RED** | >5 files | "Too many files affected (N > 5) — change scope too wide" | No PR · Slack RED alert · workflow BLOCKED |
| 🔴 **RED** | >30 bugs/file | "Too many bugs per file (N > 30) — file too broken for reliable AI fix" | No PR · Slack RED alert · workflow BLOCKED |
| 🔴 **RED** | conf <60% | "AI confidence too low (X% < 60%) — fix blocked" | No PR · Slack RED alert · workflow BLOCKED |

`auto_merge_allowed` is always `False` — the traffic light colour signals review urgency, not a merge decision.

The 60% confidence floor is **adaptive per error type** — after 5+ human decisions, the threshold self-calibrates: `new_floor = mean(approved_confidences) − 0.03`. Stored in append-only JSONL, cached in memory.

### Bug Counting (token-level diff)

Bug count is computed by an **authoritative token-level diff** between the original and fixed file — not the LLM's self-reported count.

| Granularity | Example: `arr[idx], arr[l] = arr[l], arr[idx]` → `arr[idx], arr[k] = arr[k], arr[idx]` |
|---|---|
| Per-line (too coarse) | 1 bug |
| **Per-token (used)** | **2 bugs** (each `l` → `k` is independent) |
| Per-character (too granular) | counts whitespace/formatting changes |

The same diff feeds the traffic-light evaluator, the PR report, and Slack — they always agree on the count.

---

## 6. Architecture Layer Classifier

Before generating a fix, the system classifies the failing code's place in the architecture so the AI can apply layer-appropriate strategies (`src/shared/architecture_classifier.py`).

### What it detects

| Dimension | Possible values |
|---|---|
| 🏛️ **Layer** (7 + Unknown) | 🎨 FRONTEND · ⚙️ BACKEND · 🗄️ DATABASE · 🐳 INFRA · 🧪 TESTS · 📱 MOBILE · 🧠 DATA_ML |
| 📌 **Sub-layer** (55 patterns) | API endpoint · Middleware · Auth · Migration · Schema/DDL · K8s workload · CI/CD pipeline · React hook · Form · Model training · ... |
| 📦 **Framework** (152 supported) | React, Vue, Next.js, FastAPI, Django, Spring Boot, Gin, Actix, Rails, Laravel, Phoenix, PostgreSQL, Prisma, Kubernetes, Terraform, PyTorch, TensorFlow, Flutter, SwiftUI, ... |
| 💻 **Language** (82 supported) | Python, TypeScript, Go, Rust, Java, Kotlin, Swift, Dart, Ruby, PHP, Elixir, Haskell, Solidity, ... |
| ⚙️ **Runtime** | CPython, Node.js, JVM, .NET, Apple LLVM, Go runtime, BEAM, EVM, ... |
| 🔗 **Cross-layers** | Secondary layers also implicated (e.g. backend API hitting a DB error) |
| ⚠️ **Severity boost** | 0–30% extra caution for high-risk areas |

### How it works — 3 weighted signals

```
1. Path patterns       (weight 3.0) — most reliable
   ↓
2. Content / imports   (weight 2.0) — second-most reliable
   ↓
3. Error message       (weight 1.5) — fallback
   ↓
4. Strong overrides    (weight 3.0) — definitive imports (e.g. 'react-native' → MOBILE)
```

The highest-scoring layer wins. Secondary layers with score ≥ 1.5 are reported as cross-layer involvement.

### Severity boosts — extra caution for high-risk areas

| Sub-layer | Boost | Why |
|---|---|---|
| Migration | +30% | Schema changes are often irreversible |
| Schema / DDL | +30% | Database structure changes |
| Auth / Security | +30% | Vulnerability surface |
| Trigger / Stored proc | +25% | Hidden execution paths |
| CDC / Streaming | +25% | Event-loss risk |
| Kubernetes workload | +20% | Pod restart implications |
| Infrastructure-as-code | +20% | Resource provisioning |
| CI/CD pipeline | +20% | Blocks all future builds |
| Load balancer / Proxy | +20% | Traffic routing risk |
| API endpoint | +15% | Contract breakage |
| Model training | +15% | Reproducibility concerns |

### Example classifications

```
FastAPI API endpoint:
  → BACKEND (100%) · API endpoint · FastAPI · Python · on CPython · ⚠️+15%

Django migration affecting Postgres:
  → BACKEND (100%) · Django · Python · 🔗 also: DATABASE

Postgres SQL migration:
  → DATABASE (100%) · Schema/DDL · SQL · ⚠️+30%

React Native mobile screen:
  → MOBILE (100%) · React Native · TypeScript · 🔗 also: FRONTEND

Flutter widget:
  → MOBILE (100%) · Flutter widget · Flutter · Dart · on Dart VM

Kubernetes Deployment:
  → INFRA (100%) · Kubernetes workload · Kubernetes · YAML · ⚠️+20%

Airflow DAG:
  → DATA_ML (100%) · Airflow · Python · 🔗 also: BACKEND

Elixir Phoenix controller:
  → BACKEND (100%) · Phoenix · Elixir · on BEAM
```

### What it changes in the pipeline

1. **AI prompt** — layer-specific guidance is injected before the bug context:
   > *"Framework: FastAPI. [API endpoint] Backend code: focus on input validation, error handling, and concurrency. PRESERVE THE API CONTRACT — request/response shapes, status codes, and field names must remain unchanged."*

2. **PR Report** — Architecture Layer row in the Summary table:
   ```
   | Architecture Layer | ⚙️ Backend (100% conf) · API endpoint · FastAPI · Python on CPython · 🔗 also: DATABASE · ⚠️ +15% risk |
   ```

3. **Slack notification** — dedicated Architecture section with risk note:
   ```
   🏛️ Architecture — ⚙️ Backend · API endpoint · `FastAPI` · `Python` on `CPython`
   _API contract may have changed — all consuming clients should be re-tested._
   ```

4. **Regression Risk fallback** — if the LLM doesn't produce one, the layer-specific risk note is used (e.g. for DB migrations: *"⚠️ HIGH RISK — schema changes can be irreversible. Run on staging first, verify backups exist, prepare rollback SQL."*)

### Why this matters

Different layers carry different bug profiles and different risks:

| Layer | Typical bugs | Risk profile |
|---|---|---|
| 🎨 Frontend | State, props, rendering, async race | Visual, often isolated — low blast radius |
| ⚙️ Backend | API contract, validation, concurrency | All clients affected — high blast radius |
| 🗄️ Database | Migrations, foreign keys, indexing | Data integrity — **highest risk** |
| 🐳 Infra | Docker, CI/CD, environment | Build/deploy blocking |
| 🧪 Tests | Assertions, mocks, fixtures | Safe to fix — lowest risk |
| 📱 Mobile | Platform APIs, lifecycle | Requires multi-device testing |
| 🧠 Data/ML | Training, inference, pipelines | Model drift, reproducibility |

The classifier ensures a database migration is treated with more respect than a frontend button — just like a human reviewer would.

---

## 7. Workflow State Machine

```
PENDING
  └─► ANALYSING ──────────────────────────────────────────► BLOCKED ⛔
        │               (regression detected)                + Slack RED
        └─► GENERATING_FIX ──────────────────────────────► BLOCKED ⛔
                  │              (422 too complex)            + Slack RED
                  └─► VALIDATING
                        ├─► AWAITING_REVIEW ──► APPLYING_FIX ──► COMPLETED ✅
                        │   (HITL review)  └─────────────────► BLOCKED ⛔
                        └─► BLOCKED ⛔
                             (RED traffic light: >5 files, >30 bugs/file, conf <60%)
                             + Slack RED

Any state ──► FAILED  (on unhandled agent exception)
```

- `AWAITING_REVIEW` older than **24 h** → auto-blocked (review window expired)
- Terminal states older than **48 h** → pruned from memory
- Pruning runs every **3600 s** as background asyncio task

---

## 8. AI Model System

### NVIDIA NIM — 4-Model Fallback Chain

```
PRIMARY ──► FALLBACK_1 ──► FALLBACK_2 ──► FALLBACK_3 ──► AllModelsFailed
```

All models configured via environment variables — nothing hardcoded.

### Complexity-Based Model Routing

| Score | Complexity | Model tier | Typical scenario |
|---|---|---|---|
| 0–2 | LOW | 7–8 B (fast, cheap) | Single assertion error, 1 file |
| 3–6 | MEDIUM | 32 B (balanced) | Import error, 2–3 files |
| 7+ | HIGH | 70 B+ (best quality) | Dependency / concurrency, many files |

Scoring factors: error type weight + blast radius + number of files + log length.

### Per-Agent Token Budgets

| Agent | Max tokens/req | Max tokens/hour |
|---|---|---|
| Pipeline Monitor (Agent 1) | 500 | 5 000 |
| Task Inspector (Agent 2) | 1 000 | 10 000 |
| Log Analyst (Agent 3) | 2 000 | 20 000 |
| Error Analyst (Agent 4) | 3 000 | 30 000 |
| Code Repairer (Agent 5) | 4 000 | 50 000 |
| Review & Notify (Agent 6) | 2 000 | 20 000 |

Global budget: **135 000 tokens/hour** (sum of all six). Warning at 80%.

### Cost Tracking

Per-build API cost estimated from model size tiers. Warns when a single build exceeds $0.10. Session totals in `/api/stats`.

---

## 9. AI Memory & Learning

### Fix Memory (`src/shared/fix_memory.py`)

Every fix attempt is stored. On the same error type recurring, the 3 most relevant past fixes are fetched using **Jaccard similarity** on affected file sets and injected into the prompt:

```
Past fix attempts for this error type (use as reference):
  [2026-04-20] GREEN (91%) ✓ HUMAN APPROVED: Fixed incorrect assertion in test_calc.py
  [2026-04-18] YELLOW (74%) ✗ HUMAN REJECTED — avoid: Changed test to skip instead of fixing
  [2026-04-15] RED (38%): Could not identify root cause
```

Human approve/reject decisions update the stored outcome in real time.

### Adaptive Thresholds (`src/shared/adaptive_thresholds.py`)

The module still tracks two thresholds per error type (legacy `green_threshold` ≥ 0.85, `yellow_threshold` ≥ 0.60), but the **new traffic light only uses the YELLOW threshold as the confidence floor**:

```python
# In traffic_light_evaluator.py
_, yellow_t = adaptive_thresholds.get_thresholds(error_type)
confidence_floor = max(MIN_CONFIDENCE, yellow_t)   # 0.60 default, adapts up
```

After 5+ human decisions for an error type, `yellow_t` self-calibrates:
- `new_yellow = mean(rejected_confidences) + 0.03`  (slightly above what humans reject)
- Safe bounds: `yellow ∈ [0.45, 0.80]`, `green ∈ [0.70, 0.95]`
- Stored in append-only JSONL, cached in memory

This means the system adapts to your team's risk tolerance per error type — e.g. you may accept lower-confidence SYNTAX_ERROR fixes than TYPE_ERROR fixes.

### Regression Watch (`src/shared/heal_verifier.py`)

After every fix, affected files are watched for **60 minutes**. Behaviour on re-failure:

| Scenario | Action |
|---|---|
| Same file, **same** error type, first re-failure | ✅ Allow one retry — AI may need another pass on the same problem |
| Same file, same error type, second re-failure | 🚫 BLOCKED — definitely needs human review |
| Same file, **different** error type | 🚫 BLOCKED — likely new bug introduced by fix, not a retry |

The retry counter is stored per fix record. After the 60-minute window expires, the file is unguarded again.

---

## 10. Proactive Bug Scanner (Agent 5)

### 63-Pattern AST Scanner (`src/llm_mcp/bug_scanner.py`)

Before the LLM generates a fix, the pipeline runs a full static AST scan on the original broken code. Findings are **injected into the fix prompt** so the model knows exactly what to look for — instead of tunnel-visioning on the traceback symptom line.

```
============================================================
STATIC BUG SCAN — 3 PATTERN(S) DETECTED
============================================================
  [1] Line 4 — WRONG_EDGE_RETURN (HIGH)
      Returns `1` for empty input — correct sentinel is 0/0.0/None/-1
  [2] Line 5 — WRONG_ACCUMULATOR_INIT (HIGH)
      `total` initialised to `1` but used as sum accumulator with `+=`
  [3] Line 7 — COMPARISON_AS_ASSIGNMENT (HIGH)
      `total == num` is a no-op comparison — use `total += num`
============================================================
```

#### Pattern categories (63 total)

| Category | Patterns |
|---|---|
| **Accumulation bugs** | wrong_accumulator_init, loop_overwrites_accumulator, augmented_subtract_in_sum, wrong_product_sentinel |
| **Edge-case returns** | wrong_edge_return, wrong_return_sentinel, inconsistent_return, missing_return |
| **Loop bugs** | off_by_one_range, loop_var_unused, range_excludes_last_element, range_wrong_direction, return_first_iteration, import_in_loop, infinite_while_no_break, while_condition_unchanged |
| **Comparison bugs** | comparison_as_assignment, is_literal_comparison, none_equality_check, redundant_bool_comparison, comparison_with_itself, type_not_isinstance, float_exact_equality, len_compared_to_zero |
| **Class / OOP bugs** | class_mutable_attribute, missing_super_init, forgot_self_dot, mutable_default_arg, callable_default_arg, recursive_mutable_default, dict_fromkeys_mutable_default, list_multiply_shared_refs |
| **Exception bugs** | bare_except, exception_swallowed, wrong_exception_reraise, return_in_finally, raise_in_finally, assert_for_validation, assert_tuple |
| **String / collection** | str_method_not_assigned, sorted_result_discarded, sort_returns_none, print_returns_none, extend_with_string, append_list_literal, join_non_string_elements, sum_of_lists, duplicate_dict_key, star_import |
| **Math / type bugs** | floor_div_float_context, divide_without_guard, wrong_arithmetic_op, truediv_as_index, slice_wrong_direction, windows_path_escape |
| **Code quality** | shadow_builtin, augmented_assign_to_param, recursive_call_not_returned, fstring_no_interpolation, or_default_loses_falsy, unreachable_code_after_return |

---

## 11. Log Processing Pipeline

### Agent 3 — 5-Stage Deterministic Pipeline

| Stage | Module | What it removes |
|---|---|---|
| 1 | `ansi_remover.py` | ANSI escape codes |
| 2 | `timestamp_stripper.py` | ISO/Unix timestamps, log prefixes |
| 3 | `deduplicator.py` | Duplicate consecutive lines |
| 4 | `noise_filter.py` | Progress dots, separators, blank lines |
| 5 | `stack_trace_extractor.py` | Keeps error lines, drops surrounding noise |

LLM fallback if < 50% line reduction. Typical result: 40 KB log → ~2 KB.

### Prompt Compressor (`src/shared/prompt_compressor.py`)

Second compression before LLM calls in Agent 5: keeps error lines + 2-line context window + head/tail. ~90% token reduction.

---

## 12. Observability & Monitoring

### Prometheus Metrics (`/metrics` on every service)

| Metric | Type | Description |
|---|---|---|
| `auto_healer_workflows_total` | Counter | By status: completed / failed / blocked |
| `auto_healer_confidence_score` | Histogram | Traffic light score distribution |
| `auto_healer_fix_duration_seconds` | Histogram | End-to-end pipeline duration |
| `auto_healer_quality_gate_results` | Counter | Bandit / Pylint pass & fail counts |
| `agent_model_switch_total` | Counter | LLM fallback switches per agent |
| `agent_tokens_used` | Gauge | Tokens used this hour per agent |

### Statistics API — `GET /api/stats`

Returns a live snapshot:

```json
{
  "workflows":   { "by_status": {"COMPLETED": 40, "AWAITING_REVIEW": 2, "BLOCKED": 5} },
  "cost":        { "session_total_usd": 0.023, "avg_cost_per_build_usd": 0.0005 },
  "audit_log":   { "event_counts": { "pipeline_start": 47, "regression_detected": 1 } },
  "regression_monitor": { "active_fix_watches": [...] },
  "adaptive_thresholds": { "ASSERTION_ERROR": { "green_threshold": 0.78, "adapted": true } }
}
```

### Resilience — Circuit Breaker

CLOSED → (5 failures / 60 s) → OPEN → (30 s cooldown) → HALF_OPEN → CLOSED

Independent breaker per service: NIM API, GitHub API, Slack, Teams.

---

## 13. GitHub PR Report

Every auto-heal fix opens a GitHub Pull Request with a detailed structured report. All content is in **English**.

### PR Report Sections

| Section | Content |
|---|---|
| 📊 **Summary** | Build ID, traffic light, confidence + 🟩🟨🟥 emoji bar, **Decision Reason** (e.g. "1 file, 19 bugs, confidence 95%"), **Architecture Layer** (e.g. "⚙️ Backend · API endpoint · FastAPI · Python on CPython · 🔗 also: DATABASE · ⚠️ +15% risk"), error type, blast radius, **bugs found** (token-level diff count), AI attempts, **model used** (e.g. `qwen/qwen2.5-coder-32b-instruct`), time to fix |
| 🔍 **Error Analysis** | Root cause, error type detail, blast radius explanation |
| 🐛 **Bug Report** | Per-bug list with exact line numbers and AUTO-HEAL descriptions (from token-level diff) |
| 🛠️ **Fix Strategy** | AI explanation of fix approach + detailed description |
| 📁 **Affected Files** | List of all files modified |
| 🔄 **Full File Before vs After** | Collapsible: **annotated** original with `# ← BUG: <description>` markers + fixed file with `# AUTO-HEAL:` comments |
| 🔒 **Security Analysis** | Bandit scan results on the generated fix |
| ⚠️ **Regression Risk** | LLM-produced assessment of side-effects (falls back to layer-specific risk note when LLM is silent) |
| 🧪 **Test Recommendations** | LLM-produced concrete test suggestions for the specific fix |
| 🤖 **Agent Pipeline** | Visual diagram of the 4-step pipeline with attempt count |
| 📝 **Full Patch** | Collapsible raw patch (up to 8000 chars) |

### Annotated BEFORE File

The original buggy file is rendered with inline `# ← BUG:` markers — every bug is visible at a glance:

```python
def partition(arr, l, h):
    piv = arr[h + 1]    # ← BUG: correct pivot
    idx = l + 1         # ← BUG: corrected start index
    for k in range(l, l):   # ← BUG: fixed upper bound
        if arr[k] > piv:    # ← BUG: corrected to '<'
```

### Bug Report Format

The PR Bug Report uses the token-level diff result. Each entry shows the line number and the AUTO-HEAL description the AI wrote inline:

```
🐛 Bug Report — 19 bug(s) with exact line numbers

1. 🔴 Line 2: was 'arr[h + 1]' (out of bounds) -> correct pivot
2. 🔴 Line 3: was 'l + 1' (off-by-one) -> corrected start index
3. 🔴 Line 5: was 'range(l, l)' (empty range) -> fixed upper bound
4. 🔴 Line 6: was 'arr[k] > piv' (wrong comparison) -> corrected to '<'
...
```

The annotated **BEFORE** file shows each bug inline so reviewers can see them in context:

```python
def partition(arr, l, h):
    piv = arr[h + 1]    # ← BUG: correct pivot
    idx = l + 1         # ← BUG: corrected start index
    for k in range(l, l):   # ← BUG: fixed upper bound
        if arr[k] > piv:    # ← BUG: corrected to '<'
```

This makes it immediately clear **what was wrong on which line** and **exactly what the fix is**.

---

## 14. Slack Integration

### GREEN & YELLOW — Detailed Review Message (HITL Enforced)

Both GREEN and YELLOW fixes send a rich Slack message with full analysis + Approve/Reject buttons. All text is in **English**.

**What the Slack message contains:**

| Section | Content |
|---|---|
| Header | Colour-coded title (🚀 GREEN / ⚠️ YELLOW / 🚨 RED) |
| Status banner | Status label, **emoji confidence bar** (🟩🟨🟥), time to fix, PR link |
| Build info (2-column) | Build ID, error type, blast radius, **bug count** |
| 🏛️ Architecture | Layer (🎨/⚙️/🗄️/🐳/🧪/📱/🧠), sub-layer, framework, language, runtime, cross-layers, risk note |
| 🔍 Root cause | One-line root cause |
| 🐛 Bugs preview | Top 3 bugs with line numbers + AUTO-HEAL descriptions |
| 🔍 "View all N bugs on GitHub" | Button (when bugs > 3) — opens PR for full list |
| 🛠️ What the AI fixed | Phase-by-phase explanation |
| 🔴/✅ Before/After | Code snippets |
| Action buttons | **✅ Approve & Merge** / **❌ Reject** |
| Footer | Bot name + build ID + HITL reminder |

**Example Slack message:**
```
🚀  Auto-Heal Fix Ready — Fast-Track Review
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Status   ›  🟢 HIGH CONFIDENCE
Confidence ›  🟩🟩🟩🟩🟩🟩🟩🟩🟩⬜  95%
⏱️  Fixed in 24s  |  🔗  View PR on GitHub

🆔 Build ID          📁 Error Type
`25615749991`        `SYNTAX_ERROR`

💥 Blast Radius      🐛 Bugs Found
`LOW`                19 bug(s)

🏛️ Architecture — ⚙️ Backend · API endpoint · `FastAPI` · `Python` on `CPython`
_API contract may have changed — re-test all consuming clients (frontend, mobile, integrations)._

🔍 Root Cause
> SyntaxError: expected ':'

🐛 Bugs — 19 found & fixed
1. 🔴 Line 2: was 'arr[h + 1]' (out of bounds) -> correct pivot
2. 🔴 Line 3: was 'l + 1' (off-by-one) -> corrected start index
3. 🔴 Line 5: was 'range(l, l)' (empty range) -> fixed upper bound
   ...and 16 more

[ 🔍 Visa alla 19 buggar på GitHub ]

🛠️ What the AI fixed
_Phase 1: ... Phase 2: ... Phase 3: ..._

🔴 Before (buggy)       ✅ After (fixed)
[code]                  [code]

[ ✅ Approve & Merge ]  [ ❌ Reject ]

🤖 Auto-Heal Bot  •  Build `25615749991`  •  All merges require human approval
```

The **confidence bar colour** matches the traffic light: 🟩 GREEN, 🟨 YELLOW, 🟥 RED — instantly recognisable.

Human clicks feed back to `fix_memory` and `adaptive_thresholds`.

### RED & BLOCKED — Immediate Alert

```
🚨  Auto-Heal Fix Blocked — Manual Intervention

Status   ›  🔴 FIX BLOCKED
Confidence ›  🟥🟥🟥🟥⬜⬜⬜⬜⬜⬜  45%
⏱️  Failed in 18s  |  🚫  No PR created

🆔 Build ID: build-12345
📁 Files: src/complex_module.py
💥 Reason: AI confidence too low (45% < 60%)

Manual intervention required.
```

This also fires for:
- **Regression loops** — same file failed again with same error type after retry already used
- **422 too-complex** — fix generation rejected as structurally unrecoverable
- **>5 files affected** — change scope too wide
- **>30 bugs in any file** — file too broken for reliable AI fix

### `/autoheal` Slash Commands

All commands return rich Block Kit messages with emoji, two-column layouts, and action buttons.
Build IDs work with or without prefixes — `25643594071`, `build 25643594071`, `#25643594071`, and `id: 25643594071` all resolve to the same build.

#### 🔍 Inspect commands

| Command | Example | What it shows |
|---|---|---|
| `/autoheal help` | `/autoheal help` | 🤖 Grouped command menu with all sub-commands and tips |
| `/autoheal status <build_id>` | `/autoheal status 25643594071` | 🚦 Build status (PENDING / ANALYSING / GENERATING_FIX / AWAITING_REVIEW / COMPLETED / BLOCKED), last update, error message |
| `/autoheal list` | `/autoheal list` | 📋 Last 10 active workflows with status emoji per row |
| `/autoheal explain <build_id>` | `/autoheal explain 25643594071` | 📝 Plain-English fix explanation: root cause, files changed, what AI did, human approve/reject status, button to open PR |

#### ♻️ Action commands

| Command | Example | What it does |
|---|---|---|
| `/autoheal retry <build_id>` | `/autoheal retry 25643594071` | ♻️ Re-submits the build to the orchestrator pipeline |
| `/autoheal rollback <build_id>` | `/autoheal rollback 25643594071` | 🔙 Closes the auto-heal PR on GitHub (undoes the fix) |

#### 📊 Insight commands

| Command | Example | What it shows |
|---|---|---|
| `/autoheal stats` | `/autoheal stats` | 📈 Fix success rates per error type: total count + 🟢 / 🟡 / 🔴 percentages |
| `/autoheal history <file>` | `/autoheal history quicksort.py` | 📜 Last 8 fixes for a file with date, error type, confidence, and approval status |
| `/autoheal top` | `/autoheal top` | 🏆 Most failure-prone files (medals 🥇🥈🥉 + visual failure bars) |
| `/autoheal thresholds` | `/autoheal thresholds` | 🎚️ Per-error-type GREEN/YELLOW thresholds. ⭐ marks adaptive (self-adjusted) values |

#### Example responses

**`/autoheal status 25643594071`:**
```
🟡  Build Status

🆔 Build           📊 Status
25643594071        AWAITING_REVIEW

🕒 Updated         🚦 State
01:38 UTC          🟡 AWAITING_REVIEW
```

**`/autoheal stats`:**
```
📈  Fix Success Rates by Error Type

🐛 SYNTAX_ERROR — 12 fix(es)
     🟢 83%   🟡 8%   🔴 8%

🐛 TEST_FAILURE — 5 fix(es)
     🟢 60%   🟡 20%   🔴 20%
```

**`/autoheal top`:**
```
🏆  Most Troubled Files

🥇  quicksort.py — 5 failure(s)  🔴🔴🔴🔴🔴
🥈  utils.py    — 3 failure(s)  🔴🔴🔴
🥉  parser.py   — 2 failure(s)  🔴🔴
📁  main.py     — 1 failure(s)  🔴

🎯 These files might benefit from refactoring or extra test coverage.
```

**Error responses are also helpful:**
```
❌  Build `99999` not found

💡 Tip: Use `/autoheal list` to see active builds, or check the
        Jenkins build number is correct.
🤖 Run `/autoheal help` to see all commands
```

#### Security

- All slash-command requests verified with HMAC-SHA256 signature
- 5-minute replay-attack window
- Requests signed with `SLACK_SIGNING_SECRET` env var

### Daily Digest

Every morning at 08:00 UTC: builds processed, success rates, top error types, troubled files, threshold adaptations, regression watch status.

---

## 15. Test Suite

**639 unit tests passing** · 23 traffic-light tests need updating (still test the deprecated blast-radius score formula — the new logic uses files + bugs/file + AI confidence, see Section 5)

<details>
<summary>Unit test coverage (click to expand)</summary>

| Category | Key tests |
|---|---|
| Fix Memory | record, query, Jaccard similarity, approval stamps |
| Adaptive Thresholds | calibration algorithm, safe bounds, cache |
| Heal Verifier | regression detection, file overlap, expiry |
| Secret Scanner | all 11 patterns, safe-pattern exclusions |
| Quality Gates | Bandit scan, real Pylint score, confidence modifiers |
| Fix Helpers | NoneType hint, 14 runtime error hints, fingerprint, strategy pivot, emergency rewrite |
| Bug Scanner | 63 AST patterns: accumulator init, mutable class attr, assert-tuple, shared list multiply, etc. |
| Circuit Breaker | CLOSED → OPEN → HALF_OPEN → CLOSED |
| Model Fallback | chain, AllModelsFailed, slot reset |
| Workflow Engine | state transitions, InvalidTransitionError, pruning |
| GitHub Webhook | HMAC signature, branch parsing |
| Traffic Light | file + bug + confidence rules, RED overrides, adaptive floor |
| Architecture Classifier | 152 frameworks, 82 languages, 55 sub-layers, cross-layer detection, severity boosts |
| Diff Bug Counter | token-level diff, whitespace normalisation, AUTO-HEAL parsing |
| Log Cleaner | each of 5 filters individually + full pipeline |
| Error Analyst | all 11 error types, pytest format, blast radius |
| Code Repairer | parsing, retry, FixTooLongError, SecretLeakError |
| Gerrit MCP | PR creation, rate-limit headers, code fetching |

</details>

<details>
<summary>Integration tests</summary>

| File | What it verifies |
|---|---|
| `test_full_pipeline.py` | GREEN/YELLOW path, 400/413/429, dedup, fix_memory |
| `test_analysis_pipeline.py` | Log cleaner → error analyst → traffic light chain |
| `test_global_fallback.py` | Agent crash → RED notification, FAILED state |
| `test_quality_gates_integration.py` | Bandit + Pylint in pipeline context |
| `test_smoke.py` | ⚠️ Requires live Docker: health, /metrics |
| `test_load.py` | ⚠️ Requires live Docker: concurrent pipelines |

</details>

```bash
# All unit tests (no Docker needed)
python3 -m pytest tests/unit/ -v

# Full suite
python3 -m pytest tests/ -q
```

---

## 16. Installation & Setup

### Requirements

- Docker Desktop (WSL2 on Windows)
- Python 3.11+
- ngrok account (free tier)
- GitHub repo + Slack workspace app

### Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/Mouaz7/auto-healing-devops-platform.git
cd auto-healing-devops-platform
cp .env.example .env
# Fill in your API keys in .env

# 2. Start all 8 services
docker compose up --build

# 3. Expose the orchestrator (new terminal)
ngrok http --url=<your-static-domain> 8085

# 4. Verify
curl http://localhost:8085/health
# → {"status": "ok", "service": "orchestrator_mcp"}
```

### GitHub Actions Workflow

The `.github/workflows/auto-heal.yml` already handles the loop:

```yaml
- name: Trigger Auto-Healing on failure
  # Loop guard: auto-heal commits must not re-trigger the healer
  if: |
    failure() &&
    !startsWith(github.event.head_commit.message, 'auto-heal')
  run: |
    curl -X POST https://YOUR-DOMAIN.ngrok-free.dev/tools/handle_build_failure \
      -H "Content-Type: application/json" \
      -d '{
        "build_id": "${{ github.run_id }}",
        "repo":     "${{ github.repository }}",
        "raw_log":  "..."
      }'
```

### Slack App Setup

1. **Interactivity & Shortcuts** → Request URL: `https://your-domain/webhooks/slack`
2. **Slash Commands** → `/autoheal` → `https://your-domain/webhooks/slack/commands`
3. **Basic Information** → copy `Signing Secret` → `SLACK_SIGNING_SECRET` in `.env`
4. **Incoming Webhooks** → copy URL → `SLACK_WEBHOOK_URL` in `.env`

### GitHub Webhook

Settings → Webhooks → Add webhook:
- URL: `https://your-domain/webhooks/github`
- Events: `Pull requests` + `Pull request reviews`
- Secret: matches `GITHUB_WEBHOOK_SECRET` in `.env`

---

## 17. Environment Variables

### Required

| Variable | Description |
|---|---|
| `NVIDIA_NIM_BASE_URL` | NVIDIA NIM API base URL |
| `CODE_REPAIRER_PRIMARY_API_KEY` | API key for Agent 5 |
| `CODE_REPAIRER_PRIMARY_MODEL` | Model name for Agent 5 |
| `ERROR_ANALYST_PRIMARY_API_KEY` | API key for Agent 4 |
| `ERROR_ANALYST_PRIMARY_MODEL` | Model name for Agent 4 |
| `LOG_ANALYST_PRIMARY_API_KEY` | API key for Agent 3 |
| `LOG_ANALYST_PRIMARY_MODEL` | Model name for Agent 3 |
| `REVIEW_NOTIFY_PRIMARY_API_KEY` | API key for Agent 6 |
| `REVIEW_NOTIFY_PRIMARY_MODEL` | Model name for Agent 6 |
| `GITHUB_TOKEN` | Personal Access Token (scopes: `repo`, `workflow`) |
| `GITHUB_REPO` | Target repo in `owner/repo` format |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL |

### Recommended

| Variable | Description |
|---|---|
| `GITHUB_WEBHOOK_SECRET` | HMAC secret for GitHub webhook verification |
| `SLACK_SIGNING_SECRET` | HMAC secret for Slack verification |
| `*_FALLBACK_1/2/3` + `*_FALLBACK_1/2/3_API_KEY` | Fallback models per agent |

<details>
<summary>Optional variables with defaults</summary>

| Variable | Default | Description |
|---|---|---|
| `FIX_MEMORY_PATH` | `/var/log/auto-healer/fix_memory.jsonl` | AI fix history (persisted via `autoheal-data` Docker volume) |
| `ADAPTIVE_THRESHOLDS_PATH` | `/var/log/auto-healer/adaptive_thresholds.jsonl` | Threshold learning (persisted) |
| `AUDIT_LOG_PATH` | `/var/log/auto-healer/audit.jsonl` | Audit trail (persisted) |
| `MODEL_LOW_PRIMARY` | `qwen/qwen2.5-coder-7b-instruct` | LOW complexity model |
| `MODEL_MED_PRIMARY` | `qwen/qwen2.5-coder-32b-instruct` | MEDIUM complexity model |
| `DIGEST_HOUR_UTC` | `8` | Daily Slack digest hour |
| `SCHEDULE_INTERVAL_MINUTES` | `15` | GitHub Issues polling interval |

</details>

### Docker Resource Limits

| Container | CPU | Memory |
|---|---|---|
| `orchestrator-mcp` | 1.00 | 512 MB |
| `llm-mcp` | 1.00 | 512 MB |
| `knowledge-graph-mcp` | 1.00 | 512 MB |
| `log-cleaner-mcp` | 0.50 | 256 MB |
| `gerrit-mcp` | 0.50 | 256 MB |
| `notification-mcp` | 0.50 | 256 MB |
| `jenkins-mcp` | 0.25 | 128 MB |
| `scheduler` | 0.25 | 128 MB |

---

## 18. Project Structure

```
auto-healing-devops-platform/
├── docker-compose.yml              # 8 services, resource limits, agent-network
├── Dockerfile                      # Multi-stage build
├── pyproject.toml                  # Dependencies (bandit + pylint in main deps)
├── .env.example
│
├── src/
│   ├── shared/                     # Shared infrastructure
│   │   ├── architecture_classifier.py  # 7 layers · 152 frameworks · 82 languages · 55 sub-layers
│   │   ├── quality_gates.py        # Bandit + Pylint quality gates
│   │   ├── audit_log.py            # Append-only JSONL audit trail
│   │   ├── fix_memory.py           # AI learning from past outcomes
│   │   ├── adaptive_thresholds.py  # Self-calibrating confidence floor per error type
│   │   ├── heal_verifier.py        # 60-min regression watch with smart retry
│   │   ├── secret_scanner.py       # 11-pattern hardcoded credential detection
│   │   ├── prompt_compressor.py    # ~90% token reduction
│   │   ├── task_complexity.py      # Deterministic complexity scorer
│   │   ├── resilience.py           # Circuit breaker + global fallback
│   │   ├── nim_client.py           # NVIDIA NIM client, 4-slot fallback + last_model tracking
│   │   └── models.py               # Domain models, enums
│   │
│   ├── orchestrator_mcp/           # :8085 — Central pipeline controller
│   │   ├── pipeline_mixin.py       # handle_build_failure + Agent 3→4→5→6
│   │   ├── github_mixin.py         # PR creation (HITL — auto-merge disabled)
│   │   ├── slack_mixin.py          # Approve / Reject button handler
│   │   ├── workflow.py             # State machine + pruning
│   │   └── deduplication.py        # 24h error fingerprint cache
│   │
│   ├── llm_mcp/                    # :8086 — Agent 5, Code Repairer
│   │   ├── fix_generator.py        # Retry loop: LLM → validate → Bandit → Pylint
│   │   ├── bug_scanner.py          # 63-pattern AST scanner injected before LLM prompt
│   │   ├── fix_validators.py       # AST + sandboxed run + 14 runtime error hints
│   │   ├── fix_prompts.py          # Retry prompt builder + stuck-loop pivot + emergency rewrite
│   │   └── fix_parsers.py          # Surgical patch + JSON parser
│   │
│   ├── knowledge_graph_mcp/        # :8084 — Agent 4, Error Analyst
│   │   ├── failure_analyser.py     # Regex + LLM, 11 error types, blast radius
│   │   └── dependency_tracker.py
│   │
│   ├── log_cleaner_mcp/            # :8081 — Agent 3
│   │   ├── pipeline.py             # 5-stage cleaning + LLM fallback
│   │   └── filters/                # ansi · timestamp · dedup · noise · stacktrace
│   │
│   ├── notification_mcp/           # :8087 — Agent 6, Review & Notify
│   │   ├── traffic_light_evaluator.py  # file + bug/file + confidence rules
│   │   ├── slack_notifier.py           # Block Kit, emoji bars (🟩🟨🟥), Architecture section
│   │   ├── slack_slash_handler.py      # 9 slash commands (+ help fallback) with build-id prefix stripping
│   │   ├── slash_responses.py          # Rich Block Kit responses with emoji + helpful errors
│   │   └── teams_notifier.py
│   │
│   ├── gerrit_mcp/                 # :8083 — GitHub PR manager
│   │   ├── patch_submitter.py      # Branch, commit, PR, rate-limit handling
│   │   └── gerrit_helpers.py       # Protected paths, sanitize_files
│   │
│   └── scheduler/                  # Background tasks
│       ├── daily_digest.py         # Morning Slack intelligence report
│       └── task_classifier.py      # Agent 2: Scenario A/B classification
│
└── tests/
    ├── unit/                       # 639 passing (no Docker)
    └── integration/                # End-to-end pipeline tests
```

---

## 19. Authors

| Name | Email | Program |
|---|---|---|
| Ahmad Darwich | ahda23@student.bth.se | Software Engineering |
| Mouaz Naji | moap23@student.bth.se | Software Engineering |

**Supervisor:** Ahmad Nauman Ghazi — nauman.ghazi@bth.se  
**Institution:** Blekinge Tekniska Högskola (BTH), Sweden  
**Course:** PA2534 — Kandidatarbete i Programvaruteknik  
**Title:** *Automated Remediation in CI/CD: Design and Control of an AI-based Code Repair Agent*

---

<div align="center">

*This project is a bachelor thesis prototype and is not licensed for commercial use.*

</div>
