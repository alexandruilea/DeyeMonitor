"""
MG car control over SAIC's iSmart cloud API (saic-ismart-client-ng).

One manager per car, each with its own SAIC account and a background asyncio loop.
SAIC allows one login per account: logging in here logs that account out of the
iSmart phone app, and a phone login logs the app out. After being logged out,
background refreshes wait RELOGIN_BACKOFF before logging in again so the app and the
phone don't keep taking the session from each other. Button presses and schedules
log in straight away.

With "achieve temperature" on, the climate a button or schedule started is checked
again after ACHIEVE_CHECK and restarted until the cabin reaches the set temperature.
Those checks are automatic, so they stop instead of logging in again after a logout.
"""

import asyncio
import threading
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Callable, List, Optional, Tuple

from saic_ismart_client_ng import SaicApi
from saic_ismart_client_ng.api.vehicle.schema import BasicVehicleStatus
from saic_ismart_client_ng.exceptions import SaicApiException, SaicLogoutException
from saic_ismart_client_ng.model import SaicApiConfiguration

from src.config import MGCarConfig
from src.mg_logic import (
    ACHIEVE_CHECK, ACHIEVE_MAX, ACHIEVE_MAX_ERRORS, ACHIEVE_RECHECK, ESSENTIAL_STEPS, REMOTE_BLOCK_HINT,
    AchieveJob, AchieveStep, CarStatus, MGAction, MGRequest, MGSchedule, SeatSupport, Step, StepKind,
    achieve_restart_request, achieve_step, describe_request, is_remote_block, mask_vin, new_achieve_job,
    next_run, note_cabin_reading, pick_vin, plan_commands, schedule_due, seat_support_from_config, verify_result,
)

RELOGIN_BACKOFF = timedelta(minutes=30)  # After the phone took the session, before a background login
STATUS_REFRESH = timedelta(minutes=10)   # Cached status poll (doesn't wake the car)
COMMAND_GAP_SECONDS = 5                  # Pause between commands so the car isn't asked while still busy
READBACK_DELAY_SECONDS = 15              # Let the car apply the last command before reading it back
LOOP_INTERVAL_SECONDS = 20


@dataclass
class MGCarState:
    """Snapshot of one car for the UI (a copy, safe to read on the main thread)."""
    logged_in: bool = False
    car_label: str = ""
    seat_support: Optional[SeatSupport] = None  # None until the car info is loaded
    battery_pct: Optional[int] = None
    climate: Optional[int] = None
    locked: Optional[bool] = None
    seat_left: Optional[int] = None
    seat_right: Optional[int] = None
    rear_window_heat: Optional[int] = None
    cabin_temp: Optional[int] = None
    status_time: Optional[datetime] = None
    busy: str = ""             # Current step while an action runs, "" when idle
    result: str = ""
    result_ok: bool = True
    backoff_until: Optional[datetime] = None
    next_schedule: Optional[datetime] = None
    achieve: Optional[AchieveJob] = None  # Running achieve-temperature job


def cabin_temperature(basic: BasicVehicleStatus) -> Optional[int]:
    """interiorTemperature in °C, None when missing or a placeholder (the car sends 87 for no reading)."""
    value = basic.interiorTemperature
    return value if value is not None and -40 <= value <= 80 else None


class MGCarManager:
    """Runs button presses, the schedule and status refreshes for one MG car."""

    def __init__(self, config: MGCarConfig, error_callback: Optional[Callable[[str], None]] = None):
        self.config = config
        self.error_callback = error_callback
        self._state = MGCarState()
        self._state_lock = threading.Lock()

        self._schedule: Optional[MGSchedule] = config.schedule
        self._schedule_temp = config.temperature
        self._schedule_done: Optional[date] = None  # Day the schedule ran, or gave up
        self._last_schedule_attempt: Optional[datetime] = None
        self._remote_blocked = False  # The last action hit the car's "too frequent operations" block
        self._achieve_enabled = config.achieve_temperature
        self._achieve_max_restarts = config.achieve_max_restarts
        self._achieve: Optional[AchieveJob] = None  # Guarded by _state_lock

        self._api: Optional[SaicApi] = None
        self._vin: Optional[str] = None
        self._series = ""
        self._seat_support = SeatSupport.NONE
        self._kicked_at: Optional[datetime] = None
        self._auto_login_paused = False  # After a rejected login, only a button press retries
        self._last_refresh: Optional[datetime] = None
        self._last_refresh_error = ""

        self._running = True
        self._loop = asyncio.new_event_loop()
        self._api_lock = asyncio.Lock()  # One SAIC conversation at a time (actions and refreshes)
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------
    # Public API (main thread, non-blocking)
    # ------------------------------------------------------------------

    def request(self, request: MGRequest) -> bool:
        """Run a button action in the background; False if another action is still running."""
        if not self._try_mark_busy():
            return False
        asyncio.run_coroutine_threadsafe(self._run_action(request, "Button"), self._loop)
        return True

    def set_schedule(self, schedule: Optional[MGSchedule], temperature: int) -> None:
        """Replace the schedule (None = disabled) and the temperature it uses."""
        with self._state_lock:
            self._schedule = schedule
            self._schedule_temp = temperature

    def set_achieve_temperature(self, enabled: bool, max_restarts: int) -> None:
        """Turn the achieve-temperature restarts on or off (off cancels a running one) and set
        how many restarts this car allows."""
        with self._state_lock:
            self._achieve_enabled = enabled
            self._achieve_max_restarts = max_restarts
            cancelled = self._achieve if not enabled else None
            if cancelled:
                self._achieve = None
            elif self._achieve:
                self._achieve.max_restarts = max_restarts
        if cancelled:
            self._log("Achieve temperature switched off - auto-restart cancelled")

    def get_state(self) -> MGCarState:
        with self._state_lock:
            state = replace(self._state)
            state.achieve = replace(self._achieve) if self._achieve else None
            schedule = self._schedule
        state.next_schedule = next_run(schedule, datetime.now(), self._schedule_done) if schedule else None
        return state

    def stop(self) -> None:
        """Stop the background loop."""
        self._running = False

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main_task())

    async def _main_task(self) -> None:
        await self._refresh_status()  # Log in and load the car info at startup
        while self._running:
            await asyncio.sleep(LOOP_INTERVAL_SECONDS)
            now = datetime.now()
            request = self._due_schedule_request(now)
            if request and self._try_mark_busy():
                await self._run_schedule(request, now)
            elif self._achieve_due(now) and self._try_mark_busy():
                await self._achieve_check()
            elif not self._is_busy() and (self._last_refresh is None or now - self._last_refresh >= STATUS_REFRESH):
                await self._refresh_status()
        if self._api:
            await self._api.close()

    def _due_schedule_request(self, now: datetime) -> Optional[MGRequest]:
        with self._state_lock:
            schedule, temperature = self._schedule, self._schedule_temp
        if schedule is None or not schedule_due(schedule, now, self._schedule_done,
                                                self._last_schedule_attempt):
            return None
        return MGRequest(schedule.action, temperature, schedule.windshield, schedule.rear_defrost)

    async def _run_schedule(self, request: MGRequest, now: datetime) -> None:
        self._last_schedule_attempt = now
        if await self._run_action(request, "Schedule"):
            self._schedule_done = now.date()
        elif self._remote_blocked:
            self._schedule_done = now.date()  # Retries can't help until someone uses the key
            self._log("Schedule: no more tries today")

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------

    async def _ensure_session(self, automatic: bool) -> bool:
        """Log in and load the car if needed. Automatic callers respect the re-login backoff."""
        if self._api is not None and self._api.is_logged_in and self._vin:
            return True
        if automatic:
            if self._auto_login_paused:
                return False
            if self._kicked_at and datetime.now() < self._kicked_at + RELOGIN_BACKOFF:
                return False

        if self._api is None:
            phone = self.config.phone_country_code or None
            self._api = SaicApi(SaicApiConfiguration.mg_eu(
                self.config.username, self.config.password,
                username_is_email=phone is None, phone_country_code=phone,
            ))
        try:
            await self._api.login()
            cars = (await self._api.vehicle_list()).vinList
            vin = pick_vin([c.vin for c in cars if c.vin], self.config.vin)
        except (SaicApiException, ValueError) as e:
            # SAIC rejected the login (wrong password, revoked share) or the car isn't on the
            # account: don't keep retrying in the background. Network errors carry a __cause__.
            if e.__cause__ is None:
                self._auto_login_paused = True
            raise
        self._auto_login_paused = False
        self._kicked_at = None

        car = next(c for c in cars if c.vin == vin)
        heated_seat = next((c.itemValue for c in car.vehicleModelConfiguration if c.itemCode == "HeatedSeat"), None)
        self._vin = vin
        self._series = car.series or ""
        self._seat_support = seat_support_from_config(heated_seat)
        with self._state_lock:
            self._state.logged_in = True
            self._state.backoff_until = None
            self._state.car_label = f"{car.modelName} {mask_vin(vin)}"
            self._state.seat_support = self._seat_support
        self._log(f"Logged in: {car.modelName} {car.modelYear} ({self._series}), "
                  f"heated seats: {self._seat_support.value}, token until {self._api.token_expiration:%Y-%m-%d}")
        return True

    def _on_logged_out(self) -> None:
        """The account was used in the iSmart app, which ended our session."""
        self._kicked_at = datetime.now()
        if self._api:
            self._api.logout()
        until = self._kicked_at + RELOGIN_BACKOFF
        with self._state_lock:
            self._state.logged_in = False
            self._state.backoff_until = until
        self._log(f"Logged out by the iSmart app - background login waits until {until:%H:%M} "
                  f"(buttons and the schedule still log in)")

    # ------------------------------------------------------------------
    # Status refresh
    # ------------------------------------------------------------------

    async def _refresh_status(self) -> None:
        """Read SAIC's cached status (doesn't wake the car)."""
        async with self._api_lock:
            self._last_refresh = datetime.now()
            try:
                if not await self._ensure_session(automatic=True):
                    return
                cached = await self._api.get_vehicle_status_cached(self._vin)
                seen = datetime.fromtimestamp(cached.statusTime) if cached.statusTime else None
                self._apply_status(cached.basicVehicleStatus, seen)
                self._last_refresh_error = ""
            except SaicLogoutException:
                self._on_logged_out()
            except Exception as e:
                message = f"Status refresh failed: {e}"
                if message != self._last_refresh_error:  # Log each new problem once
                    self._last_refresh_error = message
                    self._log(message)

    def _apply_status(self, basic: Optional[BasicVehicleStatus], seen: Optional[datetime] = None) -> None:
        """Merge the fields the car reported into the UI state (missing fields keep their last value)."""
        if basic is None:
            return
        battery = basic.extendedData1 if basic.extendedData1 is not None and 0 <= basic.extendedData1 <= 100 else None
        cabin = cabin_temperature(basic)
        locked = None if basic.lockStatus is None else basic.lockStatus == 1
        with self._state_lock:
            s = self._state
            for name, value in (("battery_pct", battery), ("climate", basic.remoteClimateStatus),
                                ("locked", locked), ("seat_left", basic.frontLeftSeatHeatLevel),
                                ("seat_right", basic.frontRightSeatHeatLevel),
                                ("rear_window_heat", basic.rmtHtdRrWndSt), ("cabin_temp", cabin)):
                if value is not None:
                    setattr(s, name, value)
            s.status_time = seen or datetime.now()

    @staticmethod
    def _car_status(basic: Optional[BasicVehicleStatus]) -> CarStatus:
        if basic is None:
            return CarStatus()
        return CarStatus(
            locked=None if basic.lockStatus is None else basic.lockStatus == 1,
            climate=basic.remoteClimateStatus,
            rear_window_heat=basic.rmtHtdRrWndSt,
            seat_left=basic.frontLeftSeatHeatLevel,
            seat_right=basic.frontRightSeatHeatLevel,
            cabin_temp=cabin_temperature(basic),
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def _run_action(self, request: MGRequest, source: str) -> bool:
        """Run one button/schedule action; returns True when the car confirmed it."""
        label = describe_request(request)
        self._log(f"{source}: {label}")
        with self._state_lock:
            ended, self._achieve = self._achieve, None
        if ended:
            self._log("Achieve temperature: the previous auto-restart ends with this command")
        self._remote_blocked = False
        try:
            async with self._api_lock:
                try:
                    return await self._execute(request, label)
                except SaicLogoutException:
                    # The phone took the session since our last call: log in again once
                    self._api.logout()
                    self._log("Session was taken by the iSmart app, logging in again")
                    return await self._execute(request, label)
        except SaicLogoutException:
            self._on_logged_out()
            self._set_result(False, f"{label} failed: logged out by the iSmart app")
        except Exception as e:
            if is_remote_block(str(e)):
                self._remote_blocked = True
                self._set_result(False, f"{label} refused: {REMOTE_BLOCK_HINT}")
            else:
                self._set_result(False, f"{label} failed: {e}")
        finally:
            self._set_busy("")
        return False

    async def _execute(self, request: MGRequest, label: str) -> bool:
        self._set_busy("Logging in...")
        await self._ensure_session(automatic=False)

        # Live status (wakes the car): the lock state decides whether to lock first
        self._set_busy("Waking the car...")
        basic = (await self._api.get_vehicle_status(self._vin)).basicVehicleStatus
        self._apply_status(basic)
        before = self._car_status(basic)
        steps, notes = plan_commands(request, self._series, self._seat_support, before)
        for note in notes:
            self._log(note)
        if not steps:
            self._set_result(True, f"{label}: nothing to do, already off")
            return True

        started = datetime.now()
        problems, after = await self._send_steps(request, steps)
        if problems:
            self._set_result(False, f"{label}: {'; '.join(problems)}")
        else:
            self._set_result(True, f"{label}: done")
        if request.action != MGAction.ALL_OFF and after.climate != 0:
            # The car may only report the cabin once the climate runs
            cabin = before.cabin_temp if before.cabin_temp is not None else after.cabin_temp
            self._arm_achieve(request, cabin, started)
        return not problems

    async def _send_steps(self, request: MGRequest, steps: List[Step]) -> Tuple[List[str], CarStatus]:
        """Send the commands, then read the car back; returns (problems, status afterwards)."""
        problems = []
        for i, step in enumerate(steps):
            if i:
                await asyncio.sleep(COMMAND_GAP_SECONDS)
            self._set_busy(f"{step.kind.value}...")
            try:
                response = await self._send(step)
            except SaicLogoutException:
                raise
            except SaicApiException as e:
                if step.kind in ESSENTIAL_STEPS:
                    raise
                problems.append(f"{step.kind.value.lower()} failed ({e})")
                continue
            self._apply_status(response.basicVehicleStatus)

        self._set_busy("Checking the result...")
        await asyncio.sleep(READBACK_DELAY_SECONDS)
        basic = (await self._api.get_vehicle_status(self._vin)).basicVehicleStatus
        self._apply_status(basic)
        after = self._car_status(basic)
        return problems + verify_result(request, self._seat_support, after), after

    async def _send(self, step: Step):
        vin = self._vin
        if step.kind == StepKind.LOCK:
            return await self._api.lock_vehicle(vin)
        if step.kind == StepKind.CLIMATE_ON:
            return await self._api.start_ac(vin, temperature_idx=step.temperature_idx)
        if step.kind == StepKind.FRONT_DEFROST:
            return await self._api.start_front_defrost(vin)
        if step.kind == StepKind.CLIMATE_OFF:
            return await self._api.stop_ac(vin)
        if step.kind == StepKind.REAR_WINDOW:
            return await self._api.control_rear_window_heat(vin, enable=step.enable)
        return await self._api.control_heated_seats(vin, left_side_level=step.left, right_side_level=step.right)

    # ------------------------------------------------------------------
    # Achieve temperature
    # ------------------------------------------------------------------

    def _arm_achieve(self, request: MGRequest, cabin: Optional[int], started: datetime) -> None:
        """After a climate start: check the cabin again later, if the switch is on."""
        with self._state_lock:
            if not self._achieve_enabled:
                return
            job = self._achieve = new_achieve_job(request, self._series, cabin, started, self._achieve_max_restarts)
        start_reading = f"cabin {cabin}°C" if cabin is not None else "no cabin reading yet"
        self._log(f"Achieve temperature: {'heating' if job.heating else 'cooling'} to {job.target}°C "
                  f"({start_reading}), checking the cabin at {job.next_check:%H:%M}")

    def _achieve_due(self, now: datetime) -> bool:
        with self._state_lock:
            return self._achieve is not None and now >= self._achieve.next_check

    async def _achieve_check(self) -> None:
        """Read the cabin temperature and start the climate again if the car stopped it too early."""
        job = None
        try:
            async with self._api_lock:
                with self._state_lock:
                    job = self._achieve
                if job is None:
                    return  # Switched off while waiting
                self._set_busy("Checking the cabin temperature...")
                if not await self._ensure_session(automatic=True):
                    self._end_achieve(job, False, "not logged in (the iSmart app has the session), auto-restart stopped")
                    return
                basic = (await self._api.get_vehicle_status(self._vin)).basicVehicleStatus
                self._apply_status(basic)
                await self._achieve_next(job, self._car_status(basic), basic.interiorTemperature if basic else None)
        except SaicLogoutException:
            self._on_logged_out()
            self._end_achieve(job, False, "logged out by the iSmart app, auto-restart stopped")
        except Exception as e:
            if is_remote_block(str(e)):
                self._end_achieve(job, False, f"restart refused - {REMOTE_BLOCK_HINT}")
            else:
                self._achieve_error(job, f"check failed ({e})")
        finally:
            self._set_busy("")

    async def _achieve_next(self, job: AchieveJob, status: CarStatus, raw_cabin: Optional[int]) -> None:
        now = datetime.now()
        with self._state_lock:
            note_cabin_reading(job, status, now)
        step = achieve_step(job, status, now)
        if status.cabin_temp is not None:
            cabin = f"{status.cabin_temp}°C"
        elif job.cabin_temp is not None:
            cabin = f"{job.cabin_temp}°C at {job.cabin_time:%H:%M}"  # The car sent none just now
        else:
            cabin = "--"

        if step == AchieveStep.WAIT:
            with self._state_lock:
                job.next_check = now + ACHIEVE_RECHECK
                job.errors = 0
            return
        if step == AchieveStep.REACHED:
            restarts = f" after {job.restarts} restart(s)" if job.restarts else ""
            self._end_achieve(job, True, f"reached, cabin {cabin}{restarts}")
            return
        if step == AchieveStep.UNLOCKED:
            self._end_achieve(job, True, f"car unlocked, auto-restart stopped (cabin {cabin})")
            return
        if step == AchieveStep.TIMED_OUT:
            minutes = int(ACHIEVE_MAX.total_seconds() // 60)
            self._end_achieve(job, False, f"cabin still {cabin} after {minutes} min, auto-restart stopped")
            return
        if step == AchieveStep.NO_RESTARTS_LEFT:
            self._end_achieve(job, False, f"cabin {cabin} after {job.restarts} of {job.max_restarts} restart(s) "
                                          f"this car allows, auto-restart stopped")
            return
        if step == AchieveStep.NO_READING:
            self._end_achieve(job, False, f"the car didn't report the cabin temperature (sent {raw_cabin}), "
                                          f"auto-restart stopped")
            return

        request = achieve_restart_request(job)
        steps, notes = plan_commands(request, self._series, self._seat_support, status)
        for note in notes:
            self._log(note)
        with self._state_lock:
            job.restarts += 1
        what = "climate and seats" if any(s.kind == StepKind.SEATS for s in steps) else "climate"
        self._log(f"Achieve {job.target}°C: cabin {cabin} and the climate stopped, restarting the {what} "
                  f"({job.restarts}/{job.max_restarts})")
        started = datetime.now()
        problems, after = await self._send_steps(request, steps)
        if after.climate == 0:
            self._achieve_error(job, "the climate didn't start again")
            return
        with self._state_lock:
            job.next_check = started + ACHIEVE_CHECK
            job.errors = 0
            note_cabin_reading(job, after, datetime.now())
        details = f"; {'; '.join(problems)}" if problems else ""
        self._set_result(not problems, f"Achieve {job.target}°C: cabin {cabin}, {what} restarted "
                                       f"({job.restarts}/{job.max_restarts}){details}")

    def _achieve_error(self, job: Optional[AchieveJob], text: str) -> None:
        """Try again shortly; give up after ACHIEVE_MAX_ERRORS failures in a row."""
        if job is None:
            return
        with self._state_lock:
            if self._achieve is not job:
                return
            job.errors += 1
            job.next_check = datetime.now() + ACHIEVE_RECHECK
            give_up = job.errors >= ACHIEVE_MAX_ERRORS
        if give_up:
            self._end_achieve(job, False, f"{text}, auto-restart stopped after {job.errors} tries")
        else:
            self._log(f"Achieve {job.target}°C: {text}, trying again in a minute")

    def _end_achieve(self, job: Optional[AchieveJob], ok: bool, text: str) -> None:
        if job is None:
            return
        with self._state_lock:
            if self._achieve is not job:
                return  # Switched off or replaced meanwhile
            self._achieve = None
        self._set_result(ok, f"Achieve {job.target}°C: {text}")

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _try_mark_busy(self) -> bool:
        with self._state_lock:
            if self._state.busy:
                return False
            self._state.busy = "Starting..."
            return True

    def _is_busy(self) -> bool:
        with self._state_lock:
            return bool(self._state.busy)

    def _set_busy(self, text: str) -> None:
        with self._state_lock:
            self._state.busy = text

    def _set_result(self, ok: bool, text: str) -> None:
        stamped = f"{datetime.now():%H:%M} {text}"
        with self._state_lock:
            self._state.result = stamped
            self._state.result_ok = ok
        self._log(text)

    def _log(self, message: str) -> None:
        if self.error_callback:
            self.error_callback(f"[{self.config.name}] {message}")
