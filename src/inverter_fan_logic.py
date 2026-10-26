"""
Inverter cooling fan control: hysteresis on the inverter AC side (heat sink) temperature.

The fan turns ON when the temperature rises above `on_temp` and turns OFF only
once it drops below `off_temp`. Between the two thresholds the current state is
kept, which prevents the fan from flapping around a single set point.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


@dataclass
class FanSettings:
    enabled: bool
    on_temp: float
    off_temp: float


class FanResult(Enum):
    DISABLED = "Disabled"
    OFFLINE = "Fan outlet offline"
    NO_DATA = "No temperature reading"
    INVALID_CONFIG = "Invalid thresholds"
    TURN_ON = "Cooling (turning ON)"
    TURN_OFF = "Cooled down (turning OFF)"
    RUNNING = "Cooling"
    IDLE = "Idle"


def decide_fan_state(
    settings: FanSettings,
    temperature: Optional[float],
    fan_is_on: bool,
    fan_connected: bool = True,
) -> Tuple[Optional[bool], FanResult, str]:
    """
    Decide the desired fan state.

    Returns (desired_state, result, detail). desired_state is None when no
    command should be sent (disabled, offline, missing data, invalid config).
    """
    if not settings.enabled:
        return None, FanResult.DISABLED, ""
    if settings.on_temp <= settings.off_temp:
        return None, FanResult.INVALID_CONFIG, f"ON {settings.on_temp:g}°C must be above OFF {settings.off_temp:g}°C"
    if not fan_connected:
        return None, FanResult.OFFLINE, ""
    if temperature is None:
        return None, FanResult.NO_DATA, ""

    if temperature > settings.on_temp:
        desired = True
    elif temperature < settings.off_temp:
        desired = False
    else:
        desired = fan_is_on  # Inside the hysteresis band: keep current state

    if desired and not fan_is_on:
        return True, FanResult.TURN_ON, f"{temperature:.1f}°C > {settings.on_temp:g}°C"
    if not desired and fan_is_on:
        return False, FanResult.TURN_OFF, f"{temperature:.1f}°C < {settings.off_temp:g}°C"
    if desired:
        return True, FanResult.RUNNING, f"{temperature:.1f}°C, OFF below {settings.off_temp:g}°C"
    return False, FanResult.IDLE, f"{temperature:.1f}°C, ON above {settings.on_temp:g}°C"
