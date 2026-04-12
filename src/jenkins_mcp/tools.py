"""MCP tool definitions for Agent 1 — Pipeline Monitor."""
from __future__ import annotations

TOOLS: list[dict] = [
    {
        "name": "fetch_logs",
        "description": "Fetch raw build console output from Jenkins",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_name": {"type": "string", "description": "Jenkins job name"},
                "build_id": {"type": "string", "description": "Build number or ID"},
            },
            "required": ["job_name", "build_id"],
        },
    },
    {
        "name": "get_build_info",
        "description": "Get build metadata (status, branch, repo, timestamp)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "build_id": {"type": "string", "description": "Build ID to look up"},
            },
            "required": ["build_id"],
        },
    },
    {
        "name": "handle_webhook",
        "description": "Process an incoming Jenkins build webhook payload",
        "inputSchema": {
            "type": "object",
            "properties": {
                "build_id": {"type": "string"},
                "repo":     {"type": "string"},
                "branch":   {"type": "string"},
                "status":   {"type": "string"},
                "job_name": {"type": "string"},
                "log_url":  {"type": "string"},
            },
            "required": ["build_id", "status"],
        },
    },
]
