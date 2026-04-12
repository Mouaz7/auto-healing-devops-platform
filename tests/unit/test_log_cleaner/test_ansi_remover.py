from __future__ import annotations

from src.log_cleaner_mcp.filters.ansi_remover import remove_ansi


class TestRemoveAnsi:
    def test_removes_colour_codes(self, ansi_log):
        result = remove_ansi(ansi_log)
        assert "\x1b" not in result

    def test_preserves_text_content(self, ansi_log):
        result = remove_ansi(ansi_log)
        assert "ERROR" in result
        assert "INFO" in result
        assert "ImportError" in result

    def test_plain_text_unchanged(self):
        text = "This is a plain log line\n"
        assert remove_ansi(text) == text

    def test_removes_csi_cursor_sequences(self):
        text = "\x1b[2J\x1b[H cleared"
        result = remove_ansi(text)
        assert "\x1b" not in result
        assert "cleared" in result

    def test_empty_string(self):
        assert remove_ansi("") == ""

    def test_multiline(self):
        text = "\x1b[32mGREEN\x1b[0m\n\x1b[31mRED\x1b[0m\n"
        result = remove_ansi(text)
        assert "GREEN" in result
        assert "RED" in result
        assert "\x1b" not in result
