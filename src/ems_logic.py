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
    SAFETY_UPS_OVERLOAD = "SAFETY KILL: UPS OVERLOAD"
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
    WAIT_LOW_VOLTAGE = "Wait: Low Voltage Block"
    WAIT_LV_RECOVERY = "Wait: LV Recovery Timer"
    WAIT_CHARGING = "Wait: SOC Charging"
    TAPO_OFFLINE = "HP: TAPO OFFLINE"


@dataclass
class EMSParameters:
    """Current EMS parameters from UI."""
    phase_max: int
    safety_lv: float
    manual_mode: bool
    max_ups_total_power: int = 16000  # Maximum UPS/Backup port output across all phases


@dataclass
class LogicState:
    """State for EMS logic processing."""
    lv_timers: dict[int, Optional[float]] = None  # outlet_id -> timer_start
    runtime_start: dict[int, Optional[float]] = None  # outlet_id -> runtime_start
    lv_shutdown: dict[int, bool] = None  # outlet_id -> was_shut_down_by_lv
    lv_recovery_timers: dict[int, Optional[float]] = None  # outlet_id -> recovery_timer_start
    
    def __post_init__(self):
        if self.lv_timers is None:
            self.lv_timers = {}
        if self.runtime_start is None:
            self.runtime_start = {}
        if self.lv_shutdown is None:
            self.lv_shutdown = {}
        if self.lv_recovery_timers is None:
            self.lv_recovery_timers = {}
    
    def reset_lv_timer(self, outlet_id: int) -> None:
        """Reset the low-voltage timer for an outlet."""
        self.lv_timers[outlet_id] = None
    
    def start_lv_timer(self, outlet_id: int) -> None:
        """Start the low-voltage timer for an outlet if not already started."""
        if outlet_id not in self.lv_timers or self.lv_timers[outlet_id] is None:
            self.lv_timers[outlet_id] = time.time()
    
    def lv_timer_elapsed(self, outlet_id: int, delay: float) -> bool:
        """Check if low-voltage timer has exceeded the delay for an outlet."""
        if outlet_id not in self.lv_timers or self.lv_timers[outlet_id] is None:
            return False
        return (time.time() - self.lv_timers[outlet_id]) >= delay
    
    def start_runtime(self, outlet_id: int) -> None:
        """Start tracking runtime for an outlet."""
        if outlet_id not in self.runtime_start or self.runtime_start[outlet_id] is None:
            self.runtime_start[outlet_id] = time.time()
    
    def reset_runtime(self, outlet_id: int) -> None:
        """Reset runtime tracking for an outlet."""
        self.runtime_start[outlet_id] = None
    
    def get_runtime(self, outlet_id: int) -> float:
        """Get current runtime in seconds for an outlet."""
        if outlet_id not in self.runtime_start or self.runtime_start[outlet_id] is None:
            return 0.0
        return time.time() - self.runtime_start[outlet_id]
    
    def mark_lv_shutdown(self, outlet_id: int) -> None:
        """Mark that an outlet was shut down due to low voltage."""
        self.lv_shutdown[outlet_id] = True
        self.lv_recovery_timers[outlet_id] = None
    
    def start_lv_recovery(self, outlet_id: int) -> None:
        """Start the low-voltage recovery timer for an outlet."""
        if outlet_id not in self.lv_recovery_timers or self.lv_recovery_timers[outlet_id] is None:
            self.lv_recovery_timers[outlet_id] = time.time()
    
    def reset_lv_recovery(self, outlet_id: int) -> None:
        """Reset the low-voltage recovery timer for an outlet."""
        self.lv_recovery_timers[outlet_id] = None
    
    def lv_recovery_elapsed(self, outlet_id: int, delay: float) -> bool:
        """Check if low-voltage recovery timer has exceeded the delay."""
        if outlet_id not in self.lv_recovery_timers or self.lv_recovery_timers[outlet_id] is None:
            return False
        return (time.time() - self.lv_recovery_timers[outlet_id]) >= delay
    
    def clear_lv_shutdown(self, outlet_id: int) -> None:
        """Clear the low-voltage shutdown flag for an outlet."""
        self.lv_shutdown[outlet_id] = False
        self.lv_recovery_timers[outlet_id] = None
    
    def is_lv_shutdown(self, outlet_id: int) -> bool:
        """Check if outlet is in low-voltage shutdown state."""
        return self.lv_shutdown.get(outlet_id, False)


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
        Implements cascade control for multiple outlets by priority.
        
        Args:
            data: Current inverter readings
            params: Current EMS parameters
            
        Returns:
            Tuple of (LogicResult, detail_message)
        """
        # Get all outlets
        outlets = self.tapo.get_all_outlets()
        if not outlets:
            return LogicResult.TAPO_OFFLINE, ""
        
        # Get only connected outlets for processing
        connected_outlets = {oid: o for oid, o in outlets.items() if o.is_connected}
        
        # If NO outlets are connected, show offline status
        if not connected_outlets:
            offline_names = [o.config.name for o in outlets.values()]
            return LogicResult.TAPO_OFFLINE, f"All offline: {', '.join(offline_names)}"
        
        # If some outlets are offline, just note it but continue processing
        offline_outlets = [o for o in outlets.values() if not o.is_connected]
        offline_status = f" ({len(offline_outlets)} offline)" if offline_outlets else ""
        
        # 1. HARD SAFETY CHECKS (always active, even in manual mode) - only for connected outlets
        for outlet_id, outlet in connected_outlets.items():
            if outlet.current_state:
                # UPS total overload protection - check sum of all UPS port outputs
                total_ups_power = sum(data.ups_loads)
                if total_ups_power > params.max_ups_total_power:
                    self.tapo.turn_off(outlet_id)
                    return LogicResult.SAFETY_UPS_OVERLOAD, f"{outlet.config.name}: Total UPS {total_ups_power}W > {params.max_ups_total_power}W"
                
                # Per-phase overload protection - check UPS port loads
                if any(w > params.phase_max for w in data.ups_loads):
                    self.tapo.turn_off(outlet_id)
                    return LogicResult.SAFETY_OVERLOAD, f"{outlet.config.name}: {max(data.ups_loads)}W > {params.phase_max}W"
                
                # Critical undervoltage protection
                if any(v < params.safety_lv for v in data.voltages):
                    self.tapo.turn_off(outlet_id)
                    return LogicResult.SAFETY_UNDERVOLTAGE, f"{outlet.config.name}: <{params.safety_lv}V"
        
        # 2. MANUAL MODE - skip auto logic
        if params.manual_mode:
            return LogicResult.MANUAL_MODE, ""
        
        # 3. PARAMETER VALIDATION (for each connected outlet's thresholds)
        for outlet in connected_outlets.values():
            if outlet.config.start_soc <= outlet.config.stop_soc:
                return LogicResult.ERROR_SOC_CONFIG, f"{outlet.config.name}"
            
            if outlet.config.hv_threshold <= outlet.config.lv_threshold:
                return LogicResult.ERROR_VOLTAGE_CONFIG, f"{outlet.config.name}"
            
            if outlet.config.lv_threshold <= params.safety_lv:
                return LogicResult.ERROR_CRITICAL_CONFIG, f"{outlet.config.name}"
        
        # 4. CASCADE CONTROL - process connected outlets by priority
        sorted_outlets = sorted(connected_outlets.values(), key=lambda o: o.config.priority)
        
        # Track runtime for running outlets
        for outlet in sorted_outlets:
            if outlet.current_state:
                self.state.start_runtime(outlet.config.outlet_id)
            else:
                self.state.reset_runtime(outlet.config.outlet_id)
        
        # First pass: Turn off outlets that violate their OFF conditions (reverse priority)
        for outlet in reversed(sorted_outlets):
            if not outlet.current_state:
                continue
            
            # Get outlet-specific parameters
            target_idx = self.PHASE_MAP.get(outlet.config.target_phase, 0)
            target_voltage = data.voltages[target_idx]
            
            # Check undervoltage timer
            if outlet.config.voltage_enabled and target_voltage < outlet.config.lv_threshold:
                self.state.start_lv_timer(outlet.config.outlet_id)
                if self.state.lv_timer_elapsed(outlet.config.outlet_id, outlet.config.lv_delay):
                    self.tapo.turn_off(outlet.config.outlet_id)
                    self.state.reset_runtime(outlet.config.outlet_id)
                    self.state.mark_lv_shutdown(outlet.config.outlet_id)  # Mark as LV shutdown
                    return LogicResult.OFF_UNDERVOLTAGE, f"{outlet.config.name}: {target_voltage}V < {outlet.config.lv_threshold}V"
                remaining = outlet.config.lv_delay - (time.time() - self.state.lv_timers[outlet.config.outlet_id])
                return LogicResult.OFF_UNDERVOLTAGE, f"{outlet.config.name}: Timer {remaining:.0f}s"
            else:
                self.state.reset_lv_timer(outlet.config.outlet_id)
            
            # Check SOC
            if outlet.config.soc_enabled and data.soc <= outlet.config.stop_soc:
                self.tapo.turn_off(outlet.config.outlet_id)
                self.state.reset_runtime(outlet.config.outlet_id)
                return LogicResult.OFF_BATTERY_LOW, f"{outlet.config.name}: SOC {data.soc}%"
        
        # Second pass: Try to turn on outlets by priority
        for outlet in sorted_outlets:
            if outlet.current_state:
                continue  # Already on
            
            # Check if priority 1 has been running for required time before allowing priority 2+
            if outlet.config.priority > 1:
                priority_1_outlets = [o for o in sorted_outlets if o.config.priority == 1]
                if priority_1_outlets:
                    priority_1_running = any(o.current_state for o in priority_1_outlets)
                    if priority_1_running:
                        priority_1_runtime = max(self.state.get_runtime(o.config.outlet_id) for o in priority_1_outlets if o.current_state)
                        if priority_1_runtime < outlet.config.runtime_delay:
                            continue  # Wait for priority 1 to run for configured time
                    else:
                        continue  # Priority 1 must be running first
            
            # Get outlet-specific parameters
            target_idx = self.PHASE_MAP.get(outlet.config.target_phase, 0)
            target_voltage = data.voltages[target_idx]
            export_watts = abs(data.grid_power) if data.grid_power < 0 else 0
            
            # LOW VOLTAGE RECOVERY CHECK: If outlet was shut down by low voltage, check recovery
            if self.state.is_lv_shutdown(outlet.config.outlet_id):
                if target_voltage >= outlet.config.lv_recovery_voltage:
                    # Voltage is above recovery threshold, start/continue recovery timer
                    self.state.start_lv_recovery(outlet.config.outlet_id)
                    if self.state.lv_recovery_elapsed(outlet.config.outlet_id, outlet.config.lv_recovery_delay):
                        # Recovery complete, clear shutdown flag
                        self.state.clear_lv_shutdown(outlet.config.outlet_id)
                    else:
                        # Still recovering
                        remaining = outlet.config.lv_recovery_delay - (time.time() - self.state.lv_recovery_timers[outlet.config.outlet_id])
                        return LogicResult.WAIT_LV_RECOVERY, f"{outlet.config.name}: {remaining:.0f}s ({target_voltage:.1f}V >= {outlet.config.lv_recovery_voltage}V)"
                else:
                    # Voltage still too low, reset recovery timer and show blocked status
                    self.state.reset_lv_recovery(outlet.config.outlet_id)
                    return LogicResult.WAIT_LV_RECOVERY, f"{outlet.config.name}: {target_voltage:.1f}V < {outlet.config.lv_recovery_voltage}V"
            
            # Calculate available headroom on the monitored phase
            available_headroom = params.phase_max - data.ups_loads[target_idx]
            
            # Check if we have enough headroom for this outlet
            if available_headroom < outlet.config.headroom:
                continue  # Not enough inverter capacity available
            
            # Check total UPS output limit
            total_ups_power = sum(data.ups_loads)
            if total_ups_power + outlet.config.headroom > params.max_ups_total_power:
                continue  # Would exceed total UPS capacity
            
            # VOLTAGE SAFETY CHECK: Do not turn on if voltage is below low voltage threshold
            # This prevents turning on during low voltage conditions regardless of other triggers
            if outlet.config.voltage_enabled and target_voltage < outlet.config.lv_threshold:
                # Check if any trigger would activate if voltage was OK
                would_activate = False
                if outlet.config.soc_enabled and data.soc >= outlet.config.start_soc:
                    would_activate = True
                if outlet.config.export_enabled and export_watts >= outlet.config.export_limit:
                    would_activate = True
                
                # Only show low voltage block if a trigger is actually trying to activate
                if would_activate:
                    return LogicResult.WAIT_LOW_VOLTAGE, f"{outlet.config.name}: {target_voltage:.1f}V < {outlet.config.lv_threshold}V (blocking SOC/Export)"
                continue  # Voltage too low, skip this outlet
            
            # THREE INDEPENDENT TRIGGERS FOR TURNING ON (any one can activate if enabled):
            
            # Trigger 1: High voltage dump (battery voltage too high) - if voltage trigger enabled
            if outlet.config.voltage_enabled and target_voltage >= outlet.config.hv_threshold:
                self.tapo.turn_on(outlet.config.outlet_id)
                return LogicResult.ON_HV_DUMP, f"{outlet.config.name}: {target_voltage}V"
            
            # Trigger 2: Export dump (too much power being exported) - if export trigger enabled
            if outlet.config.export_enabled and export_watts >= outlet.config.export_limit:
                self.tapo.turn_on(outlet.config.outlet_id)
                return LogicResult.ON_EXPORT_DUMP, f"{outlet.config.name}: {export_watts}W"
            
            # Trigger 3: SOC-based auto start (battery charged enough) - if SOC trigger enabled
            if outlet.config.soc_enabled and data.soc >= outlet.config.start_soc:
                self.tapo.turn_on(outlet.config.outlet_id)
                return LogicResult.ON_AUTO_START, f"{outlet.config.name}: SOC {data.soc}%"
        
        # All running outlets are OK
        if any(o.current_state for o in connected_outlets.values()):
            return LogicResult.RUNNING_OK, offline_status.strip()
        
        # All outlets off, waiting
        return LogicResult.WAIT_CHARGING, f"SOC: {data.soc}%{offline_status}"
    
    def _calculate_available_power(self, phase_loads: list, phase_max: int) -> int:
        """Calculate minimum available power across all phases."""
        return min(phase_max - load for load in phase_loads)

    @staticmethod
    def get_color_for_result(result: LogicResult) -> str:
        """Get the appropriate color for displaying the logic result."""
        colors = {
            LogicResult.SAFETY_OVERLOAD: "#E74C3C",
            LogicResult.SAFETY_UPS_OVERLOAD: "#E74C3C",
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
            LogicResult.WAIT_LOW_VOLTAGE: "orange",
            LogicResult.WAIT_LV_RECOVERY: "orange",
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
