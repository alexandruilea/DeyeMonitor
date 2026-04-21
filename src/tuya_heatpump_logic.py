"""
Heat pump logic for temperature-based scheduling with solar override.

Instead of toggling the relay directly, sets target temperature and hysteresis
on the Tuya thermostat so the device firmware handles relay control instantly.

Decision flow:
1. Solar override active + enough PV production → target = very high (force ON)
2. Active schedule slot → target = max_temp, hysteresis = max_temp - min_temp
3. No schedule → target = very low (force OFF)
"""

import datetime
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List

from src.tuya_heatpump import TuyaHeatpumpManager
from src.config import HeatpumpScheduleSlot, TuyaHeatpumpConfig


class HeatpumpResult(Enum):
    """Result types for heat pump logic decisions."""
    DISABLED = "HP Disabled"
    OFFLINE = "HP Offline"
    NO_TEMP = "HP: No Temperature"
    NO_SCHEDULE = "HP: No Active Schedule"
    SCHEDULE_ACTIVE = "HP: Schedule Active"
    SOLAR_OVERRIDE = "HP: Solar Override"
    SOC_OVERRIDE = "HP: SOC Override"
    HV_OVERRIDE = "HP: HV Override"
    LV_SHUTDOWN = "HP: LV Shutdown"
    SOC_LOW = "HP: SOC Low"
    BOOST = "HP: Boost"
    STANDBY = "HP: Standby"


@dataclass
class HeatpumpSettings:
    """Current heat pump settings from UI."""
    enabled: bool = False
    schedules: List[HeatpumpScheduleSlot] = field(default_factory=list)
    solar_override_enabled: bool = True
    solar_override_production_min: int = 0   # Min PV production watts to trigger ON (0 = disabled)
    solar_override_export_min: int = 0       # Min grid export watts to trigger ON (0 = disabled)
    solar_override_cloudy_production_min: int = 0  # Cloudy-day PV production threshold (0 = disabled)
    solar_override_hp_power: int = 3000    # HP rated power (W)
    solar_override_delay: int = 60         # Seconds export/import must sustain before solar override activates/deactivates
    # SOC-based override
    soc_on_threshold: int = 90             # SOC >= this → force ON
    soc_off_threshold: int = 40            # SOC <= this → force OFF
    # Voltage-based overrides
    hv_threshold: float = 252.0            # High-voltage dump ON
    hv_off_threshold: float = 245.0        # HV hysteresis OFF
    lv_threshold: float = 210.0            # Low-voltage shutdown
    lv_recovery_voltage: float = 220.0     # Voltage must exceed this for LV recovery
    lv_recovery_delay: int = 300           # Seconds voltage must stay above recovery level
    phase_change_delay: int = 10           # Seconds before voltage triggers activate
    boost: bool = False                    # Manual boost: bypass SOC threshold


class HeatpumpLogic:
    """
    Sets target temperature and hysteresis on the thermostat based on
    schedule slots and solar override conditions.
    """

    def __init__(self, manager: TuyaHeatpumpManager, config: TuyaHeatpumpConfig):
        self.manager = manager
        self.config = config
        self._last_target: Optional[float] = None
        self._last_hyst: Optional[float] = None
        self._solar_override_active: bool = False
        self._hv_override_active: bool = False
        self._soc_override_active: bool = False
        self._soc_low_lockout: bool = False
        self._lv_shutdown_active: bool = False
        self._lv_timer_start: Optional[float] = None
        self._lv_recovery_timer_start: Optional[float] = None
        self._hv_timer_start: Optional[float] = None
        self._hv_off_timer_start: Optional[float] = None
        self._soc_low_timer_start: Optional[float] = None
        self._soc_off_timer_start: Optional[float] = None
        self._solar_on_timer_start: Optional[float] = None
        self._solar_off_timer_start: Optional[float] = None

    @staticmethod
    def _get_active_schedule(schedules: List[HeatpumpScheduleSlot]) -> Optional[HeatpumpScheduleSlot]:
        """Find the currently active schedule slot based on time of day."""
        now = datetime.datetime.now()
        current_minutes = now.hour * 60 + now.minute

        for slot in schedules:
            start = slot.start_hour * 60 + slot.start_min
            end = slot.end_hour * 60 + slot.end_min

            if start <= end:
                if start <= current_minutes < end:
                    return slot
            else:
                # Overnight slot
                if current_minutes >= start or current_minutes < end:
                    return slot
        return None

    def _apply_target(self, target: float, hysteresis: float) -> None:
        """Send target and hysteresis to device only if they actually changed."""
        if target != self._last_target:
            self.manager.set_target_temp(target)
            self._last_target = target
        if hysteresis != self._last_hyst:
            self.manager.set_hysteresis(hysteresis)
            self._last_hyst = hysteresis

    def _reset_overrides(self) -> None:
        """Reset all override state flags."""
        self._solar_override_active = False
        self._hv_override_active = False
        self._soc_override_active = False
        self._soc_low_lockout = False
        self._lv_shutdown_active = False
        self._lv_timer_start = None
        self._lv_recovery_timer_start = None
        self._hv_timer_start = None
        self._hv_off_timer_start = None
        self._soc_low_timer_start = None
        self._soc_off_timer_start = None
        self._solar_on_timer_start = None
        self._solar_off_timer_start = None

    def process(self, settings: HeatpumpSettings, grid_power: int, soc: int,
                voltages: Optional[List[float]] = None, pv_power: int = 0,
                is_bad_day: bool = False) -> tuple:
        """
        Process heat pump logic.

        Priority order (highest first):
        1. Low-voltage shutdown (force OFF after delay)
        2. High-voltage dump (force ON immediately)
        3. SOC low → force OFF
        4. Solar production override (evaluated early, can boost SOC target)
        5. SOC high → schedule temp (or solar target if solar active)
        6. Solar override (standalone)
        7. Temperature schedule
        8. Standby (no schedule)

        Args:
            settings: Current settings from UI
            grid_power: Current grid power (negative = exporting)
            soc: Current battery state of charge (0-100)
            voltages: Phase voltages [L1, L2, L3] or None
            pv_power: Current solar PV production (W)

        Returns:
            Tuple of (HeatpumpResult, detail_string)
        """
        if not settings.enabled:
            self._reset_overrides()
            return HeatpumpResult.DISABLED, ""

        state = self.manager.get_state()

        if not state.is_connected:
            self._reset_overrides()
            return HeatpumpResult.OFFLINE, ""

        temperature = state.temperature
        if temperature is None:
            return HeatpumpResult.NO_TEMP, "Waiting for sensor"

        # Resolve phase voltages for monitoring
        if voltages and len(voltages) >= 3:
            phase = self.config.target_phase.upper()
            if phase == "ANY":
                v_lv = min(voltages)       # LV triggers on the lowest phase
                v_hv = max(voltages)       # HV triggers on the highest phase
                v_str = f"{voltages[0]:.1f}/{voltages[1]:.1f}/{voltages[2]:.1f}V"
            else:
                idx = {"L1": 0, "L2": 1, "L3": 2}.get(phase, 0)
                v_lv = v_hv = voltages[idx]
                v_str = f"{voltages[idx]:.1f}V"
        else:
            v_lv = v_hv = None
            v_str = "--V"

        active_slot = self._get_active_schedule(settings.schedules)
        export_watts = abs(grid_power) if grid_power < 0 else 0
        grid_import = grid_power if grid_power > 0 else 0
        dev_target = f"Dev {state.target_temp:.0f}°C" if state.target_temp is not None else "Dev --°C"
        override_target = self.config.solar_override_target
        standby_target = self.config.standby_target

        # ── 1. Low-voltage shutdown (with delay + recovery) ─────
        if v_lv is not None:
            if not self._lv_shutdown_active:
                # Trigger: voltage below LV threshold for phase_change_delay
                if v_lv < settings.lv_threshold:
                    if self._lv_timer_start is None:
                        self._lv_timer_start = time.time()
                    elapsed = time.time() - self._lv_timer_start
                    if elapsed >= settings.phase_change_delay:
                        self._solar_override_active = False
                        self._hv_override_active = False
                        self._soc_override_active = False
                        self._lv_shutdown_active = True
                        self._lv_timer_start = None
                else:
                    self._lv_timer_start = None
            else:
                # Recovery: voltage above recovery threshold for recovery_delay
                if v_lv >= settings.lv_recovery_voltage:
                    if self._lv_recovery_timer_start is None:
                        self._lv_recovery_timer_start = time.time()
                    if (time.time() - self._lv_recovery_timer_start) >= settings.lv_recovery_delay:
                        self._lv_shutdown_active = False
                        self._lv_recovery_timer_start = None
                else:
                    self._lv_recovery_timer_start = None

            if self._lv_shutdown_active:
                countdown = ""
                if self._lv_recovery_timer_start is not None:
                    remaining = settings.lv_recovery_delay - (time.time() - self._lv_recovery_timer_start)
                    countdown = f" | Recovery in {remaining:.0f}s"
                self._apply_target(standby_target, 0.5)
                return HeatpumpResult.LV_SHUTDOWN, (
                    f"{temperature:.1f}°C | {dev_target} | {v_str} | "
                    f"min {v_lv:.1f}V (recover > {settings.lv_recovery_voltage}V) | SOC {soc}% | Target→{standby_target}°C{countdown}"
                )

        # ── 2. High-voltage dump (with hysteresis + delay) ──────
        if v_hv is not None:
            if not self._hv_override_active:
                self._hv_off_timer_start = None
                if v_hv >= settings.hv_threshold:
                    if self._hv_timer_start is None:
                        self._hv_timer_start = time.time()
                    if (time.time() - self._hv_timer_start) >= settings.phase_change_delay:
                        self._hv_override_active = True
                else:
                    self._hv_timer_start = None
            else:
                self._hv_timer_start = None
                if v_hv < settings.hv_off_threshold:
                    if self._hv_off_timer_start is None:
                        self._hv_off_timer_start = time.time()
                    if (time.time() - self._hv_off_timer_start) >= settings.phase_change_delay:
                        self._hv_override_active = False
                        self._hv_off_timer_start = None
                        # Fall through to schedule/SOC — don't force standby
                else:
                    self._hv_off_timer_start = None

            if self._hv_override_active:
                countdown = ""
                if self._hv_off_timer_start is not None:
                    remaining = settings.phase_change_delay - (time.time() - self._hv_off_timer_start)
                    countdown = f" | OFF in {remaining:.0f}s"
                self._apply_target(override_target, 0.5)
                return HeatpumpResult.HV_OVERRIDE, (
                    f"{temperature:.1f}°C | {dev_target} | {v_str} | "
                    f"max {v_hv:.1f}V ≥ {settings.hv_threshold}V | SOC {soc}% | Target→{override_target}°C{countdown}"
                )

        # ── 3. SOC low → force OFF (with delay, then lockout) ─────
        # When SOC drops to soc_off_threshold, start a timer.
        # After delay seconds, force OFF and lock out schedule
        # until SOC recovers to soc_on_threshold.
        if soc <= settings.soc_off_threshold:
            if self._soc_low_timer_start is None:
                self._soc_low_timer_start = time.time()
            elapsed = time.time() - self._soc_low_timer_start
            if elapsed >= settings.solar_override_delay:
                self._solar_override_active = False
                self._soc_override_active = False
                self._soc_low_lockout = True
                self._apply_target(standby_target, 0.5)
                return HeatpumpResult.SOC_LOW, (
                    f"{temperature:.1f}°C | {dev_target} | {v_str} | "
                    f"SOC {soc}% ≤ {settings.soc_off_threshold}% | Target→{standby_target}°C"
                )
            else:
                # Still counting down — show pending shutdown but don't force OFF yet
                remaining = settings.solar_override_delay - elapsed
                return HeatpumpResult.SOC_LOW, (
                    f"{temperature:.1f}°C | {dev_target} | {v_str} | "
                    f"SOC {soc}% ≤ {settings.soc_off_threshold}% | OFF in {remaining:.0f}s"
                )
        else:
            self._soc_low_timer_start = None

        # SOC low lockout: stay off until SOC reaches soc_on_threshold
        # Boost mode bypasses the lockout (SOC already confirmed > soc_off_threshold above)
        if self._soc_low_lockout:
            if soc >= settings.soc_on_threshold or settings.boost:
                self._soc_low_lockout = False
            else:
                self._apply_target(standby_target, 0.5)
                return HeatpumpResult.SOC_LOW, (
                    f"{temperature:.1f}°C | {dev_target} | {v_str} | "
                    f"SOC {soc}% < {settings.soc_on_threshold}% (locked) | Target→{standby_target}°C"
                )

        # ── 4. Evaluate solar override conditions ─────────────
        # Evaluated before SOC/schedule returns so solar can boost the target
        # when SOC override is also active.
        # On bad weather days (detected by sunset module), use the lower
        # cloudy-day production threshold so the HP runs on moderate PV.
        if not settings.solar_override_enabled:
            # Clear stale state immediately when the feature is toggled off
            self._solar_override_active = False
            self._solar_on_timer_start = None
            self._solar_off_timer_start = None
        else:
            if not self._solar_override_active:
                self._solar_off_timer_start = None
                # Determine effective production threshold
                prod_threshold = settings.solar_override_production_min
                if is_bad_day and settings.solar_override_cloudy_production_min > 0:
                    prod_threshold = settings.solar_override_cloudy_production_min
                # Require sustained production OR export for delay seconds before activating
                production_met = prod_threshold > 0 and pv_power >= prod_threshold
                export_met = settings.solar_override_export_min > 0 and export_watts >= settings.solar_override_export_min
                if production_met or export_met:
                    if self._solar_on_timer_start is None:
                        self._solar_on_timer_start = time.time()
                    if (time.time() - self._solar_on_timer_start) >= settings.solar_override_delay:
                        self._solar_override_active = True
                        self._solar_on_timer_start = None
                else:
                    self._solar_on_timer_start = None
            else:
                self._solar_on_timer_start = None
                # Stop if grid import exceeds 50% of HP power OR solar conditions
                # are no longer met (sustained for delay).
                # SOC-based stop is handled by priority 3 (SOC low → force OFF)
                max_grid_import_solar = settings.solar_override_hp_power / 2
                # Re-evaluate original trigger conditions
                prod_threshold = settings.solar_override_production_min
                if is_bad_day and settings.solar_override_cloudy_production_min > 0:
                    prod_threshold = settings.solar_override_cloudy_production_min
                production_still_met = prod_threshold > 0 and pv_power >= prod_threshold
                export_still_met = settings.solar_override_export_min > 0 and export_watts >= settings.solar_override_export_min
                should_stop = grid_import > max_grid_import_solar or (not production_still_met and not export_still_met)
                if should_stop:
                    if self._solar_off_timer_start is None:
                        self._solar_off_timer_start = time.time()
                    if (time.time() - self._solar_off_timer_start) >= settings.solar_override_delay:
                        self._solar_override_active = False
                        self._solar_off_timer_start = None
                else:
                    self._solar_off_timer_start = None

        # ── 5. SOC high / Boost → apply schedule (or solar override target) ────
        # Once active, stays ON until SOC drops to soc_off_threshold (priority 3)
        # or grid import exceeds 50% of HP power (sustained for delay).
        # If solar override is also active, uses the higher solar target instead.
        # Boost mode: bypass SOC threshold, still respect SOC low and LV shutdown.
        max_grid_import = settings.solar_override_hp_power / 2
        boost_active = settings.boost and soc > settings.soc_off_threshold and not self._soc_low_lockout
        if not self._soc_override_active:
            self._soc_off_timer_start = None
            if soc >= settings.soc_on_threshold:
                self._soc_override_active = True
        else:
            if grid_import > max_grid_import:
                if self._soc_off_timer_start is None:
                    self._soc_off_timer_start = time.time()
                if (time.time() - self._soc_off_timer_start) >= settings.solar_override_delay:
                    self._soc_override_active = False
                    self._soc_off_timer_start = None
            else:
                self._soc_off_timer_start = None

        if self._soc_override_active or boost_active:
            # If solar override is also active, boost to solar target
            if self._solar_override_active:
                countdown = ""
                if self._solar_off_timer_start is not None:
                    remaining = settings.solar_override_delay - (time.time() - self._solar_off_timer_start)
                    countdown = f" | OFF in {remaining:.0f}s"
                self._apply_target(override_target, 0.5)
                result = HeatpumpResult.BOOST if boost_active and not self._soc_override_active else HeatpumpResult.SOLAR_OVERRIDE
                return result, (
                    f"{temperature:.1f}°C | {dev_target} | {v_str} | "
                    f"PV {pv_power}W | Export {export_watts}W | Grid {grid_import}W | SOC {soc}% | Target\u2192{override_target}\u00b0C{countdown}"
                )
            countdown = ""
            if self._soc_off_timer_start is not None:
                remaining = settings.solar_override_delay - (time.time() - self._soc_off_timer_start)
                countdown = f" | OFF in {remaining:.0f}s"
            # Use schedule interval temp, not override (80°C)
            if active_slot is not None:
                soc_target = active_slot.max_temp
                soc_hyst = active_slot.max_temp - active_slot.min_temp
            else:
                soc_target = standby_target
                soc_hyst = 0.5
            self._apply_target(soc_target, soc_hyst)
            result = HeatpumpResult.BOOST if boost_active and not self._soc_override_active else HeatpumpResult.SOC_OVERRIDE
            boost_tag = "BOOST | " if boost_active and not self._soc_override_active else ""
            return result, (
                f"{temperature:.1f}°C | {dev_target} | {v_str} | "
                f"{boost_tag}SOC {soc}% (ON ≥ {settings.soc_on_threshold}%) | Grid {grid_import}W | Target→{soc_target}°C{countdown}"
            )

        # ── 6. Solar override (standalone, SOC not active) ──────
        if self._solar_override_active:
            countdown = ""
            if self._solar_off_timer_start is not None:
                remaining = settings.solar_override_delay - (time.time() - self._solar_off_timer_start)
                countdown = f" | OFF in {remaining:.0f}s"
            self._apply_target(override_target, 0.5)
            return HeatpumpResult.SOLAR_OVERRIDE, (
                f"{temperature:.1f}°C | {dev_target} | {v_str} | "
                f"PV {pv_power}W | Export {export_watts}W | Grid {grid_import}W | SOC {soc}% | Target→{override_target}°C{countdown}"
            )

        # ── 7. Temperature schedule ─────────────────────────────
        if active_slot is not None:
            min_temp = active_slot.min_temp
            max_temp = active_slot.max_temp
            hyst = max_temp - min_temp
            slot_str = (f"{active_slot.start_hour:02d}:{active_slot.start_min:02d}-"
                        f"{active_slot.end_hour:02d}:{active_slot.end_min:02d}")
            self._apply_target(max_temp, hyst)
            return HeatpumpResult.SCHEDULE_ACTIVE, (
                f"{temperature:.1f}°C | {dev_target} | {v_str} | "
                f"Target {max_temp}°C ±{hyst}°C [{slot_str}]"
            )

        # ── 8. No schedule → standby ────────────────────────────
        self._apply_target(standby_target, 0.5)
        return HeatpumpResult.NO_SCHEDULE, f"{temperature:.1f}°C | {dev_target} | {v_str}"
