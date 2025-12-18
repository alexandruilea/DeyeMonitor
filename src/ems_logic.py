"""
EMS (Energy Management System) logic for controlling the heat pump.
"""

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from src.deye_inverter import InverterData
from src.tapo_manager import TapoManager


class LogicResult(Enum):
    """Result types for EMS logic decisions."""
    SAFETY_OVERLOAD = "SAFETY KILL: OVERLOAD"
    SAFETY_UNDERVOLTAGE = "SAFETY KILL: UNDERVOLTAGE"
    MANUAL_MODE = "MANUAL MODE ACTIVE"
    ERROR_SOC_CONFIG = "ERR: START SOC must be > STOP SOC"
    ERROR_VOLTAGE_CONFIG = "ERR: HIGH V must be > LOW V"
    ERROR_CRITICAL_CONFIG = "ERR: LOW V must be > CRITICAL V"
    OFF_UNDERVOLTAGE = "OFF: UNDER-VOLTAGE TIMER"
    OFF_BATTERY_LOW = "OFF: BATTERY LOW"
    RUNNING_OK = "Logic: Running - All OK"
    ON_HV_DUMP = "ON: HV DUMP"
    ON_EXPORT_DUMP = "ON: EXPORT DUMP"
    ON_AUTO_START = "ON: AUTO-START (SOC)"
    WAIT_HEADROOM = "Wait: Headroom insufficient"
    WAIT_CHARGING = "Wait: SOC Charging"
    TAPO_OFFLINE = "HP: TAPO OFFLINE"


@dataclass
class EMSParameters:
    """Current EMS parameters from UI."""
    start_soc: int
    stop_soc: int
    headroom: int
    phase_max: int
    safety_lv: float
    hv_threshold: float
    lv_threshold: float
    lv_delay: int
    target_phase: str  # "L1", "L2", or "L3"
    export_active: bool
    export_limit: int
    manual_mode: bool


@dataclass
class LogicState:
    """State for EMS logic processing."""
    lv_timer_start: Optional[float] = None
    
    def reset_lv_timer(self) -> None:
        """Reset the low-voltage timer."""
        self.lv_timer_start = None
    
    def start_lv_timer(self) -> None:
        """Start the low-voltage timer if not already started."""
        if self.lv_timer_start is None:
            self.lv_timer_start = time.time()
    
    def lv_timer_elapsed(self, delay: float) -> bool:
        """Check if low-voltage timer has exceeded the delay."""
        if self.lv_timer_start is None:
            return False
        return (time.time() - self.lv_timer_start) >= delay


class EMSLogic:
    """
    Energy Management System logic controller.
    Decides when to turn the heat pump on/off based on inverter data and parameters.
    """
    
    PHASE_MAP = {"L1": 0, "L2": 1, "L3": 2}
    
    def __init__(self, tapo: TapoManager):
        self.tapo = tapo
        self.state = LogicState()
        self._last_result: Optional[LogicResult] = None
        self._last_message: str = ""

    def process(self, data: InverterData, params: EMSParameters) -> tuple[LogicResult, str]:
        """
        Process EMS logic based on current inverter data and parameters.
        
        Args:
            data: Current inverter readings
            params: Current EMS parameters
            
        Returns:
            Tuple of (LogicResult, detail_message)
        """
        if not self.tapo.is_connected:
            return LogicResult.TAPO_OFFLINE, ""
        
        current_state = self.tapo.current_state
        
        # 1. HARD SAFETY CHECKS (always active, even in manual mode)
        if current_state:
            # Overload protection
            if any(w > params.phase_max for w in data.phase_loads):
                self.tapo.turn_off()
                return LogicResult.SAFETY_OVERLOAD, f"Max: {max(data.phase_loads)}W > {params.phase_max}W"
            
            # Critical undervoltage protection
            if any(v < params.safety_lv for v in data.voltages):
                self.tapo.turn_off()
                return LogicResult.SAFETY_UNDERVOLTAGE, f"<{params.safety_lv}V"
        
        # 2. MANUAL MODE - skip auto logic
        if params.manual_mode:
            return LogicResult.MANUAL_MODE, ""
        
        # 3. PARAMETER VALIDATION
        if params.start_soc <= params.stop_soc:
            return LogicResult.ERROR_SOC_CONFIG, ""
        
        if params.hv_threshold <= params.lv_threshold:
            return LogicResult.ERROR_VOLTAGE_CONFIG, ""
        
        if params.lv_threshold <= params.safety_lv:
            return LogicResult.ERROR_CRITICAL_CONFIG, ""
        
        # 4. AUTO LOGIC
        target_idx = self.PHASE_MAP.get(params.target_phase, 0)
        target_voltage = data.voltages[target_idx]
        export_watts = abs(data.grid_power) if data.grid_power < 0 else 0
        
        if current_state:
            # Running - check if we should turn off
            if target_voltage < params.lv_threshold:
                self.state.start_lv_timer()
                if self.state.lv_timer_elapsed(params.lv_delay):
                    self.tapo.turn_off()
                    return LogicResult.OFF_UNDERVOLTAGE, f"{target_voltage}V < {params.lv_threshold}V"
                remaining = params.lv_delay - (time.time() - self.state.lv_timer_start)
                return LogicResult.OFF_UNDERVOLTAGE, f"Timer: {remaining:.0f}s remaining"
            
            if data.soc <= params.stop_soc:
                self.tapo.turn_off()
                return LogicResult.OFF_BATTERY_LOW, f"SOC: {data.soc}%"
            
            # All good
            self.state.reset_lv_timer()
            return LogicResult.RUNNING_OK, ""
        
        else:
            # Standby - check if we should turn on
            
            # High voltage dump
            if target_voltage >= params.hv_threshold:
                self.tapo.turn_on()
                return LogicResult.ON_HV_DUMP, f"{target_voltage}V"
            
            # Export dump
            if params.export_active and export_watts >= params.export_limit:
                if self._has_headroom(data.phase_loads, params.phase_max, params.headroom):
                    self.tapo.turn_on()
                    return LogicResult.ON_EXPORT_DUMP, f"{export_watts}W"
            
            # SOC-based auto start
            if data.soc >= params.start_soc:
                if self._has_headroom(data.phase_loads, params.phase_max, params.headroom):
                    self.tapo.turn_on()
                    return LogicResult.ON_AUTO_START, f"SOC: {data.soc}%"
                return LogicResult.WAIT_HEADROOM, ""
            
            return LogicResult.WAIT_CHARGING, f"SOC: {data.soc}%"

    def _has_headroom(self, phase_loads: list, phase_max: int, headroom: int) -> bool:
        """Check if all phases have sufficient headroom."""
        return all((phase_max - w) >= headroom for w in phase_loads)

    @staticmethod
    def get_color_for_result(result: LogicResult) -> str:
        """Get the appropriate color for displaying the logic result."""
        colors = {
            LogicResult.SAFETY_OVERLOAD: "#E74C3C",
            LogicResult.SAFETY_UNDERVOLTAGE: "#E74C3C",
            LogicResult.MANUAL_MODE: "#E74C3C",
            LogicResult.ERROR_SOC_CONFIG: "#A569BD",
            LogicResult.ERROR_VOLTAGE_CONFIG: "#A569BD",
            LogicResult.ERROR_CRITICAL_CONFIG: "#A569BD",
            LogicResult.OFF_UNDERVOLTAGE: "#E74C3C",
            LogicResult.OFF_BATTERY_LOW: "gray",
            LogicResult.RUNNING_OK: "#2ECC71",
            LogicResult.ON_HV_DUMP: "cyan",
            LogicResult.ON_EXPORT_DUMP: "gold",
            LogicResult.ON_AUTO_START: "#2ECC71",
            LogicResult.WAIT_HEADROOM: "orange",
            LogicResult.WAIT_CHARGING: "gray",
            LogicResult.TAPO_OFFLINE: "gray",
        }
        return colors.get(result, "white")

    @staticmethod
    def is_error_result(result: LogicResult) -> bool:
        """Check if the result is a configuration error."""
        return result in (
            LogicResult.ERROR_SOC_CONFIG,
            LogicResult.ERROR_VOLTAGE_CONFIG,
            LogicResult.ERROR_CRITICAL_CONFIG,
        )
