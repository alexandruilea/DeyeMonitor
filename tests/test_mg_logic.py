"""
Unit tests for the MG car command planning, result checks, achieve-temperature
decisions, schedule timing and parsing.
"""

import unittest
from datetime import date, datetime, timedelta

from src.mg_logic import (
    ACHIEVE_CHECK, ACHIEVE_MAX, AchieveStep, CarStatus, MGAction, MGRequest, MGSchedule, SeatSupport, Step,
    StepKind, achieve_restart_request, achieve_step, format_days, is_remote_block, new_achieve_job, next_run,
    note_cabin_reading, parse_days, parse_time, pick_vin, plan_commands, schedule_due, seat_support_from_config, temperature_index,
    verify_result,
)

LOCKED = CarStatus(locked=True, climate=0, rear_window_heat=0, seat_left=0, seat_right=0)
UNLOCKED = CarStatus(locked=False, climate=0, rear_window_heat=0, seat_left=0, seat_right=0)


def kinds(steps):
    return [s.kind for s in steps]


class TestPlanCommands(unittest.TestCase):
    def test_locks_first_when_unlocked(self):
        steps, _ = plan_commands(MGRequest(MGAction.CLIMATE, 18), "ZS EV S", SeatSupport.NONE, UNLOCKED)
        self.assertEqual(kinds(steps), [StepKind.LOCK, StepKind.CLIMATE_ON])

    def test_locks_when_lock_state_unknown(self):
        steps, _ = plan_commands(MGRequest(MGAction.CLIMATE, 18), "ZS EV S", SeatSupport.NONE, CarStatus())
        self.assertEqual(steps[0].kind, StepKind.LOCK)

    def test_no_lock_when_locked(self):
        steps, _ = plan_commands(MGRequest(MGAction.CLIMATE, 18), "ZS EV S", SeatSupport.NONE, LOCKED)
        self.assertEqual(steps, [Step(StepKind.CLIMATE_ON, temperature_idx=4)])

    def test_driver_seat_on_off_car(self):
        steps, _ = plan_commands(MGRequest(MGAction.CLIMATE_DRIVER_SEAT, 18), "IS31P S", SeatSupport.ON_OFF, LOCKED)
        self.assertEqual(steps[-1], Step(StepKind.SEATS, left=1, right=0))

    def test_both_seats_level_car(self):
        steps, _ = plan_commands(MGRequest(MGAction.CLIMATE_BOTH_SEATS, 18), "EH32 S", SeatSupport.LEVELS, LOCKED)
        self.assertEqual(steps[-1], Step(StepKind.SEATS, left=3, right=3))

    def test_seats_skipped_without_support(self):
        steps, notes = plan_commands(MGRequest(MGAction.CLIMATE_BOTH_SEATS, 18), "ZS EV S", SeatSupport.NONE, LOCKED)
        self.assertNotIn(StepKind.SEATS, kinds(steps))
        self.assertTrue(any("seat" in n for n in notes))

    def test_climate_only_turns_seats_off(self):
        status = CarStatus(locked=True, climate=2, seat_left=1, seat_right=0)
        steps, _ = plan_commands(MGRequest(MGAction.CLIMATE, 18), "IS31P S", SeatSupport.ON_OFF, status)
        self.assertEqual(steps[-1], Step(StepKind.SEATS, left=0, right=0))

    def test_seats_already_set_are_not_resent(self):
        status = CarStatus(locked=True, climate=2, seat_left=1, seat_right=0)
        steps, _ = plan_commands(MGRequest(MGAction.CLIMATE_DRIVER_SEAT, 18), "IS31P S", SeatSupport.ON_OFF, status)
        self.assertEqual(kinds(steps), [StepKind.CLIMATE_ON])

    def test_windshield_and_rear_defrost(self):
        request = MGRequest(MGAction.CLIMATE_DRIVER_SEAT, 18, windshield=True, rear_defrost=True)
        steps, _ = plan_commands(request, "IS31P S", SeatSupport.ON_OFF, UNLOCKED)
        self.assertEqual(kinds(steps), [StepKind.LOCK, StepKind.FRONT_DEFROST, StepKind.REAR_WINDOW, StepKind.SEATS])
        self.assertTrue(steps[2].enable)

    def test_temperature_clamped_to_car_range(self):
        steps, notes = plan_commands(MGRequest(MGAction.CLIMATE, 31), "IS31P S", SeatSupport.ON_OFF, LOCKED)
        self.assertEqual(steps[0].temperature_idx, temperature_index("IS31P S", 28))
        self.assertTrue(notes)

    def test_all_off_only_switches_off_what_is_on(self):
        status = CarStatus(locked=False, climate=2, rear_window_heat=1, seat_left=1, seat_right=0)
        steps, _ = plan_commands(MGRequest(MGAction.ALL_OFF), "IS31P S", SeatSupport.ON_OFF, status)
        self.assertEqual(steps, [Step(StepKind.CLIMATE_OFF), Step(StepKind.REAR_WINDOW, enable=False),
                                 Step(StepKind.SEATS, left=0, right=0)])

    def test_all_off_never_locks(self):
        steps, _ = plan_commands(MGRequest(MGAction.ALL_OFF), "IS31P S", SeatSupport.ON_OFF,
                                 CarStatus(locked=False, climate=2))
        self.assertNotIn(StepKind.LOCK, kinds(steps))

    def test_all_off_when_already_off(self):
        steps, _ = plan_commands(MGRequest(MGAction.ALL_OFF), "IS31P S", SeatSupport.ON_OFF, LOCKED)
        self.assertEqual(steps, [])


class TestVerifyResult(unittest.TestCase):
    def test_climate_on_confirmed(self):
        status = CarStatus(locked=True, climate=2, seat_left=1, seat_right=0)
        self.assertEqual(verify_result(MGRequest(MGAction.CLIMATE_DRIVER_SEAT), SeatSupport.ON_OFF, status), [])

    def test_seat_mismatch_reported(self):
        status = CarStatus(locked=True, climate=2, seat_left=0, seat_right=0)
        problems = verify_result(MGRequest(MGAction.CLIMATE_DRIVER_SEAT), SeatSupport.ON_OFF, status)
        self.assertEqual(problems, ["seats 0/0, expected 1/0"])

    def test_climate_off_reported(self):
        problems = verify_result(MGRequest(MGAction.CLIMATE), SeatSupport.NONE, CarStatus(climate=0))
        self.assertEqual(problems, ["car reports climate off"])

    def test_all_off_leftovers_reported(self):
        status = CarStatus(climate=2, rear_window_heat=1, seat_left=0, seat_right=1)
        problems = verify_result(MGRequest(MGAction.ALL_OFF), SeatSupport.ON_OFF, status)
        self.assertEqual(len(problems), 3)


class TestTemperatureAndSeats(unittest.TestCase):
    def test_temperature_index_matches_tested_cars(self):
        # 18°C was sent as index 4 to both the ZS EV and the S9, which confirmed climate on
        self.assertEqual(temperature_index("ZS EV S", 18), 4)
        self.assertEqual(temperature_index("IS31P S", 18), 4)
        self.assertEqual(temperature_index("EH32 S", 18), 4)
        self.assertEqual(temperature_index("ZS EV S", 22), 8)

    def test_seat_support(self):
        self.assertEqual(seat_support_from_config("1"), SeatSupport.LEVELS)
        self.assertEqual(seat_support_from_config("2"), SeatSupport.ON_OFF)
        self.assertEqual(seat_support_from_config("0"), SeatSupport.NONE)
        self.assertEqual(seat_support_from_config(None), SeatSupport.NONE)


class TestSchedule(unittest.TestCase):
    SCHEDULE = MGSchedule(enabled=True, hour=7, minute=0, days=frozenset(range(5)))
    MONDAY_7 = datetime(2026, 11, 2, 7, 0)

    def test_due_at_time(self):
        self.assertTrue(schedule_due(self.SCHEDULE, self.MONDAY_7, None, None))

    def test_not_due_before_time(self):
        self.assertFalse(schedule_due(self.SCHEDULE, self.MONDAY_7 - timedelta(minutes=1), None, None))

    def test_due_within_grace(self):
        self.assertTrue(schedule_due(self.SCHEDULE, self.MONDAY_7 + timedelta(minutes=14), None, None))

    def test_not_due_after_grace(self):
        self.assertFalse(schedule_due(self.SCHEDULE, self.MONDAY_7 + timedelta(minutes=15), None, None))

    def test_not_due_on_unselected_day(self):
        saturday = self.MONDAY_7 + timedelta(days=5)
        self.assertFalse(schedule_due(self.SCHEDULE, saturday, None, None))

    def test_not_due_when_disabled(self):
        disabled = MGSchedule(enabled=False, hour=7, minute=0)
        self.assertFalse(schedule_due(disabled, self.MONDAY_7, None, None))

    def test_runs_once_per_day(self):
        self.assertFalse(schedule_due(self.SCHEDULE, self.MONDAY_7 + timedelta(minutes=5),
                                      self.MONDAY_7.date(), self.MONDAY_7))

    def test_retry_after_failure(self):
        now = self.MONDAY_7 + timedelta(minutes=2)
        self.assertFalse(schedule_due(self.SCHEDULE, now, None, self.MONDAY_7))
        now = self.MONDAY_7 + timedelta(minutes=3)
        self.assertTrue(schedule_due(self.SCHEDULE, now, None, self.MONDAY_7))

    def test_yesterdays_attempt_does_not_block(self):
        yesterday = self.MONDAY_7 - timedelta(days=1, minutes=-1)
        self.assertTrue(schedule_due(self.SCHEDULE, self.MONDAY_7, None, yesterday))

    def test_next_run_later_today(self):
        self.assertEqual(next_run(self.SCHEDULE, self.MONDAY_7 - timedelta(hours=1)), self.MONDAY_7)

    def test_next_run_skips_weekend_and_done_day(self):
        friday_8 = datetime(2026, 11, 6, 8, 0)
        self.assertEqual(next_run(self.SCHEDULE, friday_8), datetime(2026, 11, 9, 7, 0))
        friday_7 = datetime(2026, 11, 6, 7, 5)
        self.assertEqual(next_run(self.SCHEDULE, friday_7, last_success=date(2026, 11, 6)), datetime(2026, 11, 9, 7, 0))

    def test_next_run_none_without_days(self):
        self.assertIsNone(next_run(MGSchedule(enabled=True, days=frozenset()), self.MONDAY_7))


class TestAchieveTemperature(unittest.TestCase):
    START = datetime(2026, 12, 7, 7, 0)
    CHECK = START + ACHIEVE_CHECK

    def job(self, temperature=22, cabin_before=2, series="ZS EV S", max_restarts=5, **extras):
        return new_achieve_job(MGRequest(MGAction.CLIMATE_DRIVER_SEAT, temperature, **extras),
                               series, cabin_before, self.START, max_restarts)

    def test_stops_when_the_cars_restarts_are_used(self):
        job = self.job(max_restarts=2)
        job.restarts = 2
        self.assertEqual(achieve_step(job, self.status(14), self.CHECK), AchieveStep.NO_RESTARTS_LEFT)
        # No point polling the last run until it stops
        self.assertEqual(achieve_step(job, self.status(14, climate=2), self.CHECK), AchieveStep.NO_RESTARTS_LEFT)
        self.assertEqual(achieve_step(job, self.status(21), self.CHECK), AchieveStep.REACHED)
        job.restarts = 1
        self.assertEqual(achieve_step(job, self.status(14), self.CHECK), AchieveStep.RESTART)

    def test_zero_restarts_only_reports(self):
        self.assertEqual(achieve_step(self.job(max_restarts=0), self.status(14), self.CHECK),
                         AchieveStep.NO_RESTARTS_LEFT)

    @staticmethod
    def status(cabin, climate=0, locked=True):
        return CarStatus(locked=locked, climate=climate, cabin_temp=cabin)

    def test_new_job_times(self):
        job = self.job()
        self.assertEqual((job.next_check, job.deadline), (self.CHECK, self.START + ACHIEVE_MAX))
        self.assertTrue(job.heating)

    def test_target_clamped_to_car_range(self):
        self.assertEqual(self.job(temperature=31).target, 28)

    def test_restart_when_climate_stopped_and_cabin_cold(self):
        self.assertEqual(achieve_step(self.job(), self.status(14), self.CHECK), AchieveStep.RESTART)

    def test_reached_within_tolerance(self):
        self.assertEqual(achieve_step(self.job(), self.status(21), self.CHECK), AchieveStep.REACHED)
        self.assertEqual(achieve_step(self.job(), self.status(20), self.CHECK), AchieveStep.RESTART)

    def test_wait_while_climate_still_running(self):
        self.assertEqual(achieve_step(self.job(), self.status(14, climate=2), self.CHECK), AchieveStep.WAIT)

    def test_unlocked_car_stops(self):
        self.assertEqual(achieve_step(self.job(), self.status(14, locked=False), self.CHECK), AchieveStep.UNLOCKED)

    def test_unknown_lock_state_still_restarts(self):
        self.assertEqual(achieve_step(self.job(), CarStatus(climate=0, cabin_temp=14), self.CHECK),
                         AchieveStep.RESTART)

    def test_gives_up_at_deadline(self):
        job = self.job()
        self.assertEqual(achieve_step(job, self.status(18), job.deadline), AchieveStep.TIMED_OUT)
        self.assertEqual(achieve_step(job, self.status(18, climate=2), job.deadline), AchieveStep.TIMED_OUT)

    def test_no_cabin_reading(self):
        job = self.job(cabin_before=None)
        self.assertEqual(achieve_step(job, self.status(None), self.CHECK), AchieveStep.NO_READING)
        self.assertEqual(achieve_step(job, self.status(None, climate=2), self.CHECK), AchieveStep.WAIT)

    def test_last_reading_used_when_the_car_sends_none(self):
        job = self.job(cabin_before=None)
        note_cabin_reading(job, self.status(15, climate=2), self.CHECK)
        self.assertEqual((job.cabin_temp, job.cabin_time), (15, self.CHECK))
        note_cabin_reading(job, self.status(None), self.CHECK + timedelta(minutes=1))
        self.assertEqual(job.cabin_temp, 15)
        self.assertEqual(achieve_step(job, self.status(None), self.CHECK), AchieveStep.RESTART)
        note_cabin_reading(job, self.status(21, climate=2), self.CHECK)
        self.assertEqual(achieve_step(job, self.status(None), self.CHECK), AchieveStep.REACHED)

    def test_cooling_a_hot_cabin(self):
        job = self.job(temperature=20, cabin_before=38)
        self.assertFalse(job.heating)
        self.assertEqual(achieve_step(job, self.status(27), self.CHECK), AchieveStep.RESTART)
        self.assertEqual(achieve_step(job, self.status(21), self.CHECK), AchieveStep.REACHED)

    def test_unknown_start_temperature_means_heating(self):
        self.assertTrue(self.job(cabin_before=None).heating)

    def test_car_block_recognised(self):
        self.assertTrue(is_remote_block("return code: 8, message: Too frequent operations. Please use the "
                                        "physical key to restart the vehicle...(71), event_id: 1816245305"))
        self.assertTrue(is_remote_block("return code: 8, message: operation too frequent"))
        self.assertFalse(is_remote_block("return code: 8, message: Vehicle not locked"))

    def test_restart_drops_the_defrosters(self):
        job = self.job(windshield=True, rear_defrost=True)
        self.assertEqual(achieve_restart_request(job), MGRequest(MGAction.CLIMATE_DRIVER_SEAT, 22))


class TestParsing(unittest.TestCase):
    def test_days_round_trip(self):
        days = parse_days("Mon, tue,Fri")
        self.assertEqual(days, frozenset({0, 1, 4}))
        self.assertEqual(format_days(days), "Mon,Tue,Fri")

    def test_unknown_day_rejected(self):
        with self.assertRaises(ValueError):
            parse_days("Mon,Funday")

    def test_time(self):
        self.assertEqual(parse_time("07:05"), (7, 5))
        with self.assertRaises(ValueError):
            parse_time("24:00")

    def test_pick_vin(self):
        self.assertEqual(pick_vin(["LSJA1111"]), "LSJA1111")
        self.assertEqual(pick_vin(["LSJA1111", "LSJB3926"], "3926"), "LSJB3926")
        with self.assertRaises(ValueError):
            pick_vin(["LSJA1111", "LSJB3926"])
        with self.assertRaises(ValueError):
            pick_vin(["LSJA1111"], "9999")


if __name__ == "__main__":
    unittest.main()
