"""
Unit tests for TeeWriter console/log duplication.
"""

import io
import unittest

from main import TeeWriter


class TestTeeWriter(unittest.TestCase):
    def test_unencodable_text_does_not_raise_and_log_keeps_it(self):
        console_bytes = io.BytesIO()
        console = io.TextIOWrapper(console_bytes, encoding="cp1252", newline="\n")
        log = io.StringIO()
        writer = TeeWriter(console, log)

        writer.write("SOC ≤ 30% 45.0°C\n")
        writer.flush()

        self.assertEqual(log.getvalue(), "SOC ≤ 30% 45.0°C\n")
        self.assertEqual(console_bytes.getvalue().decode("cp1252"), "SOC ? 30% 45.0°C\n")


if __name__ == "__main__":
    unittest.main()
