from __future__ import annotations

from src.log_cleaner_mcp.filters.stack_trace_extractor import extract_stack_traces


class TestExtractStackTraces:
    def test_extracts_python_traceback(self):
        text = (
            "some noise\n"
            "Traceback (most recent call last):\n"
            '  File "main.py", line 5, in <module>\n'
            "    import foo\n"
            "ImportError: No module named foo\n"
            "more noise\n"
        )
        result = extract_stack_traces(text)
        assert "Traceback" in result
        assert "ImportError" in result
        assert "some noise" not in result
        assert "more noise" not in result

    def test_extracts_java_exception(self):
        text = (
            "Normal log\n"
            "Exception in thread main java.lang.NullPointerException\n"
            "\tat com.example.Main.run(Main.java:42)\n"
            "\tat com.example.Main.main(Main.java:10)\n"
            "Another log\n"
        )
        result = extract_stack_traces(text)
        assert "NullPointerException" in result
        assert "com.example.Main" in result
        assert "Normal log" not in result

    def test_no_stack_trace_returns_empty(self):
        text = "INFO: build started\nINFO: downloading artifact\n"
        result = extract_stack_traces(text)
        assert result == ""

    def test_empty_input(self):
        assert extract_stack_traces("") == ""

    def test_caused_by_block(self):
        text = (
            "Caused by: java.io.IOException: File not found\n"
            "\tat com.example.Util.read(Util.java:15)\n"
        )
        result = extract_stack_traces(text)
        assert "Caused by" in result
        assert "com.example.Util" in result
