# Auto-Healing AI DevOps Platform
[![Built with Claude Code](https://img.shields.io/badge/Built%20with-Claude%20Code-orange?logo=anthropic)](https://claude.ai/code)

> Automated Remediation in CI/CD: Design and Control of an AI-based Code Repair Agent

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
  Agent 3 → Analyzes the logs
  Agent 4 → Identifies the error type
  Agent 5 → Writes the fix
  Agent 6 → Evaluates safety
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

# Slack (incoming webhook URL)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../XXX
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
    paths-ignore:
      - 'auto_heal_fix.py'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: "3.11"
      - run: pip install pytest
      - name: Run tests
        id: run_tests
        run: python -m pytest tests/ -v
        continue-on-error: true
      - name: Trigger Auto-Healing on failure
        if: steps.run_tests.outcome == 'failure'
        run: |
          curl -X POST https://your-domain.ngrok-free.dev/tools/handle_build_failure \
            -H "Content-Type: application/json" \
            -d "{
              \"build_id\": \"${{ github.run_id }}\",
              \"repo\": \"${{ github.repository }}\",
              \"branch\": \"${{ github.ref_name }}\",
              \"scenario\": \"A\",
              \"raw_log\": \"Test failed on commit ${{ github.sha }}\"
            }"
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
5. Click **Save Changes**

When a YELLOW fix arrives in Slack you will see:

```
🟡 AI Fix — Human Review Required
Build: build-12345
Confidence: 74%
PR: View on GitHub

[✅ Approve & Merge]   [❌ Reject]
```

Clicking **Approve & Merge** merges the PR on GitHub and updates the Slack message to confirm.

---

## Traffic Light Safety System

| Colour | Confidence | Action |
|--------|------------|--------|
| GREEN  | >= 85%     | PR created and auto-merged immediately |
| YELLOW | 60 – 84%   | PR created, Slack buttons sent for human review |
| RED    | < 60%      | Blocked — no PR created, manual fix required |

**Safety override:** If the error affects many files (HIGH blast radius), the result is always RED regardless of confidence score.

---

## How to Test Manually

You can trigger the pipeline without pushing code:

```bash
curl -X POST http://localhost:8085/tools/handle_build_failure \
  -H "Content-Type: application/json" \
  -d '{
    "build_id": "manual-test-001",
    "repo": "YourUsername/your-repo",
    "branch": "main",
    "scenario": "A",
    "raw_log": "AssertionError: assert 1 == 2 in test_sample.py"
  }'
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

## Services & Ports

| Service | Agent | Port | Description |
|---------|-------|------|-------------|
| orchestrator-mcp | Central workflow | 8085 | Entry point — receives build failures |
| log-cleaner-mcp | Agent 3 | 8081 | Cleans and reduces log noise |
| jenkins-mcp | Agent 1 | 8082 | Pipeline monitoring |
| gerrit-mcp | — | 8083 | Creates GitHub PRs |
| knowledge-graph-mcp | Agent 4 | 8084 | Error analysis |
| llm-mcp | Agent 5 | 8086 | Generates code fixes |
| notification-mcp | Agent 6 | 8087 | Traffic light + Slack notifications |

---

## Technology Stack

- **Language:** Python 3.11+
- **Protocol:** MCP (Model Context Protocol)
- **AI Models:** NVIDIA NIM (configurable per agent, with fallback chain)
- **HTTP:** httpx (async client), aiohttp (async server)
- **Containers:** Docker, Docker Compose
- **CI/CD:** GitHub Actions
- **Notifications:** Slack (interactive buttons)
- **Tunneling:** ngrok (local → internet)
- **Monitoring:** Prometheus, structlog

---

## Project Structure

```
auto-healing-devops-platform/
├── docker-compose.yml          # All 8 services
├── Dockerfile                  # Multi-stage Docker build
├── .env.example                # Environment template
│
├── src/
│   ├── shared/                 # Shared infrastructure (models, config, fallback)
│   ├── orchestrator_mcp/       # Central workflow + traffic light (port 8085)
│   ├── log_cleaner_mcp/        # Agent 3: Log Analyst (port 8081)
│   ├── jenkins_mcp/            # Agent 1: Pipeline Monitor (port 8082)
│   ├── gerrit_mcp/             # GitHub PR creator (port 8083)
│   ├── knowledge_graph_mcp/    # Agent 4: Error Analyst (port 8084)
│   ├── llm_mcp/                # Agent 5: Code Repairer (port 8086)
│   ├── notification_mcp/       # Agent 6: Review & Notify (port 8087)
│   └── scheduler/              # Cron-based monitoring
│
├── tests/                      # Unit + integration tests
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

This project is part of a bachelor thesis at Blekinge Tekniska Hogskola (BTH).
