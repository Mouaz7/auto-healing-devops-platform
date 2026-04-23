"""Secret scanner — detects hardcoded credentials in AI-generated code.

Scans fix patches before they are pushed to GitHub.  A fix that contains
a hardcoded API key, password, or private key is blocked (confidence set to 0)
to prevent accidental secret leakage in public repositories.

Usage:
    from src.shared.secret_scanner import scan_for_secrets, SecretScanResult

    result = scan_for_secrets(fix_patch)
    if result.found:
        logger.error("secrets found: %s", result.findings)
        # do not push the patch
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Pattern catalogue
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key",    re.compile(r'AKIA[0-9A-Z]{16}', re.ASCII)),
    ("aws_secret_key",    re.compile(r'(?i)aws.{0,20}secret.{0,20}["\'][0-9a-zA-Z/+]{40}["\']')),
    ("github_token",      re.compile(r'gh[pousr]_[0-9A-Za-z]{36,}', re.ASCII)),
    ("nvapi_key",         re.compile(r'nvapi-[0-9A-Za-z_\-]{20,}', re.ASCII)),
    ("private_key_block", re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')),
    ("generic_password",  re.compile(
        r'(?i)(?:password|passwd|pwd|secret|api[_\-]?key|auth[_\-]?token)'
        r'\s*[=:]\s*["\'](?!<)[^"\']{8,}["\']'
    )),
    ("bearer_token",      re.compile(r'(?i)bearer\s+[0-9a-zA-Z\-._~+/]{20,}')),
    ("slack_token",       re.compile(r'xox[baprs]-[0-9A-Za-z\-]{10,}', re.ASCII)),
    ("stripe_key",        re.compile(r'(?:sk|pk)_(?:live|test)_[0-9a-zA-Z]{24,}', re.ASCII)),
    ("jwt_token",         re.compile(r'eyJ[0-9A-Za-z_\-]+\.[0-9A-Za-z_\-]+\.[0-9A-Za-z_\-]+')),
    ("hex_secret_40",     re.compile(
        r'(?i)(?:token|secret|key)\s*[=:]\s*["\'][0-9a-f]{40}["\']'
    )),
]

# Lines that look like env-var reads — safe, not hardcoded secrets
_SAFE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'os\.(?:environ|getenv)\b'),
    re.compile(r'os\.environ\['),
    re.compile(r'\bgetenv\b'),
    re.compile(r'\bprocess\.env\b'),
    re.compile(r'#.*example', re.IGNORECASE),
    re.compile(r'#.*placeholder', re.IGNORECASE),
    re.compile(r'YOUR_\w+_HERE', re.IGNORECASE),
    re.compile(r'<YOUR[-_]\w+>'),
]


@dataclass
class SecretFinding:
    """One detected secret instance."""

    kind: str
    line_number: int
    snippet: str       # redacted excerpt for logging


@dataclass
class SecretScanResult:
    """Result of scanning a code patch."""

    found: bool
    findings: list[SecretFinding] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if not self.found:
            return "no secrets detected"
        kinds = ", ".join({f.kind for f in self.findings})
        return f"{len(self.findings)} potential secret(s) detected: {kinds}"


def _is_safe_line(line: str) -> bool:
    """Return True if the line is likely a safe env-var reference, not hardcoded."""
    return any(p.search(line) for p in _SAFE_PATTERNS)


def _redact(text: str, max_len: int = 40) -> str:
    """Return a redacted snippet safe for logging."""
    snippet = text[:max_len]
    if len(text) > max_len:
        snippet += "..."
    # Replace actual secret-looking chars with asterisks past position 6
    if len(snippet) > 6:
        snippet = snippet[:6] + "***"
    return snippet


def scan_for_secrets(code: str) -> SecretScanResult:
    """Scan *code* for hardcoded secrets.

    Args:
        code: Source code string (fix patch or full file content).

    Returns:
        :class:`SecretScanResult` with ``found=True`` if any secrets detected.
    """
    findings: list[SecretFinding] = []

    for lineno, line in enumerate(code.splitlines(), start=1):
        if _is_safe_line(line):
            continue
        for kind, pattern in _PATTERNS:
            match = pattern.search(line)
            if match:
                findings.append(SecretFinding(
                    kind=kind,
                    line_number=lineno,
                    snippet=_redact(match.group(0)),
                ))

    return SecretScanResult(found=bool(findings), findings=findings)
