"""
Unit tests for EV charging logic: idle preset to minimum amps on low solar,
and the charger's lowering sequence.
"""

import time
import types
import unittest
from unittest.mock import patch

from src.deye_inverter import InverterData
from src.ev_logic import EVChargingLogic, EVSettings, EVResult
from src.tuya_charger import ChargerState, TuyaChargerManager


class FakeCharger:
    def __init__(self, **state):
        self.state = ChargerState(is_connected=True, **state)
        self.amps_sent = []
        self.on_off_sent = []

    def get_state(self):
        return self.state

    def set_amps(self, amps):
        self.amps_sent.append(amps)

    def turn_on(self):
        self.on_off_sent.append(True)

    def turn_off(self):
        self.on_off_sent.append(False)


def make_data(pv_power=1000, soc=60):
    return InverterData(
        soc=soc,
        battery_power=500,
        pv_power=pv_power,
        grid_power=0,
        voltages=[230.0, 230.0, 230.0],
        ups_loads=[200, 200, 200],
        grid_loads=[0, 0, 0],
        total_loads=[200, 200, 200],
        running_state=2,
        is_grid_connected=True,
        battery_voltage=52.0,
    )


def make_settings(**overrides):
    values = dict(
        enabled=True, min_amps_1p=25, min_amps_3p=8, max_amps=32,
        stop_soc=15, start_soc=40, solar_mode=True, change_interval=5,
    )
    values.update(overrides)
    return EVSettings(**values)


class TestIdlePreset(unittest.TestCase):
    def run_logic(self, settings, data=None, **charger_state):
        state = dict(is_on=True, is_charging=False, current_amps=25)
        state.update(charger_state)
        charger = FakeCharger(**state)
        logic = EVChargingLogic(charger, auto_default_phases=settings.auto_default_phases)
        result, detail = logic.process(data or make_data(), settings)
        return charger, logic, result, detail

    def start_session(self, charger, logic, settings, phase_currents, data=None, cycles=3):
        charger.state.is_charging = True
        charger.state.phase_currents = phase_currents
        for _ in range(cycles):
            result, detail = logic.process(data or make_data(), settings)
        return result, detail

    def test_charging_stop_presets_lowest_minimum(self):
        charger, _, result, detail = self.run_logic(make_settings())
        self.assertEqual(charger.amps_sent, [8])
        self.assertEqual(charger.on_off_sent, [])
        self.assertEqual(result, EVResult.IDLE)
        self.assertIn("Preset 8A", detail)

    def test_already_at_preset_does_not_write(self):
        charger, _, _, detail = self.run_logic(make_settings(), current_amps=8)
        self.assertEqual(charger.amps_sent, [])
        self.assertIn("Ready 8A", detail)

    def test_presets_regardless_of_solar(self):
        charger, *_ = self.run_logic(make_settings(), make_data(pv_power=15000))
        self.assertEqual(charger.amps_sent, [8])

    def test_presets_with_boost(self):
        charger, *_ = self.run_logic(make_settings(boost=True))
        self.assertEqual(charger.amps_sent, [8])

    def test_preset_bypasses_cooldown(self):
        settings = make_settings()
        charger = FakeCharger(is_on=True, is_charging=True, current_amps=25,
                              phase_currents=(25.0, 0.0, 0.0))
        logic = EVChargingLogic(charger)
        logic._state.last_decision_time = time.time()  # a speed change just happened
        logic.process(make_data(), settings)
        charger.state.is_charging = False  # car unplugged
        result, _ = logic.process(make_data(), settings)
        self.assertEqual(charger.amps_sent, [8])
        self.assertEqual(result, EVResult.IDLE)

    def test_rejected_preset_is_not_resent_every_cycle(self):
        charger, logic, *_ = self.run_logic(make_settings())
        for _ in range(5):  # charger keeps reporting 25A
            logic.process(make_data(), make_settings())
        self.assertEqual(charger.amps_sent, [8])

    def test_forced_single_phase_uses_1p_minimum(self):
        charger, *_ = self.run_logic(make_settings(phases="1"), current_amps=32)
        self.assertEqual(charger.amps_sent, [25])

    def test_forced_three_phase_uses_3p_minimum(self):
        charger, *_ = self.run_logic(make_settings(phases="3"))
        self.assertEqual(charger.amps_sent, [8])

    def test_charging_session_is_not_preset(self):
        charger, *_ = self.run_logic(make_settings(), is_charging=True,
                                     phase_currents=(25.0, 0.0, 0.0))
        self.assertNotIn(8, charger.amps_sent)

    def test_charger_off_is_not_touched(self):
        charger, *_ = self.run_logic(make_settings(), make_data(soc=10), is_on=False)
        self.assertEqual((charger.amps_sent, charger.on_off_sent), ([], []))

    def test_single_phase_ev_raised_to_its_minimum_after_preset(self):
        settings = make_settings()
        charger, logic, *_ = self.run_logic(settings)
        charger.state.current_amps = 8
        result, _ = self.start_session(charger, logic, settings, (8.0, 0.0, 0.0))
        self.assertEqual(logic.active_phases, 1)
        self.assertEqual(charger.amps_sent, [8, 25])
        self.assertEqual(result, EVResult.SOLAR_CHARGING)

    def test_three_phase_ev_stays_at_preset_on_low_solar(self):
        settings = make_settings()
        charger, logic, *_ = self.run_logic(settings)
        charger.state.current_amps = 8
        self.start_session(charger, logic, settings, (8.0, 8.0, 8.0))
        self.assertEqual(logic.active_phases, 3)
        self.assertEqual(charger.amps_sent, [8])

    def test_new_session_is_raised_without_waiting_for_cooldown(self):
        settings = make_settings()
        charger, logic, *_ = self.run_logic(settings)
        charger.state.current_amps = 8
        logic._state.last_decision_time = time.time()  # recent decision before the swap
        sunny = make_data(pv_power=15000)
        sunny.grid_power = -8000  # exporting 8 kW
        self.start_session(charger, logic, settings, (8.0, 8.0, 8.0), data=sunny, cycles=1)
        self.assertEqual(len(charger.amps_sent), 2)
        self.assertGreater(charger.amps_sent[-1], 8)

    def test_session_after_quick_swap_gets_fresh_preset(self):
        settings = make_settings()
        charger, logic, *_ = self.run_logic(settings)       # preset 8A
        charger.state.current_amps = 8
        self.start_session(charger, logic, settings, (8.0, 0.0, 0.0))  # 1P car → 25A
        charger.state.current_amps = 25
        charger.state.is_charging = False                   # stops again shortly after
        logic.process(make_data(), settings)
        self.assertEqual(charger.amps_sent, [8, 25, 8])


class TestEVLoadDropHint(unittest.TestCase):
    def setUp(self):
        from collections import deque
        from unittest.mock import MagicMock
        from main import DeyeApp
        self.app = MagicMock(spec=DeyeApp)
        self.app._ev_load_window = deque()
        self.app.ev_charger = MagicMock()
        self.check = DeyeApp._check_ev_load_drop.__get__(self.app, DeyeApp)
        self.cfg = patch("main.deye_config", types.SimpleNamespace(high_load_kw=4.0))
        self.cfg.start()
        self.addCleanup(self.cfg.stop)

    def feed(self, loads, charging=True, ev_power_w=5750, start=1000.0, step=1.2):
        fired = []
        for i, w in enumerate(loads):
            fired.append(self.check(w, charging, ev_power_w, start + i * step))
        return fired

    def test_drop_while_charging_triggers_once(self):
        fired = self.feed([6500, 6500, 4000, 800, 750, 700])
        self.assertEqual(fired.count(True), 1)
        self.app.ev_charger.hint_load_drop.assert_called_once()

    def test_small_fluctuation_does_not_trigger(self):
        self.feed([6500, 5000, 6200, 4500, 6400])
        self.app.ev_charger.hint_load_drop.assert_not_called()

    def test_no_trigger_when_not_charging(self):
        self.feed([9000, 500], charging=False)
        self.app.ev_charger.hint_load_drop.assert_not_called()

    def test_threshold_follows_ev_power_when_below_high_load(self):
        with patch("main.deye_config", types.SimpleNamespace(high_load_kw=6.0)):
            self.feed([6000, 600], ev_power_w=5500)  # 3P at 8A, 5.4 kW drop < 6 kW
        self.app.ev_charger.hint_load_drop.assert_called_once()

    def test_drop_older_than_window_is_ignored(self):
        self.feed([6500])
        self.feed([600], start=1040.0)  # 40s later
        self.app.ev_charger.hint_load_drop.assert_not_called()


class TestChargerLoweringSequence(unittest.TestCase):
    def setUp(self):
        self.calls = []
        config = types.SimpleNamespace(
            cloud_api_key="", cloud_api_secret="", dp_switch=123, dp_amps=6,
            dp_amps_scale=1, max_amps=32, min_amps=6, min_amps_1p=6, min_amps_3p=6,
        )
        with patch.object(TuyaChargerManager, "_run_loop", lambda self: None):
            self.manager = TuyaChargerManager(config)
        calls = self.calls
        self.manager._device = types.SimpleNamespace(
            set_socketPersistent=lambda p: None,
            set_value=lambda dp, value: calls.append((dp, value)),
        )
        self.manager.state.is_on = True
        self.manager.state.current_amps = 25

    def apply(self, amps):
        self.manager.set_amps(amps)
        with patch("src.tuya_charger.time.sleep"):
            self.manager._apply_pending()

    def test_lowering_without_car_is_single_write(self):
        self.manager.state.is_charging = False
        self.apply(8)
        self.assertEqual(self.calls, [("6", 8)])

    def test_lowering_while_charging_uses_off_set_on(self):
        self.manager.state.is_charging = True
        self.apply(8)
        self.assertEqual(self.calls, [("123", False), ("6", 8), ("123", True)])

    def test_raising_is_single_write(self):
        self.manager.state.is_charging = True
        self.apply(32)
        self.assertEqual(self.calls, [("6", 32)])


if __name__ == "__main__":
    unittest.main()
