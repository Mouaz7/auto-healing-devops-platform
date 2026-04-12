"""MCP tool descriptors for Agent 3 (Log Analyst / Log Cleaner)."""
from __future__ import annotations

TOOLS: list[dict] = [
    {
        "name": "clean_log",
        "description": (
            "Clean a raw Jenkins build log by removing noise and extracting "
            "failure-relevant lines. Returns cleaned text and reduction metrics."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "raw_log": {
                    "type": "string",
                    "description": "Raw build log text to clean.",
                },
                "build_id": {
                    "type": "string",
                    "description": "Optional build identifier for tracing.",
                },
            },
            "required": ["raw_log"],
        },
    },
]
