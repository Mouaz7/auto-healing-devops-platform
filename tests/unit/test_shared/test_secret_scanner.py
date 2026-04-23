"""Unit tests for src.shared.secret_scanner."""
from __future__ import annotations

import pytest

from src.shared.secret_scanner import scan_for_secrets, SecretScanResult


class TestScanForSecrets:
    def test_clean_code_returns_no_findings(self):
        code = "def add(a, b):\n    return a + b\n"
        result = scan_for_secrets(code)
        assert result.found is False
        assert result.findings == []
        assert result.summary == "no secrets detected"

    def test_aws_access_key_detected(self):
        code = "key = 'AKIAIOSFODNN7EXAMPLE'\n"
        result = scan_for_secrets(code)
        assert result.found is True
        assert any(f.kind == "aws_access_key" for f in result.findings)

    def test_github_token_detected(self):
        code = "TOKEN = 'ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ123456789A'\n"
        result = scan_for_secrets(code)
        assert result.found is True
        assert any(f.kind == "github_token" for f in result.findings)

    def test_nvapi_key_detected(self):
        code = "client = NvClient(api_key='nvapi-XYZ1234567890abcdefghij')\n"
        result = scan_for_secrets(code)
        assert result.found is True
        assert any(f.kind == "nvapi_key" for f in result.findings)

    def test_private_key_block_detected(self):
        code = "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n"
        result = scan_for_secrets(code)
        assert result.found is True
        assert any(f.kind == "private_key_block" for f in result.findings)

    def test_env_var_read_is_safe(self):
        code = "api_key = os.getenv('MY_API_KEY')\n"
        result = scan_for_secrets(code)
        assert result.found is False

    def test_os_environ_is_safe(self):
        code = "token = os.environ['SLACK_TOKEN']\n"
        result = scan_for_secrets(code)
        assert result.found is False

    def test_placeholder_comment_is_safe(self):
        code = "# password = 'example-placeholder'\n"
        result = scan_for_secrets(code)
        assert result.found is False

    def test_slack_token_detected(self):
        code = "SLACK_TOKEN = 'xoxb-REDACTED-REDACTED-REDACTEDREDACTEDREDACTE'\n"
        result = scan_for_secrets(code)
        assert result.found is True
        assert any(f.kind == "slack_token" for f in result.findings)

    def test_finding_has_correct_line_number(self):
        code = "line one\nkey = 'AKIAIOSFODNN7EXAMPLE'\nline three\n"
        result = scan_for_secrets(code)
        assert result.found is True
        aws_findings = [f for f in result.findings if f.kind == "aws_access_key"]
        assert aws_findings[0].line_number == 2

    def test_empty_code_is_safe(self):
        result = scan_for_secrets("")
        assert result.found is False

    def test_summary_lists_all_kinds(self):
        code = (
            "key = 'AKIAIOSFODNN7EXAMPLE'\n"
            "tok = 'ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ123456789A'\n"
        )
        result = scan_for_secrets(code)
        assert result.found is True
        assert "potential secret" in result.summary
