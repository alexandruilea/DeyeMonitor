"""
MG car (SAIC iSmart) decision logic: which commands a button or schedule sends,
when a schedule is due, when to restart the climate to reach a temperature, and
SAIC's climate temperature encoding.

Kept free of network code so it can be unit tested; src/mg_car.py runs the commands.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import FrozenSet, List, Optional, Sequence, Tuple


class MGAction(Enum):
    """The four buttons; a schedule runs one of them."""
    CLIMATE = "climate"
    CLIMATE_DRIVER_SEAT = "climate_driver"
    CLIMATE_BOTH_SEATS = "climate_both"
    ALL_OFF = "off"


ACTION_LABELS = {
    MGAction.CLIMATE: "Climate",
    MGAction.CLIMATE_DRIVER_SEAT: "Climate + Driver Seat",
    MGAction.CLIMATE_BOTH_SEATS: "Climate + Both Seats",
    MGAction.ALL_OFF: "All Off",
}


class SeatSupport(Enum):
    NONE = "none"
    ON_OFF = "on/off"
    LEVELS = "levels"


# Seat level sent for "on": on/off seats only accept 1, level seats get the warmest setting
SEAT_ON_LEVEL = {SeatSupport.ON_OFF: 1, SeatSupport.LEVELS: 3}

# remoteClimateStatus values, as the SAIC MQTT gateway names them
CLIMATE_STATES = {0: "off", 1: "blowing only", 2: "on", 5: "front defrost"}

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# A schedule still runs this long after its time (app busy, car slow to answer, app restarted)
SCHEDULE_GRACE = timedelta(minutes=15)
# Wait between attempts when a scheduled run fails, inside the grace window
SCHEDULE_RETRY = timedelta(minutes=3)

# Achieve temperature: the car stops remote climate after about 10 minutes, so the app
# checks the cabin then and starts the climate again until the cabin gets there.
# The S9 stopped reporting the cabin temperature once the climate was off, so the first
# check comes just before the stop and the last reading taken while it ran is kept.
ACHIEVE_CHECK = timedelta(minutes=9)    # After each climate start
ACHIEVE_RECHECK = timedelta(minutes=1)  # While the car still reports the climate running, or after an error
ACHIEVE_MAX = timedelta(minutes=60)     # No restarts this long after the first start
ACHIEVE_TOLERANCE = 1                   # °C: the cabin sensor reads whole degrees and settles near the set point
ACHIEVE_MAX_ERRORS = 3                  # Failed checks in a row before giving up

# After a few remote climate starts in a row (owners report two), the car refuses remote
# commands with code 8 "Too frequent operations. Please use the physical key to restart
# the vehicle..." until someone switches it on with the key. Retrying can't help.
REMOTE_BLOCK_HINT = ("the car blocks remote commands after too many remote starts in a row - switch it on "
                     "once with the key, then switch it off and lock it, and remote commands work again")


@dataclass
class MGRequest:
    action: MGAction
    temperature: int = 22
    windshield: bool = False    # front defrost mode instead of normal climate (temperature is ignored)
    rear_defrost: bool = False


@dataclass
class CarStatus:
    """The parts of SAIC's basicVehicleStatus the logic needs (None = not reported)."""
    locked: Optional[bool] = None
    climate: Optional[int] = None           # remoteClimateStatus
    rear_window_heat: Optional[int] = None  # rmtHtdRrWndSt
    seat_left: Optional[int] = None
    seat_right: Optional[int] = None
    cabin_temp: Optional[int] = None        # interiorTemperature (°C), None when invalid


class StepKind(Enum):
    LOCK = "Locking the car"
    CLIMATE_ON = "Starting climate"
    FRONT_DEFROST = "Starting windshield defrost"
    CLIMATE_OFF = "Stopping climate"
    REAR_WINDOW = "Setting rear defroster"
    SEATS = "Setting seat heating"


# A failure in these stops the action; the rest are reported and the action carries on
ESSENTIAL_STEPS = (StepKind.LOCK, StepKind.CLIMATE_ON, StepKind.FRONT_DEFROST, StepKind.CLIMATE_OFF)


@dataclass(frozen=True)
class Step:
    kind: StepKind
    temperature_idx: int = 0
    enable: bool = False
    left: int = 0
    right: int = 0


@dataclass
class MGSchedule:
    enabled: bool = False
    hour: int = 7
    minute: int = 0
    days: FrozenSet[int] = frozenset(range(5))  # 0 = Monday
    action: MGAction = MGAction.CLIMATE
    windshield: bool = False
    rear_defrost: bool = False


class AchieveStep(Enum):
    """What an achieve-temperature check decides."""
    REACHED = "reached"
    WAIT = "wait"              # Climate still running: check again shortly
    RESTART = "restart"
    UNLOCKED = "unlocked"      # Someone opened the car: leave it alone
    NO_READING = "no reading"  # Climate stopped and the car didn't report the cabin temperature
    TIMED_OUT = "timed out"
    NO_RESTARTS_LEFT = "no restarts left"  # Used the car's allowance of remote starts in a row


@dataclass
class AchieveJob:
    """Keeps a button's (or schedule's) climate going until the cabin reaches its temperature."""
    request: MGRequest
    target: int            # °C, clamped to the car's range
    heating: bool          # False when cooling a hot cabin down
    deadline: datetime     # No restarts after this
    next_check: datetime
    max_restarts: int      # Per car: the car refuses remote starts after a few in a row
    restarts: int = 0
    errors: int = 0        # Failed checks in a row
    cabin_temp: Optional[int] = None       # Last cabin reading during the job
    cabin_time: Optional[datetime] = None


def seat_support_from_config(heated_seat_value: Optional[str]) -> SeatSupport:
    """SAIC's HeatedSeat model item: "1" = levels 0-3, "2" = on/off, anything else = none."""
    value = str(heated_seat_value or "").strip()
    return {"1": SeatSupport.LEVELS, "2": SeatSupport.ON_OFF}.get(value, SeatSupport.NONE)


def temperature_range(series: str) -> Tuple[int, int]:
    """Climate temperature limits (°C) per model series, as the SAIC MQTT gateway sets them."""
    s = series.upper()
    if s.startswith("EH32"):  # MG4
        return 17, 31
    if s.startswith("MZS3E"):
        return 16, 31
    return 16, 28


def temperature_index(series: str, celsius: int) -> int:
    """SAIC's climate temperature index, as the MQTT gateway computes it (MG4 has a different offset)."""
    if series.upper().startswith("EH32"):
        return 3 + celsius - 17
    return 2 + celsius - 16


def target_seat_levels(action: MGAction, seat_support: SeatSupport) -> Tuple[int, int]:
    """(left, right) seat levels for an action; left is the driver on left-hand-drive cars."""
    level = SEAT_ON_LEVEL.get(seat_support, 0)
    if action == MGAction.CLIMATE_DRIVER_SEAT:
        return level, 0
    if action == MGAction.CLIMATE_BOTH_SEATS:
        return level, level
    return 0, 0


def plan_commands(request: MGRequest, series: str, seat_support: SeatSupport,
                  status: CarStatus) -> Tuple[List[Step], List[str]]:
    """Commands to send for a request, given the car's current status.

    Returns (steps, notes). Climate commands only work on a locked car, so the car is
    locked first unless it reports being locked. Seats follow the button: "Climate"
    turns seat heating off if it's on.
    """
    steps: List[Step] = []
    notes: List[str] = []

    if request.action == MGAction.ALL_OFF:
        if status.climate is None or status.climate > 0:
            steps.append(Step(StepKind.CLIMATE_OFF))
        # Cars without these features report 0, so only switch off what is reported on
        if status.rear_window_heat:
            steps.append(Step(StepKind.REAR_WINDOW, enable=False))
        if seat_support != SeatSupport.NONE and (status.seat_left or status.seat_right):
            steps.append(Step(StepKind.SEATS, left=0, right=0))
        return steps, notes

    if status.locked is not True:
        steps.append(Step(StepKind.LOCK))

    if request.windshield:
        steps.append(Step(StepKind.FRONT_DEFROST))
    else:
        low, high = temperature_range(series)
        celsius = min(max(request.temperature, low), high)
        if celsius != request.temperature:
            notes.append(f"{request.temperature}°C is outside this car's {low}-{high}°C range, using {celsius}°C")
        steps.append(Step(StepKind.CLIMATE_ON, temperature_idx=temperature_index(series, celsius)))

    if request.rear_defrost:
        steps.append(Step(StepKind.REAR_WINDOW, enable=True))

    target = target_seat_levels(request.action, seat_support)
    if seat_support == SeatSupport.NONE:
        if request.action in (MGAction.CLIMATE_DRIVER_SEAT, MGAction.CLIMATE_BOTH_SEATS):
            notes.append("this car has no remote seat heating, seats skipped")
    elif target != (status.seat_left or 0, status.seat_right or 0):
        steps.append(Step(StepKind.SEATS, left=target[0], right=target[1]))

    return steps, notes


def verify_result(request: MGRequest, seat_support: SeatSupport, status: CarStatus) -> List[str]:
    """Differences between what the request asked for and what the car reports afterwards."""
    problems: List[str] = []
    seats_known = seat_support != SeatSupport.NONE and status.seat_left is not None and status.seat_right is not None

    if request.action == MGAction.ALL_OFF:
        if status.climate:
            problems.append(f"climate still {climate_name(status.climate)}")
        if status.rear_window_heat:
            problems.append("rear defroster still on")
        if seats_known and (status.seat_left or status.seat_right):
            problems.append(f"seats still {status.seat_left}/{status.seat_right}")
        return problems

    if status.climate == 0:
        problems.append("car reports climate off")
    if request.rear_defrost and status.rear_window_heat == 0:
        problems.append("car reports rear defroster off")
    if seats_known:
        target = target_seat_levels(request.action, seat_support)
        if (status.seat_left, status.seat_right) != target:
            problems.append(f"seats {status.seat_left}/{status.seat_right}, expected {target[0]}/{target[1]}")
    return problems


def new_achieve_job(request: MGRequest, series: str, cabin_temp: Optional[int], started: datetime,
                    max_restarts: int) -> AchieveJob:
    """Job for a climate start; cabin_temp is the reading around the start (decides heating vs cooling)."""
    low, high = temperature_range(series)
    target = min(max(request.temperature, low), high)
    return AchieveJob(
        request=request, target=target,
        heating=cabin_temp is None or cabin_temp <= target,
        deadline=started + ACHIEVE_MAX,
        next_check=started + ACHIEVE_CHECK,
        max_restarts=max_restarts,
        cabin_temp=cabin_temp,
        cabin_time=started if cabin_temp is not None else None,
    )


def note_cabin_reading(job: AchieveJob, status: CarStatus, now: datetime) -> None:
    """Keep the latest cabin reading: the car may not report it once the climate has stopped."""
    if status.cabin_temp is not None:
        job.cabin_temp, job.cabin_time = status.cabin_temp, now


def achieve_reached(job: AchieveJob, cabin_temp: int) -> bool:
    if job.heating:
        return cabin_temp >= job.target - ACHIEVE_TOLERANCE
    return cabin_temp <= job.target + ACHIEVE_TOLERANCE


def achieve_step(job: AchieveJob, status: CarStatus, now: datetime) -> AchieveStep:
    """Decide at a check: done, wait for the running climate to stop, or start it again.

    Uses the car's current cabin reading, or the job's last one when the car sends none.
    An unlocked car means someone is at it, so the app stops instead of locking it again.
    With no restarts left it ends at once, without waiting for the last run to stop.
    """
    if status.locked is False:
        return AchieveStep.UNLOCKED
    cabin = status.cabin_temp if status.cabin_temp is not None else job.cabin_temp
    if cabin is not None and achieve_reached(job, cabin):
        return AchieveStep.REACHED
    if now >= job.deadline:
        return AchieveStep.TIMED_OUT
    if job.restarts >= job.max_restarts:
        return AchieveStep.NO_RESTARTS_LEFT
    if status.climate:
        return AchieveStep.WAIT
    if cabin is None:
        return AchieveStep.NO_READING
    return AchieveStep.RESTART


def achieve_restart_request(job: AchieveJob) -> MGRequest:
    """Restarts send the climate, plus the seats when the car reports them off (plan_commands skips
    seats already at their level). The defrosters did their job with the first start."""
    return MGRequest(job.request.action, job.request.temperature)


def is_remote_block(error_text: str) -> bool:
    """Whether a SAIC error is the car's "too frequent operations, use the physical key" refusal."""
    text = error_text.lower()
    return "too frequent" in text or "physical key" in text


def climate_name(value: Optional[int]) -> str:
    if value is None:
        return "--"
    return CLIMATE_STATES.get(value, f"unknown ({value})")


def describe_request(request: MGRequest) -> str:
    text = ACTION_LABELS[request.action]
    if request.action == MGAction.ALL_OFF:
        return text
    text += " (windshield defrost)" if request.windshield else f" at {request.temperature}°C"
    if request.rear_defrost:
        text += " + rear defroster"
    return text


def pick_vin(vins: Sequence[str], wanted: str = "") -> str:
    """The account's car: the only one, or the one whose VIN ends with `wanted`."""
    matches = [v for v in vins if v and v.upper().endswith(wanted.strip().upper())]
    if len(matches) != 1:
        hint = f"ending in '{wanted}'" if wanted else "(set MG_CAR_N_VIN to pick one)"
        raise ValueError(f"{len(matches)} cars on this account match {hint}")
    return matches[0]


def mask_vin(vin: Optional[str]) -> str:
    if not vin:
        return "?"
    return f"{vin[:3]}{'*' * (len(vin) - 7)}{vin[-4:]}"


def parse_time(raw: str) -> Tuple[int, int]:
    """'HH:MM' -> (hour, minute)."""
    hour_str, minute_str = raw.strip().split(":")
    hour, minute = int(hour_str), int(minute_str)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"time out of range: {raw!r}")
    return hour, minute


def parse_days(raw: str) -> FrozenSet[int]:
    """'Mon,Tue,Fri' -> {0, 1, 4}."""
    days = set()
    for name in raw.split(","):
        name = name.strip().capitalize()
        if not name:
            continue
        if name not in WEEKDAYS:
            raise ValueError(f"unknown day {name!r} (use {','.join(WEEKDAYS)})")
        days.add(WEEKDAYS.index(name))
    return frozenset(days)


def format_days(days: FrozenSet[int]) -> str:
    return ",".join(WEEKDAYS[d] for d in sorted(days))


def schedule_due(schedule: MGSchedule, now: datetime, last_success: Optional[date],
                 last_attempt: Optional[datetime]) -> bool:
    """Whether a schedule should run now.

    Runs once per day, from its time until SCHEDULE_GRACE later; a failed attempt is
    retried every SCHEDULE_RETRY inside that window.
    """
    if not schedule.enabled or now.weekday() not in schedule.days:
        return False
    start = now.replace(hour=schedule.hour, minute=schedule.minute, second=0, microsecond=0)
    if not (start <= now < start + SCHEDULE_GRACE):
        return False
    if last_success == now.date():
        return False
    return last_attempt is None or last_attempt < start or now - last_attempt >= SCHEDULE_RETRY


def next_run(schedule: MGSchedule, now: datetime, last_success: Optional[date] = None) -> Optional[datetime]:
    """When the schedule runs next (a time in the past means it is running in its grace window)."""
    if not schedule.enabled or not schedule.days:
        return None
    for offset in range(8):
        day = (now + timedelta(days=offset)).date()
        if day.weekday() not in schedule.days or day == last_success:
            continue
        start = datetime.combine(day, time(schedule.hour, schedule.minute))
        if start + SCHEDULE_GRACE > now:
            return start
    return None
