"""
Unit tests for exporting the live UI settings into a .env copy.
"""

import io
import unittest

from dotenv import dotenv_values

from src.env_export import merge_env_text, build_numbered_lines, format_env_value


TEMPLATE = (
    "# Inverter\r\n"
    "DEYE_IP=192.168.0.122\r\n"
    "EV_CHARGER_LOCAL_KEY=secret_key\r\n"
    "EV_CHARGER_MAX_AMPS=32                       # Maximum charging current (A)\r\n"
    "EV_CHARGER_SOLAR_MODE=false\r\n"
    "# EV_CHARGER_PHASES=auto\r\n"
    "SCHEDULE_1=23:00-06:00,40,40,185,sell,20,500\r\n"
    "SCHEDULE_2=06:00-08:00,60,0,150,nosell,20,0\r\n"
    "HEATPUMP_SCHEDULE_1=16:00-18:00,40,45\r\n"
    "OUTLET_1_IP=192.168.0.50\r\n"
)


class TestFormatEnvValue(unittest.TestCase):
    def test_types(self):
        self.assertEqual(format_env_value(True), "true")
        self.assertEqual(format_env_value(False), "false")
        self.assertEqual(format_env_value((8, 16, 24)), "8,16,24")
        self.assertEqual(format_env_value(251.5), "251.5")
        self.assertEqual(format_env_value(7), "7")


class TestMergeEnvText(unittest.TestCase):
    def _merge(self, values, groups=None):
        return merge_env_text(TEMPLATE, values, groups)

    def test_replaces_values_and_keeps_everything_else(self):
        out = self._merge({"EV_CHARGER_SOLAR_MODE": True})
        parsed = dotenv_values(stream=io.StringIO(out))
        self.assertEqual(parsed["EV_CHARGER_SOLAR_MODE"], "true")
        self.assertEqual(parsed["DEYE_IP"], "192.168.0.122")
        self.assertEqual(parsed["EV_CHARGER_LOCAL_KEY"], "secret_key")
        self.assertIn("# Inverter\r\n", out)

    def test_keeps_inline_comment_aligned(self):
        out = self._merge({"EV_CHARGER_MAX_AMPS": 16})
        self.assertIn(
            "EV_CHARGER_MAX_AMPS=16                       # Maximum charging current (A)\r\n", out
        )
        self.assertEqual(dotenv_values(stream=io.StringIO(out))["EV_CHARGER_MAX_AMPS"], "16")

    def test_preserves_crlf_line_endings(self):
        out = self._merge({"EV_CHARGER_PHASES": "3"})
        self.assertNotRegex(out.replace("\r\n", ""), "\n")

    def test_missing_and_commented_keys_are_appended(self):
        out = self._merge({"EV_CHARGER_PHASES": "3", "SUNSET_TARGET_SOC": 95})
        self.assertIn("# EV_CHARGER_PHASES=auto\r\n", out)
        self.assertIn("Added by 'Save current settings'", out)
        parsed = dotenv_values(stream=io.StringIO(out))
        self.assertEqual(parsed["EV_CHARGER_PHASES"], "3")
        self.assertEqual(parsed["SUNSET_TARGET_SOC"], "95")

    def test_schedule_group_replaced_in_place(self):
        rows = [
            {"enabled": True, "value": "22:00-05:00,40,40,185,sell,25,600"},
            {"enabled": False, "value": "05:00-07:00,60,0,150,nosell,20,0"},
            {"enabled": True, "value": "07:00-09:00,60,0,150,nosell,20,0"},
        ]
        out = self._merge({}, {"SCHEDULE_": build_numbered_lines("SCHEDULE_", rows)})
        lines = out.splitlines()
        start = lines.index("SCHEDULE_1=22:00-05:00,40,40,185,sell,25,600")
        self.assertEqual(lines[start - 1], "# EV_CHARGER_PHASES=auto")
        self.assertEqual(lines[start + 1], "# DISABLED SCHEDULE_x=05:00-07:00,60,0,150,nosell,20,0")
        self.assertEqual(lines[start + 2], "SCHEDULE_2=07:00-09:00,60,0,150,nosell,20,0")
        self.assertEqual(lines[start + 3], "HEATPUMP_SCHEDULE_1=16:00-18:00,40,45")
        parsed = dotenv_values(stream=io.StringIO(out))
        self.assertNotIn("SCHEDULE_3", parsed)

    def test_reexport_removes_previously_disabled_rows(self):
        first = merge_env_text(TEMPLATE, {}, {"SCHEDULE_": build_numbered_lines(
            "SCHEDULE_", [{"enabled": False, "value": "01:00-02:00,1,1,1,nosell,20,0"}])})
        second = merge_env_text(first, {}, {"SCHEDULE_": build_numbered_lines(
            "SCHEDULE_", [{"enabled": True, "value": "03:00-04:00,2,2,2,sell,20,100"}])})
        self.assertNotIn("DISABLED", second)
        self.assertEqual([l for l in second.splitlines() if l.startswith("SCHEDULE_")],
                         ["SCHEDULE_1=03:00-04:00,2,2,2,sell,20,100"])
        self.assertIn("HEATPUMP_SCHEDULE_1=16:00-18:00,40,45", second)

    def test_deleting_all_rows_removes_group(self):
        out = self._merge({}, {"SCHEDULE_": []})
        self.assertNotIn("\nSCHEDULE_", "\n" + out)
        self.assertIn("HEATPUMP_SCHEDULE_1=", out)

    def test_group_appended_when_template_has_none(self):
        out = merge_env_text("DEYE_IP=1.2.3.4\n", {}, {"HEATPUMP_SCHEDULE_": ["HEATPUMP_SCHEDULE_1=10:00-12:00,30,35"]})
        self.assertTrue(out.endswith("HEATPUMP_SCHEDULE_1=10:00-12:00,30,35\n"))

    def test_empty_template(self):
        out = merge_env_text("", {"EV_CHARGER_MAX_AMPS": 20})
        self.assertEqual(dotenv_values(stream=io.StringIO(out))["EV_CHARGER_MAX_AMPS"], "20")


if __name__ == "__main__":
    unittest.main()
