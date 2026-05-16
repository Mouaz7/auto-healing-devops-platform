"""Domain models for the Auto-Healing AI DevOps Platform."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum


class TrafficLightColour(str, Enum):
    """Traffic light result for a generated fix."""

    GREEN = "GREEN"    # score >= 0.85  → human fast-track review
    YELLOW = "YELLOW"  # score 0.60-0.84 → human careful review required
    RED = "RED"        # score < 0.60   → blocked, no PR created


class BlastRadius(str, Enum):
    """How many files a failure affects."""

    LOW = "LOW"       # 1 file
    MEDIUM = "MEDIUM"  # 2-5 files
    HIGH = "HIGH"     # 6+ files — ALWAYS forces RED regardless of confidence


class WorkflowStatus(str, Enum):
    """State machine states for a single workflow run."""

    PENDING = "PENDING"
    ANALYSING = "ANALYSING"
    GENERATING_FIX = "GENERATING_FIX"
    VALIDATING = "VALIDATING"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    APPLYING_FIX = "APPLYING_FIX"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class TaskScenario(str, Enum):
    """Which scenario the task belongs to."""

    BUG_FIX_FROM_COMMENT = "A"    # Agent 4 + Agent 5 (bug from issue comment)
    AUTONOMOUS_DEVELOPMENT = "B"   # Agent 5 only (new feature from description)
    YELLOW_MANUAL = "YELLOW"       # Mixed text — human must classify


class ErrorType(str, Enum):
    """Error type detected by Agent 4 (Error Analyst)."""

    IMPORT_ERROR = "IMPORT_ERROR"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    TYPE_ERROR = "TYPE_ERROR"
    ASSERTION_ERROR = "ASSERTION_ERROR"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    ATTRIBUTE_ERROR = "ATTRIBUTE_ERROR"
    NAME_ERROR = "NAME_ERROR"
    VALUE_ERROR = "VALUE_ERROR"
    KEY_ERROR = "KEY_ERROR"
    INDEX_ERROR = "INDEX_ERROR"
    ZERO_DIVISION_ERROR = "ZERO_DIVISION_ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass
class BuildEvent:
    """Emitted by Agent 1 (Pipeline Monitor) when a build failure is detected."""

    build_id: str
    repo: str
    branch: str
    timestamp: datetime
    job_name: str = ""
    status: str = "FAILED"
    log_url: str = ""


@dataclass
class FailureAnalysis:
    """Output of Agent 4 (Error Analyst)."""

    build_id: str
    error_type: ErrorType
    blast_radius: BlastRadius
    affected_files: list[str] = field(default_factory=list)
    confidence: float = 0.0
    root_cause: str = ""
    stack_trace: str = ""


@dataclass
class CodeFix:
    """Output of Agent 5 (Code Repairer)."""

    build_id: str
    fix_patch: str
    files_to_modify: list[str] = field(default_factory=list)
    confidence: float = 0.0
    explanation: str = ""
    lint_ok: bool = False
    test_ok: bool = False
    changed_lines: dict = field(default_factory=dict)   # {line_number: new_code}
    bugs_found: list = field(default_factory=list)      # ["bug description", ...]
    model_used: str = ""                                 # AI model name used for this fix
    regression_risk: str = ""                            # human-readable side-effect warning
    test_hints: list = field(default_factory=list)       # ["test suggestion", ...]


@dataclass
class TrafficLightResult:
    """Output of Agent 6 (Review & Notify) — traffic light evaluation."""

    build_id: str
    colour: TrafficLightColour
    final_score: float
    auto_merge_allowed: bool
    reason: str
    blast_radius: BlastRadius
    safety_override: bool = False  # True when HIGH blast radius forced RED


@dataclass
class WorkflowState:  # pylint: disable=too-many-instance-attributes
    """Full state of one pipeline run through all 6 agents."""

    build_id: str
    status: WorkflowStatus
    scenario: TaskScenario | None = None
    failure_analysis: FailureAnalysis | None = None
    code_fix: CodeFix | None = None
    traffic_light: TrafficLightResult | None = None
    retry_count: int = 0
    max_retries: int = 3
    error_message: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # updated_at: set by orchestrator on each state transition
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
