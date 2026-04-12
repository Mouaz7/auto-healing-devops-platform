"""MCP tool descriptors for Agent 6 (Review & Notify)."""
from __future__ import annotations

TOOLS: list[dict] = [
    {
        "name": "evaluate_and_notify",
        "description": (
            "Evaluate a code fix with traffic light scoring and send "
            "notifications to Teams and Slack."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "build_id":       {"type": "string"},
                "fix_patch":      {"type": "string"},
                "confidence":     {"type": "number"},
                "explanation":    {"type": "string"},
                "error_type":     {"type": "string"},
                "blast_radius":   {"type": "string"},
                "affected_files": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["build_id", "blast_radius"],
        },
    },
]
