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
)


class DeyeApp(ctk.CTk):
    """Main application window for Deye Inverter EMS Pro."""
    
    POLL_INTERVAL = 1.2  # seconds
    
    def __init__(self):
        super().__init__()
        self.title("Deye Inverter EMS Pro")
        self.geometry("650x1000")
        ctk.set_appearance_mode("dark")
        
        # Initialize hardware managers
        self.inverter = DeyeInverter()
        self.tapo = TapoManager()
        self.ems = EMSLogic(self.tapo)
        
        # Configuration variables
        self._init_config_variables()
        
        # Track pending outlet state change
        self._pending_outlet_state = None
        
        # Setup UI
        self._setup_ui()
        
        # Start data polling thread
        self._running = True
        self._poll_thread = threading.Thread(target=self._data_loop, daemon=True)
        self._poll_thread.start()

    def _init_config_variables(self) -> None:
        """Initialize configuration variables with default values."""
        self.cfg = {
            "start_soc": ctk.StringVar(value=str(ems_defaults.start_soc)),
            "stop_soc": ctk.StringVar(value=str(ems_defaults.stop_soc)),
            "headroom": ctk.StringVar(value=str(ems_defaults.headroom)),
            "phase_max": ctk.StringVar(value=str(ems_defaults.phase_max)),
            "safety_lv": ctk.StringVar(value=str(ems_defaults.safety_lv)),
            "hv_threshold": ctk.StringVar(value=str(ems_defaults.hv_threshold)),
            "lv_threshold": ctk.StringVar(value=str(ems_defaults.lv_threshold)),
            "lv_delay": ctk.StringVar(value=str(ems_defaults.lv_delay)),
            "target_phase": ctk.StringVar(value=ems_defaults.target_phase),
            "export_active": ctk.BooleanVar(value=ems_defaults.export_active),
            "export_limit": ctk.StringVar(value=str(ems_defaults.export_limit)),
            "manual_mode": ctk.BooleanVar(value=False),
        }

    def _setup_ui(self) -> None:
        """Setup the user interface."""
        self.grid_columnconfigure((0, 1, 2), weight=1)
        
        # Status header
        self.header = StatusHeader(self)
        self.header.grid(row=0, column=0, columnspan=3, sticky="ew")
        
        # Phase displays
        self.phases = {}
        for i, name in enumerate(["L1", "L2", "L3"]):
            phase = PhaseDisplay(self, name)
            phase.grid(row=i + 2, column=0, columnspan=3, padx=20, pady=5, sticky="ew")
            self.phases[name] = phase
        
        # Settings panel
        self.settings = SettingsPanel(
            self,
            self.cfg,
            on_manual_toggle=self._on_manual_toggle
        )
        self.settings.grid(row=5, column=0, columnspan=3, padx=20, pady=10, sticky="nsew")
        
        # Heat pump control button
        self.btn_hp = HeatPumpButton(self, command=self._on_hp_toggle)
        self.btn_hp.grid(row=7, column=0, columnspan=3, pady=10, padx=40, sticky="ew")
        
        # Logic status label
        self.lbl_logic = ctk.CTkLabel(
            self, text="Logic: Initializing",
            font=("Roboto", 13),
            text_color="gray"
        )
        self.lbl_logic.grid(row=8, column=0, columnspan=3, pady=5)

    def _on_manual_toggle(self) -> None:
        """Handle manual mode toggle."""
        is_manual = self.cfg["manual_mode"].get()
        self.settings.set_manual_mode_visuals(is_manual)

    def _on_hp_toggle(self) -> None:
        """Handle heat pump toggle button press."""
        # Prevent action if already pending
        if self._pending_outlet_state is not None:
            return
        
        # Automatically enable manual mode when button is pressed
        if not self.cfg["manual_mode"].get():
            self.cfg["manual_mode"].set(True)
            self._on_manual_toggle()
        
        # Set pending state and disable button
        self._pending_outlet_state = not self.tapo.current_state
        self.btn_hp.set_state(HeatPumpButton.STATE_SWITCHING)
        self.btn_hp.configure(state="disabled")
        
        self.tapo.toggle()

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
            start_soc=int(self._get_safe_value(self.cfg["start_soc"], ems_defaults.start_soc)),
            stop_soc=int(self._get_safe_value(self.cfg["stop_soc"], ems_defaults.stop_soc)),
            headroom=int(self._get_safe_value(self.cfg["headroom"], ems_defaults.headroom)),
            phase_max=int(self._get_safe_value(self.cfg["phase_max"], ems_defaults.phase_max)),
            safety_lv=float(self._get_safe_value(self.cfg["safety_lv"], ems_defaults.safety_lv)),
            hv_threshold=float(self._get_safe_value(self.cfg["hv_threshold"], ems_defaults.hv_threshold)),
            lv_threshold=float(self._get_safe_value(self.cfg["lv_threshold"], ems_defaults.lv_threshold)),
            lv_delay=int(self._get_safe_value(self.cfg["lv_delay"], ems_defaults.lv_delay)),
            target_phase=self.cfg["target_phase"].get(),
            export_active=self.cfg["export_active"].get(),
            export_limit=int(self._get_safe_value(self.cfg["export_limit"], ems_defaults.export_limit)),
            manual_mode=self.cfg["manual_mode"].get(),
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
                load=data.phase_loads[i],
                max_load=phase_max
            )
        
        # Update heat pump button
        if not self.tapo.is_connected:
            self._pending_outlet_state = None
            self.btn_hp.configure(state="normal")
            self.btn_hp.set_state(HeatPumpButton.STATE_OFFLINE)
        elif self._pending_outlet_state is not None:
            # Check if state has been confirmed
            if self.tapo.current_state == self._pending_outlet_state:
                self._pending_outlet_state = None
                self.btn_hp.configure(state="normal")
                # Continue to update with actual state below
                if self.tapo.current_state:
                    self.btn_hp.set_state(HeatPumpButton.STATE_RUNNING)
                else:
                    self.btn_hp.set_state(HeatPumpButton.STATE_STANDBY)
            # else: keep showing SWITCHING state
        else:
            # Normal state updates when not pending
            if self.tapo.current_state:
                self.btn_hp.set_state(HeatPumpButton.STATE_RUNNING)
            else:
                self.btn_hp.set_state(HeatPumpButton.STATE_STANDBY)

    def _process_logic(self, data: InverterData) -> None:
        """Process EMS logic (called from background thread)."""
        if not self.tapo.is_connected:
            return
        
        params = self._get_ems_parameters()
        result, detail = self.ems.process(data, params)
        
        # Update UI
        color = EMSLogic.get_color_for_result(result)
        message = f"{result.value}" + (f" ({detail})" if detail else "")
        
        self.after(0, lambda: self.lbl_logic.configure(text=message, text_color=color))
        
        # Update invalid config visuals
        is_invalid = EMSLogic.is_error_result(result)
        self.after(0, lambda: self.settings.set_invalid_config(is_invalid))

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
