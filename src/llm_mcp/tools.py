"""MCP tool descriptors for Agent 5 (Code Repairer)."""
from __future__ import annotations

TOOLS: list[dict] = [
    {
        "name": "generate_fix",
        "description": (
            "Generate a minimal code fix for a build failure. "
            "Runs bandit and pylint on the output before returning."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "build_id":      {"type": "string"},
                "error_type":    {"type": "string"},
                "blast_radius":  {"type": "string"},
                "affected_files": {"type": "array", "items": {"type": "string"}},
                "confidence":    {"type": "number"},
                "root_cause":    {"type": "string"},
                "cleaned_logs":  {"type": "string"},
                "code_context":  {"type": "string"},
            },
            "required": ["build_id", "error_type", "blast_radius", "cleaned_logs"],
        },
    },
]
