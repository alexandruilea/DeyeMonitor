"""
Unit tests for per-register write throttling and max-charge register consistency.
"""

import time
import unittest
from unittest.mock import MagicMock, patch

from src.config import _parse_register_intervals, deye_config
from src.deye_inverter import DeyeInverter, InverterData
from main import DeyeApp


class TestRegisterIntervalConfig(unittest.TestCase):
    def test_parse_overrides(self):
        self.assertEqual(_parse_register_intervals("108:600, 143:60"), {108: 600, 143: 60})

    def test_parse_ignores_empty_and_malformed(self):
        self.assertEqual(_parse_register_intervals(""), {})
        self.assertEqual(_parse_register_intervals("abc:1,108,109:x,110:5"), {110: 5})
        self.assertEqual(_parse_register_intervals("  # just a comment"), {})
        self.assertEqual(_parse_register_intervals("108:600 # trailing"), {108: 600})

    def test_get_interval_falls_back_to_default(self):
        with patch.object(deye_config, "register_write_intervals", {143: 60}), \
             patch.object(deye_config, "min_register_write_interval", 600):
            self.assertEqual(deye_config.get_register_write_interval(143), 60)
            self.assertEqual(deye_config.get_register_write_interval(108), 600)


class TestInverterWriteThrottle(unittest.TestCase):
    def setUp(self):
        self.inv = DeyeInverter()
        self.inv._connect = MagicMock(return_value=True)
        self.inv._modbus = MagicMock()
        self.registers = {}
        self.inv._modbus.read_holding_registers.side_effect = lambda reg, n: [self.registers.get(reg, 0)]
        self.inv._modbus.write_multiple_holding_registers.side_effect = (
            lambda reg, vals: self.registers.__setitem__(reg, vals[0]))
        patcher_a = patch.object(deye_config, "min_register_write_interval", 600)
        patcher_b = patch.object(deye_config, "register_write_intervals", {})
        patcher_a.start()
        patcher_b.start()
        self.addCleanup(patcher_a.stop)
        self.addCleanup(patcher_b.stop)

    def test_second_write_to_same_register_is_throttled(self):
        self.assertTrue(self.inv._write_register(108, 40))
        self.assertFalse(self.inv._write_register(108, 60))
        self.assertEqual(self.registers[108], 40)
        self.assertGreater(self.inv.write_cooldown_remaining(108), 590)

    def test_throttle_is_per_register(self):
        self.assertTrue(self.inv._write_register(108, 40))
        self.assertTrue(self.inv._write_register(109, 100))
        self.assertEqual(self.registers[109], 100)
        self.assertEqual(self.inv.write_cooldown_remaining(143), 0)

    def test_write_allowed_after_interval(self):
        self.assertTrue(self.inv._write_register(108, 40))
        value, _ = self.inv._write_cache[108]
        self.inv._write_cache[108] = (value, time.time() - 601)
        self.assertEqual(self.inv.write_cooldown_remaining(108), 0)
        self.assertTrue(self.inv._write_register(108, 60))
        self.assertEqual(self.registers[108], 60)

    def test_noop_write_does_not_start_cooldown(self):
        self.registers[108] = 40
        self.assertTrue(self.inv._write_register(108, 40))
        self.inv._modbus.write_multiple_holding_registers.assert_not_called()
        self.assertEqual(self.inv.write_cooldown_remaining(108), 0)
        self.assertTrue(self.inv._write_register(108, 60))
        self.assertEqual(self.registers[108], 60)

    def test_per_register_override(self):
        with patch.object(deye_config, "register_write_intervals", {108: 30}):
            self.assertTrue(self.inv._write_register(108, 40))
            self.assertLessEqual(self.inv.write_cooldown_remaining(108), 30)


class TestMaxChargeConsistency(unittest.TestCase):
    def setUp(self):
        self.app = MagicMock(spec=DeyeApp)
        self.app._offgrid_active = False
        self.app._apply_charge_caps = DeyeApp._apply_charge_caps.__get__(self.app, DeyeApp)
        self.app._get_export_breakdown = DeyeApp._get_export_breakdown.__get__(self.app, DeyeApp)
        self.app._is_charge_speed_settled = DeyeApp._is_charge_speed_settled.__get__(self.app, DeyeApp)

    def test_charge_caps_without_bms_limit(self):
        self.app._bms_charge_limit = 0
        self.app._current_max_charge = 20
        self.assertEqual(self.app._apply_charge_caps(40), 40)
        self.assertEqual(self.app._apply_charge_caps(10_000), deye_config.max_charge_amps_limit)

    def test_raise_below_bms_limit_writes_full_target(self):
        """Register below the BMS limit: write the full 150A target, not the 100A BMS limit."""
        self.app._bms_charge_limit = 100
        self.app._current_max_charge = 60
        self.assertEqual(self.app._apply_charge_caps(150), 150)
        self.assertEqual(self.app._apply_charge_caps(80), 80)

    def test_rising_bms_limit_needs_no_further_write(self):
        """After the full target is written, a BMS limit rising towards it keeps the register as is."""
        self.app._current_max_charge = 60
        self.app._bms_charge_limit = 100
        written = self.app._apply_charge_caps(150)
        self.app._current_max_charge = written
        for bms_limit in (110, 130, 150):
            self.app._bms_charge_limit = bms_limit
            self.assertEqual(self.app._apply_charge_caps(150), written)

    def test_no_write_above_bms_limit_when_register_meets_it(self):
        """Register at/above the BMS limit: a higher target leaves the register untouched."""
        self.app._current_max_charge = 120
        self.app._bms_charge_limit = 100
        self.assertEqual(self.app._apply_charge_caps(200), 120)
        self.app._current_max_charge = 100
        self.assertEqual(self.app._apply_charge_caps(200), 100)

    def test_falling_bms_limit_does_not_change_target(self):
        """Register already at/above BMS limit: keep it, no write to follow the BMS down."""
        self.app._current_max_charge = 100
        self.app._bms_charge_limit = 37
        self.assertEqual(self.app._apply_charge_caps(140), 100)
        self.assertEqual(self.app._apply_charge_caps(160), 100)

    def test_real_reduction_below_bms_still_applies(self):
        self.app._current_max_charge = 100
        self.app._bms_charge_limit = 37
        self.assertEqual(self.app._apply_charge_caps(20), 20)

    def test_offgrid_multiplier_follows_bms_rule(self):
        self.app._offgrid_active = True
        self.app._current_max_charge = 40
        self.app._bms_charge_limit = 100
        self.assertEqual(self.app._apply_charge_caps(80), 120)  # 80 × 1.5 = 120, register below BMS → full target
        self.app._current_max_charge = 100
        self.assertEqual(self.app._apply_charge_caps(80), 100)  # register meets BMS → no write

    def test_writers_agree_after_capped_write(self):
        """Value written by one path is recomputed identically by the others."""
        self.app._bms_charge_limit = 100
        self.app._current_max_charge = 60
        written = self.app._apply_charge_caps(180)
        self.app._current_max_charge = written
        self.assertEqual(self.app._apply_charge_caps(180), written)

    def test_settled_check_uses_bms_limit(self):
        """Register above BMS limit: settled when charging at the BMS-limited rate."""
        self.app._current_max_charge = 40
        data = InverterData(
            soc=97, battery_power=-25 * 55, pv_power=8000, grid_power=-3000,
            voltages=[240.0] * 3, ups_loads=[500] * 3, grid_loads=[0] * 3,
            total_loads=[500] * 3, running_state=2, is_grid_connected=True,
            battery_voltage=55.0, bms_charge_current_limit=25,
        )
        self.assertTrue(self.app._is_charge_speed_settled(data, 55.0))


class TestProtectionRespectsCooldown(unittest.TestCase):
    def setUp(self):
        self.app = MagicMock(spec=DeyeApp)
        self.app._protection_boost_amps = 0
        self.app._protection_active = False
        self.app._last_protection_adjustment = 0
        self.app._current_max_charge = 20
        self.app._sunset_active = False
        self.app._sunset_boost_amps = 0
        self.app._offgrid_active = False
        self.app.inverter = MagicMock()
        self.app.protection_panel = MagicMock()
        self.app.protection_panel.is_enabled.return_value = True
        self.app.protection_panel.get_settings.return_value = {
            "max_sell_power": 3000,
            "power_threshold_pct": 80,
            "recovery_threshold_pct": 60,
            "voltage_warning": 253.0,
            "voltage_recovery": 248.0,
            "charge_step": 10,
            "adjustment_interval": 10,
        }
        self.app.after = MagicMock(side_effect=lambda delay, fn, *args: fn(*args) if callable(fn) else None)
        self.app._get_export_breakdown = DeyeApp._get_export_breakdown.__get__(self.app, DeyeApp)
        self.app._process_overpower_protection = DeyeApp._process_overpower_protection.__get__(self.app, DeyeApp)

    def test_no_boost_while_register_cooling_down(self):
        self.app.inverter.max_charge_cooldown_remaining.return_value = 300
        data = InverterData(
            soc=60, battery_power=-1000, pv_power=8000, grid_power=-2900,
            voltages=[240.0] * 3, ups_loads=[1000] * 3, grid_loads=[0] * 3,
            total_loads=[1000] * 3, running_state=2, is_grid_connected=True,
            battery_voltage=52.0, bms_charge_current_limit=180,
        )
        self.app._process_overpower_protection(data)
        self.app.inverter.set_max_charge_current.assert_not_called()
        self.assertEqual(self.app._protection_boost_amps, 0)


if __name__ == "__main__":
    unittest.main()
