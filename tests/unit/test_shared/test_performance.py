"""Performance baseline tests — verify speed guarantees."""
from __future__ import annotations

import time


class TestLogCleanerSpeed:
    def test_log_cleaner_pipeline_speed(self):
        """Pipeline handles 1000-line log in under 1 second."""
        from src.log_cleaner_mcp.pipeline import LogCleaningPipeline

        big_log = "Some noise line\n" * 900 + "ImportError: cannot import name 'Foo'\n" * 100
        pipeline = LogCleaningPipeline(nim_client=None)

        start = time.perf_counter()
        result = pipeline.clean(big_log)
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"Pipeline took {elapsed:.2f}s — expected < 1.0s"
        assert result.reduction_ratio > 0.5


class TestFailureAnalyserSpeed:
    def test_failure_analyser_speed(self):
        """FailureAnalyser regex analysis completes in under 0.1 second."""
        from src.knowledge_graph_mcp.failure_analyser import FailureAnalyser

        analyser = FailureAnalyser(nim_client=None)
        logs = (
            "ImportError: cannot import name 'Foo' from 'bar'\n"
            '  File "src/main.py", line 10, in <module>\n'
        )

        start = time.perf_counter()
        result = analyser.analyse(logs, "build-perf")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.1, f"FailureAnalyser took {elapsed:.3f}s — expected < 0.1s"
        assert result.error_type.value == "IMPORT_ERROR"


class TestTrafficLightSpeed:
    def test_traffic_light_throughput(self):
        """evaluate_traffic_light handles 10 000 calls in under 2 seconds."""
        from src.notification_mcp.traffic_light_evaluator import evaluate_traffic_light
        from src.shared.models import BlastRadius, CodeFix, ErrorType, FailureAnalysis

        fix = CodeFix("perf-b", "patch", confidence=0.9)
        analysis = FailureAnalysis(
            "perf-b", ErrorType.IMPORT_ERROR, BlastRadius.LOW
        )

        start = time.perf_counter()
        for _ in range(10_000):
            evaluate_traffic_light(fix, analysis)
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, f"Traffic light took {elapsed:.2f}s for 10k calls"


class TestCircuitBreakerSpeed:
    def test_circuit_breaker_record_speed(self):
        """CircuitBreaker handles 100 000 record_failure calls in under 1 second."""
        from src.shared.resilience import CircuitBreaker

        cb = CircuitBreaker("perf-test", failure_threshold=999_999)

        start = time.perf_counter()
        for _ in range(100_000):
            cb.record_failure()
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"CircuitBreaker took {elapsed:.2f}s for 100k calls"


class TestQualityGatesSpeed:
    def test_evaluate_quality_speed(self):
        """evaluate_quality (pure Python, no subprocess) completes instantly."""
        from src.shared.quality_gates import BanditResult, PylintResult, evaluate_quality

        bandit = BanditResult(ok=True, high_count=0, issues=[])
        pylint = PylintResult(ok=True, score=9.0, messages=[])

        start = time.perf_counter()
        for _ in range(100_000):
            evaluate_quality(bandit, pylint)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, f"evaluate_quality took {elapsed:.3f}s for 100k calls"
