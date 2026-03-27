"""
Deye Inverter EMS Pro - Main Application

A professional energy management system for Deye inverters with Tapo smart plug integration.
"""

import time
import threading
import sys
import os
from datetime import datetime
import customtkinter as ctk

from src.config import ems_defaults, deye_config, protection_config, ev_charger_config, heatpump_config, get_app_path
from src.deye_inverter import DeyeInverter, InverterData, BMSData
from src.tapo_manager import TapoManager
from src.ems_logic import EMSLogic, EMSParameters, LogicResult
from src.tuya_charger import TuyaChargerManager
from src.ev_logic import EVChargingLogic, EVSettings, EVResult
from src.tuya_heatpump import TuyaHeatpumpManager
from src.tuya_heatpump_logic import HeatpumpLogic, HeatpumpSettings, HeatpumpResult
from src.weather_forecast import WeatherForecast
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
    SunsetChargingPanel,
    EVChargerPanel,
    HeatpumpPanel,
    BatteryStatsDialog,
)


class TeeWriter:
    """Duplicates writes to both the original stream and a log file."""
    def __init__(self, original, log_file):
        self.original = original
        self.log_file = log_file

    def write(self, text):
        if text:
            self.original.write(text)
            try:
                self.log_file.write(text)
                self.log_file.flush()
            except Exception:
                pass

    def flush(self):
        self.original.flush()
        try:
            self.log_file.flush()
        except Exception:
            pass

    def fileno(self):
        return self.original.fileno()


def setup_file_logging():
    """Setup logging to a timestamped file in a logs/ directory next to the app."""
    logs_dir = get_app_path() / "logs"
    logs_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_path = logs_dir / f"deye_{timestamp}.txt"
    log_file = open(log_path, "w", encoding="utf-8")
    sys.stdout = TeeWriter(sys.__stdout__, log_file)
    sys.stderr = TeeWriter(sys.__stderr__, log_file)
    print(f"[INIT] Log file: {log_path}")
    return log_file


class DeyeApp(ctk.CTk):
    """Main application window for Deye Inverter EMS Pro."""
    
    POLL_INTERVAL = 1.2  # seconds
    
    def __init__(self):
        super().__init__()
        self.title("Deye Inverter EMS Pro")
        self.geometry("1300x1400")
        ctk.set_appearance_mode("dark")
        
        # Set custom window icon
        icon_path = get_app_path() / "icon.ico"
        if icon_path.exists():
            self.after(200, lambda: self.iconbitmap(str(icon_path)))
        
        # Initialize hardware managers
        self.inverter = DeyeInverter()
        self._inverter_lock = threading.Lock()  # Serialize modbus access across threads
        self.tapo = TapoManager(error_callback=self._log_error)
        self.ems = EMSLogic(self.tapo)
        
        # Tuya heat pump outlet
        self.hp_manager = None
        self.hp_logic = None
        if heatpump_config.device_id:
            self.hp_manager = TuyaHeatpumpManager(heatpump_config, error_callback=self._log_error)
            self.hp_logic = HeatpumpLogic(self.hp_manager, heatpump_config)

        # EV charger (Tuya)
        self.ev_charger = None
        self.ev_logic = None
        if ev_charger_config.device_id:
            self.ev_charger = TuyaChargerManager(ev_charger_config, error_callback=self._log_error)
            self.ev_logic = EVChargingLogic(self.ev_charger)
        
        # Configuration variables
        self._init_config_variables()
        
        # Track pending outlet state changes per outlet
        self._pending_outlet_states = {}  # outlet_id -> pending_state
        
        # Overpower protection state
        self._protection_boost_amps = 0  # Current boost amount added on top of schedule
        self._protection_active = False  # Whether protection is currently boosting
        self._last_protection_adjustment = 0.0  # Timestamp of last charge adjustment
        
        # Sunset charging state
        self._sunset_boost_amps = 0  # Current sunset boost amount
        self._sunset_active = False  # Whether sunset charging is actively boosting
        self._last_sunset_adjustment = 0.0  # Timestamp of last sunset charge adjustment
        self._pv_samples: list[tuple[float, int]] = []  # (timestamp, pv_watts) rolling window
        self._cloud_boost_factor = 1.0  # Current cloudy day boost multiplier
        
        # Weather forecast for predictive sunset charging
        from src.config import sunset_config
        self._weather = WeatherForecast(
            latitude=sunset_config.latitude,
            longitude=sunset_config.longitude,
            refresh_hours=sunset_config.weather_refresh_hours,
        )
        self._weather_enabled = sunset_config.weather_enabled
        
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
                "phase_change_delay": ctk.StringVar(value=str(outlet.config.phase_change_delay)),
                "lv_recovery_voltage": ctk.StringVar(value=str(outlet.config.lv_recovery_voltage)),
                "lv_recovery_delay": ctk.StringVar(value=str(outlet.config.lv_recovery_delay)),
                "headroom": ctk.StringVar(value=str(outlet.config.headroom)),
                "target_phase": ctk.StringVar(value=outlet.config.target_phase),
                "soc_enabled": ctk.BooleanVar(value=outlet.config.soc_enabled),
                "voltage_enabled": ctk.BooleanVar(value=outlet.config.voltage_enabled),
                "export_enabled": ctk.BooleanVar(value=outlet.config.export_enabled),
                "export_limit": ctk.StringVar(value=str(outlet.config.export_limit)),
                "export_delay": ctk.StringVar(value=str(outlet.config.export_delay)),
                "soc_delay": ctk.StringVar(value=str(outlet.config.soc_delay)),
                "off_grid_mode": ctk.BooleanVar(value=outlet.config.off_grid_mode),
                "on_grid_always_on": ctk.BooleanVar(value=outlet.config.on_grid_always_on),
                "restart_delay_enabled": ctk.BooleanVar(value=outlet.config.restart_delay_enabled),
                "restart_delay_minutes": ctk.StringVar(value=str(outlet.config.restart_delay_minutes)),
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
        self.header = StatusHeader(self.scrollable, bat_stats_command=self._open_battery_stats)
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
        
        # Sunset Charging Panel
        self.sunset_panel = SunsetChargingPanel(
            self.scrollable,
            on_settings_change=self._on_sunset_change
        )
        self.sunset_panel.grid(row=8, column=0, columnspan=3, padx=20, pady=10, sticky="ew")
        
        # Tuya Heat Pump Panel
        self.heatpump_panel = HeatpumpPanel(
            self.scrollable,
            on_settings_change=self._on_heatpump_change
        )
        self.heatpump_panel.grid(row=9, column=0, columnspan=3, padx=20, pady=10, sticky="ew")

        # EV Charger Panel
        self.ev_panel = EVChargerPanel(
            self.scrollable,
            on_settings_change=self._on_ev_change
        )
        self.ev_panel.grid(row=10, column=0, columnspan=3, padx=20, pady=10, sticky="ew")
        
        # Track last applied schedule to avoid redundant writes
        self._last_applied_schedule = None
        
        # Track current charge settings for display
        self._current_max_charge = None
        self._current_grid_charge = None
        self._current_max_discharge = None
        self._current_work_mode = None
        self._current_sell_power = None
        self._protection_disabled_by_sell = False  # Track if protection was auto-disabled by sell mode
        
        # Global Settings panel
        self.settings = SettingsPanel(
            self.scrollable,
            self.cfg,
            on_manual_toggle=self._on_manual_toggle
        )
        self.settings.grid(row=11, column=0, columnspan=3, padx=20, pady=10, sticky="nsew")
        
        # Outlet-specific settings panels
        self.outlet_settings = {}
        outlets = self.tapo.get_all_outlets()
        sorted_outlets = sorted(outlets.values(), key=lambda o: o.config.priority)
        
        current_row = 13
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
            
            # Initialize protection boost from inverter state so we don't reset
            # charging speed on app restart (e.g. inverter at 180A, base is 40A → boost = 140A)
            base_charge = self._get_base_charge_amps()
            if max_charge > base_charge:
                self._protection_boost_amps = max_charge - base_charge
                self._protection_active = True
                print(f"[INIT] Protection boost initialized: inverter={max_charge}A - base={base_charge}A = boost={self._protection_boost_amps}A")
        else:
            print("[INIT] Could not read charge settings from inverter")
        
        # Read max sell power for protection panel
        max_sell = self.inverter.read_max_sell_power()
        if max_sell is not None:
            print(f"[INIT] Max sell power from inverter: {max_sell}W")
            self.after(0, lambda: self.protection_panel.set_max_sell_power(max_sell))
        
        # If any default schedule has selling enabled, disable boost protection at startup
        # to prevent it from fighting the intentional battery export
        any_sell = any(
            s.get("sell", False) for s in self.schedule_panel.get_all_schedules() if s
        )
        if any_sell and self.protection_panel.is_enabled():
            self._protection_disabled_by_sell = True
            self.after(0, lambda: self.protection_panel.set_enabled(False))
            print("[INIT] Boost protection disabled at startup (sell mode detected in schedule)")
    
    def _log_error(self, message: str) -> None:
        """Log error message to UI and log file (called from background thread)."""
        print(f"[LOG] {message}")
        try:
            if self._main_loop_started:
                self.after(0, lambda: self.log_viewer.add_log(message))
        except RuntimeError:
            pass

    def _open_battery_stats(self) -> None:
        """Open the Battery Statistics dialog with live BMS data."""
        # Disable button while loading
        self.header.btn_batstats.configure(state="disabled", text="Loading...")
        
        def _read_and_show():
            with self._inverter_lock:
                bms_data = self.inverter.read_bms_data()
            self.after(0, lambda: self._show_battery_dialog(bms_data))
        
        # Read BMS data in background thread to avoid freezing UI
        threading.Thread(target=_read_and_show, daemon=True).start()
    
    def _show_battery_dialog(self, bms_data) -> None:
        """Show the battery stats dialog (called on main thread)."""
        self.header.btn_batstats.configure(state="normal", text="BatStats")
        BatteryStatsDialog(self, bms_data)

    def _on_schedule_change(self) -> None:
        """Handle schedule enable/disable toggle."""
        # Reset last applied schedule so it will be re-evaluated
        self._last_applied_schedule = None
        
        # If schedule was just disabled, apply defaults in background thread
        if not self.schedule_panel.is_enabled():
            defaults = self.schedule_panel.get_default_values()
            print(f"[SCHEDULE] Disabled - applying defaults: Max={defaults['max_charge_amps']}A, Grid={defaults['grid_charge_amps']}A, Discharge={defaults['max_discharge_amps']}A")
            
            def apply_defaults():
                with self._inverter_lock:
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
                    
                    # Restore Zero Export mode when schedule is disabled
                    if self._current_work_mode != deye_config.zero_export_mode:
                        if self.inverter.set_work_mode(deye_config.zero_export_mode):
                            self._current_work_mode = deye_config.zero_export_mode
                    
                    # Restore boost protection if it was disabled by sell mode
                    if self._protection_disabled_by_sell:
                        # Restore max sell power to config value before re-enabling protection
                        config_sell_power = protection_config.max_sell_power
                        if self._current_sell_power != config_sell_power:
                            if self.inverter.set_max_sell_power(config_sell_power):
                                self._current_sell_power = config_sell_power
                                self.after(0, lambda p=config_sell_power: self.protection_panel.set_max_sell_power(p))
                        self._protection_disabled_by_sell = False
                        self.after(0, lambda: self.protection_panel.set_enabled(True))
                        print("[SCHEDULE] Boost protection restored (schedule disabled)")
                    
                    if success1 and success2 and success3:
                        self.after(0, self._update_charge_display)
                    self._log_error(f"Schedule disabled - defaults applied: Max={defaults['max_charge_amps']}A, Grid={defaults['grid_charge_amps']}A, Discharge={defaults['max_discharge_amps']}A")
            
            threading.Thread(target=apply_defaults, daemon=True).start()

    def _process_schedule(self) -> None:
        """Process time-based charge/sell schedule and apply settings if needed."""
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
            target_sell = active_schedule.get("sell", False)
            target_sell_power = active_schedule.get("sell_power", 0)
            schedule_key = (
                active_schedule["start_hour"],
                active_schedule["start_min"],
                active_schedule["end_hour"],
                active_schedule["end_min"],
                target_max,
                target_grid,
                target_discharge,
                target_sell,
                target_sell_power,
            )
        else:
            # No active time slot - use defaults
            defaults = self.schedule_panel.get_default_values()
            target_max = defaults["max_charge_amps"]
            target_grid = defaults["grid_charge_amps"]
            target_discharge = defaults["max_discharge_amps"]
            target_sell = defaults.get("sell", False)
            target_sell_power = defaults.get("sell_power", 0)
            schedule_key = ("default", target_max, target_grid, target_discharge, target_sell, target_sell_power)
        
        # Only apply if settings changed
        if self._last_applied_schedule == schedule_key:
            return
        
        # Determine work mode: 0 = Selling First, 1/2 = Zero Export (from config)
        target_work_mode = 0 if target_sell else deye_config.zero_export_mode
        
        # Apply the settings - only write values that actually changed
        sell_str = f", Sell={target_sell_power}W" if target_sell else ""
        if active_schedule:
            print(f"[SCHEDULE] Applying slot: Max={target_max}A, Grid={target_grid}A, Discharge={target_discharge}A{sell_str}")
        else:
            print(f"[SCHEDULE] No active slot - applying defaults: Max={target_max}A, Grid={target_grid}A, Discharge={target_discharge}A{sell_str}")
        
        all_success = True
        
        # Only write max charge if it changed
        if self._current_max_charge != target_max:
            if self.inverter.set_max_charge_current(target_max):
                self._current_max_charge = target_max
            else:
                all_success = False
        
        # Only write grid charge if it changed
        if self._current_grid_charge != target_grid:
            if self.inverter.set_grid_charge_current(target_grid):
                self._current_grid_charge = target_grid
            else:
                all_success = False
        
        # Only write max discharge if it changed
        if self._current_max_discharge != target_discharge:
            if self.inverter.set_max_discharge_current(target_discharge):
                self._current_max_discharge = target_discharge
            else:
                all_success = False
        
        # Set work mode (Selling First or Zero Export)
        if self._current_work_mode != target_work_mode:
            if self.inverter.set_work_mode(target_work_mode):
                self._current_work_mode = target_work_mode
                print(f"[SCHEDULE] Work mode set to {'Selling First' if target_work_mode == 0 else 'Zero Export (' + ('Load' if target_work_mode == 1 else 'CT') + ')'}")
            else:
                all_success = False
        
        # Interlock: disable boost protection when selling, restore when not
        if target_sell and not self._protection_disabled_by_sell:
            if self.protection_panel.is_enabled():
                self._protection_disabled_by_sell = True
                self.after(0, lambda: self.protection_panel.set_enabled(False))
                print("[SCHEDULE] Boost protection paused (sell mode active)")
        elif not target_sell and self._protection_disabled_by_sell:
            # Restore max sell power to config value before re-enabling protection
            config_sell_power = protection_config.max_sell_power
            if self._current_sell_power != config_sell_power:
                if self.inverter.set_max_sell_power(config_sell_power):
                    self._current_sell_power = config_sell_power
                    self.after(0, lambda p=config_sell_power: self.protection_panel.set_max_sell_power(p))
                    print(f"[SCHEDULE] Max sell power restored to {config_sell_power}W")
            self._protection_disabled_by_sell = False
            self.after(0, lambda: self.protection_panel.set_enabled(True))
            print("[SCHEDULE] Boost protection restored (sell mode ended)")
        
        # Set max sell power when in selling mode
        if target_sell and self._current_sell_power != target_sell_power:
            if self.inverter.set_max_sell_power(target_sell_power):
                self._current_sell_power = target_sell_power
                # Also update the boost protection panel to match
                self.after(0, lambda p=target_sell_power: self.protection_panel.set_max_sell_power(p))
                print(f"[SCHEDULE] Max sell power set to {target_sell_power}W")
            else:
                all_success = False
        
        if all_success:
            self._last_applied_schedule = schedule_key
            self._update_charge_display()
            if active_schedule:
                self._log_error(f"Schedule applied: Max={target_max}A, Grid={target_grid}A, Discharge={target_discharge}A{sell_str}")
            else:
                self._log_error(f"Defaults applied: Max={target_max}A, Grid={target_grid}A, Discharge={target_discharge}A{sell_str}")
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

    def _on_sunset_change(self) -> None:
        """Handle sunset charging settings change."""
        if not self.sunset_panel.is_enabled():
            if self._sunset_boost_amps > 0:
                self._sunset_boost_amps = 0
                self._sunset_active = False
                self._cloud_boost_factor = 1.0
                self._last_applied_schedule = None
                print("[SUNSET] Disabled - clearing boost")

    def _on_heatpump_change(self) -> None:
        """Handle heat pump panel settings change."""
        if not self.heatpump_panel.is_enabled():
            print("[HP] Disabled via UI")

    def _on_ev_change(self) -> None:
        """Handle EV charger panel settings change."""
        if not self.ev_panel.is_enabled():
            print("[EV] Disabled via UI")



    def _process_sunset_charging(self, data) -> None:
        """
        Process sunset-aware charging logic.
        
        Uses a solar-curve-weighted algorithm: charges more aggressively around
        the configured peak solar hour (or solar noon if set to auto) and less
        in the early morning and late afternoon. The weighting follows a cosine
        curve from sunrise to the deadline, peaking at the configured hour.
        
        Cloudy day compensation: when peak_expected_kw is configured, compares
        a 15-minute rolling average of actual PV production against the expected
        cos² curve. If production is below the threshold, applies a boost
        multiplier to charge faster and compensate for reduced solar.
        """
        from astral import LocationInfo
        from astral.sun import sun
        from datetime import datetime, timezone, timedelta
        import math
        
        if not self.sunset_panel.is_enabled():
            if self._sunset_active:
                self._sunset_boost_amps = 0
                self._sunset_active = False
                self._last_applied_schedule = None
                self._cloud_boost_factor = 1.0
            self.after(0, lambda: self.sunset_panel.update_state("--:--", None, 0, False))
            return
        
        # Throttle adjustments to avoid excessive inverter writes
        current_time = time.time()

        # Track PV production samples (rolling 15-min window) for cloudy day detection
        self._pv_samples.append((current_time, data.pv_power))
        cutoff = current_time - 900  # 15 minutes
        self._pv_samples = [(t, w) for t, w in self._pv_samples if t >= cutoff]

        if current_time - self._last_sunset_adjustment < deye_config.min_register_write_interval:
            return
        
        settings = self.sunset_panel.get_settings()
        
        # Calculate sun times
        loc = LocationInfo(latitude=settings["latitude"], longitude=settings["longitude"])
        now = datetime.now(timezone.utc)
        try:
            s = sun(loc.observer, date=now.date())
            sunrise_utc = s["sunrise"]
            sunset_utc = s["sunset"]
            noon_utc = s["noon"]
        except Exception:
            self.after(0, lambda: self.sunset_panel.update_state("Error", None, 0, False))
            return
        
        # Effective deadline = sunset minus buffer
        deadline = sunset_utc - timedelta(minutes=settings["buffer_minutes"])
        hours_left = (deadline - now).total_seconds() / 3600.0
        
        # Format sunset in local time
        sunset_local = sunset_utc.astimezone()
        sunset_str = sunset_local.strftime("%H:%M")
        
        # Refresh weather forecast in background if needed
        if self._weather_enabled and self._weather.needs_refresh():
            self._weather.latitude = settings["latitude"]
            self._weather.longitude = settings["longitude"]
            threading.Thread(target=self._weather.fetch, daemon=True).start()
        
        weather_str = self._weather.summary_str() if self._weather_enabled else ""
        sparkline = self._weather.day_sparkline() if self._weather_enabled else ""
        
        current_soc = data.soc
        target_soc = settings["target_soc"]
        capacity_ah = settings["battery_capacity_ah"]
        min_charge = settings["min_charge_amps"]
        
        if current_soc >= target_soc or hours_left <= 0:
            # Already at target or past deadline
            if self._sunset_active:
                self._sunset_boost_amps = 0
                self._sunset_active = False
                self._cloud_boost_factor = 1.0
                self._last_applied_schedule = None
            self.after(0, lambda: self.sunset_panel.update_state(
                sunset_str, hours_left if hours_left > 0 else 0, 0, False))
            return
        
        # Solar-curve-weighted charging calculation
        remaining_ah = capacity_ah * (target_soc - current_soc) / 100.0
        
        # Determine peak time for cos² fallback curve
        peak_hour = settings.get("peak_solar_hour", 0.0)
        if peak_hour > 0:
            peak_h = int(peak_hour)
            peak_m = int((peak_hour - peak_h) * 60)
            peak_local = now.astimezone().replace(hour=peak_h, minute=peak_m, second=0, microsecond=0)
            peak_utc = peak_local.astimezone(timezone.utc)
        else:
            peak_utc = noon_utc
        
        # Try forecast-based weights first, fall back to cos² curve
        forecast_active = False
        forecast_weights = []
        if self._weather_enabled and self._weather.is_available:
            steps_fc = max(1, int(hours_left * 4))
            forecast_weights = self._weather.get_solar_weights(sunrise_utc, deadline, steps_fc)
        
        # Calculate solar day span for weighting (from sunrise to deadline)
        day_span = (deadline - sunrise_utc).total_seconds()
        
        if day_span <= 0:
            # Fallback: flat rate if something is off
            required_amps = math.ceil(remaining_ah / max(hours_left, 0.1))
        elif forecast_weights:
            # --- Forecast-based weighting ---
            forecast_active = True
            steps_fc = len(forecast_weights)
            dt = hours_left / steps_fc
            now_frac = (now - sunrise_utc).total_seconds() / day_span
            now_frac = max(0.0, min(1.0, now_frac))
            
            # Current weight: interpolate from forecast at now_frac
            now_idx = int(now_frac * steps_fc)
            now_idx = min(now_idx, steps_fc - 1)
            current_weight = max(0.05, forecast_weights[now_idx])
            
            # Sum remaining weighted hours (from current position to end)
            total_weighted_hours = 0.0
            start_idx = max(0, int(now_frac * steps_fc))
            for i in range(start_idx, steps_fc):
                total_weighted_hours += max(0.05, forecast_weights[i]) * dt
            
            if total_weighted_hours > 0:
                required_amps = math.ceil(remaining_ah * current_weight / total_weighted_hours)
            else:
                required_amps = math.ceil(remaining_ah / max(hours_left, 0.1))
            
            # Log forecast influence periodically
            budget = self._weather.get_remaining_budget_ratio(now, deadline)
            if budget is not None and not hasattr(self, "_last_weather_log") or \
               current_time - getattr(self, "_last_weather_log", 0) > 600:
                self._last_weather_log = current_time
                print(f"[SUNSET] Forecast active: weight={current_weight:.2f}, "
                      f"solar budget remaining={budget:.0%}, "
                      f"cloud={self._weather.get_cloud_cover_at(now) or 0:.0f}%")
        else:
            # --- Theoretical cos² weighting (fallback) ---
            # Current position as fraction of solar day (0=sunrise, 1=deadline)
            now_frac = (now - sunrise_utc).total_seconds() / day_span
            noon_frac = (peak_utc - sunrise_utc).total_seconds() / day_span
            now_frac = max(0.0, min(1.0, now_frac))
            
            # Weight at current time: cos²(π × (t - peak_frac))
            # Peaks at configured peak hour (or solar noon), tapers to ~0 at edges
            def solar_weight(t_frac):
                angle = math.pi * (t_frac - noon_frac)
                return max(0.05, math.cos(angle) ** 2)  # Floor of 0.05 to avoid zero
            
            # Integrate remaining weighted hours from now to deadline using 15-min steps
            steps = max(1, int(hours_left * 4))
            dt = hours_left / steps
            total_weighted_hours = 0.0
            for i in range(steps):
                t = now_frac + (i + 0.5) * (1.0 - now_frac) / steps
                total_weighted_hours += solar_weight(t) * dt
            
            # Current weight determines how much of the remaining Ah to charge now
            current_weight = solar_weight(now_frac)
            
            if total_weighted_hours > 0:
                required_amps = math.ceil(remaining_ah * current_weight / total_weighted_hours)
            else:
                required_amps = math.ceil(remaining_ah / max(hours_left, 0.1))
        
        # Cloudy day compensation (reactive fallback — only when forecast is not active)
        # When forecast is active, the weight curve already accounts for predicted clouds
        peak_kw = settings.get("peak_expected_kw", 0.0)
        cloud_threshold = settings.get("cloud_threshold_pct", 60) / 100.0
        cloud_max_boost = settings.get("cloud_max_boost", 3.0)
        
        if not forecast_active and peak_kw > 0 and day_span > 0 and len(self._pv_samples) >= 3:
            # Expected production at current time from cos² curve (kW)
            expected_kw = peak_kw * solar_weight(now_frac)
            # Rolling average of actual PV production (kW)
            avg_pv_kw = sum(w for _, w in self._pv_samples) / len(self._pv_samples) / 1000.0
            
            if expected_kw > 0.5:  # Only compensate when meaningful production is expected
                production_ratio = avg_pv_kw / expected_kw
                if production_ratio < cloud_threshold:
                    # Scale boost inversely with production ratio
                    # At 30% of expected → boost ~2x; at 10% → boost ~3x (capped)
                    self._cloud_boost_factor = min(cloud_max_boost, expected_kw / max(avg_pv_kw, 0.1))
                    required_amps = math.ceil(required_amps * self._cloud_boost_factor)
                    required_amps = min(required_amps, deye_config.max_charge_amps_limit)
                    if required_amps != getattr(self, "_last_cloud_boost_amps", None):
                        self._last_cloud_boost_amps = required_amps
                        print(f"[SUNSET] Cloudy boost: PV avg={avg_pv_kw:.1f}kW vs expected={expected_kw:.1f}kW"
                              f" ({production_ratio:.0%}), boost={self._cloud_boost_factor:.1f}x → {required_amps}A")
                else:
                    self._cloud_boost_factor = 1.0
            else:
                self._cloud_boost_factor = 1.0
        else:
            self._cloud_boost_factor = 1.0
        
        required_amps = max(min_charge, min(required_amps, deye_config.max_charge_amps_limit))
        
        # Compare with current base charge rate
        base_charge = self._get_base_charge_amps()
        
        # Add any existing protection boost
        effective_charge = base_charge + self._protection_boost_amps
        
        if required_amps > effective_charge:
            # Need more than what schedule+protection provides
            sunset_boost = required_amps - base_charge - self._protection_boost_amps
            sunset_boost = max(0, sunset_boost)
            
            # Round to 10A steps to avoid writing every single amp change
            sunset_boost = ((sunset_boost + 9) // 10) * 10
            
            if sunset_boost != self._sunset_boost_amps:
                # Verify inverter has caught up before changing charge speed
                if not self._is_charge_speed_settled(data, data.battery_voltage if data.battery_voltage > 0 else 52):
                    self.after(0, lambda: self.sunset_panel.update_state(
                        sunset_str, hours_left, required_amps, self._sunset_active,
                        self._cloud_boost_factor, weather_str, sparkline))
                    return
                
                self._sunset_boost_amps = sunset_boost
                self._sunset_active = True
                self._last_sunset_adjustment = current_time
                target_charge = base_charge + self._protection_boost_amps + self._sunset_boost_amps
                target_charge = min(target_charge, deye_config.max_charge_amps_limit)
                
                peak_info = f"peak={peak_hour:.1f}h" if peak_hour > 0 else "peak=auto"
                src_info = "forecast" if forecast_active else peak_info
                print(f"[SUNSET] Boosting: Base={base_charge}A + Protection={self._protection_boost_amps}A"
                      f" + Sunset={self._sunset_boost_amps}A = {target_charge}A"
                      f" (need {remaining_ah:.0f}Ah in {hours_left:.1f}h, weight={current_weight:.2f},"
                      f" {src_info}, SOC {current_soc}%→{target_soc}%)")
                
                if self.inverter.set_max_charge_current(target_charge):
                    self._current_max_charge = target_charge
                    self._update_charge_display()
                    self._log_error(
                        f"Sunset charging: {target_charge}A "
                        f"({remaining_ah:.0f}Ah in {hours_left:.1f}h, SOC {current_soc}%→{target_soc}%)")
        else:
            # Base + protection is enough, no sunset boost needed
            if self._sunset_boost_amps > 0:
                self._sunset_boost_amps = 0
                self._sunset_active = False
                self._last_applied_schedule = None
                print(f"[SUNSET] Base charge ({effective_charge}A) sufficient for {required_amps}A required")
        
        self.after(0, lambda: self.sunset_panel.update_state(
            sunset_str, hours_left, required_amps, self._sunset_active,
            self._cloud_boost_factor, weather_str, sparkline))

    def _get_base_charge_amps(self) -> int:
        """Get the base charge amps from schedule or defaults (before protection boost)."""
        if self.schedule_panel.is_enabled():
            active_schedule = self.schedule_panel.get_active_schedule()
            if active_schedule:
                return active_schedule["max_charge_amps"]
        # Use defaults
        defaults = self.schedule_panel.get_default_values()
        return defaults["max_charge_amps"]

    def _is_charge_speed_settled(self, data, battery_voltage: float) -> bool:
        """Check if the inverter's actual charging power is within 10% of the expected power.
        
        The inverter can lag behind when adjusting max charge/discharge amps.
        Before changing the setting again, verify the actual battery power
        has caught up to within 10% of (current_max_charge × battery_voltage).
        
        Returns True if settled (OK to adjust), False if still ramping.
        """
        if self._current_max_charge is None or battery_voltage <= 0:
            return True  # No prior setting or no voltage reading — allow adjustment
        
        # Only check when battery is actually charging (negative power = charging for Deye)
        if data.battery_power >= 0:
            return True  # Discharging or idle — allow adjustment
        
        expected_power = self._current_max_charge * battery_voltage
        actual_power = abs(data.battery_power)
        
        # Check if actual power is within 10% of expected
        if abs(actual_power - expected_power) > expected_power * 0.10:
            print(f"[CHARGE] Waiting for inverter to settle: actual={actual_power}W vs expected={expected_power:.0f}W "
                  f"({self._current_max_charge}A × {battery_voltage:.1f}V), diff={abs(actual_power - expected_power) / expected_power:.0%}")
            return False
        
        return True

    def _process_overpower_protection(self, data) -> None:
        """
        Process overpower protection logic with proportional response.
        
        Uses proportional amp calculation based on how far export power is from
        the target (midpoint between warning and recovery thresholds).
        For large deviations, jumps proportionally; for small ones, uses charge_step
        for fine-tuning to find the hysteresis point.
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
        battery_voltage = data.battery_voltage if data.battery_voltage > 0 else protection_config.battery_nominal_voltage
        
        # Target power: midpoint between warning and recovery (stable equilibrium)
        target_power = (power_warning_threshold + power_recovery_threshold) / 2
        
        # Determine if we need to boost or reduce
        needs_boost = (export_power >= power_warning_threshold) or (max_voltage >= voltage_warning)
        # Voltage hold: if voltage is still within hold margin of warning, don't recover
        # even if export dropped. This prevents voltage-driven boosts from being backed down
        # by the export recovery logic while voltage is still elevated.
        voltage_hold_margin = settings.get("voltage_hold_margin", protection_config.voltage_hold_margin)
        voltage_held = max_voltage >= (voltage_warning - voltage_hold_margin)
        can_recover = (export_power < power_recovery_threshold) and (max_voltage < voltage_recovery) and not voltage_held
        
        base_charge = self._get_base_charge_amps()
        max_charge_limit = deye_config.max_charge_amps_limit
        
        if needs_boost:
            # Verify inverter has caught up to current charge setting before increasing further
            if not self._is_charge_speed_settled(data, battery_voltage):
                self.after(0, lambda: self.protection_panel.update_protection_state(
                    self._protection_active, self._protection_boost_amps
                ))
                return
            
            # BMS charge limit check: if the BMS reports a charge current limit,
            # don't boost beyond what the BMS will accept
            if data.bms_charge_current_limit > 0:
                target_after_boost = base_charge + self._protection_boost_amps + charge_step
                if target_after_boost > data.bms_charge_current_limit:
                    self.after(0, lambda: self.protection_panel.update_protection_state(
                        self._protection_active, self._protection_boost_amps, bms_limited=True
                    ))
                    return
            
            # Calculate proportional step: how many amps to absorb excess above target
            excess_power = export_power - target_power
            proportional_step = int(excess_power / battery_voltage) if battery_voltage > 0 else charge_step
            # Round to nearest charge_step multiple, minimum one step
            proportional_step = ((proportional_step + charge_step // 2) // charge_step) * charge_step
            step = max(charge_step, proportional_step)
            
            new_boost = min(self._protection_boost_amps + step, max_charge_limit - base_charge)
            # Cap at BMS charge current limit if available
            if data.bms_charge_current_limit > 0:
                new_boost = min(new_boost, max(0, data.bms_charge_current_limit - base_charge))
            if new_boost != self._protection_boost_amps:
                self._protection_boost_amps = new_boost
                self._protection_active = True
                self._last_protection_adjustment = current_time
                target_charge = base_charge + self._protection_boost_amps
                
                step_type = "PROPORTIONAL" if proportional_step > charge_step else "STEP"
                print(f"[PROTECTION] BOOST ({step_type} +{step}A): Base={base_charge}A + Boost={self._protection_boost_amps}A = {target_charge}A "
                      f"(Export={export_power}W/{max_sell}W, MaxV={max_voltage:.1f}V)")
                
                if self.inverter.set_max_charge_current(target_charge):
                    self._current_max_charge = target_charge
                    self._update_charge_display()
                    self._log_error(f"Protection: Boosting +{step}A ({step_type}) to {target_charge}A (export={export_power}W, voltage={max_voltage:.1f}V)")
                    
        elif can_recover and self._protection_boost_amps > 0:
            # If sunset charging is active and driving a higher rate anyway,
            # silently clear protection boost without writing to the register
            # to avoid fighting between the two systems.
            if self._sunset_active and self._sunset_boost_amps > 0:
                if self._protection_boost_amps > 0:
                    print(f"[PROTECTION] Yielding to sunset charging (sunset boost={self._sunset_boost_amps}A) - clearing protection boost silently")
                    self._protection_boost_amps = 0
                    self._protection_active = False
                    self._last_protection_adjustment = current_time
            else:
                # Verify inverter has caught up before reducing further
                if not self._is_charge_speed_settled(data, battery_voltage):
                    self.after(0, lambda: self.protection_panel.update_protection_state(
                        self._protection_active, self._protection_boost_amps
                    ))
                    return
                
                # Calculate proportional step: how many amps of headroom we have below target
                margin_power = target_power - export_power
                proportional_step = int(margin_power / battery_voltage) if battery_voltage > 0 else charge_step
                # Round to nearest charge_step multiple, minimum one step
                proportional_step = ((proportional_step + charge_step // 2) // charge_step) * charge_step
                step = max(charge_step, proportional_step)
                
                new_boost = max(0, self._protection_boost_amps - step)
                if new_boost != self._protection_boost_amps:
                    self._protection_boost_amps = new_boost
                    self._last_protection_adjustment = current_time
                    target_charge = base_charge + self._protection_boost_amps
                    
                    step_type = "PROPORTIONAL" if proportional_step > charge_step else "STEP"
                    if self._protection_boost_amps == 0:
                        self._protection_active = False
                        print(f"[PROTECTION] RECOVERED ({step_type} -{step}A): Back to base {target_charge}A")
                    else:
                        print(f"[PROTECTION] Reducing ({step_type} -{step}A) boost to +{self._protection_boost_amps}A = {target_charge}A")
                    
                    if self.inverter.set_max_charge_current(target_charge):
                        self._current_max_charge = target_charge
                        self._update_charge_display()
                        if self._protection_boost_amps == 0:
                            self._log_error(f"Protection: Recovered (-{step}A {step_type}), back to {target_charge}A")
                        else:
                            self._log_error(f"Protection: Reduced -{step}A ({step_type}) to {target_charge}A")
        
        # Update protection state display
        self.after(0, lambda: self.protection_panel.update_protection_state(
            self._protection_active, self._protection_boost_amps
        ))

    def _process_ev_charging(self, data: InverterData) -> None:
        """Process EV charger logic (called from background thread)."""
        if self.ev_logic is None:
            return

        ui_settings = self.ev_panel.get_settings()
        sunset_settings = self.sunset_panel.get_settings()

        settings = EVSettings(
            enabled=ui_settings["enabled"],
            min_amps=ui_settings["min_amps"],
            max_amps=ui_settings["max_amps"],
            stop_soc=ui_settings["stop_soc"],
            start_soc=ui_settings["start_soc"],
            solar_mode=ui_settings["solar_mode"],
            change_interval=ui_settings["change_interval"],
            battery_capacity_ah=sunset_settings.get("battery_capacity_ah", 0),
            charge_by_hour=ui_settings.get("charge_by_hour", 7),
            grid_charge=ui_settings.get("grid_charge", False),
            grid_charge_amps=ui_settings.get("grid_charge_amps", 20),
            solar_ramp_down_delay=ui_settings.get("solar_ramp_down_delay", 5),
            solar_amp_steps=ui_settings.get("solar_amp_steps", (8, 16, 24, 32)),
        )

        result, detail = self.ev_logic.process(data, settings)
        charger_state = self.ev_charger.get_state()

        # Log only on state changes to avoid spam
        # For solar charging, ignore wattage fluctuations — dedup on amps only
        if result == EVResult.SOLAR_CHARGING:
            import re
            m = re.search(r'(\d+)A', detail)
            ev_key = (result, m.group(1) if m else detail)
        else:
            ev_key = (result, detail)
        if ev_key != getattr(self, "_last_ev_key", None):
            self._last_ev_key = ev_key
            if result in (EVResult.CHARGING, EVResult.SOLAR_CHARGING,
                          EVResult.SOC_TOO_LOW, EVResult.STOPPED,
                          EVResult.CHARGER_OFFLINE, EVResult.BATTERY_PACED,
                          EVResult.GRID_CHARGING, EVResult.GRID_PULL_STOP):
                self._log_error(f"EV: {result.value} ({detail})")

        self.after(0, lambda: self.ev_panel.update_ev_state(
            connected=charger_state.is_connected,
            is_on=charger_state.is_on,
            charging=charger_state.is_charging,
            error_state=charger_state.error_state,
            current_amps=charger_state.current_amps,
            result_text=result.value,
            detail=detail,
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
            with self._inverter_lock:
                data = self.inverter.read_data()
            
                if data is not None:
                    self.after(0, self._update_dashboard, data)
                    self._process_logic(data)
                    # Process time-based charge schedule
                    self._process_schedule()
                    # Process overpower protection (may override schedule charge values)
                    self._process_overpower_protection(data)
                    # Process sunset charging (may further boost if needed to reach target by sunset)
                    self._process_sunset_charging(data)
                    # Process Tuya heat pump logic
                    self._process_heatpump(data)
                    # Process EV charger logic
                    self._process_ev_charging(data)
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
                outlet.config.phase_change_delay = int(self._get_safe_value(cfg_vars["phase_change_delay"], outlet.config.phase_change_delay))
                outlet.config.lv_recovery_voltage = float(self._get_safe_value(cfg_vars["lv_recovery_voltage"], outlet.config.lv_recovery_voltage))
                outlet.config.lv_recovery_delay = int(self._get_safe_value(cfg_vars["lv_recovery_delay"], outlet.config.lv_recovery_delay))
                outlet.config.headroom = int(self._get_safe_value(cfg_vars["headroom"], outlet.config.headroom))
                outlet.config.target_phase = cfg_vars["target_phase"].get()
                outlet.config.soc_enabled = cfg_vars["soc_enabled"].get()
                outlet.config.voltage_enabled = cfg_vars["voltage_enabled"].get()
                outlet.config.export_enabled = cfg_vars["export_enabled"].get()
                outlet.config.export_limit = int(self._get_safe_value(cfg_vars["export_limit"], outlet.config.export_limit))
                outlet.config.export_delay = int(self._get_safe_value(cfg_vars["export_delay"], outlet.config.export_delay))
                outlet.config.soc_delay = int(self._get_safe_value(cfg_vars["soc_delay"], outlet.config.soc_delay))
                outlet.config.off_grid_mode = cfg_vars["off_grid_mode"].get()
                outlet.config.on_grid_always_on = cfg_vars["on_grid_always_on"].get()
                outlet.config.restart_delay_enabled = cfg_vars["restart_delay_enabled"].get()
                outlet.config.restart_delay_minutes = int(self._get_safe_value(cfg_vars["restart_delay_minutes"], outlet.config.restart_delay_minutes))

    def _process_logic(self, data: InverterData) -> None:
        """Process EMS logic (called from background thread)."""
        outlets = self.tapo.get_all_outlets()
        if not outlets or not any(o.is_connected for o in outlets.values()):
            return
        
        # Sync outlet configs from UI
        self._sync_outlet_configs()
        
        params = self._get_ems_parameters()
        result, detail = self.ems.process(data, params)
        
        # Log turn-on events to the UI log panel (not just terminal)
        if result in (LogicResult.ON_HV_DUMP, LogicResult.ON_EXPORT_DUMP,
                      LogicResult.ON_AUTO_START, LogicResult.ON_GRID_ALWAYS_ON):
            self._log_error(f"EMS: {result.value} ({detail})")
        
        # Update UI
        color = EMSLogic.get_color_for_result(result)
        message = f"{result.value}" + (f" ({detail})" if detail else "")
        
        self.after(0, lambda: self.lbl_logic.configure(text=message, text_color=color))
        
        # Update invalid config visuals on outlet panels
        is_invalid = EMSLogic.is_error_result(result)
        for outlet_panel in self.outlet_settings.values():
            self.after(0, lambda p=outlet_panel: p.set_invalid_config(is_invalid))

    def _process_heatpump(self, data: InverterData) -> None:
        """Process Tuya heat pump logic (called from background thread)."""
        if self.hp_logic is None:
            return

        ui_settings = self.heatpump_panel.get_settings()

        settings = HeatpumpSettings(
            enabled=ui_settings["enabled"],
            schedules=ui_settings["schedules"],
            solar_override_enabled=ui_settings["solar_override_enabled"],
            solar_override_export_min=ui_settings["solar_override_export_min"],
            solar_override_hp_power=ui_settings["solar_override_hp_power"],
            solar_override_delay=ui_settings["solar_override_delay"],
            soc_on_threshold=ui_settings["soc_on_threshold"],
            soc_off_threshold=ui_settings["soc_off_threshold"],
            hv_threshold=ui_settings["hv_threshold"],
            hv_off_threshold=ui_settings["hv_off_threshold"],
            lv_threshold=ui_settings["lv_threshold"],
            lv_recovery_voltage=ui_settings["lv_recovery_voltage"],
            lv_recovery_delay=ui_settings["lv_recovery_delay"],
            phase_change_delay=ui_settings["phase_change_delay"],
        )

        result, detail = self.hp_logic.process(settings, data.grid_power, data.soc, data.voltages)
        hp_state = self.hp_manager.get_state()

        # Log only on state transitions (ignore detail changes within the same state)
        if result != getattr(self, "_last_hp_result", None):
            self._last_hp_result = result
            if result in (HeatpumpResult.SCHEDULE_ACTIVE, HeatpumpResult.SOLAR_OVERRIDE,
                          HeatpumpResult.SOC_OVERRIDE, HeatpumpResult.HV_OVERRIDE,
                          HeatpumpResult.LV_SHUTDOWN, HeatpumpResult.SOC_LOW,
                          HeatpumpResult.NO_SCHEDULE, HeatpumpResult.OFFLINE):
                self._log_error(f"HP: {result.value} ({detail})")

        self.after(0, lambda: self.heatpump_panel.update_hp_state(
            connected=hp_state.is_connected,
            is_on=hp_state.is_on,
            temperature=hp_state.temperature,
            target_temp=hp_state.target_temp,
            result_text=result.value,
            detail=detail,
        ))

    def destroy(self) -> None:
        """Clean up resources on window close."""
        self._running = False
        if self.hp_manager:
            self.hp_manager.stop()
        if self.ev_charger:
            self.ev_charger.stop()
        self.inverter.disconnect()
        super().destroy()


def main():
    """Application entry point."""
    log_file = setup_file_logging()
    try:
        app = DeyeApp()
        # Mark that main loop is starting (for safe error logging)
        app._main_loop_started = True
        app.mainloop()
    finally:
        log_file.close()


if __name__ == "__main__":
    main()
