"""
Unit tests for the inverter cooling fan hysteresis and temperature register parsing.
"""

import unittest
from unittest.mock import MagicMock

from src.deye_inverter import DeyeInverter
from src.inverter_fan_logic import FanSettings, FanResult, decide_fan_state


SETTINGS = FanSettings(enabled=True, on_temp=49.5, off_temp=45.0)


class TestFanHysteresis(unittest.TestCase):
    def test_turns_on_above_on_threshold(self):
        desired, result, _ = decide_fan_state(SETTINGS, 49.6, fan_is_on=False)
        self.assertTrue(desired)
        self.assertEqual(result, FanResult.TURN_ON)

    def test_stays_off_at_on_threshold(self):
        desired, result, _ = decide_fan_state(SETTINGS, 49.5, fan_is_on=False)
        self.assertFalse(desired)
        self.assertEqual(result, FanResult.IDLE)

    def test_keeps_running_inside_band(self):
        for temp in (49.5, 47.0, 45.0):
            desired, result, _ = decide_fan_state(SETTINGS, temp, fan_is_on=True)
            self.assertTrue(desired, temp)
            self.assertEqual(result, FanResult.RUNNING)

    def test_stays_off_inside_band(self):
        desired, result, _ = decide_fan_state(SETTINGS, 47.0, fan_is_on=False)
        self.assertFalse(desired)
        self.assertEqual(result, FanResult.IDLE)

    def test_turns_off_below_off_threshold(self):
        desired, result, _ = decide_fan_state(SETTINGS, 44.9, fan_is_on=True)
        self.assertFalse(desired)
        self.assertEqual(result, FanResult.TURN_OFF)

    def test_reasserts_on_when_switched_off_externally_while_hot(self):
        desired, result, _ = decide_fan_state(SETTINGS, 52.0, fan_is_on=False)
        self.assertTrue(desired)
        self.assertEqual(result, FanResult.TURN_ON)

    def test_full_cycle(self):
        fan_on = False
        states = []
        for temp in (44.0, 48.0, 50.0, 48.0, 45.5, 44.9, 47.0, 49.0):
            desired, _, _ = decide_fan_state(SETTINGS, temp, fan_on)
            fan_on = desired
            states.append(fan_on)
        self.assertEqual(states, [False, False, True, True, True, False, False, False])

    def test_no_command_when_disabled(self):
        desired, result, _ = decide_fan_state(FanSettings(False, 49.5, 45.0), 60.0, fan_is_on=False)
        self.assertIsNone(desired)
        self.assertEqual(result, FanResult.DISABLED)

    def test_no_command_without_temperature(self):
        desired, result, _ = decide_fan_state(SETTINGS, None, fan_is_on=True)
        self.assertIsNone(desired)
        self.assertEqual(result, FanResult.NO_DATA)

    def test_no_command_when_offline(self):
        desired, result, _ = decide_fan_state(SETTINGS, 60.0, fan_is_on=False, fan_connected=False)
        self.assertIsNone(desired)
        self.assertEqual(result, FanResult.OFFLINE)

    def test_invalid_thresholds(self):
        desired, result, _ = decide_fan_state(FanSettings(True, 45.0, 45.0), 60.0, fan_is_on=False)
        self.assertIsNone(desired)
        self.assertEqual(result, FanResult.INVALID_CONFIG)


class TestTemperatureRegisters(unittest.TestCase):
    def test_parse_temperature_offset(self):
        self.assertEqual(DeyeInverter._parse_temperature(1473), 47.3)
        self.assertEqual(DeyeInverter._parse_temperature(1000), 0.0)
        self.assertEqual(DeyeInverter._parse_temperature(950), -5.0)

    def test_parse_temperature_rejects_implausible(self):
        self.assertIsNone(DeyeInverter._parse_temperature(0))
        self.assertIsNone(DeyeInverter._parse_temperature(65535))

    def test_read_data_maps_registers_540_541(self):
        inverter = DeyeInverter()
        main_raw = [0] * 90
        main_raw[0] = 50
        main_raw[56] = main_raw[57] = main_raw[58] = 2300
        status_raw = [0] * 53
        status_raw[40] = 1401  # DC transformer
        status_raw[41] = 1495  # Heat sink (AC)
        modbus = MagicMock()
        modbus.read_holding_registers.side_effect = (
            lambda register_addr=None, quantity=None, *args: main_raw if register_addr == 588
            else status_raw if register_addr == 500 else [0]
        )
        inverter._modbus = modbus
        data = inverter.read_data()
        self.assertIsNotNone(data)
        self.assertEqual(data.ac_temperature, 49.5)
        self.assertEqual(data.dc_temperature, 40.1)


class TestProcessInverterFan(unittest.TestCase):
    def _make_app(self, fan_on: bool, enabled: bool = True):
        from main import DeyeApp
        app = MagicMock(spec=DeyeApp)
        app._process_inverter_fan = DeyeApp._process_inverter_fan.__get__(app, DeyeApp)
        app._last_fan_result = None
        app.after = lambda _delay, fn: fn()
        outlet = MagicMock(current_state=fan_on, is_connected=True)
        app.fan_tapo = MagicMock()
        app.fan_tapo.get_outlet.return_value = outlet
        app.fan_panel = MagicMock()
        app.fan_panel.get_settings.return_value = {"enabled": enabled, "on_temp": 49.5, "off_temp": 45.0}
        return app

    @staticmethod
    def _data(ac_temp):
        from src.deye_inverter import InverterData
        return InverterData(
            soc=50, battery_power=0, pv_power=0, grid_power=0, voltages=[230.0] * 3,
            ups_loads=[0] * 3, grid_loads=[0] * 3, total_loads=[0] * 3,
            running_state=2, is_grid_connected=True, ac_temperature=ac_temp,
        )

    def test_hot_turns_fan_on_and_logs_once(self):
        app = self._make_app(fan_on=False)
        app._process_inverter_fan(self._data(50.0))
        app._process_inverter_fan(self._data(50.2))
        self.assertEqual(app.fan_tapo.turn_on.call_count, 2)
        app.fan_tapo.turn_off.assert_not_called()
        self.assertEqual(app._log_error.call_count, 1)

    def test_cool_turns_fan_off(self):
        app = self._make_app(fan_on=True)
        app._process_inverter_fan(self._data(44.0))
        app.fan_tapo.turn_off.assert_called_once_with(1)
        app.fan_tapo.turn_on.assert_not_called()

    def test_band_and_disabled_send_nothing(self):
        for fan_on, enabled, temp in ((True, True, 47.0), (False, True, 47.0), (False, False, 60.0)):
            app = self._make_app(fan_on=fan_on, enabled=enabled)
            app._process_inverter_fan(self._data(temp))
            app.fan_tapo.turn_on.assert_not_called()
            app.fan_tapo.turn_off.assert_not_called()


if __name__ == "__main__":
    unittest.main()
