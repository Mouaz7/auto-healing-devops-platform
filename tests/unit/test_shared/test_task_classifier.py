"""Unit tests for Agent 2: TaskClassifier."""
from __future__ import annotations

import pytest

from src.scheduler.task_classifier import TaskClassifier, _parse_llm_scenario
from src.shared.models import TaskScenario


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def classifier() -> TaskClassifier:
    """Classifier in regex-only mode (no NIM client)."""
    return TaskClassifier(nim_client=None)


# ---------------------------------------------------------------------------
# Regex fast path — Scenario A (bug)
# ---------------------------------------------------------------------------

class TestScenarioA:
    def test_error_keyword_is_bug(self, classifier):
        result = classifier.classify("Build error", "ImportError in module", [])
        assert result == TaskScenario.BUG_FIX_FROM_COMMENT

    def test_traceback_in_description(self, classifier):
        result = classifier.classify("CI failed", 'File "src/app.py", line 3', [])
        assert result == TaskScenario.BUG_FIX_FROM_COMMENT

    def test_exception_word_is_bug(self, classifier):
        result = classifier.classify("NullPointerException", "", [])
        assert result == TaskScenario.BUG_FIX_FROM_COMMENT

    def test_failed_keyword_is_bug(self, classifier):
        result = classifier.classify("Tests failed", "", [])
        assert result == TaskScenario.BUG_FIX_FROM_COMMENT

    def test_crash_keyword_is_bug(self, classifier):
        result = classifier.classify("App crash on startup", "", [])
        assert result == TaskScenario.BUG_FIX_FROM_COMMENT

    def test_code_pattern_triple_backtick(self, classifier):
        result = classifier.classify("Issue", "```\nraise ValueError\n```", [])
        assert result == TaskScenario.BUG_FIX_FROM_COMMENT

    def test_attributeerror_name_is_bug(self, classifier):
        result = classifier.classify("AttributeError on login", "", [])
        assert result == TaskScenario.BUG_FIX_FROM_COMMENT


# ---------------------------------------------------------------------------
# Regex fast path — Scenario B (feature)
# ---------------------------------------------------------------------------

class TestScenarioB:
    def test_feature_keyword_is_b(self, classifier):
        result = classifier.classify("Add dark mode", "Implement dark mode toggle", [])
        assert result == TaskScenario.AUTONOMOUS_DEVELOPMENT

    def test_create_keyword_is_b(self, classifier):
        result = classifier.classify("Create export feature", "", [])
        assert result == TaskScenario.AUTONOMOUS_DEVELOPMENT

    def test_implement_keyword_is_b(self, classifier):
        result = classifier.classify("Implement OAuth login", "", [])
        assert result == TaskScenario.AUTONOMOUS_DEVELOPMENT

    def test_new_keyword_is_b(self, classifier):
        result = classifier.classify("New dashboard widget", "", [])
        assert result == TaskScenario.AUTONOMOUS_DEVELOPMENT

    def test_enable_keyword_is_b(self, classifier):
        result = classifier.classify("Enable 2FA support", "", [])
        assert result == TaskScenario.AUTONOMOUS_DEVELOPMENT


# ---------------------------------------------------------------------------
# YELLOW — ambiguous or empty
# ---------------------------------------------------------------------------

class TestYellowManual:
    def test_empty_text_is_yellow(self, classifier):
        result = classifier.classify("", "", [])
        assert result == TaskScenario.YELLOW_MANUAL

    def test_whitespace_only_is_yellow(self, classifier):
        result = classifier.classify("   ", "  ", [])
        assert result == TaskScenario.YELLOW_MANUAL

    def test_both_bug_and_feature_is_yellow(self, classifier):
        result = classifier.classify(
            "Fix and add feature", "error in new implementation", []
        )
        assert result == TaskScenario.YELLOW_MANUAL

    def test_generic_text_no_keywords_is_yellow(self, classifier):
        result = classifier.classify("Update README", "Minor docs update", [])
        assert result == TaskScenario.YELLOW_MANUAL


# ---------------------------------------------------------------------------
# LLM fallback
# ---------------------------------------------------------------------------

class TestLlmFallback:
    def test_llm_called_for_ambiguous_text(self, monkeypatch):
        """When regex is ambiguous, LLM should be called."""
        called = []

        class FakeNim:
            def complete(self, messages):
                called.append(messages)
                return "A"

        clf = TaskClassifier(nim_client=FakeNim())
        # Ambiguous: both bug and feature keywords
        clf.classify("Fix and add feature", "error in new code", [])
        assert len(called) == 1

    def test_llm_not_called_for_clear_bug(self, monkeypatch):
        """When regex is unambiguous, LLM should NOT be called."""
        called = []

        class FakeNim:
            def complete(self, messages):
                called.append(messages)
                return "A"

        clf = TaskClassifier(nim_client=FakeNim())
        clf.classify("ImportError in app", "", [])
        assert len(called) == 0

    def test_llm_returns_a_maps_to_bug(self):
        class FakeNim:
            def complete(self, messages):
                return "A"

        clf = TaskClassifier(nim_client=FakeNim())
        # Ambiguous input → LLM decides
        result = clf.classify("Possible issue", "Something happened", [])
        assert result == TaskScenario.BUG_FIX_FROM_COMMENT

    def test_llm_returns_b_maps_to_feature(self):
        class FakeNim:
            def complete(self, messages):
                return "B"

        clf = TaskClassifier(nim_client=FakeNim())
        result = clf.classify("Possible issue", "Something happened", [])
        assert result == TaskScenario.AUTONOMOUS_DEVELOPMENT

    def test_llm_failure_falls_back_to_yellow(self):
        class FakeNim:
            def complete(self, messages):
                raise RuntimeError("API down")

        clf = TaskClassifier(nim_client=FakeNim())
        result = clf.classify("Something", "Something else", [])
        assert result == TaskScenario.YELLOW_MANUAL


# ---------------------------------------------------------------------------
# LLM response parsing
# ---------------------------------------------------------------------------

class TestParseLlmScenario:
    def test_a_returns_bug(self):
        assert _parse_llm_scenario("A") == TaskScenario.BUG_FIX_FROM_COMMENT

    def test_a_with_explanation(self):
        assert _parse_llm_scenario("A — this is a bug") == TaskScenario.BUG_FIX_FROM_COMMENT

    def test_b_returns_feature(self):
        assert _parse_llm_scenario("B") == TaskScenario.AUTONOMOUS_DEVELOPMENT

    def test_yellow_returns_manual(self):
        assert _parse_llm_scenario("YELLOW") == TaskScenario.YELLOW_MANUAL

    def test_unknown_returns_yellow(self):
        assert _parse_llm_scenario("C") == TaskScenario.YELLOW_MANUAL

    def test_lowercase_a_works(self):
        assert _parse_llm_scenario("a") == TaskScenario.BUG_FIX_FROM_COMMENT
