"""
Deye Inverter EMS Pro - Main Application

A professional energy management system for Deye inverters with Tapo smart plug integration.
"""

import time
import threading
import customtkinter as ctk

from src.config import ems_defaults, deye_config
from src.deye_inverter import DeyeInverter, InverterData
from src.tapo_manager import TapoManager
from src.ems_logic import EMSLogic, EMSParameters, LogicResult
from src.ui_components import (
    PhaseDisplay,
    SettingsPanel,
    StatusHeader,
    HeatPumpButton,
    OutletButton,
    OutletSettingsPanel,
    ErrorLogViewer,
    TimeSchedulePanel,
    OverpowerProtectionPanel,
)


class DeyeApp(ctk.CTk):
    """Main application window for Deye Inverter EMS Pro."""
    
    POLL_INTERVAL = 1.2  # seconds
    
    def __init__(self):
        super().__init__()
        self.title("Deye Inverter EMS Pro")
        self.geometry("1300x1400")
        ctk.set_appearance_mode("dark")
        
        # Initialize hardware managers
        self.inverter = DeyeInverter()
        self.tapo = TapoManager(error_callback=self._log_error)
        self.ems = EMSLogic(self.tapo)
        
        # Configuration variables
        self._init_config_variables()
        
        # Track pending outlet state changes per outlet
        self._pending_outlet_states = {}  # outlet_id -> pending_state
        
        # Overpower protection state
        self._protection_boost_amps = 0  # Current boost amount added on top of schedule
        self._protection_active = False  # Whether protection is currently boosting
        self._last_protection_adjustment = 0.0  # Timestamp of last charge adjustment
        
        # Track if main loop has started (for safe error logging from threads)
        self._main_loop_started = False
        
        # Setup UI
        self._setup_ui()
        
        # Read initial charge settings from inverter
        self._read_initial_charge_settings()
        
        # Start data polling thread
        self._running = True
        self._poll_thread = threading.Thread(target=self._data_loop, daemon=True)
        self._poll_thread.start()

    def _init_config_variables(self) -> None:
        """Initialize configuration variables with default values."""
        self.cfg = {
            "phase_max": ctk.StringVar(value=str(ems_defaults.phase_max)),
            "safety_lv": ctk.StringVar(value=str(ems_defaults.safety_lv)),
            "max_ups_total_power": ctk.StringVar(value=str(ems_defaults.max_ups_total_power)),
            "manual_mode": ctk.BooleanVar(value=False),
        }
        
        # Per-outlet configuration variables
        self.outlet_cfg = {}
        outlets = self.tapo.get_all_outlets()
        for outlet_id, outlet in outlets.items():
            self.outlet_cfg[outlet_id] = {
                "start_soc": ctk.StringVar(value=str(outlet.config.start_soc)),
                "stop_soc": ctk.StringVar(value=str(outlet.config.stop_soc)),
                "power": ctk.StringVar(value=str(outlet.config.power)),
                "hv_threshold": ctk.StringVar(value=str(outlet.config.hv_threshold)),
                "lv_threshold": ctk.StringVar(value=str(outlet.config.lv_threshold)),
                "lv_delay": ctk.StringVar(value=str(outlet.config.lv_delay)),
                "lv_recovery_voltage": ctk.StringVar(value=str(outlet.config.lv_recovery_voltage)),
                "lv_recovery_delay": ctk.StringVar(value=str(outlet.config.lv_recovery_delay)),
                "headroom": ctk.StringVar(value=str(outlet.config.headroom)),
                "target_phase": ctk.StringVar(value=outlet.config.target_phase),
                "soc_enabled": ctk.BooleanVar(value=outlet.config.soc_enabled),
                "voltage_enabled": ctk.BooleanVar(value=outlet.config.voltage_enabled),
                "export_enabled": ctk.BooleanVar(value=outlet.config.export_enabled),
                "export_limit": ctk.StringVar(value=str(outlet.config.export_limit)),
                "off_grid_mode": ctk.BooleanVar(value=outlet.config.off_grid_mode),
                "on_grid_always_on": ctk.BooleanVar(value=outlet.config.on_grid_always_on),
            }

    def _setup_ui(self) -> None:
        """Setup the user interface."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # Main scrollable frame
        self.scrollable = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scrollable.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        self.scrollable.grid_columnconfigure((0, 1, 2), weight=1)
        
        # Status header
        self.header = StatusHeader(self.scrollable)
        self.header.grid(row=0, column=0, columnspan=3, sticky="ew")
        
        # Phase displays
        self.phases = {}
        for i, name in enumerate(["L1", "L2", "L3"]):
            phase = PhaseDisplay(self.scrollable, name)
            phase.grid(row=i + 2, column=0, columnspan=3, padx=20, pady=5, sticky="ew")
            self.phases[name] = phase
        
        # Stats row (Total UPS power + Load consumption + Current charge settings)
        stats_frame = ctk.CTkFrame(self.scrollable, fg_color="transparent")
        stats_frame.grid(row=5, column=0, columnspan=3, pady=5, sticky="ew")
        stats_frame.grid_columnconfigure((0, 1, 2), weight=1)
        
        # Total UPS power display
        self.lbl_total_power = ctk.CTkLabel(
            stats_frame,
            text="Total UPS: 0 W / 16000 W",
            font=("Roboto", 14, "bold"),
            text_color="#FFA500"
        )
        self.lbl_total_power.grid(row=0, column=0, padx=10, sticky="w")
        
        # Total load consumption per phase display
        self.lbl_load_consumption = ctk.CTkLabel(
            stats_frame,
            text="L1: 0W L2: 0W L3: 0W",
            font=("Roboto", 14, "bold"),
            text_color="#9B59B6"
        )
        self.lbl_load_consumption.grid(row=0, column=1, padx=10)
        
        # Current charge settings display
        self.lbl_charge_settings = ctk.CTkLabel(
            stats_frame,
            text="Charge Limits: Max: --A | Grid: --A | Discharge: --A",
            font=("Roboto", 14, "bold"),
            text_color="#3498DB"
        )
        self.lbl_charge_settings.grid(row=0, column=2, padx=10, sticky="e")
        
        # Time Schedule Panel (for charge scheduling)
        self.schedule_panel = TimeSchedulePanel(
            self.scrollable,
            on_schedule_change=self._on_schedule_change
        )
        self.schedule_panel.grid(row=6, column=0, columnspan=3, padx=20, pady=10, sticky="ew")
        
        # Overpower Protection Panel
        self.protection_panel = OverpowerProtectionPanel(
            self.scrollable,
            on_settings_change=self._on_protection_change
        )
        self.protection_panel.grid(row=7, column=0, columnspan=3, padx=20, pady=10, sticky="ew")
        
        # Track last applied schedule to avoid redundant writes
        self._last_applied_schedule = None
        
        # Track current charge settings for display
        self._current_max_charge = None
        self._current_grid_charge = None
        self._current_max_discharge = None
        
        # Global Settings panel
        self.settings = SettingsPanel(
            self.scrollable,
            self.cfg,
            on_manual_toggle=self._on_manual_toggle
        )
        self.settings.grid(row=8, column=0, columnspan=3, padx=20, pady=10, sticky="nsew")
        
        # Outlet-specific settings panels
        self.outlet_settings = {}
        outlets = self.tapo.get_all_outlets()
        sorted_outlets = sorted(outlets.values(), key=lambda o: o.config.priority)
        
        current_row = 9
        for outlet in sorted_outlets:
            outlet_panel = OutletSettingsPanel(
                self.scrollable,
                outlet_name=outlet.config.name,
                variables=self.outlet_cfg[outlet.config.outlet_id]
            )
            outlet_panel.grid(row=current_row, column=0, columnspan=3, padx=20, pady=10, sticky="nsew")
            self.outlet_settings[outlet.config.outlet_id] = outlet_panel
            current_row += 1
        
        # Outlet control buttons (dynamically created from config)
        self.outlet_buttons = {}
        for outlet in sorted_outlets:
            btn = OutletButton(
                self.scrollable,
                outlet_name=outlet.config.name,
                power=outlet.config.power,
                command=lambda oid=outlet.config.outlet_id: self._on_outlet_toggle(oid)
            )
            btn.grid(row=current_row, column=0, columnspan=3, pady=5, padx=40, sticky="ew")
            self.outlet_buttons[outlet.config.outlet_id] = btn
            current_row += 1
        
        # Logic status label
        self.lbl_logic = ctk.CTkLabel(
            self.scrollable, text="Logic: Initializing",
            font=("Roboto", 13),
            text_color="gray"
        )
        self.lbl_logic.grid(row=current_row, column=0, columnspan=3, pady=5)
        current_row += 1
        
        # Error log viewer
        self.log_viewer = ErrorLogViewer(self.scrollable)
        self.log_viewer.grid(row=current_row, column=0, columnspan=3, sticky="nsew", padx=20, pady=10)

    def _read_initial_charge_settings(self) -> None:
        """Read and display initial charge settings from the inverter."""
        print("[INIT] Reading initial charge settings from inverter...")
        max_charge, grid_charge, max_discharge = self.inverter.read_battery_settings()
        
        if max_charge is not None and grid_charge is not None and max_discharge is not None:
            print(f"[INIT] Current settings: Max={max_charge}A, Grid={grid_charge}A, Discharge={max_discharge}A")
            self._current_max_charge = max_charge
            self._current_grid_charge = grid_charge
            self._current_max_discharge = max_discharge
            self._update_charge_display()
        else:
            print("[INIT] Could not read charge settings from inverter")
        
        # Read max sell power for protection panel
        max_sell = self.inverter.read_max_sell_power()
        if max_sell is not None:
            print(f"[INIT] Max sell power from inverter: {max_sell}W")
            self.after(0, lambda: self.protection_panel.set_max_sell_power(max_sell))
    
    def _log_error(self, message: str) -> None:
        """Log error message to UI (called from background thread)."""
        try:
            if self._main_loop_started:
                self.after(0, lambda: self.log_viewer.add_log(message))
            else:
                # Main loop not started yet, just print to console
                print(f"[LOG] {message}")
        except RuntimeError:
            # Fallback if after() fails
            print(f"[LOG] {message}")

    def _on_schedule_change(self) -> None:
        """Handle schedule enable/disable toggle."""
        # Reset last applied schedule so it will be re-evaluated
        self._last_applied_schedule = None
        
        # If schedule was just disabled, apply defaults in background thread
        if not self.schedule_panel.is_enabled():
            defaults = self.schedule_panel.get_default_values()
            print(f"[SCHEDULE] Disabled - applying defaults: Max={defaults['max_charge_amps']}A, Grid={defaults['grid_charge_amps']}A, Discharge={defaults['max_discharge_amps']}A")
            
            def apply_defaults():
                success1 = True
                success2 = True
                success3 = True
                
                # Only write max charge if it changed
                if self._current_max_charge != defaults["max_charge_amps"]:
                    success1 = self.inverter.set_max_charge_current(defaults["max_charge_amps"])
                    if success1:
                        self._current_max_charge = defaults["max_charge_amps"]
                
                # Only write grid charge if it changed
                if self._current_grid_charge != defaults["grid_charge_amps"]:
                    success2 = self.inverter.set_grid_charge_current(defaults["grid_charge_amps"])
                    if success2:
                        self._current_grid_charge = defaults["grid_charge_amps"]
                
                # Only write max discharge if it changed
                if self._current_max_discharge != defaults["max_discharge_amps"]:
                    success3 = self.inverter.set_max_discharge_current(defaults["max_discharge_amps"])
                    if success3:
                        self._current_max_discharge = defaults["max_discharge_amps"]
                
                if success1 and success2 and success3:
                    self.after(0, self._update_charge_display)
                self._log_error(f"Schedule disabled - defaults applied: Max={defaults['max_charge_amps']}A, Grid={defaults['grid_charge_amps']}A, Discharge={defaults['max_discharge_amps']}A")
            
            threading.Thread(target=apply_defaults, daemon=True).start()

    def _process_schedule(self) -> None:
        """Process time-based charge schedule and apply settings if needed."""
        if not self.schedule_panel.is_enabled():
            # Schedule is disabled, nothing to do
            self.after(0, lambda: self.schedule_panel.update_status(None))
            return
        
        active_schedule = self.schedule_panel.get_active_schedule()
        
        # Update UI status
        self.after(0, lambda: self.schedule_panel.update_status(active_schedule))
        
        # Determine what settings to apply
        if active_schedule is not None:
            target_max = active_schedule["max_charge_amps"]
            target_grid = active_schedule["grid_charge_amps"]
            target_discharge = active_schedule["max_discharge_amps"]
            schedule_key = (
                active_schedule["start_hour"],
                active_schedule["start_min"],
                active_schedule["end_hour"],
                active_schedule["end_min"],
                target_max,
                target_grid,
                target_discharge,
            )
        else:
            # No active time slot - use defaults
            defaults = self.schedule_panel.get_default_values()
            target_max = defaults["max_charge_amps"]
            target_grid = defaults["grid_charge_amps"]
            target_discharge = defaults["max_discharge_amps"]
            schedule_key = ("default", target_max, target_grid, target_discharge)
        
        # Only apply if settings changed
        if self._last_applied_schedule == schedule_key:
            return
        
        # Apply the settings - only write values that actually changed
        if active_schedule:
            print(f"[SCHEDULE] Applying slot: Max={target_max}A, Grid={target_grid}A, Discharge={target_discharge}A")
        else:
            print(f"[SCHEDULE] No active slot - applying defaults: Max={target_max}A, Grid={target_grid}A, Discharge={target_discharge}A")
        
        success1 = True
        success2 = True
        success3 = True
        
        # Only write max charge if it changed
        if self._current_max_charge != target_max:
            success1 = self.inverter.set_max_charge_current(target_max)
            if success1:
                self._current_max_charge = target_max
        
        # Only write grid charge if it changed
        if self._current_grid_charge != target_grid:
            success2 = self.inverter.set_grid_charge_current(target_grid)
            if success2:
                self._current_grid_charge = target_grid
        
        # Only write max discharge if it changed
        if self._current_max_discharge != target_discharge:
            success3 = self.inverter.set_max_discharge_current(target_discharge)
            if success3:
                self._current_max_discharge = target_discharge
        
        if success1 and success2 and success3:
            self._last_applied_schedule = schedule_key
            self._update_charge_display()
            if active_schedule:
                self._log_error(f"Schedule applied: Max={target_max}A, Grid={target_grid}A, Discharge={target_discharge}A")
            else:
                self._log_error(f"Defaults applied: Max={target_max}A, Grid={target_grid}A, Discharge={target_discharge}A")
        else:
            self._log_error(f"Failed to apply charge settings")

    def _update_charge_display(self) -> None:
        """Update the charge settings display label."""
        max_str = f"{self._current_max_charge}A" if self._current_max_charge is not None else "--A"
        grid_str = f"{self._current_grid_charge}A" if self._current_grid_charge is not None else "--A"
        discharge_str = f"{self._current_max_discharge}A" if self._current_max_discharge is not None else "--A"
        self.after(0, lambda: self.lbl_charge_settings.configure(
            text=f"Charge Limits: Max: {max_str} | Grid: {grid_str} | Discharge: {discharge_str}"
        ))

    def _on_protection_change(self) -> None:
        """Handle protection settings change."""
        if not self.protection_panel.is_enabled():
            # Reset boost when protection is disabled
            if self._protection_boost_amps > 0:
                self._protection_boost_amps = 0
                self._protection_active = False
                # Force schedule to re-apply base values
                self._last_applied_schedule = None
                print("[PROTECTION] Disabled - clearing boost")

    def _get_base_charge_amps(self) -> int:
        """Get the base charge amps from schedule or defaults (before protection boost)."""
        if self.schedule_panel.is_enabled():
            active_schedule = self.schedule_panel.get_active_schedule()
            if active_schedule:
                return active_schedule["max_charge_amps"]
        # Use defaults
        defaults = self.schedule_panel.get_default_values()
        return defaults["max_charge_amps"]

    def _process_overpower_protection(self, data) -> None:
        """
        Process overpower protection logic.
        
        Increases charging to absorb excess power when:
        - Export power exceeds threshold percentage of max sell power
        - Any phase voltage exceeds warning threshold
        
        Decreases charging (removes boost) when:
        - Export power drops below recovery threshold
        - All phase voltages are below recovery threshold
        
        Respects adjustment_interval to allow system to stabilize between changes.
        """
        if not self.protection_panel.is_enabled():
            self.after(0, lambda: self.protection_panel.update_protection_state(False, 0))
            return
        
        settings = self.protection_panel.get_settings()
        
        # Get current export power (negative grid_power = exporting)
        export_power = abs(min(0, data.grid_power))  # Only count exports (negative values)
        max_sell = settings["max_sell_power"]
        max_voltage = max(data.voltages)
        
        # Update state display
        self.after(0, lambda: self.protection_panel.update_state_display(
            export_power, max_sell, max_voltage
        ))
        
        # Check if enough time has passed since last adjustment
        adjustment_interval = settings.get("adjustment_interval", 10)
        current_time = time.time()
        if current_time - self._last_protection_adjustment < adjustment_interval:
            # Not enough time passed, just update display and return
            self.after(0, lambda: self.protection_panel.update_protection_state(
                self._protection_active, self._protection_boost_amps
            ))
            return
        
        # Calculate thresholds
        power_warning_threshold = max_sell * settings["power_threshold_pct"] / 100
        power_recovery_threshold = max_sell * settings["recovery_threshold_pct"] / 100
        voltage_warning = settings["voltage_warning"]
        voltage_recovery = settings["voltage_recovery"]
        charge_step = settings["charge_step"]
        
        # Determine if we need to boost or reduce
        needs_boost = (export_power >= power_warning_threshold) or (max_voltage >= voltage_warning)
        can_recover = (export_power < power_recovery_threshold) and (max_voltage < voltage_recovery)
        
        base_charge = self._get_base_charge_amps()
        max_charge_limit = deye_config.max_charge_amps_limit
        
        if needs_boost:
            # Increase boost by one step
            new_boost = min(self._protection_boost_amps + charge_step, max_charge_limit - base_charge)
            if new_boost != self._protection_boost_amps:
                self._protection_boost_amps = new_boost
                self._protection_active = True
                self._last_protection_adjustment = current_time
                target_charge = base_charge + self._protection_boost_amps
                
                print(f"[PROTECTION] BOOST: Base={base_charge}A + Boost={self._protection_boost_amps}A = {target_charge}A "
                      f"(Export={export_power}W/{max_sell}W, MaxV={max_voltage:.1f}V)")
                
                if self.inverter.set_max_charge_current(target_charge):
                    self._current_max_charge = target_charge
                    self._update_charge_display()
                    self._log_error(f"Protection: Boosting to {target_charge}A (export={export_power}W, voltage={max_voltage:.1f}V)")
                    
        elif can_recover and self._protection_boost_amps > 0:
            # Reduce boost by one step
            new_boost = max(0, self._protection_boost_amps - charge_step)
            if new_boost != self._protection_boost_amps:
                self._protection_boost_amps = new_boost
                self._last_protection_adjustment = current_time
                target_charge = base_charge + self._protection_boost_amps
                
                if self._protection_boost_amps == 0:
                    self._protection_active = False
                    print(f"[PROTECTION] RECOVERED: Back to base {target_charge}A")
                else:
                    print(f"[PROTECTION] Reducing boost to +{self._protection_boost_amps}A = {target_charge}A")
                
                if self.inverter.set_max_charge_current(target_charge):
                    self._current_max_charge = target_charge
                    self._update_charge_display()
                    if self._protection_boost_amps == 0:
                        self._log_error(f"Protection: Recovered, back to {target_charge}A")
                    else:
                        self._log_error(f"Protection: Reduced to {target_charge}A")
        
        # Update protection state display
        self.after(0, lambda: self.protection_panel.update_protection_state(
            self._protection_active, self._protection_boost_amps
        ))

    def _on_manual_toggle(self) -> None:
        """Handle manual mode toggle."""
        is_manual = self.cfg["manual_mode"].get()
        self.settings.set_manual_mode_visuals(is_manual)
        for outlet_panel in self.outlet_settings.values():
            outlet_panel.set_manual_mode_visuals(is_manual)

    def _on_outlet_toggle(self, outlet_id: int) -> None:
        """Handle outlet toggle button press."""
        # Prevent action if already pending for this outlet
        if outlet_id in self._pending_outlet_states:
            return
        
        # Automatically enable manual mode when button is pressed
        if not self.cfg["manual_mode"].get():
            self.cfg["manual_mode"].set(True)
            self._on_manual_toggle()
        
        # Get current state
        outlet = self.tapo.get_outlet(outlet_id)
        if outlet is None:
            return
        
        # Set pending state and disable button
        self._pending_outlet_states[outlet_id] = not outlet.current_state
        self.outlet_buttons[outlet_id].set_state(OutletButton.STATE_SWITCHING)
        self.outlet_buttons[outlet_id].configure(state="disabled")
        
        self.tapo.toggle(outlet_id)

    def _get_safe_value(self, var: ctk.StringVar, default: float) -> float:
        """Safely get a numeric value from a StringVar."""
        try:
            val = var.get()
            return float(val) if "." in val else int(val)
        except (ValueError, TypeError):
            return default

    def _get_ems_parameters(self) -> EMSParameters:
        """Build current EMS parameters from UI variables."""
        return EMSParameters(
            phase_max=int(self._get_safe_value(self.cfg["phase_max"], ems_defaults.phase_max)),
            safety_lv=float(self._get_safe_value(self.cfg["safety_lv"], ems_defaults.safety_lv)),
            manual_mode=self.cfg["manual_mode"].get(),
            max_ups_total_power=int(self._get_safe_value(self.cfg["max_ups_total_power"], ems_defaults.max_ups_total_power)),
        )

    def _data_loop(self) -> None:
        """Background thread for polling inverter data."""
        while self._running:
            data = self.inverter.read_data()
            
            if data is not None:
                self.after(0, self._update_dashboard, data)
                self._process_logic(data)
                # Process time-based charge schedule
                self._process_schedule()
                # Process overpower protection (may override schedule charge values)
                self._process_overpower_protection(data)
            else:
                self.after(0, lambda: self.header.update_status("CONNECTING...", "orange"))
            
            time.sleep(self.POLL_INTERVAL)

    def _update_dashboard(self, data: InverterData) -> None:
        """Update the dashboard with new inverter data (called on main thread)."""
        # Update header with grid connection status
        self.header.update_status("SYSTEM ONLINE", "#2ECC71", data.is_grid_connected)
        self.header.update_solar(data.pv_power)
        self.header.update_battery(data.soc, data.battery_power)
        self.header.update_grid(data.grid_power)
        
        # Update phase displays
        phase_max = int(self._get_safe_value(self.cfg["phase_max"], ems_defaults.phase_max))
        for i, name in enumerate(["L1", "L2", "L3"]):
            self.phases[name].update(
                voltage=data.voltages[i],
                load=data.grid_loads[i],  # Grid side phase power (actual grid import/export per phase)
                ups_load=data.ups_loads[i],  # UPS output (always available)
                max_load=phase_max
            )
        
        # Update total UPS power display
        total_ups = sum(data.ups_loads)
        max_total = int(self._get_safe_value(self.cfg["max_ups_total_power"], ems_defaults.max_ups_total_power))
        color = "#E74C3C" if total_ups > max_total else "#FFA500" if total_ups > max_total * 0.8 else "#2ECC71"
        self.lbl_total_power.configure(text=f"Total UPS: {total_ups} W / {max_total} W", text_color=color)
        
        # Update total load consumption per phase display
        self.lbl_load_consumption.configure(text=f"L1: {data.total_loads[0]}W L2: {data.total_loads[1]}W L3: {data.total_loads[2]}W")
        
        # Update outlet buttons
        outlets = self.tapo.get_all_outlets()
        phase_max = int(self._get_safe_value(self.cfg["phase_max"], ems_defaults.phase_max))
        
        for outlet_id, outlet in outlets.items():
            btn = self.outlet_buttons.get(outlet_id)
            if btn is None:
                continue
            
            # Update headroom display (always calculate, even if outlet is offline)
            panel = self.outlet_settings.get(outlet_id)
            if panel:
                target_idx = {"L1": 0, "L2": 1, "L3": 2}.get(outlet.config.target_phase, 0)
                # Use UPS port loads for headroom calculation (inverter output, not grid consumption)
                available_headroom = phase_max - data.ups_loads[target_idx]
                panel.update_headroom_status(available_headroom, outlet.config.headroom)
            
            if not outlet.is_connected:
                # Clear pending state and mark offline
                if outlet_id in self._pending_outlet_states:
                    del self._pending_outlet_states[outlet_id]
                btn.configure(state="normal")
                btn.set_state(OutletButton.STATE_OFFLINE)
            elif outlet_id in self._pending_outlet_states:
                # Check if state has been confirmed
                if outlet.current_state == self._pending_outlet_states[outlet_id]:
                    del self._pending_outlet_states[outlet_id]
                    btn.configure(state="normal")
                    # Continue to update with actual state below
                    if outlet.current_state:
                        btn.set_state(OutletButton.STATE_RUNNING)
                    else:
                        btn.set_state(OutletButton.STATE_STANDBY)
                # else: keep showing SWITCHING state
            else:
                # Normal state updates when not pending
                if outlet.current_state:
                    btn.set_state(OutletButton.STATE_RUNNING)
                else:
                    btn.set_state(OutletButton.STATE_STANDBY)

    def _sync_outlet_configs(self) -> None:
        """Sync outlet configurations from UI variables."""
        outlets = self.tapo.get_all_outlets()
        for outlet_id, outlet in outlets.items():
            if outlet_id in self.outlet_cfg:
                cfg_vars = self.outlet_cfg[outlet_id]
                outlet.config.start_soc = int(self._get_safe_value(cfg_vars["start_soc"], outlet.config.start_soc))
                outlet.config.stop_soc = int(self._get_safe_value(cfg_vars["stop_soc"], outlet.config.stop_soc))
                outlet.config.power = int(self._get_safe_value(cfg_vars["power"], outlet.config.power))
                outlet.config.hv_threshold = float(self._get_safe_value(cfg_vars["hv_threshold"], outlet.config.hv_threshold))
                outlet.config.lv_threshold = float(self._get_safe_value(cfg_vars["lv_threshold"], outlet.config.lv_threshold))
                outlet.config.lv_delay = int(self._get_safe_value(cfg_vars["lv_delay"], outlet.config.lv_delay))
                outlet.config.lv_recovery_voltage = float(self._get_safe_value(cfg_vars["lv_recovery_voltage"], outlet.config.lv_recovery_voltage))
                outlet.config.lv_recovery_delay = int(self._get_safe_value(cfg_vars["lv_recovery_delay"], outlet.config.lv_recovery_delay))
                outlet.config.headroom = int(self._get_safe_value(cfg_vars["headroom"], outlet.config.headroom))
                outlet.config.target_phase = cfg_vars["target_phase"].get()
                outlet.config.soc_enabled = cfg_vars["soc_enabled"].get()
                outlet.config.voltage_enabled = cfg_vars["voltage_enabled"].get()
                outlet.config.export_enabled = cfg_vars["export_enabled"].get()
                outlet.config.export_limit = int(self._get_safe_value(cfg_vars["export_limit"], outlet.config.export_limit))
                outlet.config.off_grid_mode = cfg_vars["off_grid_mode"].get()
                outlet.config.on_grid_always_on = cfg_vars["on_grid_always_on"].get()

    def _process_logic(self, data: InverterData) -> None:
        """Process EMS logic (called from background thread)."""
        outlets = self.tapo.get_all_outlets()
        if not outlets or not any(o.is_connected for o in outlets.values()):
            return
        
        # Sync outlet configs from UI
        self._sync_outlet_configs()
        
        params = self._get_ems_parameters()
        result, detail = self.ems.process(data, params)
        
        # Update UI
        color = EMSLogic.get_color_for_result(result)
        message = f"{result.value}" + (f" ({detail})" if detail else "")
        
        self.after(0, lambda: self.lbl_logic.configure(text=message, text_color=color))
        
        # Update invalid config visuals on outlet panels
        is_invalid = EMSLogic.is_error_result(result)
        for outlet_panel in self.outlet_settings.values():
            self.after(0, lambda p=outlet_panel: p.set_invalid_config(is_invalid))

    def destroy(self) -> None:
        """Clean up resources on window close."""
        self._running = False
        self.inverter.disconnect()
        super().destroy()


def main():
    """Application entry point."""
    app = DeyeApp()
    # Mark that main loop is starting (for safe error logging)
    app._main_loop_started = True
    app.mainloop()


if __name__ == "__main__":
    main()
