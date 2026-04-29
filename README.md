# Auto-Healing AI DevOps Platform

[![Built with Claude Code](https://img.shields.io/badge/Built%20with-Claude%20Code-orange?logo=anthropic)](https://claude.ai/code)
[![Tests](https://img.shields.io/badge/tests-540%20passing-brightgreen)](tests/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/thesis-BTH%202026-lightgrey)](https://www.bth.se)

> **Automated Remediation in CI/CD: Design and Control of an AI-based Code Repair Agent**
>
> Bachelor Thesis — Blekinge Tekniska Högskola (BTH), 2026

---

## Innehållsförteckning / Table of Contents

1. [What the System Does](#1-what-the-system-does)
2. [The 6 Agents — Architecture](#2-the-6-agents--architecture)
3. [Complete Pipeline Flow](#3-complete-pipeline-flow)
4. [Workflow State Machine](#4-workflow-state-machine)
5. [AI Model System](#5-ai-model-system)
6. [Traffic Light Safety System](#6-traffic-light-safety-system)
7. [AI Memory & Learning](#7-ai-memory--learning)
8. [Adaptive Confidence Thresholds](#8-adaptive-confidence-thresholds)
9. [Regression Detection](#9-regression-detection)
10. [Log Processing Pipeline](#10-log-processing-pipeline)
11. [Security Features](#11-security-features)
12. [Token & Cost Optimization](#12-token--cost-optimization)
13. [Resilience System](#13-resilience-system)
14. [Slack Integration](#14-slack-integration)
15. [Prometheus Metrics](#15-prometheus-metrics)
16. [Monitoring & Statistics API](#16-monitoring--statistics-api)
17. [All API Endpoints](#17-all-api-endpoints)
18. [Complete Module Reference](#18-complete-module-reference)
19. [Test Suite](#19-test-suite)
20. [Installation & Setup](#20-installation--setup)
21. [Docker & Resource Limits](#21-docker--resource-limits)
22. [Environment Variables](#22-environment-variables)
23. [Project Structure](#23-project-structure)
24. [Authors](#24-authors)

---

## 1. What the System Does

When a developer pushes code to GitHub, the system reacts automatically:

1. **GitHub Actions** runs the test suite
2. If tests **fail** → the raw log is sent to the Auto-Healer via ngrok
3. **6 AI agents** analyze the error, generate a fix, evaluate safety, and notify
4. The fix is either **auto-merged** (GREEN), **sent for human review** (YELLOW), or **blocked** (RED)
5. Every human decision **teaches the system** to make better choices next time

The system requires **zero developer interaction** for high-confidence failures and gets smarter with every run.

---

## 2. The 6 Agents — Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    GitHub Actions / ngrok                       │
│                    POST /tools/handle_build_failure             │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │ Orchestrator│  Port 8085
                    │   (Central) │  State machine, pipeline control,
                    │             │  dedup, rate limit, cost tracking
                    └──────┬──────┘
           ┌───────────────┼───────────────────────┐
           │               │                       │
    ┌──────▼──────┐ ┌──────▼──────┐        ┌──────▼──────┐
    │ Log Cleaner │ │   Error     │         │  LLM Code   │
    │  Agent 3    │ │  Analyst    │         │  Repairer   │
    │  Port 8081  │ │  Agent 4    │         │  Agent 5    │
    │             │ │  Port 8084  │         │  Port 8086  │
    │ 5 filters + │ │ Regex + LLM │         │ Fix memory  │
    │ LLM fallback│ │ Blast radius│         │ + security  │
    └─────────────┘ └─────────────┘         └─────────────┘
                                                    │
                                            ┌───────▼──────┐
                                            │  Review &    │
                                            │   Notify     │
                                            │  Agent 6     │
                                            │  Port 8087   │
                                            │ Adaptive TL  │
                                            │ Slack notify │
                                            └──────────────┘

Supporting services:
  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
  │Pipeline Mon.│    │  Gerrit MCP │    │  Scheduler  │
  │  Agent 1   │    │  Port 8083  │    │ Daily Digest│
  │  Port 8082  │    │ GitHub PRs  │    │ Task polling│
  └─────────────┘    └─────────────┘    └─────────────┘
```

### Agent Responsibilities

| Agent | Service | Port | Role |
|-------|---------|------|------|
| **Agent 1** — Pipeline Monitor | `jenkins-mcp` | 8082 | Polls GitHub Issues/Jenkins, classifies tasks via NIM |
| **Agent 2** — Task Inspector | inside scheduler | — | Classifies task as Scenario A (bug) or Scenario B (feature) |
| **Agent 3** — Log Analyst | `log-cleaner-mcp` | 8081 | 5-stage regex pipeline + LLM fallback for log compression |
| **Agent 4** — Error Analyst | `knowledge-graph-mcp` | 8084 | Regex + LLM failure analysis, blast radius, affected files |
| **Agent 5** — Code Repairer | `llm-mcp` | 8086 | Fix generation with memory, secret scanning, quality gates |
| **Agent 6** — Review & Notify | `notification-mcp` | 8087 | Adaptive traffic light evaluation + Slack/Teams notify |
| **Orchestrator** | `orchestrator-mcp` | 8085 | Pipeline orchestration, state machine, webhooks |
| **Gerrit MCP** | `gerrit-mcp` | 8083 | GitHub PR creation, branch management, rate-limit handling |
| **Scheduler** | `scheduler` | — | Daily digest, task polling, periodic monitors |

---

## 3. Complete Pipeline Flow

```
POST /tools/handle_build_failure
        │
        ├─ Rate limit check (10 req/60s per IP) ──► 429 if exceeded
        ├─ Input size check (> 500 KB) ────────────► 413 if too large
        ├─ Duplicate build_id check ───────────────► 409 if already running
        │
        ▼ PENDING
        │
        ├─ [Agent 3] clean_logs
        │   • ANSI code removal
        │   • Timestamp stripping
        │   • Duplicate line removal
        │   • Noise line filtering
        │   • Stack trace extraction
        │   • LLM fallback if reduction < 50%
        │
        ▼ ANALYSING
        │
        ├─ [Agent 4] analyze_failure
        │   • Regex pattern matching (6 error types)
        │   • Pytest-format file extraction (FAILED tests/foo.py::test_bar)
        │   • Python traceback file extraction
        │   • Blast radius calculation (LOW/MEDIUM/HIGH)
        │   • LLM fallback for UNKNOWN error types
        │
        ├─ Regression check: do failing files overlap with a recent fix?
        ├─ Deduplication check: same error fingerprint in last 24h?
        │
        ├─ [Gerrit MCP] fetch_file (code context for affected files)
        │
        ▼ GENERATING_FIX
        │
        ├─ [Agent 5] generate_fix
        │   • Log compression (~90% token reduction)
        │   • Fix memory context injection (past 3 relevant attempts)
        │   • Task complexity scoring (LOW/MEDIUM/HIGH)
        │   • LLM call with quality-adapted model selection
        │   • Secret scan on generated code
        │   • Bandit security scan
        │   • Pylint quality check
        │   • Confidence adjustment based on quality
        │   • Retry on security issues (max 2 retries)
        │
        ▼ VALIDATING
        │
        ├─ [Agent 6] evaluate_and_notify
        │   • Adaptive traffic light evaluation (per-error-type thresholds)
        │   • Safety override for HIGH blast radius → always RED
        │   • Slack/Teams notification
        │
        ├─ Deduplication record (cache this error for 24h)
        ├─ Fix memory record (store outcome for learning)
        │
        ├─── GREEN ──► [Gerrit] Create PR → Auto-merge
        │              Register with regression verifier (60 min watch)
        │              ▼ APPLYING_FIX → COMPLETED
        │
        ├─── YELLOW ─► [Gerrit] Create PR (no merge)
        │              Send Slack interactive buttons (Approve/Reject)
        │              ▼ AWAITING_REVIEW
        │              │
        │              ├─ Human clicks Approve → merge PR → COMPLETED
        │              │  Feed decision to adaptive thresholds + fix_memory
        │              └─ Human clicks Reject → close PR → BLOCKED
        │                 Feed decision to adaptive thresholds + fix_memory
        │
        └─── RED ────► No PR created → BLOCKED
```

---

## 4. Workflow State Machine

The orchestrator tracks every build through a strict state machine:

```
PENDING
  └─► ANALYSING
        └─► GENERATING_FIX
              └─► VALIDATING
                    ├─► AWAITING_REVIEW ──► APPLYING_FIX ──► COMPLETED
                    ├─►                └─► BLOCKED
                    ├─► APPLYING_FIX ──────────────────────► COMPLETED
                    └─► BLOCKED

Any state ──► FAILED (on agent crash)
```

**Pruning:**
- `AWAITING_REVIEW` workflows older than **24 hours** → auto-blocked (human missed the window)
- Terminal workflows (`COMPLETED`, `FAILED`, `BLOCKED`) older than **48 hours** → removed from memory
- Pruning runs as a background asyncio task every **3600 seconds**

---

## 5. AI Model System

### NVIDIA NIM Integration

All agents call NVIDIA NIM-hosted models via OpenAI-compatible API. Models are configured entirely through environment variables — **never hardcoded**.

### 4-Model Fallback Chain

Each agent has up to 4 model slots. If the primary model fails (timeout, error, rate limit), the system automatically switches to the next:

```
PRIMARY ──► FALLBACK_1 ──► FALLBACK_2 ──► FALLBACK_3 ──► AllModelsFailed exception
```

Every switch is logged and counted in Prometheus (`agent_model_switch_total`).

### Per-Agent Token Budgets

| Agent | Max tokens/request | Max tokens/hour | Input limit | Timeout |
|-------|-------------------|----------------|------------|---------|
| Pipeline Monitor | 500 | 5,000 | 1,000 | 10s |
| Task Inspector | 1,000 | 10,000 | 2,000 | 15s |
| Log Analyst | 2,000 | 20,000 | 8,000 | 30s |
| Error Analyst | 3,000 | 30,000 | 6,000 | 30s |
| Code Repairer | 4,000 | 50,000 | 8,000 | 60s |
| Review & Notify | 2,000 | 20,000 | 4,000 | 20s |

**Global budget:** 135,000 tokens/hour across all agents. Warning fires at 80%.

### Task Complexity-Based Model Routing

Before calling the LLM, the system scores the error complexity deterministically (no AI needed):

| Score | Complexity | Model tier | Examples |
|-------|-----------|-----------|---------|
| 0–2 | **LOW** | 7–8 B parameter model (fast, cheap) | Single assertion error, 1 file |
| 3–6 | **MEDIUM** | 32 B parameter model (balanced) | Import error, 2–3 files |
| 7+ | **HIGH** | 70 B+ model (best quality) | Dependency/memory/concurrency, many files |

**Scoring factors:** error type weight + blast radius weight + number of affected files + log length + root cause verbosity.

### Token Tracking

The `TokenTracker` module tracks usage per agent per hour with thread-safe locking. Usage is visible in `/api/stats` and Prometheus gauges.

### Cost Tracking

The `CostTracker` module estimates API cost per build using pricing tiers based on model parameter count:

| Model size | Price/1K tokens |
|-----------|----------------|
| < 3B | $0.0001 |
| 7–8B | $0.0002 |
| 27–32B | $0.0006 |
| 70–72B | $0.0018 |
| 100–125B | $0.0040 |
| 400B+ | $0.0120 |

Warns when a single build exceeds $0.10. Session totals visible in `/api/stats`.

---

## 6. Traffic Light Safety System

### Score Formula

```
final_score = (llm_confidence × 0.6) + (blast_radius_score × 0.4)

Blast radius scores:
  LOW    → 1.0
  MEDIUM → 0.6
  HIGH   → 0.2  (but HIGH always forces RED regardless of score)
```

### Adaptive Thresholds (default values, adapt per error type)

| Colour | Default threshold | Action |
|--------|-----------------|--------|
| 🟢 **GREEN** | ≥ 0.85 | PR created + auto-merged immediately. Regression watch activated. |
| 🟡 **YELLOW** | 0.60 – 0.84 | PR created. Slack Approve/Reject buttons sent. 24h review window. |
| 🔴 **RED** | < 0.60 | No PR. Build blocked. Manual intervention required. |

**Safety override:** `HIGH` blast radius **always** returns RED, regardless of confidence.

---

## 7. AI Memory & Learning

### Fix Memory (`src/shared/fix_memory.py`)

Every fix attempt is stored in an append-only JSONL file. Each record contains:
- Timestamp, build ID, error type, root cause hash, affected files
- Fix preview (first 300 chars of the patch)
- Outcome (GREEN/YELLOW/RED), confidence score
- PR URL, human approval status

**Query algorithm:** When the same error type recurs, the system fetches the 3 most relevant past fixes using:
1. **Exact match** on error type
2. **Jaccard similarity** on affected file sets: `|A ∩ B| / |A ∪ B|`
3. **Sort order:** GREEN first, then by file similarity, then by recency

**Prompt injection:** Past fixes are formatted and injected into the LLM prompt:

```
Past fix attempts for this error type (use as reference):
  [2026-04-20] GREEN (91%) ✓ HUMAN APPROVED: Fixed incorrect assertion in test_calc
  [2026-04-18] YELLOW (74%) ✗ HUMAN REJECTED — avoid this approach: Changed test to skip
  [2026-04-15] RED (38%): Could not identify root cause
```

This is **few-shot learning from history** — the AI learns from what worked and avoids what was rejected.

**Human feedback loop:** When a human approves or rejects via Slack, `fix_memory.update_outcome()` is called. This updates the approval status in the JSONL file so future queries include the human verdict.

**Statistics API:** `fix_memory.stats()` returns per-error-type success rates (green/yellow/red percentages) used in the daily digest and `/autoheal stats` slash command.

---

## 8. Adaptive Confidence Thresholds

### `src/shared/adaptive_thresholds.py`

The traffic light thresholds are **not fixed** — they self-calibrate per error type based on what humans actually accept.

**Algorithm:**
1. Every human approve/reject from Slack is recorded with the fix's confidence score
2. After 5+ decisions for an error type, thresholds are recalculated:
   - `new_GREEN = mean(approved_confidences) − 0.03`
   - `new_YELLOW = mean(rejected_confidences) + 0.03`
3. Safe bounds enforced: GREEN stays in [70%, 95%], YELLOW in [45%, 80%]
4. YELLOW is always at least 10 percentage points below GREEN

**Example:** The AI produces ASSERTION_ERROR fixes at 0.72 confidence. Humans approve them 8 times in a row. After the 5th approval, GREEN threshold for ASSERTION_ERROR drops from 0.85 → 0.72, enabling auto-merge for this error type.

**Storage:** Append-only JSONL at `ADAPTIVE_THRESHOLDS_PATH`. Cached in-memory per error type. Cache invalidated on each new decision.

**Visibility:** `/autoheal thresholds` slash command, `/api/stats` response.

---

## 9. Regression Detection

### `src/shared/heal_verifier.py`

After a GREEN auto-merge, the system does not simply forget the fix. It activates a **60-minute regression watch**:

1. `heal_verifier.record_fix(build_id, affected_files)` — stores the fix in memory
2. When the next failure arrives, `heal_verifier.check_regression(new_id, failing_files)` is called
3. If the failing files **overlap** with a recently fixed build → regression detected:
   - `regression_detected` audit event logged
   - Warning logged with original build ID, overlapping files, and age in minutes
   - New build is still processed normally (not skipped)

**Why this matters:** Without regression detection, the system would silently generate another fix without realising it was undoing the previous one.

**Active watches** are visible in `/api/stats` under `regression_monitor.active_fix_watches`.

---

## 10. Log Processing Pipeline

### Agent 3 — Log Analyst (`src/log_cleaner_mcp/`)

Five-stage deterministic pipeline (pure regex, zero latency):

| Stage | Module | What it removes |
|-------|--------|----------------|
| 1 | `ansi_remover.py` | ANSI escape codes (`\x1b[32m`, colour codes) |
| 2 | `timestamp_stripper.py` | ISO timestamps, Unix timestamps, log prefixes |
| 3 | `deduplicator.py` | Duplicate consecutive lines (download progress spam) |
| 4 | `noise_filter.py` | Dotted progress lines, `---` separators, blank-only lines |
| 5 | `stack_trace_extractor.py` | Preserves error/traceback lines, drops surrounding noise |

**LLM fallback:** If the 5-stage pipeline achieves less than 50% line reduction (the log is genuinely complex), Agent 3 falls back to the NIM LLM (7B model) with a focused system prompt to extract diagnostic lines.

**Output:** `CleanResult` with `cleaned_text`, `reduction_ratio`, `used_llm` flag, and line counts.

### Log Compression for LLM Prompts (`src/shared/prompt_compressor.py`)

A second-stage compressor runs before LLM calls in Agent 5:

- Keeps **error lines** (ERROR, FAILED, Exception, AssertionError, Traceback...)
- Keeps **context window** (2 lines before/after each error line)
- Keeps **head** (first 5 lines) and **tail** (last 10 lines) of log
- Marks omitted sections with `... (lines omitted)`
- Hard-truncates to `max_chars` with `... (truncated)` marker

Result: a 40 KB log → ~2 KB with no diagnostic loss. **~90% token reduction.**

---

## 11. Security Features

### Secret Scanner (`src/shared/secret_scanner.py`)

Every AI-generated fix is scanned **before** being pushed to GitHub. Detected pattern types:

| Pattern | Example |
|---------|---------|
| AWS Access Key | `AKIAIOSFODNN7EXAMPLE` |
| AWS Secret Key | `aws_secret_key = "abc123..."` |
| GitHub Token | `ghp_...`, `ghs_...`, `gho_...`, `ghr_...` |
| NVIDIA API Key | `nvapi-XYZ...` |
| Private Key Block | `-----BEGIN RSA PRIVATE KEY-----` |
| Generic password | `password = "mysecret"` |
| Bearer token | `Authorization: Bearer eyJ...` |
| Slack Token | `xoxb-...`, `xoxp-...` |
| Stripe Key | `sk_live_...`, `pk_live_...` |
| JWT Token | `eyJ...` (3-part format) |
| Hex secret 40-char | `token = "a1b2c3..."` (40 hex chars) |

**Safe patterns excluded:** Lines with `os.getenv()`, `os.environ`, `process.env`, `# example`, `YOUR_KEY_HERE` are not flagged.

**On detection:** The fix is blocked and the AI is asked to rewrite using environment variables (up to 2 retries). If all retries fail, `SecretLeakError` is raised and the pipeline returns RED.

### Rate Limiting (`src/orchestrator_mcp/rate_limiter.py`)

- **Sliding window counter** per client IP address
- Default: **10 requests per 60 seconds**
- Uses `deque` for O(1) append/pop, thread-safe with `threading.Lock`
- Returns HTTP **429** with `retry_after_seconds: 60` when exceeded
- Prometheus gauge tracks active keys

### Input Size Cap

- `raw_log` payload larger than **500 KB** → HTTP **413 Payload Too Large**
- Prevents memory exhaustion from malformed or malicious payloads

### Slack Signature Verification (`src/notification_mcp/slack_slash_handler.py`)

All Slack webhooks and slash commands are verified using Slack's HMAC-SHA256 protocol:

```
base_string = f"v0:{timestamp}:{request_body}"
expected    = "v0=" + HMAC-SHA256(SLACK_SIGNING_SECRET, base_string)
```

- **Replay attack prevention:** Requests older than 5 minutes are rejected
- Returns HTTP **403** on invalid signature
- Falls back gracefully if `SLACK_SIGNING_SECRET` is not set (logs warning)

### GitHub Webhook Signature

All GitHub PR events verified with `X-Hub-Signature-256` (HMAC-SHA256) when `GITHUB_WEBHOOK_SECRET` is configured.

### Quality Gates on Generated Code

Before any fix is returned, Agent 5 runs two quality scanners:

| Gate | Tool | Checks |
|------|------|--------|
| **Bandit** | `run_bandit_scan()` | Python security issues (HIGH/MEDIUM severity count) |
| **Pylint** | `run_pylint_check()` | Code quality score |

Results adjust the confidence score via `evaluate_quality()`. HIGH security issues trigger a retry with the security problem described in the prompt.

---

## 12. Token & Cost Optimization

Five independent optimization layers working together:

| Layer | Module | Mechanism | Typical saving |
|-------|--------|-----------|----------------|
| **Log compression** | `prompt_compressor.py` | Keep error lines only | ~90% token reduction |
| **Deduplication** | `deduplication.py` | Skip pipeline for repeated errors | 100% saving for repeated failures |
| **Fix memory** | `fix_memory.py` | Inject only 3 past examples, capped at 800 chars | Avoids unbounded context growth |
| **Per-agent budgets** | `config.py` | Hard token limits per agent per hour | Prevents runaway costs |
| **Surgical patches** | `fix_parsers.py` | LLM returns `changed_lines` only (1-based line edits) | ~70% smaller fixes, fewer retries |

### Deduplication Cache (`src/orchestrator_mcp/deduplication.py`)

Creates an MD5 fingerprint from `error_type + root_cause[:200] + sorted(files)`. Cache window: **24 hours**. On cache hit, returns `{deduplicated: true, original_build, cache_age_min}` without running any AI agents.

---

## 13. Resilience System

### Circuit Breaker (`src/shared/resilience.py`)

Independent circuit breaker for each external dependency:

| Service | Breaker name |
|---------|-------------|
| NVIDIA NIM API | `llm_api` |
| GitHub API | `github_api` |
| Jenkins API | `jenkins_api` |
| Microsoft Teams | `teams_webhook` |
| Slack | `slack_webhook` |

**States:** CLOSED (normal) → OPEN (5 failures within 60s) → HALF_OPEN (30s cooldown) → CLOSED (on success)

### Per-Agent Internal Retries

Each agent that calls the LLM (Agents 4, 5) carries its own retry policy with exponential backoff. The orchestrator's per-call HTTP timeouts (`LLM_FIX_TIMEOUT=1200s`, `GERRIT_FETCH_TIMEOUT=10s`) are configured to exceed these internal budgets so retries always finish before the outer connection times out.

### Global Fallback

If any agent crashes or returns an invalid response:
1. `handle_agent_failure()` records the event in Prometheus (`agent_fallback_triggered_total`)
2. `trigger_global_fallback()` sends a RED payload directly to Agent 6
3. Agent 6 sends an immediate Slack alert
4. The workflow is marked FAILED — never stuck in a non-terminal state

### Correlation IDs

Every pipeline run generates a UUID correlation ID (`X-Request-ID` header) that is propagated to all 6 agent calls. This allows a single build to be traced across log lines from 6 different services using a single search.

---

## 14. Slack Integration

### Interactive Buttons (YELLOW path)

When Agent 6 evaluates a fix as YELLOW, a Slack Block Kit message is sent with two buttons:

```
🟡 Human Review Required
Build: build-12345  |  Confidence: 74%  |  Blast radius: LOW

What the AI did:
  Fixed incorrect import path in src/utils.py

PR: [View on GitHub →]

[✅ Approve & Merge]    [❌ Reject]
```

**On Approve:** GitHub PR is merged via API. Original Slack message is updated to show "✅ Fix Applied". Feeds decision to `fix_memory` and `adaptive_thresholds`.

**On Reject:** GitHub PR is closed. Slack message updated to "❌ Fix Rejected". Feeds decision to `fix_memory` and `adaptive_thresholds`.

**Response URL:** Slack responses are sent via the original message's `response_url` so the message is updated in-place (not a new message).

### Microsoft Teams Integration

`teams_notifier.py` sends equivalent notifications to a Teams channel via incoming webhook. Runs in parallel with Slack notification.

### Slash Commands (`/autoheal`)

9 commands, all with HMAC-SHA256 signature verification:

| Command | Description |
|---------|-------------|
| `/autoheal status <build_id>` | Current workflow state, colour, last update time, error message |
| `/autoheal list` | Last 10 workflows with colour emoji and status |
| `/autoheal stats` | Fix success rates by error type (GREEN/YELLOW/RED %) |
| `/autoheal retry <build_id>` | Re-submit a failed build to the pipeline |
| `/autoheal explain <build_id>` | Plain-English explanation of what the AI found and fixed |
| `/autoheal rollback <build_id>` | Close the associated GitHub PR (undo the fix) |
| `/autoheal history <file_path>` | All past fixes for a specific source file |
| `/autoheal top` | Most problematic files (sorted by failure count, all time) |
| `/autoheal thresholds` | Current adaptive confidence thresholds per error type |

### Daily Intelligence Digest (`src/scheduler/daily_digest.py`)

Every morning at **08:00 UTC** (configurable via `DIGEST_HOUR_UTC`), the system posts a rich Slack report:

```
🤖 Auto-Healer Daily Report — Friday, April 25

Builds: 47  |  Auto-fixed (GREEN): 85%  |  Reviews sent: 6  |  Blocked: 1
API cost (session): $0.023  |  Avg cost per build: $0.0005

📊 Top Error Types:
  • ASSERTION_ERROR — 28 occurrences (🟢 89%)
  • IMPORT_ERROR — 12 occurrences (🟢 75%)
  • TYPE_ERROR — 7 occurrences (🟢 71%)

🗂️ Most Troubled Files:
  • tests/test_payments.py — 8 failures
  • src/auth/validator.py — 5 failures

🧠 Adaptive Thresholds:
  2 error types with self-adjusted thresholds: ASSERTION_ERROR, TYPE_ERROR

🔍 Regression Monitor:
  Watching 3 recently deployed fixes for regressions

💡 Recommendation:
  tests/test_payments.py has failed 8 times recently.
  Consider adding stronger unit tests or refactoring this module.
```

---

## 15. Prometheus Metrics

All 8 services expose `/metrics` in Prometheus text format.

| Metric | Type | Description |
|--------|------|-------------|
| `auto_healer_workflows_total` | Counter | Workflows processed by status (completed/failed/blocked) |
| `auto_healer_confidence_score` | Histogram | Traffic light score distribution (buckets: 0, 0.3, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0) |
| `auto_healer_fix_duration_seconds` | Histogram | End-to-end pipeline duration (buckets: 5s, 10s, 30s, 60s, 120s, 300s) |
| `auto_healer_log_reduction_ratio` | Gauge | Agent 3's last log reduction percentage |
| `auto_healer_quality_gate_results` | Counter | Bandit/Pylint pass/fail counts by gate name |
| `agent_model_switch_total` | Counter | LLM model switches per agent and reason |
| `agent_tokens_used` | Gauge | Tokens used this hour per agent |
| `agent_token_budget_remaining` | Gauge | Remaining hourly token budget per agent |
| `agent_fallback_triggered_total` | Counter | Global fallback events per agent |

---

## 16. Monitoring & Statistics API

### `GET /api/stats`

Returns a complete system snapshot:

```json
{
  "workflows": {
    "by_status":        {"COMPLETED": 40, "AWAITING_REVIEW": 2, "BLOCKED": 5},
    "total":            47,
    "active":           2,
    "pruned_this_call": {"pruned": 0, "timed_out": 0}
  },
  "tokens_used_this_hour": {
    "code_repairer": 45000,
    "error_analyst": 12000
  },
  "cost": {
    "session_total_usd":     0.023,
    "builds_tracked":        47,
    "avg_cost_per_build_usd": 0.0005
  },
  "deduplication": {
    "cache_size": 12
  },
  "rate_limiter": {
    "active_keys": {"127.0.0.1": 3}
  },
  "audit_log": {
    "event_counts": {
      "pipeline_start":    47,
      "pipeline_complete": 44,
      "pipeline_failed":   3,
      "regression_detected": 1
    },
    "recent_events": [...]
  },
  "regression_monitor": {
    "active_fix_watches": [
      {"build_id": "build-123", "fixed_files": ["src/foo.py"], "age_minutes": 12.3}
    ]
  },
  "adaptive_thresholds": {
    "ASSERTION_ERROR": {"green_threshold": 0.78, "yellow_threshold": 0.57, "adapted": true},
    "IMPORT_ERROR":    {"green_threshold": 0.85, "yellow_threshold": 0.60, "adapted": false}
  }
}
```

### Audit Log (`src/shared/audit_log.py`)

Every pipeline event is appended to an append-only JSONL file:

| Event | When |
|-------|------|
| `pipeline_start` | Build failure received |
| `pipeline_complete` | Pipeline finished (any colour) |
| `pipeline_failed` | Unhandled exception |
| `rate_limit_blocked` | IP exceeded rate limit |
| `fix_deduplicated` | Error fingerprint matched cache |
| `regression_detected` | Re-failure on recently fixed files |
| `pr_approved` | Human clicked Approve in Slack |
| `pr_rejected` | Human clicked Reject in Slack |
| `pipeline_retry` | `/autoheal retry` called |

---

## 17. All API Endpoints

### Orchestrator (port 8085)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/tools/handle_build_failure` | **Main entry point.** Runs full pipeline. |
| `GET` | `/tools/get_workflow_status` | Query status by `?build_id=` |
| `POST` | `/tools/retry_build` | Re-queue a failed build |
| `GET` | `/api/stats` | System-wide statistics snapshot |
| `POST` | `/webhooks/github` | GitHub PR webhook (merge/approve events) |
| `POST` | `/webhooks/slack` | Slack interactive button callbacks |
| `POST` | `/webhooks/slack/commands` | Slack `/autoheal` slash commands |
| `POST` | `/workflows` | Register a workflow (REST) |
| `GET` | `/workflows/active` | List all active workflows |
| `GET` | `/workflows/{build_id}` | Get workflow state |
| `POST` | `/workflows/{build_id}/advance` | Manually advance state |
| `GET` | `/health` | Health check → `{"status":"ok"}` |
| `GET` | `/metrics` | Prometheus metrics |

### Log Cleaner (port 8081)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/tools/clean_logs` | Run 5-stage log cleaning pipeline |
| `GET` | `/health` | Health check |
| `GET` | `/metrics` | Prometheus metrics |

### Knowledge Graph / Error Analyst (port 8084)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/tools/analyze_failure` | Regex + LLM failure analysis |
| `GET` | `/health` | Health check |
| `GET` | `/metrics` | Prometheus metrics |

### LLM / Code Repairer (port 8086)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/tools/generate_fix` | Generate code fix with quality gates |
| `GET` | `/health` | Health check |
| `GET` | `/metrics` | Prometheus metrics |

### Notification / Review & Notify (port 8087)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/tools/evaluate_and_notify` | Traffic light evaluation + Slack/Teams notification |
| `GET` | `/health` | Health check |
| `GET` | `/metrics` | Prometheus metrics |

### Gerrit MCP (port 8083)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/tools/fetch_file` | Fetch file content from GitHub |
| `POST` | `/tools/submit_patch` | Create GitHub PR with fix |
| `GET` | `/health` | Health check |

### Jenkins / Pipeline Monitor (port 8082)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/tools/fetch_logs` | Fetch build logs from Jenkins/GitHub |
| `POST` | `/webhooks/jenkins` | Receive Jenkins build events |
| `GET` | `/health` | Health check |

---

## 18. Complete Module Reference

### `src/shared/` — Shared Infrastructure

| Module | Description |
|--------|-------------|
| `models.py` | Domain models: `BuildEvent`, `FailureAnalysis`, `CodeFix`, `TrafficLightResult`, `WorkflowState`. All enums: `ErrorType`, `BlastRadius`, `WorkflowStatus`, `TrafficLightColour`, `TaskScenario` |
| `config.py` | `AgentModelConfig` dataclass, `AGENT_CONFIGS` dict, `SERVICE_URLS`, global token budget |
| `nim_client.py` | NVIDIA NIM OpenAI-compatible client. `NimClient.complete()` with 4-slot fallback chain, token tracking, structured logging |
| `model_fallback.py` | `ModelFallbackManager` — tracks current slot, switches on failure, resets on success, raises `AllModelsFailed` |
| `task_complexity.py` | `score_complexity()` returns `Complexity.LOW/MEDIUM/HIGH`. Deterministic — no AI needed, instant scoring |
| `resilience.py` | `CircuitBreaker`, `handle_agent_failure()`, `trigger_global_fallback()` |
| `quality_gates.py` | `run_bandit_scan()`, `run_pylint_check()`, `evaluate_quality()`. Uses `tempfile.NamedTemporaryFile` (no security vulnerability) |
| `secret_scanner.py` | `scan_for_secrets()`. 11 regex patterns, safe-pattern exclusions, `SecretScanResult` dataclass |
| `prompt_compressor.py` | `compress_log()`. Error-aware log compression with context window and hard truncation |
| `fix_memory.py` | `FixMemory` class: `record()`, `update_outcome()`, `query()` (Jaccard similarity), `stats()`. `build_memory_context()` formats for LLM prompts |
| `adaptive_thresholds.py` | `AdaptiveThresholds`: `record_decision()`, `get_thresholds()`, `summary()`. Self-calibrating per error type |
| `heal_verifier.py` | `HealVerifier`: `record_fix()`, `check_regression()`, `active_fixes()`. 60-minute regression watch window |
| `audit_log.py` | Append-only JSONL event stream. `AuditLog.log()`, `tail()`, `summary()`. Graceful fallback to Python logger |
| `cost_tracker.py` | Per-build API cost estimation. `CostTracker.record()`, `session_summary()`. Pricing tiers by model size |
| `token_tracker.py` | Thread-safe per-agent token counting with hourly reset. `usage_snapshot()` |
| `metrics.py` | Prometheus counters, histograms, and gauges. `generate_metrics_output()` |
| `mcp_base.py` | `MCPServiceBase` — base class for all aiohttp services. Registers `/health` and `/metrics` |

### `src/orchestrator_mcp/` — Central Pipeline Controller

The orchestrator was originally one 1253-line `server.py`. It has been split into focused mixin modules (each ≤ ~480 lines) so each area can be edited and debugged in isolation:

| Module | Description |
|--------|-------------|
| `server.py` | `OrchestratorMCPServer` — thin shell composing the mixins below + lifecycle (pruner) |
| `pipeline_mixin.py` | `handle_build_failure` + the Agent 3→4→5→6 pipeline split into per-step methods (`_step_clean_logs`, `_step_analyse`, `_step_fetch_context`, `_step_generate_fix`, `_step_notify`, `_finalise`) |
| `pipeline_helpers.py` | Pure helpers — FAILED_FILE regex, ERROR_TYPE map, FILE_CONTENT extractor |
| `github_mixin.py` | PR creation, auto-merge, GitHub webhook + HMAC signature verify |
| `slack_mixin.py` | Slack interactive Approve / Reject button handler |
| `workflow_api_mixin.py` | REST CRUD for workflows |
| `admin_mixin.py` | `/api/stats`, `retry_build`, `review_code` (AI-triggered healing) |
| `workflow.py` | `WorkflowEngine` state machine. `VALID_TRANSITIONS` graph. `prune_stale()`, `stats()` |
| `deduplication.py` | `DeduplicationCache`. MD5 fingerprinting of error signatures. 24h cache window |
| `rate_limiter.py` | `RateLimiter`. Sliding-window counter per IP. Thread-safe deque |
| `traffic_light.py` | Legacy traffic light module (orchestrator-side copy) |
| `tools.py` | MCP tool definitions for orchestrator |

### `src/llm_mcp/` — Code Repairer

`fix_generator.py` was originally 757 lines. The validators, prompt-builder, and parser have been extracted so the main file focuses on the LLM retry loop:

| Module | Description |
|--------|-------------|
| `fix_generator.py` | `FixGenerator.generate_fix()` — the retry loop. Integrates log compression, fix memory, complexity scoring, secret scanner, bandit, pylint |
| `fix_validators.py` | Static + runtime gates (AST parse, self-assignment detector, sandboxed subprocess run, sort-output sanity) |
| `fix_prompts.py` | `build_retry_prompt()` (with stuck-loop detection), `extract_bug_list()` |
| `fix_parsers.py` | `apply_surgical_patch()`, `parse_response()` |
| `prompt_templates.py` | `SYSTEM_PROMPT`, `SCENARIO_A_TEMPLATE`, `COMPLEX_REPAIR_TEMPLATE`, line-count constants |
| `quality_check.py` | Additional quality checks for generated code |
| `server.py` | aiohttp server for Agent 5 |
| `tools.py` | MCP tool definitions |

### `src/log_cleaner_mcp/` — Log Analyst

| Module | Description |
|--------|-------------|
| `pipeline.py` | `CleanResult` dataclass. `clean_pipeline()` orchestrating all 5 filters + LLM fallback |
| `filters/ansi_remover.py` | Removes ANSI escape sequences |
| `filters/timestamp_stripper.py` | Strips ISO/Unix timestamps and log prefixes |
| `filters/deduplicator.py` | Removes duplicate consecutive lines |
| `filters/noise_filter.py` | Removes progress dots, separators, empty lines |
| `filters/stack_trace_extractor.py` | Extracts error/traceback lines |
| `server.py` | aiohttp server for Agent 3 |

### `src/knowledge_graph_mcp/` — Error Analyst

| Module | Description |
|--------|-------------|
| `failure_analyser.py` | `FailureAnalyser.analyze()`. Regex patterns for 6 error types. Pytest-format file extraction. LLM fallback for UNKNOWN |
| `dependency_tracker.py` | `DependencyTracker` — tracks file dependency graph for blast radius calculation |
| `server.py` | aiohttp server for Agent 4 |

### `src/notification_mcp/` — Review & Notify

| Module | Description |
|--------|-------------|
| `traffic_light_evaluator.py` | `evaluate_traffic_light()` with adaptive thresholds |
| `slack_notifier.py` | `send_slack_review_buttons()`. Block Kit templates for GREEN/YELLOW/RED. Approve/Reject button construction |
| `slack_slash_handler.py` | 9 slash commands with HMAC-SHA256 verification — one `_cmd_*` function per sub-command |
| `slash_responses.py` | Pure response builders (status / list / stats / explain / history / top / thresholds blocks) |
| `teams_notifier.py` | Microsoft Teams adaptive card notifications |
| `server.py` | aiohttp server for Agent 6 |

### `src/scheduler/` — Background Tasks

| Module | Description |
|--------|-------------|
| `monitor.py` | `ScheduledMonitor`. Polls GitHub Issues / Jira. Routes tasks via TaskClassifier |
| `task_classifier.py` | `TaskClassifier`. Regex heuristics → NIM LLM for A/B/YELLOW classification |
| `daily_digest.py` | `DailyDigest.send()`. Builds Slack Block Kit report from live stats |

### `src/gerrit_mcp/` — GitHub PR Manager

| Module | Description |
|--------|-------------|
| `patch_submitter.py` | `PatchSubmitter.submit()`. Creates branch, commits files, opens PR. Rate-limit handling (Retry-After / X-RateLimit-Reset headers). Finds existing PR on 422 |
| `code_fetcher.py` | `CodeFetcher.fetch()`. Reads file content from GitHub API via `SERVICE_URLS` |
| `github_approver.py` | `extract_build_id()` from branch name `auto-heal/{build_id}` |
| `server.py` | aiohttp server |

### `src/jenkins_mcp/` — Pipeline Monitor

| Module | Description |
|--------|-------------|
| `log_fetcher.py` | Fetches build logs from Jenkins or GitHub Actions |
| `webhook_handler.py` | Processes incoming Jenkins build events |
| `nim_client.py` | Agent 1's own NIM client instance |
| `server.py` | aiohttp server for Agent 1 |

---

## 19. Test Suite

**540 tests passing** (21 skipped — they require live Docker services or were tied to dead-code modules removed during the cleanup).

### Unit Tests — `tests/unit/`

| Category | File(s) | Coverage |
|----------|---------|---------|
| **Fix Memory** | `test_fix_memory.py` | record, query, Jaccard similarity, approval stamps, stats |
| **Adaptive Thresholds** | `test_adaptive_thresholds.py` | calibration algorithm, safe bounds, cache invalidation |
| **Heal Verifier** | `test_heal_verifier.py` | regression detection, file overlap, expiry window |
| **Secret Scanner** | `test_secret_scanner.py` | all 11 pattern types, safe exclusions |
| **Prompt Compressor** | `test_prompt_compressor.py` | error preservation, size limits, head/tail sections |
| **Task Complexity** | `test_task_complexity.py` | scoring algorithm, LOW/MEDIUM/HIGH boundaries |
| **Task Classifier** | `test_task_classifier.py` | Scenario A/B classification, NIM fallback, YELLOW escalation |
| **Circuit Breaker** | `test_circuit_breaker.py` | CLOSED→OPEN→HALF_OPEN→CLOSED transitions |
| **Model Fallback** | `test_model_fallback.py` | fallback chain, AllModelsFailed, slot reset |
| **Token Tracker** | `test_token_tracker.py` | thread safety, hourly reset, usage snapshot |
| **Quality Gates** | `test_quality_gates.py` | bandit scan, pylint check, confidence modifier |
| **Resilience Async** | `test_resilience_async.py` | global fallback notifier — RED payload |
| **Models** | `test_models.py` | dataclass fields, enum values, serialisation |
| **Workflow Engine** | `test_workflow.py` | state transitions, InvalidTransitionError, pruning |
| **GitHub Webhook** | `test_github_webhook.py` | HMAC signature verification, branch parsing |
| **Traffic Light** | `test_traffic_light.py` + `test_edge_cases.py` | adaptive thresholds, safety override, score formula |
| **Log Cleaner** | `test_pipeline.py` + 5 filter tests | each filter individually, full pipeline combination |
| **Error Analyst** | `test_failure_analyser.py` + `test_edge_cases.py` | all 6 error types, pytest format, blast radius |
| **Code Repairer** | `test_fix_generator.py` + edge cases | parsing, retry, FixTooLongError, SecretLeakError |
| **Gerrit MCP** | 4 test files | PR creation, rate-limit headers, code fetching |
| **Notifiers** | 3 test files | Block Kit rendering, Slack/Teams notifications |
| **Scheduler** | `test_scheduler_monitor.py` | task polling, classification |

### Integration Tests — `tests/integration/`

| File | What it tests |
|------|---------------|
| `test_full_pipeline.py` | GREEN/YELLOW path, 400/409/413/429 errors, dedup, fix_memory recording |
| `test_analysis_pipeline.py` | Log cleaner → error analyst chain, traffic light green/yellow/red, safety override |
| `test_global_fallback.py` | Agent crash → RED notification, FAILED workflow state |
| `test_quality_gates_integration.py` | Bandit + Pylint in pipeline context |
| `test_webhook_to_clean.py` | Webhook event → log cleaner flow |
| `test_smoke.py` | ⚠️ Live Docker: health checks, /metrics, log reduction |
| `test_load.py` | ⚠️ Live Docker: concurrent pipelines, state isolation |

### Running Tests

```bash
# All unit tests (fast, no Docker)
python3 -m pytest tests/unit/ -v

# Integration pipeline tests (in-process aiohttp + respx mocks)
python3 -m pytest tests/integration/test_full_pipeline.py -v

# Full suite
python3 -m pytest tests/ -q

# Specific module
python3 -m pytest tests/unit/test_shared/test_adaptive_thresholds.py -v
```

---

## 20. Installation & Setup

### Requirements

- Docker Desktop (WSL2 integration enabled on Windows)
- Python 3.11+
- ngrok account (free tier is sufficient)
- GitHub repository
- Slack workspace with an app

### Step 1 — Clone and Configure

```bash
git clone https://github.com/Mouaz7/auto-healing-devops-platform.git
cd auto-healing-devops-platform
cp .env.example .env
# Edit .env and fill in all required values
```

### Step 2 — Start All Services

```bash
docker compose up --build
# Wait for all 8 containers to show "Started"
```

### Step 3 — Start ngrok Tunnel

```bash
# In a new terminal:
ngrok http --url=<your-static-domain> 8085
# Forwarding: https://your-domain.ngrok-free.dev → http://localhost:8085
```

### Step 4 — Verify

```bash
curl http://localhost:8085/health
# → {"status": "ok", "service": "orchestrator_mcp"}

curl http://localhost:8085/api/stats
# → full system stats JSON

# Run demo
source venv/bin/activate
python scripts/demo.py
```

### Step 5 — GitHub Actions

The `.github/workflows/auto-heal.yml` is already included in this repository. It triggers on every push and pull request:

```yaml
name: Auto-Healing Pipeline

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install pytest

      - name: Run tests
        id: run_tests
        run: python -m pytest tests/ -v || true

      - name: Trigger Auto-Healing on failure
        if: failure()
        run: |
          curl -X POST https://YOUR-DOMAIN.ngrok-free.dev/tools/handle_build_failure \
            -H "Content-Type: application/json" \
            -d '{
              "build_id": "${{ github.run_id }}",
              "repo":     "${{ github.repository }}",
              "branch":   "${{ github.ref_name }}",
              "scenario": "A",
              "raw_log":  "Build failed on commit ${{ github.sha }}"
            }'
```

Replace `YOUR-DOMAIN.ngrok-free.dev` with your actual ngrok static domain. With ngrok Pro you can reserve a permanent subdomain so the workflow file never needs updating.

### Step 6 — Slack App Configuration

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → Your App
2. **Interactivity & Shortcuts** → Turn ON → Request URL:
   ```
   https://your-domain.ngrok-free.dev/webhooks/slack
   ```
3. **Slash Commands** → Add `/autoheal` → Request URL:
   ```
   https://your-domain.ngrok-free.dev/webhooks/slack/commands
   ```
4. **Basic Information** → copy `Signing Secret` → add to `.env` as `SLACK_SIGNING_SECRET`
5. **Incoming Webhooks** → Add webhook → copy URL → add to `.env` as `SLACK_WEBHOOK_URL`

### Step 7 — GitHub Webhook

In your GitHub repo → **Settings → Webhooks → Add webhook:**
- Payload URL: `https://your-domain.ngrok-free.dev/webhooks/github`
- Content type: `application/json`
- Secret: (same value as `GITHUB_WEBHOOK_SECRET` in `.env`)
- Events: `Pull requests`, `Pull request reviews`

---

## 21. Docker & Resource Limits

All 8 services run in `docker-compose.yml` on an isolated `agent-network` bridge network:

| Container | CPU limit | Memory limit | Memory reservation |
|-----------|-----------|-------------|-------------------|
| `orchestrator-mcp` | 1.00 | 512 MB | 128 MB |
| `llm-mcp` | 1.00 | 512 MB | 128 MB |
| `knowledge-graph-mcp` | 1.00 | 512 MB | 128 MB |
| `log-cleaner-mcp` | 0.50 | 256 MB | 64 MB |
| `gerrit-mcp` | 0.50 | 256 MB | 64 MB |
| `notification-mcp` | 0.50 | 256 MB | 64 MB |
| `jenkins-mcp` | 0.25 | 128 MB | 32 MB |
| `scheduler` | 0.25 | 128 MB | 32 MB |

All services use `restart: unless-stopped` and share the `agent-network` bridge.

---

## 22. Environment Variables

### Required

| Variable | Description |
|----------|-------------|
| `NVIDIA_NIM_BASE_URL` | NVIDIA NIM API base URL |
| `PIPELINE_MONITOR_PRIMARY_API_KEY` | API key for Agent 1 |
| `PIPELINE_MONITOR_PRIMARY_MODEL` | Model name for Agent 1 |
| `LOG_ANALYST_PRIMARY_API_KEY` | API key for Agent 3 |
| `LOG_ANALYST_PRIMARY_MODEL` | Model name for Agent 3 |
| `ERROR_ANALYST_PRIMARY_API_KEY` | API key for Agent 4 |
| `ERROR_ANALYST_PRIMARY_MODEL` | Model name for Agent 4 |
| `CODE_REPAIRER_PRIMARY_API_KEY` | API key for Agent 5 |
| `CODE_REPAIRER_PRIMARY_MODEL` | Model name for Agent 5 |
| `REVIEW_NOTIFY_PRIMARY_API_KEY` | API key for Agent 6 |
| `REVIEW_NOTIFY_PRIMARY_MODEL` | Model name for Agent 6 |
| `GITHUB_TOKEN` | GitHub Personal Access Token (scopes: repo, workflow) |
| `GITHUB_REPO` | Target repo in `owner/repo` format |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL |

### Recommended

| Variable | Description |
|----------|-------------|
| `GITHUB_WEBHOOK_SECRET` | HMAC secret for GitHub webhook verification |
| `SLACK_SIGNING_SECRET` | HMAC secret for Slack webhook + slash command verification |
| `*_FALLBACK_1/2/3` | Fallback model names per agent |
| `*_FALLBACK_1/2/3_API_KEY` | Fallback API keys per agent |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `FIX_MEMORY_PATH` | `/var/log/auto-healer/fix_memory.jsonl` | AI fix history file |
| `ADAPTIVE_THRESHOLDS_PATH` | `/var/log/auto-healer/adaptive_thresholds.jsonl` | Threshold learning file |
| `AUDIT_LOG_PATH` | `/var/log/auto-healer/audit.jsonl` | Audit trail file |
| `MODEL_LOW_PRIMARY` | `qwen/qwen2.5-coder-7b-instruct` | Model for LOW complexity |
| `MODEL_LOW_FALLBACK_1` | `google/gemma-3-12b-it` | Fallback for LOW complexity |
| `MODEL_MED_PRIMARY` | `qwen/qwen2.5-coder-32b-instruct` | Model for MEDIUM complexity |
| `MODEL_MED_FALLBACK_1` | `meta/llama-3.1-70b-instruct` | Fallback for MEDIUM complexity |
| `DIGEST_HOUR_UTC` | `8` | Hour (0–23) to send daily Slack digest |
| `SCHEDULE_INTERVAL_MINUTES` | `15` | GitHub Issues polling interval |
| `LOG_CLEANER_URL` | `http://localhost:8081` | Internal service URL |
| `JENKINS_URL` | `http://localhost:8082` | Internal service URL |
| `GERRIT_URL` | `http://localhost:8083` | Internal service URL |
| `KNOWLEDGE_GRAPH_URL` | `http://localhost:8084` | Internal service URL |
| `ORCHESTRATOR_URL` | `http://localhost:8085` | Internal service URL |
| `LLM_URL` | `http://localhost:8086` | Internal service URL |
| `NOTIFICATION_URL` | `http://localhost:8087` | Internal service URL |

---

## 23. Project Structure

```
auto-healing-devops-platform/
│
├── docker-compose.yml            # 8 services, resource limits, agent-network
├── Dockerfile                    # Multi-stage build
├── .env.example                  # Environment template (copy to .env)
├── pyproject.toml                # pytest config (asyncio AUTO mode)
├── requirements.txt              # Python dependencies
│
├── src/
│   ├── shared/                   # Shared infrastructure (all agents import from here)
│   │   ├── models.py             # Domain models + enums
│   │   ├── config.py             # Agent configs, SERVICE_URLS, LLM_FIX_TIMEOUT
│   │   ├── nim_client.py         # NVIDIA NIM LLM client (4-slot fallback)
│   │   ├── model_fallback.py     # ModelFallbackManager
│   │   ├── task_complexity.py    # Deterministic complexity scorer
│   │   ├── resilience.py         # Circuit breaker + global fallback notifier
│   │   ├── quality_gates.py      # Bandit + Pylint code quality
│   │   ├── secret_scanner.py     # Hardcoded secret detection
│   │   ├── prompt_compressor.py  # Log compression for LLM prompts
│   │   ├── fix_memory.py         # AI learning from past fix outcomes
│   │   ├── adaptive_thresholds.py# Self-calibrating traffic light thresholds
│   │   ├── heal_verifier.py      # Post-merge regression detection
│   │   ├── audit_log.py          # Append-only JSONL audit trail
│   │   ├── cost_tracker.py       # Per-build API cost estimation
│   │   ├── token_tracker.py      # Thread-safe per-agent token counting
│   │   ├── metrics.py            # Prometheus metrics definitions
│   │   └── mcp_base.py           # Base aiohttp server class
│   │
│   ├── orchestrator_mcp/         # Port 8085 — Central controller
│   │   ├── server.py             # Thin shell — composes mixins + lifecycle
│   │   ├── pipeline_mixin.py     # handle_build_failure + 4-step pipeline
│   │   ├── pipeline_helpers.py   # Pure helpers (regex, ERROR_TYPE map)
│   │   ├── github_mixin.py       # PR creation, auto-merge, GitHub webhook
│   │   ├── slack_mixin.py        # Slack Approve / Reject buttons
│   │   ├── workflow_api_mixin.py # REST CRUD for workflows
│   │   ├── admin_mixin.py        # /api/stats, retry, AI code review
│   │   ├── workflow.py           # State machine + pruning
│   │   ├── deduplication.py      # 24h error fingerprint cache
│   │   ├── rate_limiter.py       # Sliding-window rate limiter
│   │   └── traffic_light.py      # Legacy traffic light copy
│   │
│   ├── log_cleaner_mcp/          # Port 8081 — Agent 3
│   │   ├── pipeline.py           # 5-stage cleaning pipeline
│   │   └── filters/              # ansi, timestamp, dedup, noise, stack_trace
│   │
│   ├── jenkins_mcp/              # Port 8082 — Agent 1
│   │   ├── log_fetcher.py
│   │   └── webhook_handler.py
│   │
│   ├── gerrit_mcp/               # Port 8083 — GitHub PR manager
│   │   ├── patch_submitter.py    # PR creation with rate-limit handling
│   │   ├── code_fetcher.py       # File content from GitHub API
│   │   └── github_approver.py    # Branch → build_id extraction
│   │
│   ├── knowledge_graph_mcp/      # Port 8084 — Agent 4
│   │   ├── failure_analyser.py   # Regex + LLM error analysis
│   │   └── dependency_tracker.py # Blast radius calculation
│   │
│   ├── llm_mcp/                  # Port 8086 — Agent 5
│   │   ├── fix_generator.py      # FixGenerator retry loop
│   │   ├── fix_validators.py     # Syntax + runtime gates
│   │   ├── fix_prompts.py        # Retry prompt builder + bug list
│   │   ├── fix_parsers.py        # Surgical patch + JSON parser
│   │   ├── prompt_templates.py   # System + user prompts
│   │   └── quality_check.py      # Additional code quality checks
│   │
│   ├── notification_mcp/         # Port 8087 — Agent 6
│   │   ├── traffic_light_evaluator.py  # Adaptive traffic light
│   │   ├── slack_notifier.py     # Block Kit templates + interactive buttons
│   │   ├── slack_slash_handler.py# 9 slash commands
│   │   ├── slash_responses.py    # Pure response builders
│   │   └── teams_notifier.py     # Microsoft Teams adaptive cards
│   │
│   └── scheduler/                # Background tasks
│       ├── monitor.py            # GitHub Issues / Jira polling
│       ├── task_classifier.py    # Agent 2: A/B/YELLOW classification
│       └── daily_digest.py       # Morning Slack intelligence report
│
├── tests/
│   ├── unit/                     # Unit tests (no Docker, no network)
│   │   ├── test_shared/          # Shared infrastructure modules
│   │   ├── test_code_repairer/   # Agent 5 tests
│   │   ├── test_error_analyst/   # Agent 4 tests
│   │   ├── test_gerrit_mcp/      # PR creation tests
│   │   ├── test_log_cleaner/     # All 5 filter tests + pipeline
│   │   ├── test_orchestrator/    # Workflow, webhooks, mixins
│   │   ├── test_pipeline_monitor/# Agent 1 tests
│   │   ├── test_review_notify/   # Agent 6 tests
│   │   └── test_traffic_light/   # Traffic light edge cases
│   │
│   └── integration/              # End-to-end pipeline tests
│       ├── test_full_pipeline.py # GREEN, YELLOW, 400/409/413/429, dedup
│       ├── test_analysis_pipeline.py  # Log cleaner + error analyst + TL chain
│       ├── test_global_fallback.py    # Agent crash → RED
│       ├── test_quality_gates_integration.py
│       ├── test_webhook_to_clean.py
│       ├── test_smoke.py         # ⚠️ Requires live Docker services
│       └── test_load.py          # ⚠️ Requires live Docker services
│
├── scripts/
│   └── demo.py                   # Full pipeline demonstration
│
└── docs/                         # Architecture docs + thesis chapters
```

---

## 24. Authors

| Name | Email | Role |
|------|-------|------|
| Ahmad Darwich | ahda23@student.bth.se | Author |
| Mouaz Naji | moap23@student.bth.se | Author |

**Supervisor:** Ahmad Nauman Ghazi — nauman.ghazi@bth.se

**Institution:** Blekinge Tekniska Högskola (BTH), Sweden

**Thesis title:** Automated Remediation in CI/CD: Design and Control of an AI-based Code Repair Agent

---

*This project is a bachelor thesis and is not licensed for commercial use.*
