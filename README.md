# Auto-Healing AI DevOps Platform
[![Built with Claude Code](https://img.shields.io/badge/Built%20with-Claude%20Code-orange?logo=anthropic)](https://claude.ai/code)

> Automated Remediation in CI/CD: Design and Control of an AI-based Code Repair Agent
>
> Bachelor Thesis — Blekinge Tekniska Högskola (BTH), 2026

---

## What Does It Do?

Every time you push code to GitHub, the system automatically:

1. Runs your tests via GitHub Actions
2. If a test **fails** → 6 AI agents analyze the error and generate a fix
3. The fix is evaluated and one of three things happens:

```
You push code to GitHub
        ↓
GitHub Actions runs tests
        ↓
    Test OK? ──── YES ──→ Done! ✅
        │
        NO
        ↓
AI system receives the error via ngrok
        ↓
6 AI agents work together:
  Agent 1 → Monitors the pipeline
  Agent 3 → Analyzes and compresses the logs
  Agent 4 → Identifies the error type and blast radius
  Agent 5 → Writes the fix (with memory of past attempts)
  Agent 6 → Evaluates safety + sends Slack notification
        ↓
GREEN  (≥85% confidence) → Auto-merged to GitHub, no human needed
YELLOW (60-84%)          → Slack buttons → You approve or reject
RED    (<60%)            → Blocked → You fix manually
```

---

## Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (with WSL 2 integration enabled)
- Python 3.11+
- [ngrok](https://ngrok.com) account (free)
- GitHub account
- Slack workspace

---

## Step 1 — Clone & Configure

```bash
git clone https://github.com/Mouaz7/auto-healing-devops-platform.git
cd auto-healing-devops-platform

# Copy environment file
cp .env.example .env
```

Open `.env` and fill in the required values:

```bash
# AI Models (NVIDIA NIM)
NVIDIA_NIM_BASE_URL=https://integrate.api.nvidia.com/v1
PIPELINE_MONITOR_PRIMARY_MODEL=meta/llama-3.2-1b-instruct
PIPELINE_MONITOR_PRIMARY_API_KEY=nvapi-xxxx
# ... (see .env.example for all agents)

# GitHub (token needs: repo + workflow + admin:repo_hook scopes)
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
GITHUB_REPO=YourUsername/your-repo
GITHUB_WEBHOOK_SECRET=your-secret-string

# Slack
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../XXX
SLACK_SIGNING_SECRET=your-slack-signing-secret

# Smart model routing (optional — defaults provided)
MODEL_LOW_PRIMARY=qwen/qwen2.5-coder-7b-instruct
MODEL_MED_PRIMARY=qwen/qwen2.5-coder-32b-instruct
```

---

## Step 2 — Start All Services (Terminal 1)

```bash
docker compose up --build
```

Wait until you see all 8 containers running:

```
Container log-cleaner-mcp     Started
Container jenkins-mcp         Started
Container gerrit-mcp          Started
Container knowledge-graph-mcp Started
Container llm-mcp             Started
Container notification-mcp    Started
Container orchestrator-mcp    Started
Container scheduler           Started
```

> Keep this terminal open — do not close it.

---

## Step 3 — Start ngrok (Terminal 2)

Open a **new terminal** and run:

```bash
ngrok http --url=<your-ngrok-domain> 8085
```

You will see:

```
Forwarding  https://your-domain.ngrok-free.dev -> http://localhost:8085
```

> ngrok makes your local AI system reachable from the internet so GitHub Actions can call it.

---

## Step 4 — Verify Everything Works

```bash
# Health check — all agents should return "ok"
curl http://localhost:8085/health
curl http://localhost:8081/health
curl http://localhost:8087/health

# System stats
curl http://localhost:8085/api/stats

# Run the built-in demo
source venv/bin/activate
python scripts/demo.py
```

---

## Step 5 — Set Up GitHub Actions

Add this workflow file to your repository at `.github/workflows/auto-heal.yml`:

```yaml
name: Auto-Healing Pipeline

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: "3.11"
      - run: pip install pytest
      - name: Run tests and capture output
        id: run_tests
        run: python -m pytest tests/ -v 2>&1 | tee /tmp/pytest_output.txt; exit ${PIPESTATUS[0]}
        continue-on-error: true
      - name: Trigger Auto-Healing on failure
        if: steps.run_tests.outcome == 'failure'
        timeout-minutes: 5
        run: |
          python3 - <<'EOF'
          import json, os, urllib.request
          log = open("/tmp/pytest_output.txt").read()[:400000]
          payload = json.dumps({
            "build_id": os.environ["GITHUB_RUN_ID"],
            "repo":     os.environ["GITHUB_REPOSITORY"],
            "raw_log":  log,
          }).encode()
          req = urllib.request.Request(
            "https://your-domain.ngrok-free.dev/tools/handle_build_failure",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
          )
          resp = urllib.request.urlopen(req, timeout=300)
          print(resp.read().decode())
          EOF
```

---

## Step 6 — Set Up Slack Interactive Buttons

To approve or reject AI fixes directly from Slack:

1. Go to https://api.slack.com/apps
2. Click your app → **Interactivity & Shortcuts**
3. Turn **Interactivity ON**
4. Set **Request URL** to:
   ```
   https://your-domain.ngrok-free.dev/webhooks/slack
   ```
5. Click **Slash Commands** → Add `/autoheal` command
6. Set the Request URL to:
   ```
   https://your-domain.ngrok-free.dev/webhooks/slack/commands
   ```
7. Click **Save Changes**

When a YELLOW fix arrives in Slack you will see:

```
🟡 AI Fix — Human Review Required
Build: build-12345
Confidence: 74%
PR: View on GitHub

[✅ Approve & Merge]   [❌ Reject]
```

Clicking **Approve & Merge** merges the PR on GitHub and updates the Slack message to confirm.

### Slack Slash Commands

| Command | Description |
|---------|-------------|
| `/autoheal status <build_id>` | Check status of a specific build |
| `/autoheal list` | List the last 10 workflows |
| `/autoheal stats` | Show AI fix success rates by error type |

---

## Traffic Light Safety System

| Colour | Confidence | Action |
|--------|------------|--------|
| GREEN  | >= 85%     | PR created and auto-merged immediately |
| YELLOW | 60 – 84%   | PR created, Slack buttons sent for human review |
| RED    | < 60%      | Blocked — no PR created, manual fix required |

**Safety override:** If the error affects many files (HIGH blast radius), the result is always RED regardless of confidence score.

---

## AI Memory & Learning

The system learns from every fix attempt it makes. When the same error type appears again, the LLM prompt is enriched with relevant past attempts so the AI can:

- Replicate patterns that worked (GREEN / approved by human)
- Avoid repeating patterns that were rejected

Memory is stored in `/var/log/auto-healer/fix_memory.jsonl` and survives container restarts.

Example prompt injection:
```
Past fix attempts for this error type (use as reference):
  [2026-04-20] GREEN (91%) ✓ HUMAN APPROVED: Fixed incorrect assertion in test_calc
  [2026-04-18] YELLOW (74%): Changed import path in utils.py
```

Configure with `FIX_MEMORY_PATH` env var.

---

## Security Features

### Secret Scanner
Every AI-generated fix is scanned for hardcoded credentials **before** being pushed to GitHub. Detected patterns include:

- AWS access/secret keys
- GitHub tokens (`ghp_`, `ghs_`, `gho_`)
- NVIDIA NIM API keys (`nvapi-`)
- Private key blocks (`-----BEGIN RSA PRIVATE KEY-----`)
- Slack tokens, Stripe keys, JWT tokens
- Generic `password = "..."` patterns

If a secret is detected, the fix is **blocked** and the AI is asked to rewrite it using environment variables instead (up to 2 retries).

### Rate Limiting
- 10 requests per 60 seconds per client IP
- Returns `429 Too Many Requests` when exceeded

### Input Size Cap
- Logs larger than 500 KB are rejected with `413 Payload Too Large`

### Slack Signature Verification
- Every Slack webhook and slash command is verified using HMAC-SHA256 with your `SLACK_SIGNING_SECRET`
- Replay attacks blocked (5-minute timestamp window)

### GitHub Webhook Signature
- All GitHub PR events verified with `X-Hub-Signature-256` when `GITHUB_WEBHOOK_SECRET` is set

---

## Smart Token Optimization

### Log Compression (~90% token reduction)
Raw CI logs (10–50 KB) are compressed before being sent to the LLM:
- Error and traceback lines are always kept
- Progress/download spam is removed
- A 40 KB log is compressed to ~2 KB with no diagnostic loss

### Task Complexity Scoring
Each error is scored deterministically (no LLM call) to select the cheapest adequate model:

| Complexity | Model Tier | Examples |
|------------|-----------|---------|
| LOW | 7–8 B parameter | Single assertion error, 1 file |
| MEDIUM | 32 B parameter | Import error, 2–3 files |
| HIGH | 70 B+ parameter | Dependency/memory/concurrency errors, many files |

### Deduplication Cache
Identical errors (same type + root cause + files) within 24 hours are deduplicated — the pipeline is skipped and the original fix result is returned. This avoids wasting tokens on repeated identical failures.

---

## Monitoring & Statistics

### `/api/stats` endpoint

```json
{
  "workflows": {
    "by_status": {"COMPLETED": 12, "AWAITING_REVIEW": 2, "BLOCKED": 1},
    "total": 15,
    "active": 2
  },
  "tokens_used_this_hour": {"code_repairer": 45000, "failure_analyser": 12000},
  "cost": {
    "session_total_usd": 0.043,
    "builds_tracked": 15,
    "avg_cost_per_build_usd": 0.003
  },
  "deduplication": {"cache_size": 8},
  "rate_limiter": {"active_keys": {"127.0.0.1": 3}},
  "audit_log": {
    "event_counts": {"pipeline_start": 15, "pipeline_complete": 14},
    "recent_events": [...]
  }
}
```

### Prometheus Metrics (port 8085/metrics)
- `pipeline_duration_seconds` — end-to-end processing time
- `quality_gate_results_total` — bandit/pylint pass/fail counts
- `agent_fallback_triggered_total` — model fallback frequency
- `fix_confidence_score` — confidence distribution

---

## Resilience Features

### Circuit Breaker
Each external service (LLM API, GitHub API, Slack) has an independent circuit breaker:
- Trips after 5 failures within 60 seconds
- 30-second cooldown, then one probe request
- Automatically resets on success

### Retry with Exponential Backoff + Jitter
All agent calls retry up to 3 times with delays `[1s, 2s, 4s]` ± 25% jitter to prevent thundering-herd.

### Global Fallback
If any agent crashes, the system immediately:
1. Records the failure in the audit log
2. Notifies via Slack with RED status
3. Never leaves a workflow stuck in a non-terminal state

### Workflow Pruning
- AWAITING_REVIEW workflows older than 24 hours → auto-blocked
- Terminal workflows older than 48 hours → removed from memory

---

## How to Test Manually

```bash
# Trigger a pipeline
curl -X POST http://localhost:8085/tools/handle_build_failure \
  -H "Content-Type: application/json" \
  -d '{
    "build_id": "manual-test-001",
    "repo": "YourUsername/your-repo",
    "raw_log": "FAILED tests/test_sample.py::test_calc\nAssertionError: assert 1 == 2"
  }'

# Check workflow status
curl "http://localhost:8085/tools/get_workflow_status?build_id=manual-test-001"

# View stats
curl http://localhost:8085/api/stats
```

Expected response:

```json
{
  "build_id": "manual-test-001",
  "status": "COMPLETED",
  "colour": "GREEN",
  "final_score": 0.97,
  "notified": true,
  "pr_url": "https://github.com/YourUsername/your-repo/pull/1"
}
```

---

## Running the Test Suite

```bash
# Install dependencies
pip install -r requirements.txt

# Unit tests (fast, no Docker)
python3 -m pytest tests/unit/ -v

# Integration tests (in-process aiohttp server + respx mocks, no Docker)
python3 -m pytest tests/integration/ -v

# All tests
python3 -m pytest tests/ -v
```

The test suite currently includes **73+ tests** across:
- Fix memory (learning system)
- Secret scanner
- Task complexity scorer
- Log compressor
- Diff generator
- Circuit breaker
- Rate limiter
- Deduplication cache
- Full end-to-end pipeline (GREEN, YELLOW, RED paths)

---

## Services & Ports

| Service | Agent | Port | Description |
|---------|-------|------|-------------|
| orchestrator-mcp | Central workflow | 8085 | Entry point — receives build failures |
| log-cleaner-mcp | Agent 3 | 8081 | Cleans and compresses logs |
| jenkins-mcp | Agent 1 | 8082 | Pipeline monitoring |
| gerrit-mcp | — | 8083 | Creates GitHub PRs |
| knowledge-graph-mcp | Agent 4 | 8084 | Error analysis + blast radius |
| llm-mcp | Agent 5 | 8086 | Generates code fixes |
| notification-mcp | Agent 6 | 8087 | Traffic light + Slack notifications |
| scheduler | Cron | — | Periodic monitoring |

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `NVIDIA_NIM_BASE_URL` | Yes | NVIDIA NIM API endpoint |
| `*_PRIMARY_API_KEY` | Yes | API key per agent |
| `*_PRIMARY_MODEL` | Yes | Model name per agent |
| `GITHUB_TOKEN` | Yes | GitHub personal access token |
| `GITHUB_REPO` | Yes | `owner/repo` format |
| `GITHUB_WEBHOOK_SECRET` | Recommended | For webhook signature verification |
| `SLACK_WEBHOOK_URL` | Yes | Incoming webhook URL |
| `SLACK_SIGNING_SECRET` | Recommended | For slash command security |
| `FIX_MEMORY_PATH` | No | AI memory file (default: `/var/log/auto-healer/fix_memory.jsonl`) |
| `AUDIT_LOG_PATH` | No | Audit log file (default: `/var/log/auto-healer/audit.jsonl`) |
| `MODEL_LOW_PRIMARY` | No | Model for LOW complexity tasks |
| `MODEL_MED_PRIMARY` | No | Model for MEDIUM complexity tasks |

---

## Technology Stack

- **Language:** Python 3.11+
- **Protocol:** MCP (Model Context Protocol)
- **AI Models:** NVIDIA NIM (configurable per agent, 4-model fallback chain)
- **HTTP:** httpx (async client), aiohttp (async server)
- **Containers:** Docker, Docker Compose
- **CI/CD:** GitHub Actions
- **Notifications:** Slack (interactive buttons + slash commands)
- **Tunneling:** ngrok (local → internet)
- **Monitoring:** Prometheus, structlog
- **Security:** HMAC-SHA256 webhook verification, secret scanning, rate limiting

---

## Project Structure

```
auto-healing-devops-platform/
├── docker-compose.yml          # All 8 services with resource limits
├── Dockerfile                  # Multi-stage Docker build
├── .env.example                # Environment template
│
├── src/
│   ├── shared/                 # Shared infrastructure
│   │   ├── fix_memory.py       # AI learning — stores past fix outcomes
│   │   ├── secret_scanner.py   # Blocks hardcoded secrets in fixes
│   │   ├── prompt_compressor.py # Compresses logs to save tokens
│   │   ├── diff_generator.py   # Unified diffs for PR/Slack display
│   │   ├── task_complexity.py  # Scores error complexity (LOW/MED/HIGH)
│   │   ├── model_router.py     # Routes to cheapest adequate model
│   │   ├── audit_log.py        # Append-only event stream
│   │   ├── cost_tracker.py     # Tracks API spend per build
│   │   ├── resilience.py       # Circuit breaker + retry + fallback
│   │   └── quality_gates.py    # Bandit + Pylint code quality checks
│   │
│   ├── orchestrator_mcp/       # Central workflow + traffic light (port 8085)
│   │   ├── server.py           # Main pipeline orchestration
│   │   ├── workflow.py         # State machine (PENDING→COMPLETED)
│   │   ├── deduplication.py    # 24h error deduplication cache
│   │   └── rate_limiter.py     # Sliding-window rate limiter
│   │
│   ├── log_cleaner_mcp/        # Agent 3: Log Analyst (port 8081)
│   ├── jenkins_mcp/            # Agent 1: Pipeline Monitor (port 8082)
│   ├── gerrit_mcp/             # GitHub PR creator (port 8083)
│   ├── knowledge_graph_mcp/    # Agent 4: Error Analyst (port 8084)
│   ├── llm_mcp/                # Agent 5: Code Repairer (port 8086)
│   │   ├── fix_generator.py    # LLM integration with memory + security
│   │   └── prompt_templates.py # Prompt templates (with memory slot)
│   ├── notification_mcp/       # Agent 6: Review & Notify (port 8087)
│   │   └── slack_slash_handler.py # /autoheal slash commands
│   └── scheduler/              # Cron-based monitoring
│
├── tests/
│   ├── unit/                   # Fast unit tests (no network, no Docker)
│   └── integration/            # End-to-end with in-process server
│
├── scripts/demo.py             # Full pipeline demo
└── docs/                       # Architecture docs + thesis chapters
```

---

## Authors

- Ahmad Darwich (ahda23@student.bth.se)
- Mouaz Naji (moap23@student.bth.se)

## Supervisor

Ahmad Nauman Ghazi (nauman.ghazi@bth.se)

## Licence

This project is part of a bachelor thesis at Blekinge Tekniska Högskola (BTH).
