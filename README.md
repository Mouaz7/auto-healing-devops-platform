<div align="center">

# 🤖 Auto-Healing AI DevOps Platform

### Automated Remediation in CI/CD: Design and Control of an AI-based Code Repair Agent

[![Tests](https://img.shields.io/badge/tests-653%20passing-brightgreen?style=flat-square)](tests/)
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
6. [Workflow State Machine](#6-workflow-state-machine)
7. [AI Model System](#7-ai-model-system)
8. [AI Memory & Learning](#8-ai-memory--learning)
9. [Log Processing Pipeline](#9-log-processing-pipeline)
10. [Observability & Monitoring](#10-observability--monitoring)
11. [Slack Integration](#11-slack-integration)
12. [Test Suite](#12-test-suite)
13. [Installation & Setup](#13-installation--setup)
14. [Environment Variables](#14-environment-variables)
15. [Project Structure](#15-project-structure)
16. [Authors](#16-authors)

---

## 1. Research Questions & Code Mapping

> This codebase is the PoC artifact for thesis **PA2534**. Every research question maps directly to running code.

### RQ1 — How should an AI code repair agent be designed to detect and fix build failures from logs?

| Design Decision | Code Location |
|---|---|
| 6-agent pipeline: clean → analyse → fetch → generate → evaluate → notify | `src/orchestrator_mcp/pipeline_mixin.py` |
| 5-stage log compression, ~90% token reduction before LLM | `src/log_cleaner_mcp/pipeline.py` |
| Regex + LLM fallback error analysis for 6 error types, blast radius | `src/knowledge_graph_mcp/failure_analyser.py` |
| Fix generation: retry loop 6–14 attempts, surgical patch or full rewrite | `src/llm_mcp/fix_generator.py` |
| Proactive AST bug scanner: 63 patterns injected into prompt before LLM sees traceback | `src/llm_mcp/bug_scanner.py` |
| 14 runtime error hints: NoneType, IndexError, KeyError, RecursionError, ZeroDivision, etc. | `src/llm_mcp/fix_validators.py` |
| Stuck-loop pivot: identical error type twice → strategy change in prompt | `src/llm_mcp/fix_prompts.py:45` |
| 4-model fallback chain per agent, complexity-based model routing | `src/shared/nim_client.py`, `src/shared/task_complexity.py` |

### RQ2 — What control mechanisms are required to prevent unsafe changes or technical debt?

| Control Mechanism | What it does | Code Location |
|---|---|---|
| **Human-in-the-Loop (enforced)** | Auto-merge permanently **disabled** for all confidence levels. GREEN = fast-track review, YELLOW = careful review. Both send Slack Approve/Reject buttons. | `src/orchestrator_mcp/github_mixin.py:94` |
| **Transparent confidence score** | Every Slack notification shows the exact score and threshold: "High confidence — fix proposed for review (score 97%, threshold 85%)". | `src/notification_mcp/traffic_light_evaluator.py` |
| **BLOCKED-state notification** | Regression loops and 422-rejected fixes send Slack RED alert immediately — no silent failures. | `src/orchestrator_mcp/pipeline_mixin.py:200` |
| **Bandit security scan** | Scans every generated fix for HIGH-severity issues. Triggers LLM retry with feedback. | `src/shared/quality_gates.py` |
| **Pylint linting (real score)** | Real weighted score via `--output-format=json2`. Low score reduces confidence modifier (−0.20 or −0.40). | `src/shared/quality_gates.py` |
| **Secret scanner** | 11 regex patterns block hardcoded credentials before any GitHub push. | `src/shared/secret_scanner.py` |
| **Audit trail** | Append-only JSONL log — every pipeline event with UTC timestamp. | `src/shared/audit_log.py` |
| **Regression loop prevention** | Same files fail again after recent fix → workflow → BLOCKED + Slack RED. | `src/orchestrator_mcp/pipeline_mixin.py` |
| **Retry limits** | Max 6–14 attempts by bug complexity. `FixStillBrokenError` on exhaustion. | `src/llm_mcp/fix_generator.py:254` |
| **CI loop guard** | `!startsWith(commit.message, 'auto-heal')` — healer commits never re-trigger the healer. | `.github/workflows/auto-heal.yml` |
| **Protected paths** | AI cannot modify `.github/`, `Dockerfile`, `pyproject.toml`, or infra files. | `src/gerrit_mcp/gerrit_helpers.py:is_protected_path` |
| **Deduplication** | MD5 fingerprint of error+files prevents re-processing the same failure for 24 h. | `src/orchestrator_mcp/deduplication.py` |

### RQ3 — What are the primary barriers to trust, and how does the design address them?

| Trust Barrier | Architectural Mitigation | Code Location |
|---|---|---|
| AI introduces security vulnerabilities | Bandit scan → retry or block | `src/shared/quality_gates.py` |
| AI produces low-quality code | Pylint real score → confidence penalty | `src/shared/quality_gates.py` |
| AI hallucinates wrong fixes | AST parse + sandboxed subprocess run + 14 runtime hints before accepting | `src/llm_mcp/fix_validators.py` |
| AI targets symptom not root cause | 63-pattern static scanner pre-annotates code with bug locations before LLM call | `src/llm_mcp/bug_scanner.py` |
| AI cannot be trusted to merge | **Auto-merge disabled** — human clicks Merge on GitHub | `src/orchestrator_mcp/github_mixin.py` |
| No accountability or traceability | Audit trail + PR body with confidence, root cause, elapsed time | `src/shared/audit_log.py` |
| System loops infinitely | Regression block + CI guard prevent infinite repair cycles | `src/orchestrator_mcp/pipeline_mixin.py` |
| Confidence score is opaque | Exact score + threshold shown in every notification: "fix proposed for review (score 97%, threshold 85%)". `auto_merge_allowed` always `False`. | `src/notification_mcp/traffic_light_evaluator.py` |
| Thresholds don't fit the domain | Adaptive thresholds self-calibrate from human approve/reject decisions | `src/shared/adaptive_thresholds.py` |

---

## 2. Architecture — The 6 Agents

```
┌──────────────────────────────────────────────────────┐
│           GitHub Actions  ──►  ngrok tunnel           │
│         POST /tools/handle_build_failure              │
└──────────────────────┬───────────────────────────────┘
                       │
              ┌────────▼────────┐
              │   Orchestrator  │  :8085
              │  State machine  │  Pipeline control
              │  Dedup · Rate   │  Cost tracking
              └────────┬────────┘
        ┌──────────────┼──────────────────┐
        │              │                  │
┌───────▼──────┐ ┌─────▼──────┐  ┌───────▼──────┐
│  Agent 3     │ │  Agent 4   │  │   Agent 5    │
│  Log Cleaner │ │  Error     │  │  Code        │
│  :8081       │ │  Analyst   │  │  Repairer    │
│  5-stage     │ │  :8084     │  │  :8086       │
│  regex +     │ │  Regex +   │  │  Fix memory  │
│  LLM fallbk  │ │  blast rad │  │  + Bandit    │
└──────────────┘ └────────────┘  │  + Pylint    │
                                  └───────┬──────┘
                                          │
                                 ┌────────▼────────┐
                                 │   Agent 6       │
                                 │  Review & Notify│
                                 │  :8087          │
                                 │  Adaptive TL    │
                                 │  Slack · Teams  │
                                 └─────────────────┘

Supporting services:
  Gerrit MCP :8083 — GitHub PR creation, branch management
  Jenkins MCP :8082 — Agent 1, pipeline monitor
  Scheduler — daily digest, task polling
```

| Agent | Role |
|---|---|
| **Agent 1** — Pipeline Monitor (`:8082`) | Polls GitHub Issues/Jenkins, classifies tasks |
| **Agent 3** — Log Analyst (`:8081`) | 5-stage regex + LLM fallback log compression |
| **Agent 4** — Error Analyst (`:8084`) | Regex + LLM analysis, blast radius, affected files |
| **Agent 5** — Code Repairer (`:8086`) | Fix generation with memory, Bandit, Pylint |
| **Agent 6** — Review & Notify (`:8087`) | Adaptive traffic light + Slack/Teams notification |
| **Orchestrator** (`:8085`) | Central pipeline, state machine, webhooks |

---

## 3. Pipeline Flow

```
POST /tools/handle_build_failure
  │
  ├─ Rate limit (10 req/60s)  ──────────────────────────► 429
  ├─ Payload size (> 500 KB)  ──────────────────────────► 413
  ├─ Duplicate build_id       ──────────────────────────► 409
  │
  ▼  [Agent 3]  Clean logs
     • Remove ANSI codes, timestamps, duplicate lines, noise
     • Extract stack traces  •  LLM fallback if < 50% reduction
  │
  ▼  [Agent 4]  Analyse failure
     • Regex → 6 error types  •  Blast radius (LOW / MEDIUM / HIGH)
     • Affected files from pytest output and tracebacks
  │
  ├─ Regression check ──────── same files recently fixed? ──► BLOCKED ⛔
  ├─ Deduplication ──────────── same error in 24 h?        ──► cached result
  │
  ▼  [Gerrit MCP]  Fetch file content (code context, max 3 files)
  │
  ▼  [Agent 5]  Generate fix
     • Inject fix memory (past 3 relevant outcomes)
     • Complexity score → model tier (7 B / 32 B / 70 B+)
     • LLM call  →  parse  →  apply patch
     • Secret scan  •  Bandit  •  Pylint
     • Retry on security issues (up to budget)
  │
  ▼  [Agent 6]  Evaluate & Notify
     • Adaptive traffic light: confidence × 0.6 + blast_score × 0.4
     • HIGH blast radius always forces 🔴 RED
  │
  ├─── 🟢 GREEN  ──► PR opened · Slack Approve / Reject buttons (fast-track)
  │                  Score shown: "High confidence — fix proposed for review (97%)"
  │                  Regression watch activated (60 min)
  │
  ├─── 🟡 YELLOW ──► PR opened · Slack Approve / Reject buttons (careful review)
  │                  Score shown: "Medium confidence — careful review required (72%)"
  │                  Human decision feeds adaptive thresholds + fix memory
  │
  ├─── 🔴 RED    ──► No PR · BLOCKED · Slack RED alert sent immediately
  │                  Score shown: "Low confidence — fix blocked (45% below 60%)"
  │                  Manual intervention required
  │
  └─── ⛔ BLOCKED ─► Regression loop OR 422 too-complex
                     Slack RED alert with reason · BLOCKED state in workflow
                     Audit event logged · no fix attempted
```

---

## 4. Control Mechanisms (RQ2)

### 🔒 Human-in-the-Loop — Always Enforced

Auto-merge is **permanently disabled** for all confidence levels. Every fix — even a GREEN fix at 99% confidence — requires explicit human approval before merging. The colour signals review urgency, not autonomous action:

| Colour | What it means for the reviewer |
|---|---|
| 🟢 GREEN | High confidence — **fast-track review** recommended. Check the diff briefly and merge if it looks right. |
| 🟡 YELLOW | Medium confidence — **careful review** required. Read the fix closely and consider testing locally. |
| 🔴 RED | Low confidence or HIGH blast radius — **fix is blocked**, no PR created. Manual intervention required. |

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

1. **Regression blocking** — `_check_regression()` returns `True` if the failing files were fixed within the last 60 minutes → workflow advances to `BLOCKED`, Slack RED alert sent immediately with the reason, no new fix generated
2. **CI guard** — GitHub Actions trigger steps require `!startsWith(head_commit.message, 'auto-heal')`, so healer commits never re-trigger the healer
3. **Protected paths** — AI cannot modify `.github/`, `Dockerfile`, `pyproject.toml`, `requirements.txt`, or any infra file

---

## 5. Traffic Light Safety System

### Score Formula

```
final_score = (llm_confidence × 0.6) + (blast_radius_score × 0.4)

Blast radius scores:
  LOW    → 1.0
  MEDIUM → 0.6
  HIGH   → 0.2  ── HIGH always forces 🔴 RED regardless of confidence
```

### Thresholds (adaptive per error type)

| Colour | Score | Reason text sent to Slack | Action |
|---|---|---|---|
| 🟢 **GREEN** | ≥ 0.85 | "High confidence — fix proposed for review (score X%, threshold 85%)" | PR opened · Slack Approve/Reject buttons (fast-track) · regression watch started |
| 🟡 **YELLOW** | 0.60–0.84 | "Medium confidence — careful human review required (score X%, threshold 60%)" | PR opened · Slack Approve/Reject buttons · 24 h review window |
| 🔴 **RED** | < 0.60 | "Low confidence — fix blocked (score X% below 60% threshold)" | No PR · Slack RED alert · workflow BLOCKED · manual intervention required |
| 🔴 **RED** (safety) | any | "Safety override: HIGH blast radius forces RED (score X%)" | No PR · Slack RED alert · workflow BLOCKED |

`auto_merge_allowed` is always `False` — the traffic light colour signals review urgency, not a merge decision.

Thresholds are **not fixed** — they self-calibrate per error type. After 5+ human decisions, `new_GREEN = mean(approved_confidences) − 0.03`. Stored in append-only JSONL, cached in memory.

---

## 6. Workflow State Machine

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
                             (RED traffic light / safety override)
                             + Slack RED

Any state ──► FAILED  (on unhandled agent exception)
```

- `AWAITING_REVIEW` older than **24 h** → auto-blocked (review window expired)
- Terminal states older than **48 h** → pruned from memory
- Pruning runs every **3600 s** as background asyncio task

---

## 7. AI Model System

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
| Log Analyst | 2 000 | 20 000 |
| Error Analyst | 3 000 | 30 000 |
| Code Repairer | 4 000 | 50 000 |
| Review & Notify | 2 000 | 20 000 |

Global budget: **135 000 tokens/hour**. Warning at 80%.

### Cost Tracking

Per-build API cost estimated from model size tiers. Warns when a single build exceeds $0.10. Session totals in `/api/stats`.

---

## 8. AI Memory & Learning

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

After 5+ human decisions for an error type:
- `new_GREEN  = mean(approved_confidences) − 0.03`
- `new_YELLOW = mean(rejected_confidences) + 0.03`
- Safe bounds: GREEN ∈ [0.70, 0.95], YELLOW ∈ [0.45, 0.80]

### Regression Watch (`src/shared/heal_verifier.py`)

After every fix, affected files are watched for **60 minutes**. Re-failure on the same files → `regression_detected` audit event + pipeline blocked.

---

## 9. Proactive Bug Scanner (Agent 5)

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

## 10. Log Processing Pipeline

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

## 11. Observability & Monitoring

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

## 12. Slack Integration

### GREEN & YELLOW — Interactive Review Buttons (HITL Enforced)

Both GREEN and YELLOW fixes send Slack Approve/Reject buttons. The difference is review urgency, not process:

**GREEN (fast-track):**
```
✅ Auto-fix Proposed (Review Required)
Build: build-12345  |  Confidence: 97%  |  Blast radius: LOW
High confidence — fix proposed for review (score 97%, threshold 85%)
Files: src/utils.py
Duration: 42s

PR: [View on GitHub →]

[✅ Approve & Merge]    [❌ Reject]
```

**YELLOW (careful review):**
```
🟡 Human Review Required
Build: build-12345  |  Confidence: 74%  |  Blast radius: LOW
Medium confidence — careful human review required (score 74%, threshold 60%)
Files: src/utils.py
Duration: 58s

PR: [View on GitHub →]

[✅ Approve & Merge]    [❌ Reject]
```

Human clicks feed back to `fix_memory` and `adaptive_thresholds`.

### RED & BLOCKED — Immediate Alert

```
🔴 Fix Blocked
Build: build-12345
Low confidence — fix blocked (score 45% below 60% threshold)
Files: src/complex_module.py
Duration: 120s  |  Manual intervention required.
```

This also fires for regression loops ("Regression loop detected — same file fixed recently") and 422-rejected fixes ("Fix generation rejected — too complex").

### `/autoheal` Slash Commands (9 commands)

| Command | Description |
|---|---|
| `/autoheal status <build_id>` | Workflow state, colour, last update |
| `/autoheal list` | Last 10 workflows with colour emoji |
| `/autoheal stats` | Fix success rates by error type |
| `/autoheal retry <build_id>` | Re-submit a failed build |
| `/autoheal explain <build_id>` | Plain-English explanation of the fix |
| `/autoheal rollback <build_id>` | Close the associated PR |
| `/autoheal history <file>` | All past fixes for a specific file |
| `/autoheal top` | Most problematic files (by failure count) |
| `/autoheal thresholds` | Current adaptive thresholds per error type |

All slash commands verified with HMAC-SHA256 signature + 5-minute replay-attack window.

### Daily Digest

Every morning at 08:00 UTC: builds processed, success rates, top error types, troubled files, threshold adaptations, regression watch status.

---

## 13. Test Suite

**653 tests passing** · 9 pre-existing failures in blast-radius tests (unrelated to any recent changes)

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
| Traffic Light | adaptive thresholds, safety override, score formula |
| Log Cleaner | each of 5 filters individually + full pipeline |
| Error Analyst | all 6 error types, pytest format, blast radius |
| Code Repairer | parsing, retry, FixTooLongError, SecretLeakError |
| Gerrit MCP | PR creation, rate-limit headers, code fetching |

</details>

<details>
<summary>Integration tests</summary>

| File | What it verifies |
|---|---|
| `test_full_pipeline.py` | GREEN/YELLOW path, 400/409/413/429, dedup, fix_memory |
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

## 14. Installation & Setup

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

## 15. Environment Variables

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
| `FIX_MEMORY_PATH` | `/var/log/auto-healer/fix_memory.jsonl` | AI fix history |
| `ADAPTIVE_THRESHOLDS_PATH` | `/var/log/auto-healer/adaptive_thresholds.jsonl` | Threshold learning |
| `AUDIT_LOG_PATH` | `/var/log/auto-healer/audit.jsonl` | Audit trail |
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

## 16. Project Structure

```
auto-healing-devops-platform/
├── docker-compose.yml              # 8 services, resource limits, agent-network
├── Dockerfile                      # Multi-stage build
├── pyproject.toml                  # Dependencies (bandit + pylint in main deps)
├── .env.example
│
├── src/
│   ├── shared/                     # Shared infrastructure
│   │   ├── quality_gates.py        # Bandit + Pylint quality gates
│   │   ├── audit_log.py            # Append-only JSONL audit trail
│   │   ├── fix_memory.py           # AI learning from past outcomes
│   │   ├── adaptive_thresholds.py  # Self-calibrating traffic light thresholds
│   │   ├── heal_verifier.py        # 60-min regression watch
│   │   ├── secret_scanner.py       # 11-pattern hardcoded credential detection
│   │   ├── prompt_compressor.py    # ~90% token reduction
│   │   ├── task_complexity.py      # Deterministic complexity scorer
│   │   ├── resilience.py           # Circuit breaker + global fallback
│   │   ├── nim_client.py           # NVIDIA NIM client, 4-slot fallback
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
│   │   ├── failure_analyser.py     # Regex + LLM, 6 error types, blast radius
│   │   └── dependency_tracker.py
│   │
│   ├── log_cleaner_mcp/            # :8081 — Agent 3
│   │   ├── pipeline.py             # 5-stage cleaning + LLM fallback
│   │   └── filters/                # ansi · timestamp · dedup · noise · stacktrace
│   │
│   ├── notification_mcp/           # :8087 — Agent 6, Review & Notify
│   │   ├── traffic_light_evaluator.py  # Adaptive thresholds
│   │   ├── slack_notifier.py           # Block Kit + interactive buttons
│   │   ├── slack_slash_handler.py      # 9 slash commands
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
    ├── unit/                       # 653 passing (no Docker)
    └── integration/                # End-to-end pipeline tests
```

---

## 17. Authors

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
