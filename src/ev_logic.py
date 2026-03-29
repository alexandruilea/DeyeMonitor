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
    solar_ramp_down_delay: int = 5    # Minutes: step-down condition must persist this long before acting
    solar_amp_steps: tuple = (8, 16, 24, 32)  # Significant amp levels for ramp-down
    ev_first: bool = False            # True = include battery charge power as available surplus


@dataclass
class EVState:
    """Internal state tracking for rate-limiting and hysteresis."""
    last_decision_time: float = 0.0
    last_amps_sent: int = 0
    last_on_off_sent: Optional[bool] = None  # True=on, False=off
    was_charging: bool = False
    grid_pull_since: float = 0.0   # Timestamp when grid-import (no battery) started
    grid_pull_active: bool = False # True once we detect sustained grid import
    last_ramp_down_time: float = 0.0  # Timestamp of last solar ramp-down
    step_down_since: float = 0.0     # When step-down condition first became true
    step_down_target: int = 0        # The target amps when step-down condition started


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
        """Calculate target amps from surplus solar power.
        
        Uses grid export as the ground truth for surplus:
          surplus = current_charger_watts + grid_export
        
        When the charger is drawing power, that draw is already reflected
        in the grid meter — so we add it back to see the *available*
        solar for charging.  Grid export (negative grid_power) tells us
        how much extra is being pushed to the grid on top of that.
        
        This avoids estimating household loads entirely and works
        regardless of which phase the charger is on.
        """
        # grid_power: positive = importing, negative = exporting
        # Surplus = what the charger already draws + what's being exported
        # (or minus what's being imported). This reacts to grid import too,
        # so if grid goes +2000W we reduce the charger accordingly.
        avg_voltage = sum(data.voltages) / len(data.voltages) if data.voltages else 230.0
        charger_watts = charger_state.current_amps * avg_voltage if charger_state.is_charging else 0

        surplus_watts = max(0, int(charger_watts - data.grid_power))

        # EV-first mode: also count battery charge power as available for EV
        # battery_power < 0 means charging — that energy could go to the EV instead
        ev_first_extra = 0
        if settings.ev_first and data.battery_power < 0:
            ev_first_extra = abs(data.battery_power)
            surplus_watts += ev_first_extra

        target_amps = max(settings.min_amps, min(int(surplus_watts / avg_voltage), settings.max_amps))
        surplus_label = f"{surplus_watts}W surplus" + (f", +{ev_first_extra}W bat" if ev_first_extra else "")

        if target_amps < settings.min_amps:
            # Not enough solar to run at minimum amps
            if data.soc > settings.stop_soc:
                # Battery has enough charge — keep charging at min amps from battery
                target_amps = settings.min_amps
            else:
                # Battery too low to supplement — stop
                self._state.step_down_since = 0  # Reset sustain timer
                if charger_state.is_on:
                    self._send_off(now)
                    return EVResult.SOLAR_CHARGING, f"OFF ({surplus_label} < {settings.min_amps}A, SOC {data.soc}%)"
                return EVResult.SOLAR_CHARGING, f"Waiting for solar ({surplus_label}, SOC {data.soc}%)"
        else:
            target_amps = min(target_amps, settings.max_amps)

        if not charger_state.is_on:
            self._state.step_down_since = 0  # Reset sustain timer
            self._send_on(target_amps, now)
            return EVResult.SOLAR_CHARGING, f"ON {target_amps}A ({surplus_label})"

        # Already on — adjust amps if different
        if target_amps != charger_state.current_amps:
            current = charger_state.current_amps
            if target_amps > current:
                # Ramping UP — apply immediately (more solar available)
                self._state.step_down_since = 0  # Reset sustain timer
                self._send_amps(target_amps, now)
                return EVResult.SOLAR_CHARGING, f"↑ {target_amps}A ({surplus_label})"
            else:
                # Ramping DOWN — require sustained condition before acting
                sustain_seconds = settings.solar_ramp_down_delay * 60
                # Find the step target first (used for sustain tracking)
                steps = sorted(settings.solar_amp_steps)
                step_target = steps[0]
                for s in reversed(steps):
                    if s <= target_amps:
                        step_target = s
                        break
                step_target = max(settings.min_amps, step_target)

                # Check if step-down condition is sustained
                if self._state.step_down_since == 0 or self._state.step_down_target != step_target:
                    # Condition just started or target changed — start tracking
                    self._state.step_down_since = now
                    self._state.step_down_target = step_target
                    remaining = sustain_seconds
                    return EVResult.SOLAR_CHARGING, (
                        f"{current}A (holding, ↓{step_target}A in {remaining}s, "
                        f"{surplus_label})"
                    )

                elapsed = now - self._state.step_down_since
                if elapsed < sustain_seconds:
                    remaining = int(sustain_seconds - elapsed)
                    return EVResult.SOLAR_CHARGING, (
                        f"{current}A (holding, ↓{step_target}A in {remaining}s, "
                        f"{surplus_label})"
                    )

                # Sustained long enough — apply the ramp-down
                if step_target != current:
                    self._state.step_down_since = 0  # Reset for next step
                    self._send_amps(step_target, now)
                    self._state.last_ramp_down_time = now
                    return EVResult.SOLAR_CHARGING, f"↓ {step_target}A ({surplus_label})"
        else:
            # Target matches current — conditions are stable, reset sustain timer
            self._state.step_down_since = 0

        self._state.was_charging = True
        return EVResult.SOLAR_CHARGING, f"{charger_state.current_amps}A ({surplus_watts}W surplus)"

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
