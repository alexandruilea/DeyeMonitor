"""
Unit tests for solar export detection and battery boost / sunset charging protection.
"""

import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from src.deye_inverter import InverterData
from main import DeyeApp


class TestExportBreakdown(unittest.TestCase):
    def setUp(self):
        # Create a mock app instance without running tkinter UI init
        self.app = MagicMock(spec=DeyeApp)
        self.app._get_export_breakdown = DeyeApp._get_export_breakdown.__get__(self.app, DeyeApp)

    def test_night_battery_export(self):
        """At night when exporting from battery, all export is battery export, no solar export."""
        data = InverterData(
            soc=50,
            battery_power=3200,  # discharging 3200W
            pv_power=0,  # no PV
            grid_power=-3000,  # exporting 3000W
            voltages=[230.0, 230.0, 230.0],
            ups_loads=[100, 50, 50],
            grid_loads=[0, 0, 0],
            total_loads=[100, 50, 50],  # 200W total house load
            running_state=2,
            is_grid_connected=True,
            battery_voltage=52.0,
        )
        solar_w, batt_w, has_solar, is_mostly_batt = self.app._get_export_breakdown(data)
        self.assertEqual(solar_w, 0)
        self.assertEqual(batt_w, 3000)
        self.assertFalse(has_solar)
        self.assertTrue(is_mostly_batt)

    def test_daytime_pure_solar_export(self):
        """During day with high PV and battery charging, all export is solar export."""
        data = InverterData(
            soc=60,
            battery_power=-2000,  # charging 2000W
            pv_power=8000,  # 8kW solar
            grid_power=-5000,  # exporting 5000W
            voltages=[230.0, 230.0, 230.0],
            ups_loads=[500, 300, 200],
            grid_loads=[0, 0, 0],
            total_loads=[500, 300, 200],  # 1000W total load
            running_state=2,
            is_grid_connected=True,
            battery_voltage=53.0,
        )
        solar_w, batt_w, has_solar, is_mostly_batt = self.app._get_export_breakdown(data)
        self.assertEqual(solar_w, 5000)
        self.assertEqual(batt_w, 0)
        self.assertTrue(has_solar)
        self.assertFalse(is_mostly_batt)

    def test_daytime_solar_export_with_minor_battery_discharge(self):
        """Solar covers loads and most export, minor battery discharge."""
        data = InverterData(
            soc=80,
            battery_power=500,  # minor discharge 500W
            pv_power=6000,  # 6kW solar
            grid_power=-5000,  # exporting 5000W
            voltages=[230.0, 230.0, 230.0],
            ups_loads=[500, 300, 200],
            grid_loads=[0, 0, 0],
            total_loads=[500, 300, 200],  # 1000W load -> 5000W solar surplus
            running_state=2,
            is_grid_connected=True,
            battery_voltage=53.0,
        )
        solar_w, batt_w, has_solar, is_mostly_batt = self.app._get_export_breakdown(data)
        self.assertGreater(solar_w, batt_w)
        self.assertTrue(has_solar)
        self.assertFalse(is_mostly_batt)

    def test_daytime_battery_selling_low_pv(self):
        """Scheduled battery export with minimal PV: export is mostly battery."""
        data = InverterData(
            soc=90,
            battery_power=5000,  # discharging 5000W
            pv_power=400,  # only 400W solar
            grid_power=-4500,  # exporting 4500W
            voltages=[230.0, 230.0, 230.0],
            ups_loads=[400, 300, 200],
            grid_loads=[0, 0, 0],
            total_loads=[400, 300, 200],  # 900W load > 400W PV
            running_state=2,
            is_grid_connected=True,
            battery_voltage=52.5,
        )
        solar_w, batt_w, has_solar, is_mostly_batt = self.app._get_export_breakdown(data)
        self.assertEqual(solar_w, 0)
        self.assertEqual(batt_w, 4500)
        self.assertFalse(has_solar)
        self.assertTrue(is_mostly_batt)

    def test_no_export_importing(self):
        """When grid power is positive (importing), export breakdown returns zero."""
        data = InverterData(
            soc=40,
            battery_power=500,
            pv_power=0,
            grid_power=1500,  # importing 1500W
            voltages=[230.0, 230.0, 230.0],
            ups_loads=[1000, 500, 500],
            grid_loads=[0, 0, 0],
            total_loads=[1000, 500, 500],
            running_state=2,
            is_grid_connected=True,
            battery_voltage=51.0,
        )
        solar_w, batt_w, has_solar, is_mostly_batt = self.app._get_export_breakdown(data)
        self.assertEqual(solar_w, 0)
        self.assertEqual(batt_w, 0)
        self.assertFalse(has_solar)
        self.assertFalse(is_mostly_batt)


class TestBatteryBoostProtection(unittest.TestCase):
    def setUp(self):
        self.app = MagicMock(spec=DeyeApp)
        self.app._protection_boost_amps = 0
        self.app._protection_active = False
        self.app._last_protection_adjustment = 0
        self.app._current_max_charge = 10
        self.app._sunset_active = False
        self.app._sunset_boost_amps = 0
        self.app._offgrid_active = False
        self.app.inverter = MagicMock()
        self.app.protection_panel = MagicMock()
        self.app.protection_panel.is_enabled.return_value = True
        self.app.protection_panel.get_settings.return_value = {
            "max_sell_power": 3000,
            "power_threshold_pct": 80,  # 2400W warning
            "recovery_threshold_pct": 60,  # 1800W recovery
            "voltage_warning": 253.0,
            "voltage_recovery": 248.0,
            "charge_step": 10,
            "adjustment_interval": 10,
        }
        self.app.after = MagicMock(side_effect=lambda delay, fn, *args: fn(*args) if callable(fn) else None)
        self.app._get_export_breakdown = DeyeApp._get_export_breakdown.__get__(self.app, DeyeApp)
        self.app._process_overpower_protection = DeyeApp._process_overpower_protection.__get__(self.app, DeyeApp)

    def test_protection_does_not_boost_when_exporting_from_battery_at_night(self):
        """At night when exporting 3000W from battery (> 2400W warning), protection must NOT write to inverter."""
        data = InverterData(
            soc=70,
            battery_power=3200,
            pv_power=0,
            grid_power=-3000,  # 3000W export exceeds 2400W threshold
            voltages=[230.0, 230.0, 230.0],
            ups_loads=[100, 50, 50],
            grid_loads=[0, 0, 0],
            total_loads=[100, 50, 50],
            running_state=2,
            is_grid_connected=True,
            battery_voltage=52.0,
            bms_charge_current_limit=180,
        )
        self.app._process_overpower_protection(data)
        
        # Verify NO write to inverter occurred
        self.app.inverter.set_max_charge_current.assert_not_called()
        self.assertEqual(self.app._protection_boost_amps, 0)
        self.assertFalse(self.app._protection_active)
        self.app.protection_panel.update_protection_state.assert_called_with(False, 0)

    def test_protection_clears_existing_boost_silently_on_battery_export(self):
        """If protection had boost amps from daytime, entering battery export clears it silently without writing."""
        self.app._protection_boost_amps = 30
        self.app._protection_active = True
        
        data = InverterData(
            soc=70,
            battery_power=3200,
            pv_power=0,
            grid_power=-3000,
            voltages=[230.0, 230.0, 230.0],
            ups_loads=[100, 50, 50],
            grid_loads=[0, 0, 0],
            total_loads=[100, 50, 50],
            running_state=2,
            is_grid_connected=True,
            battery_voltage=52.0,
            bms_charge_current_limit=180,
        )
        self.app._process_overpower_protection(data)
        
        self.app.inverter.set_max_charge_current.assert_not_called()
        self.assertEqual(self.app._protection_boost_amps, 0)
        self.assertFalse(self.app._protection_active)


class TestSunsetChargingModule(unittest.TestCase):
    def setUp(self):
        self.app = MagicMock(spec=DeyeApp)
        self.app._sunset_boost_amps = 0
        self.app._sunset_active = False
        self.app._last_sunset_adjustment = 0
        self.app._pv_samples = []
        self.app._weather_enabled = False
        self.app.inverter = MagicMock()
        self.app.sunset_panel = MagicMock()
        self.app.sunset_panel.is_enabled.return_value = True
        self.app.sunset_panel.get_settings.return_value = {
            "latitude": 47.29,
            "longitude": 22.91,
            "target_soc": 100,
            "battery_capacity_ah": 600,
            "min_charge_amps": 20,
            "buffer_minutes": 60,
            "peak_solar_hour": 0.0,
            "peak_expected_kw": 0.0,
            "cloud_threshold_pct": 60,
            "cloud_max_boost": 3.0,
        }
        self.app.sunset_panel.is_selling_first_enabled.return_value = False
        self.app.after = MagicMock(side_effect=lambda delay, fn, *args: fn(*args) if callable(fn) else None)
        self.app._get_export_breakdown = DeyeApp._get_export_breakdown.__get__(self.app, DeyeApp)
        self.app._process_sunset_charging = DeyeApp._process_sunset_charging.__get__(self.app, DeyeApp)

    def test_sunset_does_not_run_when_exporting_from_battery(self):
        """When exporting mostly from battery, sunset charging suspends and does not write to inverter."""
        self.app._sunset_boost_amps = 20
        self.app._sunset_active = True
        
        data = InverterData(
            soc=50,
            battery_power=3500,
            pv_power=200,
            grid_power=-3000,
            voltages=[230.0, 230.0, 230.0],
            ups_loads=[200, 100, 100],
            grid_loads=[0, 0, 0],
            total_loads=[200, 100, 100],
            running_state=2,
            is_grid_connected=True,
            battery_voltage=52.0,
        )
        self.app._process_sunset_charging(data)
        
        self.app.inverter.set_max_charge_current.assert_not_called()
        self.assertEqual(self.app._sunset_boost_amps, 0)
        self.assertFalse(self.app._sunset_active)

    def test_sunset_does_not_run_without_pv(self):
        """When pv_power <= 50W (night), sunset charging suspends and does not write to inverter."""
        self.app._sunset_boost_amps = 10
        self.app._sunset_active = True
        
        data = InverterData(
            soc=40,
            battery_power=300,
            pv_power=0,
            grid_power=0,
            voltages=[230.0, 230.0, 230.0],
            ups_loads=[100, 100, 100],
            grid_loads=[0, 0, 0],
            total_loads=[100, 100, 100],
            running_state=2,
            is_grid_connected=True,
            battery_voltage=51.5,
        )
        self.app._process_sunset_charging(data)
        
        self.app.inverter.set_max_charge_current.assert_not_called()
        self.assertEqual(self.app._sunset_boost_amps, 0)
        self.assertFalse(self.app._sunset_active)


class TestEVSEOfflineStatus(unittest.TestCase):
    def setUp(self):
        self.app = MagicMock(spec=DeyeApp)
        self.app._evse_offline = False
        self.app.lbl_solar_sell = MagicMock()
        self.app.lbl_evse_offline = MagicMock()
        self.app.after = MagicMock(side_effect=lambda delay, fn, *args: fn(*args) if callable(fn) else None)
        self.app._update_sell_label = DeyeApp._update_sell_label.__get__(self.app, DeyeApp)
        self.app._update_evse_offline_display = DeyeApp._update_evse_offline_display.__get__(self.app, DeyeApp)
        self.app._on_ev_change = DeyeApp._on_ev_change.__get__(self.app, DeyeApp)

    def test_evse_offline_label_updates_display(self):
        """When EVSE is offline, label displays ' - EVSE: Offline'."""
        self.app._evse_offline = True
        self.app._update_evse_offline_display()
        self.app.lbl_evse_offline.configure.assert_called_with(text=" - EVSE: Offline")

    def test_evse_online_label_clears_display(self):
        """When EVSE is online, label displays empty string."""
        self.app._evse_offline = False
        self.app._update_evse_offline_display()
        self.app.lbl_evse_offline.configure.assert_called_with(text="")

    def test_sell_label_update_maintains_evse_offline_status(self):
        """Updating sell label also refreshes EVSE offline label."""
        self.app._evse_offline = True
        self.app._update_sell_label(sell_on=True)
        self.app.lbl_solar_sell.configure.assert_called_with(text="Sell: ON", text_color="#2ECC71")
        self.app.lbl_evse_offline.configure.assert_called_with(text=" - EVSE: Offline")

    def test_on_ev_change_clears_offline_when_disabled(self):
        """Disabling EV panel clears offline indicator."""
        self.app._evse_offline = True
        self.app.ev_panel = MagicMock()
        self.app.ev_panel.is_enabled.return_value = False
        self.app._on_ev_change()
        self.assertFalse(self.app._evse_offline)
        self.app.lbl_evse_offline.configure.assert_called_with(text="")


if __name__ == "__main__":
    unittest.main()
