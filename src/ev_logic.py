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
    min_amps_1p: int = 20     # Minimum amps when charging on single phase (e.g. 20A = ~4.6 kW)
    min_amps_3p: int = 8      # Minimum amps when charging on three phase (e.g. 8A = ~5.5 kW)
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
    boost: bool = False               # Manual boost: bypass start_soc threshold
    phases: str = "auto"              # Phase mode: "auto", "1", or "3"
    auto_default_phases: int = 3      # Default phase assumption in auto mode before detection (3 or 1)

    def get_min_amps(self, phases: int = 1) -> int:
        """Return the effective minimum amps for the current phase configuration."""
        return self.min_amps_3p if phases == 3 else self.min_amps_1p


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
    detected_phases: int = 3         # 1 or 3 (detected or initial default, defaults to 3)
    detected_single_phase_idx: int = 0  # 0=L1, 1=L2, 2=L3 (which phase the 1P EV is on)
    phase_detect_streak_3p: int = 0  # Consecutive samples indicating 3-phase
    phase_detect_streak_1p: int = 0  # Consecutive samples indicating 1-phase
    last_boost: bool = False         # Track boost toggle state to bypass cooldown on change


class EVChargingLogic:
    """
    Stateless-ish logic engine for EV charging decisions.
    Call `process()` every inverter poll cycle.
    """

    def __init__(self, charger: TuyaChargerManager, auto_default_phases: int = 3):
        self.charger = charger
        self._state = EVState(detected_phases=auto_default_phases)
        self.active_phases: int = auto_default_phases
        self.single_phase_idx: int = 0

    def _get_effective_voltage(self, data: InverterData, phases: int, single_phase_idx: int = 0) -> float:
        """Return effective voltage for power and amperage calculations.

        For 1-phase: measured voltage of the active phase (data.voltages[single_phase_idx]).
        For 3-phase: sum of all 3 measured phase voltages (L1 + L2 + L3).
        Falls back safely to 230V (1-phase) or 690V (3-phase) if voltages are missing.
        """
        if phases == 3:
            if data.voltages and len(data.voltages) >= 3 and all(v > 0 for v in data.voltages[:3]):
                return sum(data.voltages[:3])
            v_ref = data.voltages[0] if (data.voltages and len(data.voltages) > 0 and data.voltages[0] > 0) else 230.0
            return v_ref * 3.0

        idx = max(0, min(2, single_phase_idx))
        if data.voltages and len(data.voltages) > idx and data.voltages[idx] > 0:
            return data.voltages[idx]
        return 230.0

    def _resolve_active_phases(self, data: InverterData, settings: EVSettings,
                               charger_state: ChargerState) -> Tuple[int, int]:
        """Resolve whether to calculate as 1-phase or 3-phase, and which phase for 1-phase.

        Returns (active_phases, single_phase_idx) where active_phases is 1 or 3,
        and single_phase_idx is 0 (L1), 1 (L2), or 2 (L3).
        """
        mode = (settings.phases or "auto").lower()
        is_manual_1p = mode in ("1", "1p", "single")
        is_manual_3p = mode in ("3", "3p", "three")

        if charger_state.is_charging:
            i_amps = charger_state.current_amps if charger_state.current_amps >= 6 else 6

            # Check 1: Direct telemetry from charger if available
            c_phases = getattr(charger_state, "phase_currents", (0.0, 0.0, 0.0))
            if any(c > 1.0 for c in c_phases):
                active_list = [i for i, c in enumerate(c_phases) if c > 1.5]
            else:
                # Check 2: Inverter total load per phase
                active_list = []
                for i in range(min(3, len(data.total_loads), len(data.voltages))):
                    v_i = data.voltages[i] if data.voltages[i] > 0 else 230.0
                    thresh = max(500.0, 0.45 * i_amps * v_i)
                    if data.total_loads[i] >= thresh:
                        active_list.append(i)

            # If any 2 (or all 3) phases have current on them -> 3-phase EV
            if len(active_list) >= 2:
                self._state.phase_detect_streak_3p += 1
                self._state.phase_detect_streak_1p = 0
                if self._state.phase_detect_streak_3p >= 3:
                    if self._state.detected_phases != 3:
                        self._state.detected_phases = 3
                        self._state.last_decision_time = 0.0  # Allow immediate adaptation to 3P min amps
                        print(f"[EV] Auto-detected 3-phase EV ({len(active_list)} active phases: {[f'L{i+1}' for i in active_list]} at {i_amps}A)")
            # If only 1 phase has current on it -> 1-phase EV on that specific phase
            elif len(active_list) == 1:
                active_idx = active_list[0]
                self._state.phase_detect_streak_1p += 1
                self._state.phase_detect_streak_3p = 0
                if self._state.phase_detect_streak_1p >= 3:
                    if self._state.detected_phases != 1 or self._state.detected_single_phase_idx != active_idx:
                        self._state.detected_phases = 1
                        self._state.detected_single_phase_idx = active_idx
                        self._state.last_decision_time = 0.0  # Allow immediate adaptation to 1P min amps
                        print(f"[EV] Auto-detected 1-phase EV on L{active_idx + 1} at {i_amps}A (adapting immediately)")
        else:
            # Not actively drawing current: if in auto mode, restore the configured default phase assumption
            if not is_manual_1p and not is_manual_3p:
                self._state.detected_phases = settings.auto_default_phases
                self._state.phase_detect_streak_3p = 0
                self._state.phase_detect_streak_1p = 0

        if is_manual_3p:
            active_p = 3
        elif is_manual_1p:
            active_p = 1
        else:
            active_p = self._state.detected_phases

        return active_p, self._state.detected_single_phase_idx

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

        active_phases, single_phase_idx = self._resolve_active_phases(data, settings, charger_state)
        self.active_phases = active_phases
        self.single_phase_idx = single_phase_idx
        phase_label = "3P" if active_phases == 3 else f"1P-L{single_phase_idx + 1}"

        # ── Grid charge mode — charge at configured amps while grid available ─
        if settings.grid_charge and data.is_grid_connected:
            grid_a = settings.grid_charge_amps
            if not charger_state.is_on:
                self._send_on(grid_a, time.time())
                return EVResult.GRID_CHARGING, f"{grid_a}A ({phase_label}, grid)"
            if charger_state.current_amps != grid_a:
                self._send_amps(grid_a, time.time())
                return EVResult.GRID_CHARGING, f"→ {grid_a}A ({phase_label}, grid)"
            return EVResult.GRID_CHARGING, f"{grid_a}A ({phase_label}, grid)"

        now = time.time()

        # Handle boost button toggling: bypass cooldown and ensure immediate action
        if settings.boost != self._state.last_boost:
            self._state.last_boost = settings.boost
            self._state.last_decision_time = 0.0
            self._state.grid_pull_since = 0.0
            if settings.boost:
                self._state.was_charging = True

        cooldown = settings.change_interval * 60
        time_since_last = now - self._state.last_decision_time
        within_cooldown = time_since_last < cooldown

        soc = data.soc

        # ── Grid-pull protection ─────────────────────────────────────
        # If the battery has stopped discharging and we're importing
        # from the grid for over 5 minutes, stop EV charging to avoid
        # running the house off the grid. Bypassed when Boost is ON.
        importing_from_grid = data.grid_power > 50 and data.battery_power >= 0
        if not settings.boost and importing_from_grid and charger_state.is_on:
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
        # Bypassed when Boost is ON (continues regardless of battery level)
        if not settings.boost and soc <= settings.stop_soc:
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
        if charger_state.is_on or settings.boost:
            self._state.was_charging = True

        if not settings.boost and soc < settings.start_soc and not self._state.was_charging:
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

        # ── No car drawing → don't churn the charger's flash ─────────
        # If the charger is ON but no car is actually charging (unplugged
        # or finished session), skip recomputing/writing target amps every
        # cycle. We still respond instantly when the car plugs in because
        # is_charging flips True and the cooldown is not reset here.
        if charger_state.is_on and not charger_state.is_charging:
            self._state.step_down_since = 0
            self._state.was_charging = False
            if (settings.phases or "auto").lower() == "auto":
                self._state.detected_phases = settings.auto_default_phases
                self._state.phase_detect_streak_1p = 0
                self._state.phase_detect_streak_3p = 0
            return EVResult.IDLE, f"Ready {charger_state.current_amps}A ({phase_label}, no car)"

        # ── Solar-follow mode ────────────────────────────────────────
        if settings.solar_mode:
            return self._process_solar(data, settings, charger_state, now, active_phases, phase_label)

        # ── Fixed-rate mode (max amps while SOC allows) ──────────────
        target_amps, pacing_detail = self._calc_target_amps(data, settings, active_phases, phase_label)

        if not charger_state.is_on:
            self._send_on(target_amps, now)
            if pacing_detail:
                return EVResult.BATTERY_PACED, pacing_detail
            return EVResult.CHARGING, f"{target_amps}A ({phase_label}, SOC {soc}%)"

        # Already on — ensure amps match
        if charger_state.current_amps != target_amps:
            self._send_amps(target_amps, now)
            if pacing_detail:
                return EVResult.BATTERY_PACED, pacing_detail
            return EVResult.CHARGING, f"→ {target_amps}A ({phase_label}, SOC {soc}%)"

        self._state.was_charging = True
        if pacing_detail:
            return EVResult.BATTERY_PACED, pacing_detail
        return EVResult.CHARGING, f"{charger_state.current_amps}A ({phase_label}, SOC {soc}%)"

    # ------------------------------------------------------------------
    # Battery pacing (nighttime)
    # ------------------------------------------------------------------

    def _calc_target_amps(self, data: InverterData,
                          settings: EVSettings,
                          active_phases: int = 1,
                          phase_label: str = "1P") -> Tuple[int, str]:
        """Calculate target amps for fixed-rate mode.

        When PV production is low, spreads available battery energy over
        the hours remaining until the configured charge-by hour so the
        house battery isn't depleted prematurely.

        Returns (target_amps, detail).  detail is non-empty only when
        pacing is active.
        """
        min_a = settings.get_min_amps(active_phases)
        if settings.boost:
            return settings.max_amps, f"{settings.max_amps}A ({phase_label}, BOOST)"

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
                    eff_voltage = self._get_effective_voltage(data, active_phases, self.single_phase_idx)
                    paced = int(sustainable_watts / eff_voltage)
                    target = max(min_a, min(paced, settings.max_amps))
                    return target, (f"{target}A paced ({phase_label}, "
                                    f"{usable_wh:.0f}Wh / {hours_left:.1f}h "
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
                       charger_state: ChargerState, now: float,
                       active_phases: int = 1,
                       phase_label: str = "1P") -> Tuple[EVResult, str]:
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
        eff_voltage = self._get_effective_voltage(data, active_phases, self.single_phase_idx)
        charger_watts = int(charger_state.current_amps * eff_voltage) if charger_state.is_charging else 0

        # Subtract battery discharge (positive battery_power) — that power
        # comes from the battery, not solar, and must not count as surplus.
        battery_draw = max(0, data.battery_power)

        # Solar surplus cannot exist if there is no solar PV generation
        ev_first_extra = 0
        if data.pv_power <= 50:
            surplus_watts = 0
        else:
            surplus_watts = max(0, int(charger_watts - data.grid_power - battery_draw))
            if settings.ev_first and data.battery_power < 0:
                ev_first_extra = abs(data.battery_power)
                surplus_watts += ev_first_extra
            surplus_watts = min(surplus_watts, data.pv_power + ev_first_extra)

        min_a = settings.get_min_amps(active_phases)
        raw_amps = int(surplus_watts / eff_voltage)
        if surplus_watts > 0:
            surplus_label = f"{surplus_watts}W surplus ({phase_label})" + (f", +{ev_first_extra}W bat" if ev_first_extra else "")
        else:
            surplus_label = f"0W surplus ({phase_label})"

        if raw_amps < min_a:
            # Not enough solar to run at minimum amps
            if data.soc > settings.stop_soc or settings.boost:
                # Battery has enough charge (or boost enabled) — keep charging at min amps from battery/grid
                target_amps = min_a
            else:
                # Battery too low to supplement — stop
                self._state.step_down_since = 0  # Reset sustain timer
                if charger_state.is_on:
                    self._send_off(now)
                    return EVResult.SOLAR_CHARGING, f"OFF ({surplus_label} < {min_a}A, SOC {data.soc}%)"
                return EVResult.SOLAR_CHARGING, f"Waiting for solar ({surplus_label}, SOC {data.soc}%)"
        else:
            target_amps = min(raw_amps, settings.max_amps)

        if not charger_state.is_on:
            self._state.step_down_since = 0  # Reset sustain timer
            self._send_on(target_amps, now)
            boost_prefix = "BOOST | " if settings.boost else ""
            if raw_amps < min_a:
                on_desc = f"{boost_prefix}ON {target_amps}A ({phase_label}, min rate, SOC {data.soc}%)"
            else:
                on_desc = f"{boost_prefix}ON {target_amps}A ({surplus_label})"
            return EVResult.SOLAR_CHARGING, on_desc

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
                # Include min_a in available steps so ramp-down never gets stuck above min_a
                steps = sorted(set(settings.solar_amp_steps + (min_a,)))
                step_target = min_a
                for s in reversed(steps):
                    if s <= target_amps:
                        step_target = s
                        break
                step_target = max(min_a, step_target)

                # Check if step-down condition is sustained
                if self._state.step_down_since == 0 or self._state.step_down_target != step_target:
                    # Condition just started or target changed — start tracking
                    self._state.step_down_since = now
                    self._state.step_down_target = step_target
                    remaining = sustain_seconds
                    status_desc = f"min rate, SOC {data.soc}%" if raw_amps < min_a else surplus_label
                    return EVResult.SOLAR_CHARGING, (
                        f"{current}A (holding, ↓{step_target}A in {remaining}s, "
                        f"{status_desc})"
                    )

                elapsed = now - self._state.step_down_since
                if elapsed < sustain_seconds:
                    remaining = int(sustain_seconds - elapsed)
                    status_desc = f"min rate, SOC {data.soc}%" if raw_amps < min_a else surplus_label
                    return EVResult.SOLAR_CHARGING, (
                        f"{current}A (holding, ↓{step_target}A in {remaining}s, "
                        f"{status_desc})"
                    )

                # Sustained long enough — apply the ramp-down
                if step_target != current:
                    self._state.step_down_since = 0  # Reset for next step
                    self._send_amps(step_target, now)
                    self._state.last_ramp_down_time = now
                    down_desc = f"min rate, SOC {data.soc}%" if raw_amps < min_a else surplus_label
                    return EVResult.SOLAR_CHARGING, f"↓ {step_target}A ({down_desc})"
        else:
            # Target matches current — conditions are stable, reset sustain timer
            self._state.step_down_since = 0

        self._state.was_charging = True
        boost_tag = "BOOST, " if settings.boost else ""
        if raw_amps < min_a:
            if surplus_watts > 0:
                final_detail = f"{charger_state.current_amps}A ({phase_label}, {boost_tag}{surplus_watts}W solar, SOC {data.soc}%)"
            else:
                final_detail = f"{charger_state.current_amps}A ({phase_label}, {boost_tag}min rate, SOC {data.soc}%)"
        else:
            final_detail = f"{charger_state.current_amps}A ({phase_label}, {boost_tag}{surplus_watts}W surplus)"
        return EVResult.SOLAR_CHARGING, final_detail

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
