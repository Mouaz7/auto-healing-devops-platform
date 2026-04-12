from __future__ import annotations

import pytest


@pytest.fixture
def jenkins_webhook_payload():
    return {
        "build_id": "jenkins-build-42",
        "repo": "example/my-python-app",
        "branch": "main",
        "status": "FAILURE",
        "log_url": "http://jenkins.local/job/my-python-app/42/consoleText",
    }


@pytest.fixture
def mock_jenkins_log():
    return (
        "[INFO] Scanning for projects...\n"
        "[ERROR] ImportError: cannot import name Config\n"
        "Traceback (most recent call last):\n"
        "  File src/main.py, line 5\n"
        "    from config import Config\n"
        "ImportError: cannot import name Config\n"
        "[INFO] BUILD FAILURE\n"
    )
