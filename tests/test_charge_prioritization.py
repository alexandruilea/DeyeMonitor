"""
Unit tests for Time of Use charge prioritization logic.
"""

import unittest
from unittest.mock import MagicMock, patch
import time
from datetime import datetime

from src.deye_inverter import InverterData
from main import DeyeApp


class TestChargePrioritization(unittest.TestCase):
    def setUp(self):
        self.app = MagicMock(spec=DeyeApp)
        # Bind the methods under test
        self.app._process_charge_prioritization = DeyeApp._process_charge_prioritization.__get__(self.app, DeyeApp)
        self.app._get_current_tou_slot_index = DeyeApp._get_current_tou_slot_index.__get__(self.app, DeyeApp)

        # Mock inverter
        self.app.inverter = MagicMock()
        self.app.inverter.set_time_of_use_target_soc.return_value = True

        # Mock prioritization panel
        self.app.prioritization_panel = MagicMock()
        self.app.prioritization_panel.is_enabled.return_value = True
        self.app.prioritization_panel.get_settings.return_value = {
            "enabled": True,
            "boost_target_soc": 90,
            "normal_target_soc": 20,
            "sell_trigger_power": 1000,
            "grid_pull_threshold_w": 500,
            "grid_pull_duration_sec": 300,
        }

        # Initialize tracking state variables
        self.app._prioritization_boosted = False
        self.app._prioritization_grid_pull_since = None
        self.app._last_tou_target_soc = None
        self.app._last_prioritization_slot_idx = None
        self.app._last_tou_read_time = time.time()
        self.app._protection_active = False
        self.app._protection_boost_amps = 0
        self.app._sunset_active = False
        self.app._sunset_boost_amps = 0
        self.app._log_error = MagicMock()
        self.app.after = MagicMock()

        # Set up 6 TOU slots matching user's inverter (registers 148-153):
        # Slot 0 (Time 1, reg 166): 01:00 - 07:00
        # Slot 1 (Time 2, reg 167): 07:00 - 11:30
        # Slot 2 (Time 3, reg 168): 11:30 - 16:00
        # Slot 3 (Time 4, reg 169): 16:00 - 20:00
        # Slot 4 (Time 5, reg 170): 20:00 - 23:00
        # Slot 5 (Time 6, reg 171): 23:00 - 01:00
        self.app._tou_slots_cache = [
            {"slot_idx": 0, "end_time": 100, "end_hour": 1, "end_min": 0, "target_soc": 20, "soc_register": 166},
            {"slot_idx": 1, "end_time": 700, "end_hour": 7, "end_min": 0, "target_soc": 20, "soc_register": 167},
            {"slot_idx": 2, "end_time": 1130, "end_hour": 11, "end_min": 30, "target_soc": 20, "soc_register": 168},
            {"slot_idx": 3, "end_time": 1600, "end_hour": 16, "end_min": 0, "target_soc": 20, "soc_register": 169},
            {"slot_idx": 4, "end_time": 2000, "end_hour": 20, "end_min": 0, "target_soc": 20, "soc_register": 170},
            {"slot_idx": 5, "end_time": 2300, "end_hour": 23, "end_min": 0, "target_soc": 20, "soc_register": 171},
        ]

    def test_get_current_tou_slot_index(self):
        """Verify time mapping into correct slot indices."""
        # 04:30 should be Time 1 (01:00 - 07:00) -> slot index 0 (reg 166)
        t1 = datetime(2026, 6, 1, 4, 30)
        self.assertEqual(self.app._get_current_tou_slot_index(t1), 0)

        # 09:15 should be Time 2 (07:00 - 11:30) -> slot index 1 (reg 167)
        t2 = datetime(2026, 6, 1, 9, 15)
        self.assertEqual(self.app._get_current_tou_slot_index(t2), 1)

        # 13:35 should be Time 3 (11:30 - 16:00) -> slot index 2 (reg 168)
        t3 = datetime(2026, 6, 1, 13, 35)
        self.assertEqual(self.app._get_current_tou_slot_index(t3), 2)

        # 17:00 should be Time 4 (16:00 - 20:00) -> slot index 3 (reg 169)
        t4 = datetime(2026, 6, 1, 17, 0)
        self.assertEqual(self.app._get_current_tou_slot_index(t4), 3)

        # 21:00 should be Time 5 (20:00 - 23:00) -> slot index 4 (reg 170)
        t5 = datetime(2026, 6, 1, 21, 0)
        self.assertEqual(self.app._get_current_tou_slot_index(t5), 4)

        # 23:30 should be Time 6 (23:00 - 01:00) -> slot index 5 (reg 171)
        t6 = datetime(2026, 6, 1, 23, 30)
        self.assertEqual(self.app._get_current_tou_slot_index(t6), 5)

        # 00:30 should also be Time 6 (23:00 - 01:00) -> slot index 5 (reg 171)
        t7 = datetime(2026, 6, 1, 0, 30)
        self.assertEqual(self.app._get_current_tou_slot_index(t7), 5)

    def test_boost_triggered_by_protection(self):
        """When inverter exports > 1000W and protection boost > 0A, raise target SOC to 90%."""
        with patch("datetime.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 1, 13, 35)  # Slot 2 (Time 3)

            self.app._protection_active = True
            self.app._protection_boost_amps = 25  # Protection asks for +25A

            data = InverterData(
                soc=50,
                battery_power=-1000,
                pv_power=8000,
                grid_power=-1500,  # Selling 1500W (> 1000W)
                voltages=[230.0, 230.0, 230.0],
                ups_loads=[200, 200, 200],
                grid_loads=[0, 0, 0],
                total_loads=[200, 200, 200],
                running_state=2,
                is_grid_connected=True,
                battery_voltage=52.0,
            )

            self.app._process_charge_prioritization(data)

            # Slot 2 is active, target SOC should be written as 90% (reg 168)
            self.app.inverter.set_time_of_use_target_soc.assert_called_once_with(2, 90)
            self.assertTrue(self.app._prioritization_boosted)
            self.assertEqual(self.app._last_tou_target_soc, 90)

    def test_boost_triggered_by_sunset_charging(self):
        """When inverter exports > 1000W and sunset boost > 0A, raise target SOC to 90%."""
        with patch("datetime.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 1, 13, 35)  # Slot 2 (Time 3)

            self.app._sunset_active = True
            self.app._sunset_boost_amps = 40  # Sunset asks for +40A

            data = InverterData(
                soc=40,
                battery_power=-800,
                pv_power=7000,
                grid_power=-1200,  # Selling 1200W (> 1000W)
                voltages=[230.0, 230.0, 230.0],
                ups_loads=[200, 200, 200],
                grid_loads=[0, 0, 0],
                total_loads=[200, 200, 200],
                running_state=2,
                is_grid_connected=True,
                battery_voltage=52.0,
            )

            self.app._process_charge_prioritization(data)

            self.app.inverter.set_time_of_use_target_soc.assert_called_once_with(2, 90)
            self.assertTrue(self.app._prioritization_boosted)

    def test_no_boost_when_export_below_trigger(self):
        """No boost when export is below trigger power (e.g. exporting 500W < 1000W)."""
        with patch("datetime.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 1, 13, 35)

            self.app._sunset_active = True
            self.app._sunset_boost_amps = 40

            data = InverterData(
                soc=40,
                battery_power=-2000,
                pv_power=3000,
                grid_power=-500,  # Only exporting 500W, under 1000W threshold
                voltages=[230.0, 230.0, 230.0],
                ups_loads=[200, 200, 200],
                grid_loads=[0, 0, 0],
                total_loads=[200, 200, 200],
                running_state=2,
                is_grid_connected=True,
                battery_voltage=52.0,
            )

            self.app._process_charge_prioritization(data)
            self.app.inverter.set_time_of_use_target_soc.assert_not_called()
            self.assertFalse(self.app._prioritization_boosted)

    def test_no_boost_when_no_heavy_charging_requested(self):
        """No boost when exporting > 1000W but neither protection nor sunset are boosting."""
        with patch("datetime.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 1, 13, 35)

            self.app._protection_active = False
            self.app._protection_boost_amps = 0
            self.app._sunset_active = False
            self.app._sunset_boost_amps = 0

            data = InverterData(
                soc=85,
                battery_power=0,
                pv_power=8000,
                grid_power=-5000,  # Exporting 5000W
                voltages=[230.0, 230.0, 230.0],
                ups_loads=[200, 200, 200],
                grid_loads=[0, 0, 0],
                total_loads=[200, 200, 200],
                running_state=2,
                is_grid_connected=True,
                battery_voltage=53.0,
            )

            self.app._process_charge_prioritization(data)
            self.app.inverter.set_time_of_use_target_soc.assert_not_called()
            self.assertFalse(self.app._prioritization_boosted)

    def test_fallback_on_sustained_grid_pull(self):
        """When boosted, pulling > 500W from grid for > 300s lowers target SOC back to 20%."""
        with patch("datetime.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 1, 13, 35)

            # System was already boosted in slot 2 (Time 3)
            self.app._prioritization_boosted = True
            self.app._last_tou_target_soc = 90
            self.app._last_prioritization_slot_idx = 2

            # Simulate solar loss: pulling 800W from grid (> 500W threshold)
            data = InverterData(
                soc=50,
                battery_power=0,
                pv_power=200,
                grid_power=800,  # Importing 800W
                voltages=[230.0, 230.0, 230.0],
                ups_loads=[500, 300, 200],
                grid_loads=[800, 0, 0],
                total_loads=[500, 300, 200],
                running_state=2,
                is_grid_connected=True,
                battery_voltage=52.0,
            )

            # Cycle 1: Grid pull starts (t = 1000)
            with patch("time.time", return_value=1000.0):
                self.app._process_charge_prioritization(data)
                self.app.inverter.set_time_of_use_target_soc.assert_not_called()
                self.assertTrue(self.app._prioritization_boosted)
                self.assertEqual(self.app._prioritization_grid_pull_since, 1000.0)

            # Cycle 2: 150 seconds later (under 300s duration) -> still boosted
            with patch("time.time", return_value=1150.0):
                self.app._process_charge_prioritization(data)
                self.app.inverter.set_time_of_use_target_soc.assert_not_called()
                self.assertTrue(self.app._prioritization_boosted)

            # Cycle 3: 301 seconds later (exceeds 300s) -> fallback triggered!
            with patch("time.time", return_value=1301.0):
                self.app._process_charge_prioritization(data)
                self.app.inverter.set_time_of_use_target_soc.assert_called_once_with(2, 20)
                self.assertFalse(self.app._prioritization_boosted)
                self.assertEqual(self.app._last_tou_target_soc, 20)
                self.assertIsNone(self.app._prioritization_grid_pull_since)

    def test_slot_transition_restores_previous_slot(self):
        """When slot runs out of time and transitions to next slot, previous slot is restored to normal target SOC."""
        # System was boosted in slot 2 (Time 3, 11:30 - 16:00)
        self.app._prioritization_boosted = True
        self.app._last_tou_target_soc = 90
        self.app._last_prioritization_slot_idx = 2

        # Time reaches 16:05 (Time 4, slot index 3)
        with patch("datetime.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 6, 1, 16, 5)

            # Inverter is not exporting in the new slot (e.g. 200W import)
            data = InverterData(
                soc=70,
                battery_power=0,
                pv_power=1000,
                grid_power=200,
                voltages=[230.0, 230.0, 230.0],
                ups_loads=[200, 200, 200],
                grid_loads=[200, 0, 0],
                total_loads=[200, 200, 200],
                running_state=2,
                is_grid_connected=True,
                battery_voltage=52.0,
            )

            self.app._process_charge_prioritization(data)

            # Previous slot 2 must be restored back to 20%
            self.app.inverter.set_time_of_use_target_soc.assert_called_once_with(2, 20)
            self.assertFalse(self.app._prioritization_boosted)
            self.assertEqual(self.app._last_prioritization_slot_idx, 3)


if __name__ == "__main__":
    unittest.main()
