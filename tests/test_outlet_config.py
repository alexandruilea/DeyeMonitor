"""
Unit tests for loading OUTLET_N_* blocks: an outlet with an empty IP is skipped
without hiding the outlets numbered after it.
"""

import os
import unittest
from unittest.mock import patch

from src.config import load_outlet_configs


def _block(n: int, ip: str, name: str) -> dict:
    return {f"OUTLET_{n}_IP": ip, f"OUTLET_{n}_NAME": name, f"OUTLET_{n}_USER": "u", f"OUTLET_{n}_PASS": "p"}


class TestLoadOutletConfigs(unittest.TestCase):
    def load(self, env: dict):
        with patch.dict(os.environ, env, clear=True):
            return load_outlet_configs()

    def test_consecutive_outlets(self):
        outlets = self.load({**_block(1, "192.0.2.1", "Heat Pump"), **_block(2, "192.0.2.2", "Extra Load")})
        self.assertEqual([(o.outlet_id, o.name) for o in outlets], [(1, "Heat Pump"), (2, "Extra Load")])

    def test_empty_ip_skips_only_that_outlet(self):
        # Used to stop at the first empty IP, which dropped every outlet after it too
        outlets = self.load({**_block(1, "", "Heat Pump"), **_block(2, "192.0.2.2", "Extra Load")})
        self.assertEqual(len(outlets), 1)
        self.assertEqual(outlets[0].outlet_id, 2)  # Keeps its own number
        self.assertEqual(outlets[0].name, "Extra Load")
        self.assertEqual(outlets[0].priority, 2)  # Default priority still follows the number

    def test_blank_ip_counts_as_empty(self):
        outlets = self.load({**_block(1, "   ", "Heat Pump"), **_block(2, "192.0.2.2", "Extra Load")})
        self.assertEqual([o.outlet_id for o in outlets], [2])

    def test_missing_number_is_not_the_end(self):
        outlets = self.load({**_block(1, "192.0.2.1", "A"), **_block(3, "192.0.2.3", "C")})
        self.assertEqual([o.outlet_id for o in outlets], [1, 3])

    def test_numbers_sorted_numerically(self):
        outlets = self.load({**_block(10, "192.0.2.10", "J"), **_block(2, "192.0.2.2", "B")})
        self.assertEqual([o.outlet_id for o in outlets], [2, 10])

    def test_no_outlets(self):
        self.assertEqual(self.load({"INVERTER_FAN_IP": "192.0.2.9"}), [])


if __name__ == "__main__":
    unittest.main()
