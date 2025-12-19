"""
Deye Inverter EMS Pro - Main Application

A professional energy management system for Deye inverters with Tapo smart plug integration.
"""

import time
import threading
import customtkinter as ctk

from src.config import ems_defaults
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
)


class DeyeApp(ctk.CTk):
    """Main application window for Deye Inverter EMS Pro."""
    
    POLL_INTERVAL = 1.2  # seconds
    
    def __init__(self):
        super().__init__()
        self.title("Deye Inverter EMS Pro")
        self.geometry("900x1400")
        ctk.set_appearance_mode("dark")
        
        # Initialize hardware managers
        self.inverter = DeyeInverter()
        self.tapo = TapoManager(error_callback=self._log_error)
        self.ems = EMSLogic(self.tapo)
        
        # Configuration variables
        self._init_config_variables()
        
        # Track pending outlet state changes per outlet
        self._pending_outlet_states = {}  # outlet_id -> pending_state
        
        # Setup UI
        self._setup_ui()
        
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
                "headroom": ctk.StringVar(value=str(outlet.config.headroom)),
                "target_phase": ctk.StringVar(value=outlet.config.target_phase),
                "soc_enabled": ctk.BooleanVar(value=outlet.config.soc_enabled),
                "voltage_enabled": ctk.BooleanVar(value=outlet.config.voltage_enabled),
                "export_enabled": ctk.BooleanVar(value=outlet.config.export_enabled),
                "export_limit": ctk.StringVar(value=str(outlet.config.export_limit)),
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
        
        # Total UPS power display
        self.lbl_total_power = ctk.CTkLabel(
            self.scrollable,
            text="Total UPS: 0 W / 16000 W",
            font=("Roboto", 14, "bold"),
            text_color="#FFA500"
        )
        self.lbl_total_power.grid(row=5, column=0, columnspan=3, pady=5)
        
        # Global Settings panel
        self.settings = SettingsPanel(
            self.scrollable,
            self.cfg,
            on_manual_toggle=self._on_manual_toggle
        )
        self.settings.grid(row=5, column=0, columnspan=3, padx=20, pady=10, sticky="nsew")
        
        # Outlet-specific settings panels
        self.outlet_settings = {}
        outlets = self.tapo.get_all_outlets()
        sorted_outlets = sorted(outlets.values(), key=lambda o: o.config.priority)
        
        current_row = 6
        for outlet in sorted_outlets:
            outlet_panel = OutletSettingsPanel(
                self.scrollable,
                outlet_name=outlet.config.name,
                variables=self.outlet_cfg[outlet.config.outlet_id]
            )
            outlet_panel.grid(row=current_row, column=0, columnspan=3, padx=20, pady=5, sticky="nsew")
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
    
    def _log_error(self, message: str) -> None:
        """Log error message to UI (called from background thread)."""
        self.after(0, lambda: self.log_viewer.add_log(message))

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
            else:
                self.after(0, lambda: self.header.update_status("CONNECTING...", "orange"))
            
            time.sleep(self.POLL_INTERVAL)

    def _update_dashboard(self, data: InverterData) -> None:
        """Update the dashboard with new inverter data (called on main thread)."""
        # Update header
        self.header.update_status("SYSTEM ONLINE", "#2ECC71")
        self.header.update_solar(data.pv_power)
        self.header.update_battery(data.soc, data.battery_power)
        self.header.update_grid(data.grid_power)
        
        # Update phase displays
        phase_max = int(self._get_safe_value(self.cfg["phase_max"], ems_defaults.phase_max))
        for i, name in enumerate(["L1", "L2", "L3"]):
            self.phases[name].update(
                voltage=data.voltages[i],
                load=data.grid_loads[i],  # Grid CT (may be 0 if no smart meter)
                ups_load=data.ups_loads[i],  # UPS output (always available)
                max_load=phase_max
            )
        
        # Update total UPS power display
        total_ups = sum(data.ups_loads)
        max_total = int(self._get_safe_value(self.cfg["max_ups_total_power"], ems_defaults.max_ups_total_power))
        color = "#E74C3C" if total_ups > max_total else "#FFA500" if total_ups > max_total * 0.8 else "#2ECC71"
        self.lbl_total_power.configure(text=f"Total UPS: {total_ups} W / {max_total} W", text_color=color)
        
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
                outlet.config.headroom = int(self._get_safe_value(cfg_vars["headroom"], outlet.config.headroom))
                outlet.config.target_phase = cfg_vars["target_phase"].get()
                outlet.config.soc_enabled = cfg_vars["soc_enabled"].get()
                outlet.config.voltage_enabled = cfg_vars["voltage_enabled"].get()
                outlet.config.export_enabled = cfg_vars["export_enabled"].get()
                outlet.config.export_limit = int(self._get_safe_value(cfg_vars["export_limit"], outlet.config.export_limit))

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
    app.mainloop()


if __name__ == "__main__":
    main()
