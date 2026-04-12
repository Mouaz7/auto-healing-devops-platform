# C4 Model Diagrams
## Auto-Healing AI DevOps Platform

---

## Structural Diagrams

### 1. Level 1 — System Context

```mermaid
C4Context
    title System Context — Auto-Healing AI DevOps Platform

    Person(dev, "Developer", "Writes code, reviews AI fixes")
    Person(ops, "DevOps Engineer", "Monitors pipelines, approves merges")

    System(platform, "Auto-Healing AI Platform", "6-agent pipeline that detects, analyses, and fixes CI/CD build failures autonomously")

    System_Ext(jenkins, "Jenkins", "CI/CD server, sends build webhooks")
    System_Ext(github, "GitHub / Gerrit", "Source code repository + code review")
    System_Ext(teams, "MS Teams / Slack", "Receives fix notifications")
    System_Ext(llm_api, "LLM API", "AI model provider (configurable, with fallback chain)")
    System_Ext(issues, "GitHub Issues / Jira", "Task tracking system")

    Rel(jenkins, platform, "POST /webhook/jenkins (build failure)")
    Rel(platform, github, "Fetches code, submits patches / PRs")
    Rel(platform, teams, "Sends Adaptive Card notifications")
    Rel(platform, llm_api, "Generates code fixes")
    Rel(platform, issues, "Reads tasks, posts summaries")
    Rel(dev, platform, "Reviews YELLOW fixes, approves merges")
    Rel(ops, platform, "Monitors metrics, configures models")
```

---

### 2. Level 2 — Container View (6-Agent Pipeline)

```mermaid
C4Container
    title Container View — 6-Agent Pipeline

    Person(dev, "Developer")

    System_Boundary(platform, "Auto-Healing AI Platform") {
        Container(agent1, "Agent 1: Pipeline Monitor", "Python / aiohttp", "Receives webhooks, deduplicates builds. Port 8082")
        Container(agent2, "Agent 2: Task Inspector", "Python", "Classifies tasks: Scenario A / B / YELLOW. In scheduler.")
        Container(agent3, "Agent 3: Log Analyst", "Python / regex", "Cleans logs, 97% reduction. Port 8081")
        Container(agent4, "Agent 4: Error Analyst", "Python", "Detects error type, blast radius. Port 8084")
        Container(agent5, "Agent 5: Code Repairer", "Python / LLM SDK", "Generates fix, runs Bandit + Pylint. Port 8086")
        Container(agent6, "Agent 6: Review & Notify", "Python / httpx", "Traffic light scoring, sends notifications. Port 8087")
        Container(orchestrator, "Orchestrator MCP", "Python / aiohttp", "Workflow state machine, chains all agents. Port 8085")
        Container(gerrit, "Gerrit/GitHub MCP", "Python / httpx", "Fetches code files, submits patches. Port 8083")
        Container(scheduler, "Scheduler", "Python / APScheduler", "Polls issue tracker every 15 min, routes to Agent 2")
    }

    System_Ext(jenkins, "Jenkins")
    System_Ext(github, "GitHub / Gerrit")
    System_Ext(teams, "Teams / Slack")
    System_Ext(llm_api, "LLM API")

    Rel(jenkins, agent1, "POST webhook", "HTTP")
    Rel(agent1, orchestrator, "BuildEvent", "HTTP")
    Rel(scheduler, agent2, "Task data", "function call")
    Rel(orchestrator, agent3, "raw_log", "HTTP POST 8081")
    Rel(orchestrator, agent4, "cleaned_logs", "HTTP POST 8084")
    Rel(orchestrator, gerrit, "file_path", "HTTP POST 8083")
    Rel(orchestrator, agent5, "analysis + context", "HTTP POST 8086")
    Rel(orchestrator, agent6, "fix + analysis", "HTTP POST 8087")
    Rel(agent5, llm_api, "generate fix", "HTTPS")
    Rel(agent6, teams, "Adaptive Card", "HTTPS webhook")
    Rel(gerrit, github, "fetch file / submit patch", "HTTPS API")
    Rel(dev, agent6, "reviews YELLOW fix", "manual")
```

---

### 3. Level 3 — Orchestrator Components

```mermaid
C4Component
    title Component View — Orchestrator MCP (Port 8085)

    Container_Boundary(orch, "Orchestrator MCP") {
        Component(server, "OrchestratorMCPServer", "aiohttp", "HTTP endpoints: /webhook, /tools/handle_build_failure")
        Component(engine, "WorkflowEngine", "Python", "State machine: PENDING→ANALYSING→GENERATING_FIX→VALIDATING→AWAITING_REVIEW→COMPLETED/FAILED/BLOCKED")
        Component(router, "ScenarioRouter", "Python", "Routes to Scenario A (bug) or B (feature) based on Agent 2 classification")
        Component(fallback_handler, "GlobalFallback", "Python", "If any agent fails → RED → calls Agent 6 directly")
    }

    Rel(server, engine, "create / transition workflow")
    Rel(server, router, "route by scenario")
    Rel(server, fallback_handler, "on exception")
```

---

### 4. Level 3 — Log Analyst Components (Agent 3)

```mermaid
C4Component
    title Component View — Log Analyst / Log Cleaner MCP (Port 8081)

    Container_Boundary(lc, "Log Cleaner MCP") {
        Component(server, "LogCleanerMCPServer", "aiohttp", "POST /tools/clean_logs")
        Component(pipeline, "clean_logs()", "Python", "Chains all 5 filters. Returns (cleaned_log, reduction_pct).")
        Component(ansi, "AnsiRemover", "regex", "Removes ANSI escape codes")
        Component(ts, "TimestampStripper", "regex", "Removes ISO8601 timestamps")
        Component(noise, "NoiseFilter", "regex", "Removes pip/maven noise, progress bars")
        Component(stack, "StackTraceExtractor", "regex", "Preserves Error/Exception/FAILED lines")
        Component(dedup, "Deduplicator", "hashlib MD5", "Removes repeated lines")
        Component(fallback_filter, "_fallback_filter()", "Python", "Keeps Error/Exception/FAILED if pipeline returns empty")
    }

    Rel(server, pipeline, "calls")
    Rel(pipeline, ansi, "step 1")
    Rel(pipeline, ts, "step 2")
    Rel(pipeline, noise, "step 3")
    Rel(pipeline, stack, "step 4")
    Rel(pipeline, dedup, "step 5")
    Rel(pipeline, fallback_filter, "if result empty")
```

---

## Flow Diagrams

### 5. Main Workflow Flowchart

```mermaid
flowchart TD
    A([CI/CD Webhook]) --> B[Agent 1: Pipeline Monitor\nDeduplicate via set build_id]
    B -->|Duplicate| Z1([Ignore])
    B -->|New build| C[Agent 2: Task Inspector\nClassify A / B / YELLOW]
    C -->|YELLOW| Y([Notify human\nManual decision])
    C -->|A or B| D[Agent 3: Log Analyst\n97% reduction via regex]
    D --> E[Agent 4: Error Analyst\nDetect error type + blast radius]
    E --> F[Gerrit MCP\nFetch affected files]
    F --> G[Agent 5: Code Repairer\nGenerate fix via LLM\nRun Bandit + Pylint]
    G -->|Max 2 retries| G
    G --> H[Agent 6: Review & Notify\nTraffic Light scoring]
    H -->|score ≥ 0.85\nLOW blast radius| GREEN([GREEN\nAuto-merge\nNotify team])
    H -->|0.60–0.84| YELLOW([YELLOW\nSubmit as draft\nHuman review])
    H -->|score < 0.60\nOR HIGH blast radius| RED([RED\nDo not submit\nBlock + alert])

    style GREEN fill:#22c55e,color:#fff
    style YELLOW fill:#eab308,color:#fff
    style RED fill:#ef4444,color:#fff
    style Z1 fill:#94a3b8,color:#fff
    style Y fill:#eab308,color:#fff
```

---

### 6. Traffic Light Decision Tree

```mermaid
flowchart TD
    A([Input: llm_confidence + blast_radius]) --> B{blast_radius == HIGH?}
    B -->|Yes| RED1([RED\nSafety override\nauto_merge = False])
    B -->|No| C[Compute score\n= confidence×0.6 + blast_score×0.4\nLOW=1.0 MED=0.6 HIGH=0.2]
    C --> D{score ≥ 0.85?}
    D -->|Yes| GREEN([GREEN\nauto_merge = True])
    D -->|No| E{score ≥ 0.60?}
    E -->|Yes| YELLOW([YELLOW\nauto_merge = False\nHuman review])
    E -->|No| RED2([RED\nauto_merge = False\nBlocked])

    style GREEN fill:#22c55e,color:#fff
    style YELLOW fill:#eab308,color:#fff
    style RED1 fill:#ef4444,color:#fff
    style RED2 fill:#ef4444,color:#fff
```

---

### 7. Log Analyst Filter Pipeline

```mermaid
flowchart LR
    A([Raw Jenkins Log\n~10 000 lines]) --> B[AnsiRemover\nRegex: strip ANSI]
    B --> C[TimestampStripper\nRegex: strip ISO8601]
    C --> D[NoiseFilter\nRemove pip/maven/progress]
    D --> E[StackTraceExtractor\nKeep Error/Exception/FAILED]
    E --> F[Deduplicator\nMD5 hash per line]
    F --> G{Result empty?}
    G -->|Yes| H[Fallback Filter\nKeep Error/Exception/FAILED]
    G -->|No| I([Cleaned Log\n~300 lines\n97% reduction])
    H --> I
```

---

## Sequence Diagrams

### 8. Scenario A — Happy Path (GREEN)

```mermaid
sequenceDiagram
    participant J as Jenkins
    participant A1 as Agent 1<br/>Pipeline Monitor
    participant ORC as Orchestrator
    participant A3 as Agent 3<br/>Log Analyst
    participant A4 as Agent 4<br/>Error Analyst
    participant GIT as Gerrit MCP
    participant A5 as Agent 5<br/>Code Repairer
    participant A6 as Agent 6<br/>Review & Notify
    participant DEV as Developer

    J->>A1: POST /webhook/jenkins (build failed)
    A1->>A1: Deduplicate check
    A1->>ORC: BuildEvent {build_id, repo, branch}
    ORC->>A3: POST /tools/clean_logs {raw_log}
    A3-->>ORC: {cleaned_logs, reduction_pct: 97.2}
    ORC->>A4: POST /tools/analyze_failure {cleaned_logs}
    A4-->>ORC: {error_type: IMPORT_ERROR, blast_radius: LOW}
    ORC->>GIT: POST /tools/fetch_file {file_path}
    GIT-->>ORC: {content: "...source code..."}
    ORC->>A5: POST /tools/generate_fix {analysis, context}
    A5->>A5: Call LLM API (primary model)
    A5->>A5: Run Bandit + Pylint
    A5-->>ORC: {fix_patch, confidence: 0.92, lint_ok: true}
    ORC->>A6: POST /tools/evaluate_and_notify
    A6->>A6: score = 0.92×0.6 + 1.0×0.4 = 0.952 → GREEN
    A6->>DEV: Teams/Slack: "✅ Auto-fix Applied"
    A6-->>ORC: {status: GREEN, auto_merge_allowed: true}
    ORC->>GIT: POST /tools/submit_patch
    GIT-->>ORC: {patch_url: "https://github.com/.../pull/42"}
```

---

### 9. YELLOW Path (Human Review Required)

```mermaid
sequenceDiagram
    participant ORC as Orchestrator
    participant A5 as Agent 5<br/>Code Repairer
    participant A6 as Agent 6<br/>Review & Notify
    participant DEV as Developer

    ORC->>A5: generate_fix (medium complexity)
    A5->>A5: LLM returns confidence: 0.72
    A5->>A5: Pylint score: 5.8 → modifier -0.20
    A5-->>ORC: {confidence: 0.52, lint_ok: false}
    Note over A5,ORC: confidence = 0.72 - 0.20 = 0.52
    ORC->>A6: evaluate_and_notify
    A6->>A6: score = 0.52×0.6 + 0.6×0.4 = 0.552 → RED
    A6->>DEV: Teams: "⚠️ Fix needs review"
    Note over A6,DEV: Status = AWAITING_REVIEW<br/>Human must approve before merge
    DEV->>ORC: Approve (merge PR manually)
    ORC->>ORC: transition → COMPLETED
```

---

### 10. Failure Recovery — Global Fallback

```mermaid
sequenceDiagram
    participant ORC as Orchestrator
    participant A4 as Agent 4<br/>Error Analyst
    participant A5 as Agent 5<br/>Code Repairer
    participant A6 as Agent 6<br/>Review & Notify
    participant DEV as Developer

    ORC->>A4: analyze_failure
    A4->>A4: Primary model fails
    A4->>A4: Fallback 1 fails
    A4->>A4: Fallback 2 fails
    A4->>A4: Fallback 3 fails
    A4-->>ORC: AllModelsFailed exception
    Note over ORC: Global fallback triggered!
    ORC->>A6: POST evaluate_and_notify {status: RED, reason: agent_failure, failed_agent: error_analyst}
    A6->>DEV: Teams/Slack: "🛑 Agent 4 crashed — manual intervention"
    ORC->>ORC: transition → FAILED
    Note over ORC,DEV: Human takes over manually
```

---

## Deployment Diagrams

### 11. Docker Compose Deployment (PoC)

```mermaid
graph TD
    subgraph docker["Docker Compose Network: agent-network"]
        A1["jenkins-mcp\nAgent 1: Pipeline Monitor\n:8082"]
        A3["log-cleaner-mcp\nAgent 3: Log Analyst\n:8081"]
        A4["knowledge-graph-mcp\nAgent 4: Error Analyst\n:8084"]
        A5["llm-mcp\nAgent 5: Code Repairer\n:8086"]
        A6["notification-mcp\nAgent 6: Review & Notify\n:8087"]
        ORC["orchestrator-mcp\nOrchestrator\n:8085"]
        GIT["gerrit-mcp\nCode Fetch/Submit\n:8083"]
        SCH["scheduler\nAgent 2: Task Inspector\n(no port)"]
    end

    ORC --> A1
    ORC --> A3
    ORC --> A4
    ORC --> A5
    ORC --> A6
    ORC --> GIT
    SCH --> ORC

    subgraph external["External (via .env)"]
        LLM_API["LLM API\n(configurable)"]
        JENKINS["Jenkins :8080"]
        GITHUB["GitHub API"]
        TEAMS["Teams/Slack\nWebhooks"]
    end

    A5 --> LLM_API
    A1 --> JENKINS
    GIT --> GITHUB
    A6 --> TEAMS
```

---

### 12. Network Topology

```mermaid
graph LR
    subgraph internet["External Network"]
        WEBHOOK["Jenkins\nWebhook"]
        LLM["LLM API Provider"]
        VCS["GitHub / Gerrit"]
        NOTIF["Teams / Slack"]
    end

    subgraph docker["Docker Internal Network (agent-network)"]
        ORC[":8085\nOrchestrator"]
        A1[":8082\nAgent 1"]
        A3[":8081\nAgent 3"]
        A4[":8084\nAgent 4"]
        A5[":8086\nAgent 5"]
        A6[":8087\nAgent 6"]
        GIT[":8083\nGerrit MCP"]
    end

    WEBHOOK -->|"POST :8082"| A1
    A1 --> ORC
    ORC --> A3
    ORC --> A4
    ORC --> GIT
    ORC --> A5
    ORC --> A6
    A5 -->|HTTPS| LLM
    GIT -->|HTTPS API| VCS
    A6 -->|HTTPS webhook| NOTIF
```

---

## Other Diagrams

### 13. Domain Model — Class Diagram

```mermaid
classDiagram
    class BuildEvent {
        +str build_id
        +str repo
        +str branch
        +datetime timestamp
        +str job_name
        +str status
        +str log_url
    }

    class FailureAnalysis {
        +str build_id
        +ErrorType error_type
        +BlastRadius blast_radius
        +list affected_files
        +float confidence
        +str root_cause
        +str stack_trace
    }

    class CodeFix {
        +str build_id
        +str fix_patch
        +list files_to_modify
        +float confidence
        +str explanation
        +bool lint_ok
        +bool test_ok
    }

    class TrafficLightResult {
        +str build_id
        +TrafficLightColour colour
        +float final_score
        +bool auto_merge_allowed
        +str reason
        +BlastRadius blast_radius
        +bool safety_override
    }

    class WorkflowState {
        +str build_id
        +WorkflowStatus status
        +TaskScenario scenario
        +FailureAnalysis failure_analysis
        +CodeFix code_fix
        +TrafficLightResult traffic_light
        +int retry_count
        +int max_retries
    }

    class TrafficLightColour {
        <<enumeration>>
        GREEN
        YELLOW
        RED
    }

    class BlastRadius {
        <<enumeration>>
        LOW
        MEDIUM
        HIGH
    }

    class ErrorType {
        <<enumeration>>
        IMPORT_ERROR
        SYNTAX_ERROR
        TYPE_ERROR
        ASSERTION_ERROR
        FILE_NOT_FOUND
        ATTRIBUTE_ERROR
        UNKNOWN
    }

    class TaskScenario {
        <<enumeration>>
        BUG_FIX_FROM_COMMENT
        AUTONOMOUS_DEVELOPMENT
        YELLOW_MANUAL
    }

    WorkflowState --> FailureAnalysis
    WorkflowState --> CodeFix
    WorkflowState --> TrafficLightResult
    WorkflowState --> TaskScenario
    FailureAnalysis --> ErrorType
    FailureAnalysis --> BlastRadius
    TrafficLightResult --> TrafficLightColour
    TrafficLightResult --> BlastRadius
```

---

### 14. Model Fallback Chain

```mermaid
flowchart LR
    subgraph A5["Agent 5: Code Repairer (example)"]
        P["Primary Model\n(from .env)"]
        F1["Fallback 1\n(from .env)"]
        F2["Fallback 2\n(from .env)"]
        F3["Fallback 3\n(from .env)"]
    end

    P -->|timeout / API error\ntoken budget exceeded| F1
    F1 -->|fails| F2
    F2 -->|fails| F3
    F3 -->|fails| FAIL["AllModelsFailed\n→ Global Fallback\n→ RED"]

    F1 -->|success| RESET["reset() → back to Primary"]
    F2 -->|success| RESET
    F3 -->|success| RESET

    style FAIL fill:#ef4444,color:#fff
    style RESET fill:#22c55e,color:#fff
```

---

### 15. Token Budget Flow

```mermaid
flowchart TD
    REQ["Incoming request to agent"] --> CHECK["token_tracker.check_budget\nagent_name, requested_tokens"]
    CHECK -->|"used + requested > max/hour"| EXCEED["TokenBudgetExceeded\n→ switch_to_next model"]
    CHECK -->|"used + requested ≥ 80% of limit"| WARN["Log WARNING\nBudget at 80%\n→ continue"]
    CHECK -->|"OK"| CALL["Call LLM API"]
    CALL --> RECORD["token_tracker.record_usage\nagent_name, tokens_used"]
    RECORD --> METRIC["Update Prometheus\nagent_tokens_used\nagent_token_budget_remaining"]

    subgraph Reset["Hourly Reset"]
        CLOCK["Every 3600 seconds"] --> CLEAR["_usage.clear()\n_window_start = now"]
    end

    style EXCEED fill:#ef4444,color:#fff
    style WARN fill:#eab308,color:#fff
```
