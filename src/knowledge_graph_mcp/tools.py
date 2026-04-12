"""MCP tool descriptors for Agent 4 (Error Analyst)."""
from __future__ import annotations

TOOLS: list[dict] = [
    {
        "name": "analyze_failure",
        "description": (
            "Analyse cleaned build logs to identify the error type, root cause, "
            "affected files, and blast radius."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "build_id": {
                    "type": "string",
                    "description": "Unique build identifier.",
                },
                "cleaned_logs": {
                    "type": "string",
                    "description": "Pre-cleaned build log output from Agent 3.",
                },
            },
            "required": ["build_id", "cleaned_logs"],
        },
    },
]
