"""
EV smart-charging logic.

Decides when to turn the charger on/off and what amperage to use based on:
  - Battery SOC thresholds (start dumping / stop)
  - Solar export surplus (solar-follow mode)
  - Configurable rate-limit (one change every N minutes)
"""

import time
import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from src.deye_inverter import InverterData
from src.tuya_charger import TuyaChargerManager, ChargerState


class EVResult(Enum):
    """Possible outcomes of the EV charging logic."""
    DISABLED = "EV Disabled"
    WAITING_COOLDOWN = "Cooldown"
    CHARGER_OFFLINE = "Charger Offline"
    SOC_TOO_LOW = "Battery SOC too low"
    SOC_BELOW_START = "Waiting for SOC"
    CHARGING = "Charging"
    BATTERY_PACED = "Battery Paced"
    SOLAR_CHARGING = "Solar Charging"
    GRID_CHARGING = "Grid Charging"
    GRID_PULL_STOP = "Grid Pull Stop"
    STOPPED = "Stopped"
    IDLE = "Idle"


@dataclass
class EVSettings:
    """Runtime EV charging settings (from UI)."""
    enabled: bool = False
    min_amps: int = 8
    max_amps: int = 32
    stop_soc: int = 20        # Stop charging EV if battery falls to this SOC
    start_soc: int = 80       # Only start dumping into EV above this SOC
    solar_mode: bool = False   # Scale amps based on solar export
    change_interval: int = 5   # Minutes between changes
    # Battery pacing — spread charging to finish by target hour
    battery_capacity_ah: int = 0    # 0 = pacing disabled
    charge_by_hour: int = 7         # Target completion hour (0-23, local time)
    grid_charge: bool = False       # Always charge while grid is available
    grid_charge_amps: int = 20        # Amps to use when grid-charging EV


@dataclass
class EVState:
    """Internal state tracking for rate-limiting and hysteresis."""
    last_decision_time: float = 0.0
    last_amps_sent: int = 0
    last_on_off_sent: Optional[bool] = None  # True=on, False=off
    was_charging: bool = False
    grid_pull_since: float = 0.0   # Timestamp when grid-import (no battery) started
    grid_pull_active: bool = False # True once we detect sustained grid import


class EVChargingLogic:
    """
    Stateless-ish logic engine for EV charging decisions.
    Call `process()` every inverter poll cycle.
    """

    def __init__(self, charger: TuyaChargerManager):
        self.charger = charger
        self._state = EVState()

    def process(self, data: InverterData, settings: EVSettings) -> Tuple[EVResult, str]:
        """
        Evaluate inverter data against EV settings and issue commands.

        Returns (result_enum, detail_string).
        """
        if not settings.enabled:
            return EVResult.DISABLED, ""

        charger_state = self.charger.get_state()
        if not charger_state.is_connected:
            return EVResult.CHARGER_OFFLINE, ""

        # ── Grid charge mode — charge at configured amps while grid available ─
        if settings.grid_charge and data.is_grid_connected:
            grid_a = settings.grid_charge_amps
            if not charger_state.is_on:
                self._send_on(grid_a, time.time())
                return EVResult.GRID_CHARGING, f"{grid_a}A (grid)"
            if charger_state.current_amps != grid_a:
                self._send_amps(grid_a, time.time())
                return EVResult.GRID_CHARGING, f"→ {grid_a}A (grid)"
            return EVResult.GRID_CHARGING, f"{grid_a}A (grid)"

        now = time.time()
        cooldown = settings.change_interval * 60
        time_since_last = now - self._state.last_decision_time
        within_cooldown = time_since_last < cooldown

        soc = data.soc

        # ── Grid-pull protection ─────────────────────────────────────
        # If the battery has stopped discharging and we're importing
        # from the grid for over 5 minutes, stop EV charging to avoid
        # running the house off the grid.
        importing_from_grid = data.grid_power > 50 and data.battery_power >= 0
        if importing_from_grid and charger_state.is_on:
            if self._state.grid_pull_since == 0:
                self._state.grid_pull_since = now
            elif now - self._state.grid_pull_since > 300:  # 5 minutes
                if not within_cooldown:
                    self._send_off(now)
                    return EVResult.GRID_PULL_STOP, (
                        f"Grid import {data.grid_power}W for "
                        f"{int((now - self._state.grid_pull_since) / 60)}min"
                    )
                remaining = int(cooldown - time_since_last)
                return EVResult.WAITING_COOLDOWN, f"Grid pull stop in {remaining}s"
        else:
            self._state.grid_pull_since = 0

        # ── Stop condition: battery too low ──────────────────────────
        if soc <= settings.stop_soc:
            if charger_state.is_on and not within_cooldown:
                self._send_off(now)
                return EVResult.SOC_TOO_LOW, f"SOC {soc}% ≤ {settings.stop_soc}%"
            if charger_state.is_on and within_cooldown:
                remaining = int(cooldown - time_since_last)
                return EVResult.WAITING_COOLDOWN, f"Stop in {remaining}s (SOC {soc}%)"
            return EVResult.SOC_TOO_LOW, f"SOC {soc}% ≤ {settings.stop_soc}%"

        # ── Start condition: battery not high enough yet ─────────────
        # If the charger is already on (e.g. user just enabled the feature
        # while the car was charging), treat it as "was_charging" so we
        # don't stop a session that's already in progress above stop_soc.
        if charger_state.is_on:
            self._state.was_charging = True

        if soc < settings.start_soc and not self._state.was_charging:
            if charger_state.is_on and not within_cooldown:
                self._send_off(now)
                return EVResult.SOC_BELOW_START, f"SOC {soc}% < {settings.start_soc}%"
            if not charger_state.is_on:
                return EVResult.SOC_BELOW_START, f"SOC {soc}% < {settings.start_soc}%"

        # Beyond this point SOC is adequate (above start or was already charging and above stop)

        if within_cooldown:
            remaining = int(cooldown - time_since_last)
            status = "Charging" if charger_state.is_on else "Idle"
            return EVResult.WAITING_COOLDOWN, f"{status}, next change in {remaining}s"

        # ── Solar-follow mode ────────────────────────────────────────
        if settings.solar_mode:
            return self._process_solar(data, settings, charger_state, now)

        # ── Fixed-rate mode (max amps while SOC allows) ──────────────
        target_amps, pacing_detail = self._calc_target_amps(data, settings)

        if not charger_state.is_on:
            self._send_on(target_amps, now)
            if pacing_detail:
                return EVResult.BATTERY_PACED, pacing_detail
            return EVResult.CHARGING, f"{target_amps}A (SOC {soc}%)"

        # Already on — ensure amps match
        if charger_state.current_amps != target_amps:
            self._send_amps(target_amps, now)
            if pacing_detail:
                return EVResult.BATTERY_PACED, pacing_detail
            return EVResult.CHARGING, f"→ {target_amps}A (SOC {soc}%)"

        self._state.was_charging = True
        if pacing_detail:
            return EVResult.BATTERY_PACED, pacing_detail
        return EVResult.CHARGING, f"{charger_state.current_amps}A (SOC {soc}%)"

    # ------------------------------------------------------------------
    # Battery pacing (nighttime)
    # ------------------------------------------------------------------

    def _calc_target_amps(self, data: InverterData,
                          settings: EVSettings) -> Tuple[int, str]:
        """Calculate target amps for fixed-rate mode.

        When PV production is low, spreads available battery energy over
        the hours remaining until the configured charge-by hour so the
        house battery isn't depleted prematurely.

        Returns (target_amps, detail).  detail is non-empty only when
        pacing is active.
        """
        pv_threshold = 200  # W — below this we consider it "nighttime"
        if (settings.battery_capacity_ah > 0
                and data.pv_power < pv_threshold):
            hours_left = self._hours_until(settings.charge_by_hour)
            if hours_left > 0.1:
                voltage = data.battery_voltage if data.battery_voltage > 0 else 48.0
                usable_pct = (data.soc - settings.stop_soc) / 100.0
                if usable_pct > 0:
                    usable_wh = usable_pct * settings.battery_capacity_ah * voltage
                    sustainable_watts = usable_wh / hours_left
                    paced = int(sustainable_watts / 230)
                    target = max(settings.min_amps, min(paced, settings.max_amps))
                    return target, (f"{target}A paced "
                                    f"({usable_wh:.0f}Wh / {hours_left:.1f}h "
                                    f"to {settings.charge_by_hour:02d}:00)")

        return settings.max_amps, ""

    @staticmethod
    def _hours_until(target_hour: int) -> float:
        """Return hours from now until the next occurrence of *target_hour*:00 local time."""
        from datetime import timedelta
        now = datetime.now()
        target = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return (target - now).total_seconds() / 3600.0

    # ------------------------------------------------------------------
    # Solar-follow helpers
    # ------------------------------------------------------------------

    def _process_solar(self, data: InverterData, settings: EVSettings,
                       charger_state: ChargerState, now: float
                       ) -> Tuple[EVResult, str]:
        """Calculate target amps from surplus solar export."""
        # Export power = negative grid_power means exporting
        export_watts = max(0, -data.grid_power)
        # Also add what the charger is already consuming (so we don't fight ourselves)
        if charger_state.is_on:
            # Rough estimate: amps × ~230V single-phase
            export_watts += charger_state.current_amps * 230

        target_amps = max(settings.min_amps, min(int(export_watts / 230), settings.max_amps))

        if target_amps < settings.min_amps:
            # Not enough solar to run at minimum amps from export alone
            if data.soc > settings.stop_soc:
                # Battery has enough charge — keep charging at min amps from battery
                target_amps = settings.min_amps
            else:
                # Battery too low to supplement — stop
                if charger_state.is_on:
                    self._send_off(now)
                    return EVResult.SOLAR_CHARGING, f"OFF (export {export_watts}W < {settings.min_amps}A, SOC {data.soc}%)"
                return EVResult.SOLAR_CHARGING, f"Waiting for solar ({export_watts}W, SOC {data.soc}%)"
        else:
            target_amps = min(target_amps, settings.max_amps)

        if not charger_state.is_on:
            self._send_on(target_amps, now)
            return EVResult.SOLAR_CHARGING, f"ON {target_amps}A ({export_watts}W export)"

        # Already on — adjust amps if different
        if target_amps != charger_state.current_amps:
            self._send_amps(target_amps, now)
            return EVResult.SOLAR_CHARGING, f"→ {target_amps}A ({export_watts}W export)"

        self._state.was_charging = True
        return EVResult.SOLAR_CHARGING, f"{charger_state.current_amps}A ({export_watts}W export)"

    # ------------------------------------------------------------------
    # Command helpers
    # ------------------------------------------------------------------

    def _send_on(self, amps: int, now: float) -> None:
        self.charger.set_amps(amps)
        self.charger.turn_on()
        self._state.last_decision_time = now
        self._state.last_amps_sent = amps
        self._state.last_on_off_sent = True
        self._state.was_charging = True

    def _send_off(self, now: float) -> None:
        self.charger.turn_off()
        self._state.last_decision_time = now
        self._state.last_on_off_sent = False
        self._state.was_charging = False

    def _send_amps(self, amps: int, now: float) -> None:
        self.charger.set_amps(amps)
        self._state.last_decision_time = now
        self._state.last_amps_sent = amps
        self._state.was_charging = True
