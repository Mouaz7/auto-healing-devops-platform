"""MCP tool descriptors for the Orchestrator."""
from __future__ import annotations

TOOLS: list[dict] = [
    {
        "name": "handle_build_failure",
        "description": (
            "Register a build failure and start a new workflow through the "
            "6-agent auto-healing pipeline."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "build_id": {
                    "type": "string",
                    "description": "Unique Jenkins build identifier.",
                },
            },
            "required": ["build_id"],
        },
    },
    {
        "name": "get_workflow_status",
        "description": "Return the current workflow status for a given build.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "build_id": {"type": "string"},
            },
            "required": ["build_id"],
        },
    },
]
