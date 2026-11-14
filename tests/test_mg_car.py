"""
Unit tests for the MG car manager's command flow, with a fake SAIC API (no network).
"""

import asyncio
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from saic_ismart_client_ng.api.vehicle.schema import BasicVehicleStatus, VehicleModelConfiguration, VinInfo
from saic_ismart_client_ng.exceptions import SaicApiException, SaicLogoutException

import src.mg_car as mg_car
from src.config import MGCarConfig
from src.mg_car import MGCarManager
from src.mg_logic import MGAction, MGRequest, MGSchedule, SeatSupport

# The refusal an S9 sent after several remote climate starts in a row
TOO_FREQUENT = ("Too frequent operations. Please use the physical key to restart the vehicle, lock the car "
                "and turn off the engine, and then try again.(71)")


class FakeApi:
    """Records calls and keeps a car state that the commands change."""

    def __init__(self, heated_seat="2", locked=False):
        self.calls = []
        self.logged_in = False
        self.car = {"lockStatus": 1 if locked else 0, "remoteClimateStatus": 0, "rmtHtdRrWndSt": 0,
                    "frontLeftSeatHeatLevel": 0, "frontRightSeatHeatLevel": 0, "extendedData1": 37,
                    "interiorTemperature": 4}
        self.heated_seat = heated_seat
        self.fail = {}  # call name -> exception raised once

    def _call(self, name, *args):
        self.calls.append((name, *args))
        if name in self.fail:
            raise self.fail.pop(name)

    def _status(self):
        return SimpleNamespace(basicVehicleStatus=BasicVehicleStatus(**self.car))

    @property
    def is_logged_in(self):
        return self.logged_in

    token_expiration = datetime(2027, 4, 30)

    def logout(self):
        self.logged_in = False

    async def login(self):
        self._call("login")
        self.logged_in = True

    async def vehicle_list(self):
        self._call("vehicle_list")
        config = [VehicleModelConfiguration(itemCode="HeatedSeat", itemValue=self.heated_seat)]
        return SimpleNamespace(vinList=[VinInfo(vin="LSJTEST0000003926", modelName="MG S9 PHEV", modelYear="2025",
                                                series="IS31P S", vehicleModelConfiguration=config)])

    async def get_vehicle_status(self, vin):
        self._call("status")
        return self._status()

    async def get_vehicle_status_cached(self, vin):
        self._call("cached")
        return SimpleNamespace(basicVehicleStatus=BasicVehicleStatus(extendedData1=37), statusTime=None)

    async def lock_vehicle(self, vin):
        self._call("lock")
        self.car["lockStatus"] = 1
        return self._status()

    async def start_ac(self, vin, *, temperature_idx):
        self._call("start_ac", temperature_idx)
        self.car["remoteClimateStatus"] = 2
        return self._status()

    async def start_front_defrost(self, vin):
        self._call("front_defrost")
        self.car["remoteClimateStatus"] = 5
        return self._status()

    async def stop_ac(self, vin):
        self._call("stop_ac")
        self.car["remoteClimateStatus"] = 0
        return self._status()

    async def control_rear_window_heat(self, vin, *, enable):
        self._call("rear_window", enable)
        self.car["rmtHtdRrWndSt"] = 1 if enable else 0
        return self._status()

    async def control_heated_seats(self, vin, *, left_side_level, right_side_level):
        self._call("seats", left_side_level, right_side_level)
        self.car["frontLeftSeatHeatLevel"] = left_side_level
        self.car["frontRightSeatHeatLevel"] = right_side_level
        return self._status()


class OfflineManager(MGCarManager):
    def _run_loop(self) -> None:
        pass  # No background loop: tests drive the coroutines directly


def make_manager(api: FakeApi, achieve: bool = False) -> MGCarManager:
    manager = OfflineManager(MGCarConfig(car_id=1, name="S9", username="u", password="p",
                                         achieve_temperature=achieve))
    manager._api = api
    return manager


def names(api: FakeApi):
    return [c[0] for c in api.calls]


class TestMGCarManager(unittest.TestCase):
    def setUp(self):
        self._delays = (mg_car.COMMAND_GAP_SECONDS, mg_car.READBACK_DELAY_SECONDS)
        mg_car.COMMAND_GAP_SECONDS = mg_car.READBACK_DELAY_SECONDS = 0

    def tearDown(self):
        mg_car.COMMAND_GAP_SECONDS, mg_car.READBACK_DELAY_SECONDS = self._delays

    def run_action(self, manager, request):
        manager._try_mark_busy()
        return asyncio.run(manager._run_action(request, "Test"))

    def test_locks_then_climate_then_seat(self):
        api = FakeApi(locked=False)
        manager = make_manager(api)
        self.assertTrue(self.run_action(manager, MGRequest(MGAction.CLIMATE_DRIVER_SEAT, 18)))
        self.assertEqual(api.calls, [("login",), ("vehicle_list",), ("status",), ("lock",),
                                     ("start_ac", 4), ("seats", 1, 0), ("status",)])
        state = manager.get_state()
        self.assertTrue(state.result_ok)
        self.assertEqual(state.busy, "")
        self.assertEqual((state.climate, state.locked, state.seat_left, state.battery_pct), (2, True, 1, 37))

    def test_skips_lock_when_locked(self):
        api = FakeApi(locked=True)
        self.assertTrue(self.run_action(make_manager(api), MGRequest(MGAction.CLIMATE, 18)))
        self.assertNotIn("lock", names(api))

    def test_schedule_extras(self):
        api = FakeApi(locked=True)
        request = MGRequest(MGAction.CLIMATE_BOTH_SEATS, 18, windshield=True, rear_defrost=True)
        self.assertTrue(self.run_action(make_manager(api), request))
        self.assertEqual(names(api)[3:6], ["front_defrost", "rear_window", "seats"])

    def test_all_off(self):
        api = FakeApi(locked=True)
        api.car.update(remoteClimateStatus=2, frontLeftSeatHeatLevel=1)
        self.assertTrue(self.run_action(make_manager(api), MGRequest(MGAction.ALL_OFF)))
        self.assertEqual(names(api)[3:5], ["stop_ac", "seats"])

    def test_logs_in_again_when_phone_took_the_session(self):
        api = FakeApi(locked=True)
        manager = make_manager(api)
        api.fail["status"] = SaicLogoutException("logged out", 401)
        self.assertTrue(self.run_action(manager, MGRequest(MGAction.CLIMATE, 18)))
        self.assertEqual(names(api).count("login"), 2)

    def test_failed_seat_step_reported_but_climate_kept(self):
        api = FakeApi(locked=True)
        manager = make_manager(api)
        api.fail["seats"] = SaicApiException("network status is normal.(253)", return_code=8)
        self.assertFalse(self.run_action(manager, MGRequest(MGAction.CLIMATE_DRIVER_SEAT, 18)))
        state = manager.get_state()
        self.assertEqual(state.climate, 2)
        self.assertIn("setting seat heating failed", state.result)

    def test_car_without_seat_heating(self):
        api = FakeApi(heated_seat="0", locked=True)
        manager = make_manager(api)
        self.assertTrue(self.run_action(manager, MGRequest(MGAction.CLIMATE_BOTH_SEATS, 18)))
        self.assertNotIn("seats", names(api))
        self.assertEqual(manager.get_state().seat_support, SeatSupport.NONE)

    def test_background_refresh_waits_after_logout(self):
        api = FakeApi()
        manager = make_manager(api)
        api.logged_in = True
        manager._vin = "LSJTEST0000003926"
        api.fail["cached"] = SaicLogoutException("logged out", 401)
        asyncio.run(manager._refresh_status())
        self.assertIsNotNone(manager.get_state().backoff_until)

        api.calls.clear()
        asyncio.run(manager._refresh_status())
        self.assertEqual(api.calls, [])  # Inside the backoff: no login

        manager._kicked_at = datetime.now() - mg_car.RELOGIN_BACKOFF - timedelta(seconds=1)
        asyncio.run(manager._refresh_status())
        self.assertEqual(names(api), ["login", "vehicle_list", "cached"])

    def test_buttons_ignore_backoff(self):
        api = FakeApi(locked=True)
        manager = make_manager(api)
        manager._kicked_at = datetime.now()
        self.assertTrue(self.run_action(manager, MGRequest(MGAction.CLIMATE, 18)))
        self.assertEqual(names(api)[0], "login")

    def test_rejected_login_pauses_background_logins(self):
        api = FakeApi()
        manager = make_manager(api)
        api.fail["login"] = SaicApiException("Your authorization has been revoked", return_code=1100003)
        asyncio.run(manager._refresh_status())
        api.calls.clear()
        asyncio.run(manager._refresh_status())
        self.assertEqual(api.calls, [])

    def test_busy_rejects_second_request(self):
        manager = make_manager(FakeApi())
        self.assertTrue(manager._try_mark_busy())
        self.assertFalse(manager.request(MGRequest(MGAction.CLIMATE, 18)))

    def test_car_block_explained(self):
        api = FakeApi(locked=True)
        manager = make_manager(api)
        api.fail["start_ac"] = SaicApiException(TOO_FREQUENT, return_code=8)
        self.assertFalse(self.run_action(manager, MGRequest(MGAction.CLIMATE, 18)))
        self.assertIn("switch it on once with the key", manager.get_state().result)

    def test_schedule_stops_retrying_after_car_block(self):
        api = FakeApi(locked=True)
        manager = make_manager(api)
        now = datetime.now()
        manager._schedule = MGSchedule(enabled=True, hour=now.hour, minute=now.minute, days=frozenset(range(7)))
        api.fail["start_ac"] = SaicApiException(TOO_FREQUENT, return_code=8)
        request = manager._due_schedule_request(now)
        self.assertIsNotNone(request)
        manager._try_mark_busy()
        asyncio.run(manager._run_schedule(request, now))
        self.assertIsNone(manager._due_schedule_request(now + timedelta(minutes=4)))

    def test_schedule_retries_other_failures(self):
        api = FakeApi(locked=True)
        manager = make_manager(api)
        now = datetime.now()
        manager._schedule = MGSchedule(enabled=True, hour=now.hour, minute=now.minute, days=frozenset(range(7)))
        api.fail["start_ac"] = SaicApiException("car did not answer", return_code=500)
        manager._try_mark_busy()
        asyncio.run(manager._run_schedule(manager._due_schedule_request(now), now))
        self.assertIsNotNone(manager._due_schedule_request(now + timedelta(minutes=4)))

    def test_schedule_logged_at_startup_and_on_change(self):
        # A day without a scheduled run must be explainable from the log
        log = []
        schedule = MGSchedule(enabled=True, hour=8, minute=45, action=MGAction.CLIMATE_BOTH_SEATS)
        manager = OfflineManager(MGCarConfig(car_id=1, name="S9", username="u", password="p", schedule=schedule),
                                 error_callback=log.append)
        self.assertEqual(log, ["[S9] Schedule: Mon,Tue,Wed,Thu,Fri at 08:45, Climate + Both Seats at 22°C"])

        manager.set_schedule(schedule, 22)  # Unchanged (every field edit calls this): no log
        self.assertEqual(len(log), 1)

        manager.set_schedule(MGSchedule(enabled=False, hour=8, minute=45), 22)
        manager.set_schedule(None, 22)  # Invalid time typed in the panel
        self.assertEqual(log[1:], ["[S9] Schedule changed: off",
                                   "[S9] Schedule changed: off (invalid time in the panel)"])

    def test_failure_names_the_hidden_cause(self):
        api = FakeApi(locked=True)
        manager = make_manager(api)
        error = SaicApiException("API call GET /vehicle/status failed unexpectedly", return_code=500)
        error.__cause__ = TimeoutError("read timed out")
        api.fail["status"] = error
        self.assertFalse(self.run_action(manager, MGRequest(MGAction.CLIMATE, 18)))
        self.assertIn("[TimeoutError: read timed out]", manager.get_state().result)

    def test_login_uses_longer_read_timeout(self):
        configs = []
        original = mg_car.SaicApi

        def capture(configuration):
            configs.append(configuration)
            return FakeApi()
        mg_car.SaicApi = capture
        try:
            manager = OfflineManager(MGCarConfig(car_id=1, name="S9", username="u@example.com", password="p"))
            asyncio.run(manager._ensure_session(automatic=False))
        finally:
            mg_car.SaicApi = original
        self.assertEqual(configs[0].read_timeout, mg_car.SAIC_READ_TIMEOUT_SECONDS)
        self.assertGreater(mg_car.SAIC_READ_TIMEOUT_SECONDS, 5)


class TestAchieveTemperature(unittest.TestCase):
    def setUp(self):
        self._delays = (mg_car.COMMAND_GAP_SECONDS, mg_car.READBACK_DELAY_SECONDS)
        mg_car.COMMAND_GAP_SECONDS = mg_car.READBACK_DELAY_SECONDS = 0

    def tearDown(self):
        mg_car.COMMAND_GAP_SECONDS, mg_car.READBACK_DELAY_SECONDS = self._delays

    def started(self, achieve=True, action=MGAction.CLIMATE_DRIVER_SEAT):
        """A manager whose button press started the climate at 22°C in a 4°C cabin."""
        api = FakeApi(locked=True)
        manager = make_manager(api, achieve=achieve)
        manager._try_mark_busy()
        self.assertTrue(asyncio.run(manager._run_action(MGRequest(action, 22), "Test")))
        api.calls.clear()
        return api, manager

    @staticmethod
    def climate_stopped(api, cabin):
        api.car.update(remoteClimateStatus=0, interiorTemperature=cabin)

    def check(self, manager):
        manager._try_mark_busy()
        asyncio.run(manager._achieve_check())

    def test_press_arms_a_check_after_ten_minutes(self):
        _, manager = self.started()
        job = manager.get_state().achieve
        self.assertEqual((job.target, job.heating, job.restarts), (22, True, 0))
        self.assertAlmostEqual((job.next_check - datetime.now()).total_seconds(),
                               mg_car.ACHIEVE_CHECK.total_seconds(), delta=5)

    def test_switch_off_arms_nothing(self):
        _, manager = self.started(achieve=False)
        self.assertIsNone(manager.get_state().achieve)

    def test_restarts_when_cabin_still_cold(self):
        api, manager = self.started()
        self.climate_stopped(api, 12)
        api.car.update(frontLeftSeatHeatLevel=0)
        self.check(manager)
        self.assertEqual(api.calls, [("status",), ("start_ac", 8), ("seats", 1, 0), ("status",)])
        state = manager.get_state()
        self.assertEqual(state.achieve.restarts, 1)
        self.assertGreater(state.achieve.next_check, datetime.now() + mg_car.ACHIEVE_CHECK - timedelta(seconds=5))
        self.assertTrue(state.result_ok)
        self.assertEqual(state.busy, "")

    def test_waits_while_climate_still_running(self):
        api, manager = self.started()
        api.car.update(interiorTemperature=12)
        self.check(manager)
        self.assertEqual(names(api), ["status"])
        job = manager.get_state().achieve
        self.assertLess(job.next_check, datetime.now() + timedelta(minutes=2))

    def test_uses_reading_from_while_the_climate_ran(self):
        # The S9 stopped reporting the cabin once the climate was off (2026-11-01)
        api, manager = self.started()
        api.car.update(interiorTemperature=15)
        self.check(manager)  # Climate still on: WAIT, keeps 15°C
        api.calls.clear()
        self.climate_stopped(api, None)
        self.check(manager)
        self.assertEqual(names(api), ["status", "start_ac", "status"])  # Seats still on in the fake
        state = manager.get_state()
        self.assertEqual(state.achieve.restarts, 1)
        self.assertIn("cabin 15°C at", state.result)

    def test_no_reading_at_all_stops(self):
        api, manager = self.started()
        manager._achieve.cabin_temp = None  # As if the car never sent one
        self.climate_stopped(api, 87)
        self.check(manager)
        state = manager.get_state()
        self.assertIsNone(state.achieve)
        self.assertIn("sent 87", state.result)

    def test_stops_when_reached(self):
        api, manager = self.started()
        self.climate_stopped(api, 21)
        self.check(manager)
        self.assertEqual(names(api), ["status"])
        state = manager.get_state()
        self.assertIsNone(state.achieve)
        self.assertIn("reached", state.result)

    def test_stops_without_relocking_an_unlocked_car(self):
        api, manager = self.started()
        self.climate_stopped(api, 12)
        api.car.update(lockStatus=0)
        self.check(manager)
        self.assertEqual(names(api), ["status"])
        self.assertIsNone(manager.get_state().achieve)

    def test_all_off_cancels(self):
        api, manager = self.started()
        manager._try_mark_busy()
        asyncio.run(manager._run_action(MGRequest(MGAction.ALL_OFF), "Test"))
        self.assertIsNone(manager.get_state().achieve)

    def test_switching_off_cancels(self):
        _, manager = self.started()
        manager.set_achieve_temperature(False, 2)
        self.assertIsNone(manager.get_state().achieve)

    def test_stops_after_the_cars_restart_allowance(self):
        api, manager = self.started()  # Default allowance: 2 restarts
        for expected in (1, 2):
            self.climate_stopped(api, 12)
            self.check(manager)
            self.assertEqual(manager.get_state().achieve.restarts, expected)
        api.calls.clear()
        self.climate_stopped(api, 14)
        self.check(manager)
        self.assertEqual(names(api), ["status"])  # No third start
        state = manager.get_state()
        self.assertIsNone(state.achieve)
        self.assertIn("2 of 2 restart(s)", state.result)

    def test_restart_resends_seats_only_when_off(self):
        api, manager = self.started()
        self.climate_stopped(api, 12)  # Seats still on (1/0)
        self.check(manager)
        self.assertNotIn("seats", names(api))
        self.assertIn("climate restarted", manager.get_state().result)
        api.calls.clear()
        self.climate_stopped(api, 12)
        api.car.update(frontLeftSeatHeatLevel=0)
        self.check(manager)
        self.assertIn(("seats", 1, 0), api.calls)
        self.assertIn("climate and seats restarted", manager.get_state().result)

    def test_changed_allowance_applies_to_running_job(self):
        _, manager = self.started()
        manager.set_achieve_temperature(True, 1)
        self.assertEqual(manager.get_state().achieve.max_restarts, 1)

    def test_logout_stops_without_logging_in_again(self):
        api, manager = self.started()
        api.fail["status"] = SaicLogoutException("logged out", 401)
        self.check(manager)
        self.assertEqual(names(api), ["status"])
        state = manager.get_state()
        self.assertIsNone(state.achieve)
        self.assertIsNotNone(state.backoff_until)

    def test_car_block_stops_at_once(self):
        api, manager = self.started()
        self.climate_stopped(api, 12)
        api.fail["start_ac"] = SaicApiException(TOO_FREQUENT, return_code=8)
        self.check(manager)
        state = manager.get_state()
        self.assertIsNone(state.achieve)
        self.assertIn("with the key", state.result)

    def test_gives_up_after_repeated_errors(self):
        api, manager = self.started()
        for attempt in range(mg_car.ACHIEVE_MAX_ERRORS):
            self.assertIsNotNone(manager.get_state().achieve)
            api.fail["status"] = SaicApiException("car did not answer", return_code=500)
            self.check(manager)
        state = manager.get_state()
        self.assertIsNone(state.achieve)
        self.assertFalse(state.result_ok)


if __name__ == "__main__":
    unittest.main()
