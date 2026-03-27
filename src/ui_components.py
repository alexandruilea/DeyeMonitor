"""
UI Components for Deye Inverter EMS application.
"""

import customtkinter as ctk
from typing import List, Tuple, Callable

from src.config import protection_config, deye_config, sunset_config, ev_charger_config, default_schedules, heatpump_config, heatpump_schedules, HeatpumpScheduleSlot

# Default charge current limits (Amps) - loaded from config
DEFAULT_MAX_CHARGE_AMPS = deye_config.default_max_charge_amps
DEFAULT_GRID_CHARGE_AMPS = deye_config.default_grid_charge_amps
DEFAULT_MAX_DISCHARGE_AMPS = deye_config.default_max_discharge_amps

class PhaseDisplay(ctk.CTkFrame):
    """Display widget for a single phase (voltage, load bar, power)."""
    
    def __init__(self, parent, phase_name: str, **kwargs):
        super().__init__(parent, fg_color="#2B2B2B", **kwargs)
        self.phase_name = phase_name
        
        self.grid_columnconfigure(1, weight=1)
        
        # Voltage label
        self.lbl_voltage = ctk.CTkLabel(
            self, text="0.0 V",
            font=("Roboto", 22, "bold"),
            text_color="#00BFFF",
            width=110
        )
        self.lbl_voltage.grid(row=0, column=0, padx=10, rowspan=2)
        
        # Progress bar
        self.bar = ctk.CTkProgressBar(self, height=18)
        self.bar.grid(row=0, column=1, padx=10, sticky="ew", columnspan=1)
        self.bar.set(0)
        
        # UPS load label (backup port loads) - switched to first position, yellow
        self.lbl_ups = ctk.CTkLabel(
            self, text="UPS: 0 W",
            font=("Roboto", 20, "bold"),
            text_color="#FFA500",
            width=110
        )
        self.lbl_ups.grid(row=0, column=2, padx=(20, 5), rowspan=2)
        
        # Grid label (External CT readings) - switched to second position, dynamic color
        self.lbl_grid = ctk.CTkLabel(
            self, text="Grid: 0 W",
            font=("Roboto", 20, "bold"),
            text_color="#888888",
            width=110
        )
        self.lbl_grid.grid(row=0, column=3, padx=(5, 10), rowspan=2)

    def update(self, voltage: float, load: int, ups_load: int, max_load: int) -> None:
        """Update the phase display with new values."""
        self.lbl_voltage.configure(text=f"{voltage} V")
        self.lbl_ups.configure(text=f"UPS: {ups_load} W")
        
        # Grid: grey when importing (positive), green when exporting (negative)
        grid_color = "#2ECC71" if load < 0 else "#888888"
        self.lbl_grid.configure(text=f"Grid: {load} W", text_color=grid_color)
        
        # Use load (grid_loads) for progress bar
        self.bar.set(min(abs(load) / max_load, 1.0) if max_load > 0 else 0)
        self.bar.set(min(abs(load) / max_load, 1.0) if max_load > 0 else 0)


class OutletSettingsPanel(ctk.CTkFrame):
    """Settings panel for individual outlet configuration."""
    
    def __init__(self, parent, outlet_name: str, variables: dict, **kwargs):
        super().__init__(parent, fg_color="#1E1E1E", corner_radius=10, border_width=1, border_color="#333333", **kwargs)
        self.outlet_name = outlet_name
        self.variables = variables
        self.logic_widgets: List[Tuple[ctk.CTkLabel, ctk.CTkEntry]] = []
        
        self.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1, uniform="outlet")
        
        # Outlet title
        ctk.CTkLabel(
            self, text=f"{outlet_name} CONFIGURATION",
            font=("Roboto", 13, "bold"),
            text_color="#3498DB"
        ).grid(row=0, column=0, columnspan=4, pady=(10, 5), padx=10, sticky="w")
        
        # Off-Grid Mode toggle (top right)
        self.offgrid_switch = ctk.CTkSwitch(
            self, text="Off-Grid Mode",
            variable=variables["off_grid_mode"],
            font=("Roboto", 10, "bold")
        )
        self.offgrid_switch.grid(row=0, column=4, columnspan=2, sticky="e", padx=10, pady=(10, 5))
        
        # Row 1: SOC section with toggle
        self.soc_switch = ctk.CTkSwitch(
            self, text="SOC Trigger",
            variable=variables["soc_enabled"],
            font=("Roboto", 10, "bold")
        )
        self.soc_switch.grid(row=1, column=0, sticky="w", padx=10, pady=10)
        
        # On-Grid Always On switch (next to SOC Trigger)
        self.on_grid_always_on_switch = ctk.CTkSwitch(
            self, text="On-Grid Always On",
            variable=variables["on_grid_always_on"],
            font=("Roboto", 10, "bold")
        )
        self.on_grid_always_on_switch.grid(row=1, column=1, sticky="w", padx=0, pady=8)
        
        self._add_setting_v("Start SOC %", variables["start_soc"], 1, 2)
        self._add_setting_v("Stop SOC %", variables["stop_soc"], 1, 3)
        self._add_setting_v("Power W", variables["power"], 1, 4)
        self._add_setting_v("SOC Delay (s)", variables["soc_delay"], 1, 5)
        
        # Row 3: Headroom section (applies to all triggers)
        ctk.CTkLabel(
            self, text="Required Headroom:",
            font=("Roboto", 10, "bold"),
            text_color="#FFA500"
        ).grid(row=3, column=0, sticky="e", padx=5, pady=8)
        
        ctk.CTkEntry(
            self, textvariable=variables["headroom"], 
            width=85, justify="center"
        ).grid(row=3, column=1, sticky="w", padx=5, pady=8)
        
        ctk.CTkLabel(
            self, text="Available:",
            font=("Roboto", 10, "bold"),
            text_color="#FFA500"
        ).grid(row=3, column=2, sticky="e", padx=5, pady=8)
        
        self.lbl_headroom = ctk.CTkLabel(
            self, text="0 W",
            font=("Roboto", 11, "bold"),
            text_color="#2ECC71"
        )
        self.lbl_headroom.grid(row=3, column=3, sticky="w", padx=5, pady=8)
        
        # Row 4: Export section with toggle
        self.export_switch = ctk.CTkSwitch(
            self, text="Export Trigger",
            variable=variables["export_enabled"],
            font=("Roboto", 10, "bold")
        )
        self.export_switch.grid(row=4, column=0, sticky="w", padx=10, pady=8)
        
        self._add_setting_h("Min Export:", variables["export_limit"], 4, 1)
        self._add_setting_h("Delay (s):", variables["export_delay"], 4, 3)
        
        # Row 5: Voltage section with toggle and phase selector
        self.voltage_switch = ctk.CTkSwitch(
            self, text="Voltage Trigger",
            variable=variables["voltage_enabled"],
            font=("Roboto", 10, "bold")
        )
        self.voltage_switch.grid(row=5, column=0, sticky="w", padx=10, pady=8)
        
        ctk.CTkLabel(
            self, text="Phase:",
            font=("Roboto", 10, "bold")
        ).grid(row=5, column=1, sticky="e", padx=2, pady=8)
        
        self.phase_selector = ctk.CTkSegmentedButton(
            self, values=["L1", "L2", "L3", "ANY"],
            variable=variables["target_phase"],
            height=24
        )
        self.phase_selector.grid(row=5, column=2, sticky="w", padx=5, pady=8)
        
        self._add_setting_h("High V (ON):", variables["hv_threshold"], 5, 3)
        
        # Row 6: Voltage OFF parameters
        self._add_setting_h("Low V (OFF):", variables["lv_threshold"], 6, 1)
        self._add_setting_h("Phase Delay (s):", variables["phase_change_delay"], 6, 3)
        
        # Row 7: Low Voltage Recovery parameters (with slight extra spacing)
        self._add_setting_h("LV Recovery V:", variables["lv_recovery_voltage"], 7, 1, pady=(12, 10))
        self._add_setting_h("LV Recovery (s):", variables["lv_recovery_delay"], 7, 3, pady=(12, 10))
        
        # Row 8: Restart Delay - cooldown after outlet turns off before auto-restart
        self.restart_delay_switch = ctk.CTkSwitch(
            self, text="Restart Delay",
            variable=variables["restart_delay_enabled"],
            font=("Roboto", 10, "bold")
        )
        self.restart_delay_switch.grid(row=8, column=0, sticky="w", padx=10, pady=8)
        
        self._add_setting_h("Delay (min):", variables["restart_delay_minutes"], 8, 1)
    
    def update_headroom_status(self, available: int, required: int) -> None:
        """Update headroom status display with color coding."""
        if available >= required:
            color = "#2ECC71"  # Green - sufficient
            self.lbl_headroom.configure(text=f"{available} W", text_color=color)
        else:
            color = "#E74C3C"  # Red - insufficient
            self.lbl_headroom.configure(text=f"{available} W (need {required})", text_color=color)
    
    def _add_setting_v(self, label: str, var, row: int, col: int) -> None:
        """Add a vertical setting (label above entry)."""
        lbl = ctk.CTkLabel(self, text=label, font=("Roboto", 10))
        lbl.grid(row=row, column=col, pady=(0, 2))
        
        ent = ctk.CTkEntry(self, textvariable=var, width=85, justify="center")
        ent.grid(row=row + 1, column=col, padx=5, pady=(0, 10))
        
        self.logic_widgets.append((lbl, ent))
    
    def _add_setting_h(self, label: str, var, row: int, col: int, pady=8) -> None:
        """Add a horizontal setting (label left of entry)."""
        lbl = ctk.CTkLabel(self, text=label, font=("Roboto", 10, "bold"))
        lbl.grid(row=row, column=col, sticky="e", padx=2, pady=pady)
        
        ent = ctk.CTkEntry(self, textvariable=var, width=75, justify="center")
        ent.grid(row=row, column=col + 1, sticky="w", padx=2, pady=pady)
        
        self.logic_widgets.append((lbl, ent))
    
    def set_manual_mode_visuals(self, is_manual: bool) -> None:
        """Update visuals based on manual mode state."""
        color = "#E74C3C" if is_manual else "white"
        state = "disabled" if is_manual else "normal"
        
        for lbl, ent in self.logic_widgets:
            ent.configure(text_color=color, state=state)
            lbl.configure(text_color=color)
    
    def set_invalid_config(self, is_invalid: bool) -> None:
        """Set visual indicator for invalid configuration."""
        color = "#A569BD" if is_invalid else "white"
        for _, ent in self.logic_widgets:
            ent.configure(text_color=color)


class SettingsPanel(ctk.CTkFrame):
    """Settings panel for EMS configuration."""
    
    def __init__(self, parent, variables: dict, on_manual_toggle: callable, **kwargs):
        super().__init__(parent, **kwargs)
        self.variables = variables
        
        self.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1, uniform="ems")
        
        # Title
        ctk.CTkLabel(
            self, text="GLOBAL SAFETY CONFIGURATION",
            font=("Roboto", 14, "bold")
        ).grid(row=0, column=0, columnspan=6, pady=10)
        
        # Manual override switch
        self.man_switch = ctk.CTkSwitch(
            self, text="MANUAL OVERRIDE MODE",
            variable=variables["manual_mode"],
            command=on_manual_toggle,
            progress_color="#E74C3C",
            font=("Roboto", 12, "bold")
        )
        self.man_switch.grid(row=1, column=0, columnspan=6, pady=(0, 20))
        
        # Safety row
        ctk.CTkLabel(
            self, text="SAFETY:",
            font=("Roboto", 11, "bold"),
            text_color="#E74C3C"
        ).grid(row=2, column=0, sticky="e", pady=20, padx=10)
        
        self._add_setting_h("Max Phase W:", variables["phase_max"], 2, 1, is_safety=True)
        self._add_setting_h("Max UPS Total:", variables["max_ups_total_power"], 2, 3, is_safety=True)
        
        # Row 3: Critical voltage
        self._add_setting_h("Critical LV:", variables["safety_lv"], 2, 5, is_safety=True)

    def _add_setting_h(self, label: str, var, row: int, col: int, is_safety: bool = False) -> None:
        """Add a horizontal setting (label left of entry)."""
        lbl = ctk.CTkLabel(self, text=label, font=("Roboto", 11, "bold"))
        lbl.grid(row=row, column=col, sticky="e", padx=2)
        
        ent = ctk.CTkEntry(self, textvariable=var, width=75, justify="center")
        ent.grid(row=row, column=col + 1, sticky="w", padx=2)

    def set_manual_mode_visuals(self, is_manual: bool) -> None:
        """Update visuals based on manual mode state (safety params always enabled)."""
        pass


class StatusHeader(ctk.CTkFrame):
    """Header widget showing system status and main metrics."""
    
    def __init__(self, parent, bat_stats_command=None, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        
        self.grid_columnconfigure((0, 1, 2), weight=1)
        self.grid_columnconfigure(3, weight=0)
        
        # Status label
        self.lbl_status = ctk.CTkLabel(
            self, text="CONNECTING...",
            font=("Roboto", 24, "bold")
        )
        self.lbl_status.grid(row=0, column=0, columnspan=3, pady=10)
        
        # Solar label
        self.lbl_solar = ctk.CTkLabel(
            self, text="SOLAR\n0W",
            font=("Roboto", 22, "bold"),
            text_color="#FFD700"
        )
        self.lbl_solar.grid(row=1, column=0)
        
        # Battery/SOC label
        self.lbl_soc = ctk.CTkLabel(
            self, text="BATTERY\n0%",
            font=("Roboto", 22, "bold")
        )
        self.lbl_soc.grid(row=1, column=1)
        
        # Grid label
        self.lbl_grid = ctk.CTkLabel(
            self, text="GRID\n0W",
            font=("Roboto", 22, "bold")
        )
        self.lbl_grid.grid(row=1, column=2)
        
        # BatStats button (top-right corner)
        self.btn_batstats = ctk.CTkButton(
            self, text="BatStats",
            command=bat_stats_command,
            font=("Roboto", 14, "bold"),
            width=90, height=36,
            fg_color="#2C3E50",
            hover_color="#34495E",
            corner_radius=8,
        )
        self.btn_batstats.grid(row=0, column=3, rowspan=2, padx=(10, 15), pady=10, sticky="ne")

    def update_status(self, text: str, color: str, is_grid_connected: bool = True) -> None:
        """Update the status label with grid connection status."""
        grid_status = "ON-GRID" if is_grid_connected else "OFF-GRID"
        grid_color = "#2ECC71" if is_grid_connected else "#E74C3C"
        full_text = f"{text} - {grid_status}"
        # Use the main color for status, grid status color is shown in the text
        self.lbl_status.configure(text=full_text, text_color=grid_color)

    def update_solar(self, power: int) -> None:
        """Update solar power display."""
        self.lbl_solar.configure(text=f"SOLAR\n{power}W")

    def update_battery(self, soc: int, power: int) -> None:
        """Update battery display."""
        self.lbl_soc.configure(text=f"BATTERY\n{soc}% ({power}W)")

    def update_grid(self, power: int) -> None:
        """Update grid power display."""
        prefix = "+" if power >= 0 else ""
        color = "#2ECC71" if power < 0 else "#AAAAAA"
        self.lbl_grid.configure(text=f"GRID\n{prefix}{power}W", text_color=color)


class HeatPumpButton(ctk.CTkButton):
    """Button for controlling and displaying heat pump status."""
    
    STATE_SYNCING = "syncing"
    STATE_OFFLINE = "offline"
    STATE_RUNNING = "running"
    STATE_STANDBY = "standby"
    STATE_SWITCHING = "switching"
    
    COLORS = {
        STATE_SYNCING: "#3B3B3B",
        STATE_OFFLINE: "#3B3B3B",
        STATE_RUNNING: "#27AE60",
        STATE_STANDBY: "#C0392B",
        STATE_SWITCHING: "#F39C12",
    }
    
    LABELS = {
        STATE_SYNCING: "HP: SYNCING",
        STATE_OFFLINE: "HP: TAPO OFFLINE",
        STATE_RUNNING: "HEAT PUMP: RUNNING",
        STATE_STANDBY: "HEAT PUMP: STANDBY",
        STATE_SWITCHING: "HP: SWITCHING...",
    }
    
    def __init__(self, parent, command, **kwargs):
        super().__init__(
            parent,
            text=self.LABELS[self.STATE_SYNCING],
            command=command,
            font=("Roboto", 20, "bold"),
            height=70,
            hover=False,
            **kwargs
        )
        self._current_state = self.STATE_SYNCING

    def set_state(self, state: str) -> None:
        """Set the button state."""
        if state in self.LABELS:
            self._current_state = state
            self.configure(
                text=self.LABELS[state],
                fg_color=self.COLORS[state]
            )

class OutletButton(ctk.CTkButton):
    """Button for controlling and displaying individual outlet status."""
    
    STATE_SYNCING = "syncing"
    STATE_OFFLINE = "offline"
    STATE_RUNNING = "running"
    STATE_STANDBY = "standby"
    STATE_SWITCHING = "switching"
    
    COLORS = {
        STATE_SYNCING: "#3B3B3B",
        STATE_OFFLINE: "#3B3B3B",
        STATE_RUNNING: "#27AE60",
        STATE_STANDBY: "#C0392B",
        STATE_SWITCHING: "#F39C12",
    }
    
    def __init__(self, parent, outlet_name: str, power: int, command, **kwargs):
        self.outlet_name = outlet_name
        self.power = power
        super().__init__(
            parent,
            text=self._format_text(self.STATE_SYNCING),
            command=command,
            font=("Roboto", 16, "bold"),
            height=60,
            hover=False,
            **kwargs
        )
        self._current_state = self.STATE_SYNCING

    def _format_text(self, state: str) -> str:
        """Format the button text based on state."""
        if state == self.STATE_SYNCING:
            return f"{self.outlet_name}: SYNCING"
        elif state == self.STATE_OFFLINE:
            return f"{self.outlet_name}: OFFLINE"
        elif state == self.STATE_RUNNING:
            return f"{self.outlet_name}: ON ({self.power}W)"
        elif state == self.STATE_STANDBY:
            return f"{self.outlet_name}: OFF"
        elif state == self.STATE_SWITCHING:
            return f"{self.outlet_name}: SWITCHING..."
        return f"{self.outlet_name}"

    def set_state(self, state: str) -> None:
        """Set the button state."""
        if state in self.COLORS:
            self._current_state = state
            self.configure(
                text=self._format_text(state),
                fg_color=self.COLORS[state]
            )


class ErrorLogViewer(ctk.CTkScrollableFrame):
    """Scrollable frame for displaying system errors and logs."""
    
    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color="#1A1A1A", height=150, **kwargs)
        
        self.grid_columnconfigure(0, weight=1)
        
        # Title
        self.lbl_title = ctk.CTkLabel(
            self, text="System Log",
            font=("Roboto", 12, "bold"),
            text_color="#888888"
        )
        self.lbl_title.grid(row=0, column=0, sticky="w", padx=10, pady=(5, 0))
        
        # Log container
        self.log_text = ctk.CTkTextbox(
            self, 
            font=("Consolas", 10),
            fg_color="#0D0D0D",
            text_color="#00FF00",
            wrap="word",
            state="disabled"
        )
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        
        self.grid_rowconfigure(1, weight=1)
        
        self._max_lines = 100
    
    def add_log(self, message: str) -> None:
        """Add a log message."""
        import datetime
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        
        self.log_text.configure(state="normal")
        self.log_text.insert("end", log_entry)
        
        # Auto-scroll to bottom
        self.log_text.see("end")
        
        # Limit number of lines
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > self._max_lines:
            self.log_text.delete("1.0", f"{line_count - self._max_lines}.0")
        
        self.log_text.configure(state="disabled")
    
    def clear_logs(self) -> None:
        """Clear all log messages."""
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

class TimeScheduleRow(ctk.CTkFrame):
    """A single row in the time schedule representing one time interval."""
    
    def __init__(self, parent, index: int, on_delete: Callable, on_value_change: Callable = None, **kwargs):
        super().__init__(parent, fg_color="#2B2B2B", corner_radius=5, **kwargs)
        self.index = index
        self.on_delete = on_delete
        self.on_value_change = on_value_change
        
        # Track if fields have been modified (dirty flag)
        self._dirty = False
        
        # Don't use weight on time columns to keep them compact
        
        # Enable checkbox
        self.enabled_var = ctk.BooleanVar(value=True)
        self.chk_enabled = ctk.CTkCheckBox(
            self, text="",
            variable=self.enabled_var,
            width=20
        )
        self.chk_enabled.grid(row=0, column=0, padx=(5, 10), pady=8)
        
        # Start time - grouped together
        ctk.CTkLabel(self, text="From:", font=("Roboto", 10)).grid(row=0, column=1, padx=(0, 2), sticky="e")
        self.start_hour = ctk.CTkEntry(self, width=40, justify="center", placeholder_text="HH")
        self.start_hour.grid(row=0, column=2, padx=0)
        self.start_hour.insert(0, "00")
        
        ctk.CTkLabel(self, text=":", font=("Roboto", 10, "bold")).grid(row=0, column=3, padx=0)
        self.start_min = ctk.CTkEntry(self, width=40, justify="center", placeholder_text="MM")
        self.start_min.grid(row=0, column=4, padx=0)
        self.start_min.insert(0, "00")
        
        # End time - grouped together
        ctk.CTkLabel(self, text="To:", font=("Roboto", 10)).grid(row=0, column=5, padx=(35, 2), sticky="e")
        self.end_hour = ctk.CTkEntry(self, width=40, justify="center", placeholder_text="HH")
        self.end_hour.grid(row=0, column=6, padx=0)
        self.end_hour.insert(0, "23")
        
        ctk.CTkLabel(self, text=":", font=("Roboto", 10, "bold")).grid(row=0, column=7, padx=0)
        self.end_min = ctk.CTkEntry(self, width=40, justify="center", placeholder_text="MM")
        self.end_min.grid(row=0, column=8, padx=0)
        self.end_min.insert(0, "59")
        
        # Max Charge Amps
        ctk.CTkLabel(self, text="Max Charge:", font=("Roboto", 10), text_color="#2ECC71").grid(row=0, column=9, padx=(50, 2))
        self.max_charge = ctk.CTkEntry(self, width=60, justify="center")
        self.max_charge.grid(row=0, column=10, padx=2)
        self.max_charge.insert(0, str(DEFAULT_MAX_CHARGE_AMPS))
        self.max_charge.bind("<Key>", lambda e: self._mark_dirty())
        self.max_charge.bind("<FocusOut>", lambda e: self._on_field_change())
        ctk.CTkLabel(self, text="A", font=("Roboto", 10)).grid(row=0, column=11, padx=(0, 20))
        
        # Grid Charge Amps
        ctk.CTkLabel(self, text="Grid Charge:", font=("Roboto", 10), text_color="#3498DB").grid(row=0, column=12, padx=(30, 2))
        self.grid_charge = ctk.CTkEntry(self, width=60, justify="center")
        self.grid_charge.grid(row=0, column=13, padx=2)
        self.grid_charge.insert(0, str(DEFAULT_GRID_CHARGE_AMPS))
        self.grid_charge.bind("<Key>", lambda e: self._mark_dirty())
        self.grid_charge.bind("<FocusOut>", lambda e: self._on_field_change())
        ctk.CTkLabel(self, text="A", font=("Roboto", 10)).grid(row=0, column=14, padx=(0, 20))
        
        # Max Discharge Amps
        ctk.CTkLabel(self, text="Max Discharge:", font=("Roboto", 10), text_color="#E67E22").grid(row=0, column=15, padx=(30, 2))
        self.max_discharge = ctk.CTkEntry(self, width=60, justify="center")
        self.max_discharge.grid(row=0, column=16, padx=2)
        self.max_discharge.insert(0, str(DEFAULT_MAX_DISCHARGE_AMPS))
        self.max_discharge.bind("<Key>", lambda e: self._mark_dirty())
        self.max_discharge.bind("<FocusOut>", lambda e: self._on_field_change())
        ctk.CTkLabel(self, text="A", font=("Roboto", 10)).grid(row=0, column=17, padx=(0, 10))
        
        # Battery SELL switch
        self.sell_var = ctk.BooleanVar(value=False)
        self.sw_sell = ctk.CTkSwitch(
            self, text="Battery SELL",
            variable=self.sell_var,
            font=("Roboto", 10, "bold"),
            text_color="#E74C3C",
            width=40,
            command=lambda: (self._mark_dirty(), self._on_field_change())
        )
        self.sw_sell.grid(row=0, column=18, padx=(15, 5))
        
        # Max Sell Power (W)
        ctk.CTkLabel(self, text="Sell Power:", font=("Roboto", 10), text_color="#E74C3C").grid(row=0, column=19, padx=(5, 2))
        self.sell_power = ctk.CTkEntry(self, width=70, justify="center")
        self.sell_power.grid(row=0, column=20, padx=2)
        self.sell_power.insert(0, "0")
        self.sell_power.bind("<Key>", lambda e: self._mark_dirty())
        self.sell_power.bind("<FocusOut>", lambda e: self._on_field_change())
        ctk.CTkLabel(self, text="W", font=("Roboto", 10)).grid(row=0, column=21, padx=(0, 5))
        
        # Add a spacer column to push delete button to the right
        self.grid_columnconfigure(22, weight=1)
        
        # Delete button
        self.btn_delete = ctk.CTkButton(
            self, text="✕", width=30, height=24,
            fg_color="#E74C3C", hover_color="#C0392B",
            command=lambda: self.on_delete(self.index)
        )
        self.btn_delete.grid(row=0, column=23, padx=(5, 10))
    
    def _mark_dirty(self) -> None:
        """Mark this row as having been edited."""
        self._dirty = True
    
    def _on_field_change(self) -> None:
        """Called when a field loses focus."""
        if self._dirty and self.on_value_change:
            self._dirty = False
            self.on_value_change()
    
    def get_schedule(self) -> dict:
        """Get the schedule data from this row."""
        try:
            return {
                "enabled": self.enabled_var.get(),
                "start_hour": int(self.start_hour.get()),
                "start_min": int(self.start_min.get()),
                "end_hour": int(self.end_hour.get()),
                "end_min": int(self.end_min.get()),
                "max_charge_amps": int(self.max_charge.get()),
                "grid_charge_amps": int(self.grid_charge.get()),
                "max_discharge_amps": int(self.max_discharge.get()),
                "sell": self.sell_var.get(),
                "sell_power": int(self.sell_power.get()),
            }
        except ValueError:
            return None
    
    def set_schedule(self, data: dict) -> None:
        """Set the schedule data for this row."""
        self.enabled_var.set(data.get("enabled", True))
        
        self.start_hour.delete(0, "end")
        self.start_hour.insert(0, str(data.get("start_hour", 0)).zfill(2))
        
        self.start_min.delete(0, "end")
        self.start_min.insert(0, str(data.get("start_min", 0)).zfill(2))
        
        self.end_hour.delete(0, "end")
        self.end_hour.insert(0, str(data.get("end_hour", 23)).zfill(2))
        
        self.end_min.delete(0, "end")
        self.end_min.insert(0, str(data.get("end_min", 59)).zfill(2))
        
        self.max_charge.delete(0, "end")
        self.max_charge.insert(0, str(data.get("max_charge_amps", DEFAULT_MAX_CHARGE_AMPS)))
        
        self.grid_charge.delete(0, "end")
        self.grid_charge.insert(0, str(data.get("grid_charge_amps", DEFAULT_GRID_CHARGE_AMPS)))
        
        self.max_discharge.delete(0, "end")
        self.max_discharge.insert(0, str(data.get("max_discharge_amps", DEFAULT_MAX_DISCHARGE_AMPS)))
        
        self.sell_var.set(data.get("sell", False))
        
        self.sell_power.delete(0, "end")
        self.sell_power.insert(0, str(data.get("sell_power", 0)))


class TimeSchedulePanel(ctk.CTkFrame):
    """Panel for configuring time-based charge schedules."""
    
    def __init__(self, parent, on_schedule_change: Callable = None, **kwargs):
        super().__init__(parent, fg_color="#1E1E1E", corner_radius=10, border_width=1, border_color="#333333", **kwargs)
        self.on_schedule_change = on_schedule_change
        self.schedule_rows: List[TimeScheduleRow] = []
        
        self.grid_columnconfigure(0, weight=1)
        
        # Header
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        header_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(
            header_frame, text="⏰ CHARGE / SELL SCHEDULE",
            font=("Roboto", 14, "bold"),
            text_color="#F39C12"
        ).grid(row=0, column=0, sticky="w")
        
        # Enable/Disable switch
        self.enabled_var = ctk.BooleanVar(value=True)
        self.enable_switch = ctk.CTkSwitch(
            header_frame, text="Enable Schedule",
            variable=self.enabled_var,
            font=("Roboto", 11, "bold"),
            command=self._on_enable_toggle
        )
        self.enable_switch.grid(row=0, column=1, padx=20)
        
        # Status label
        self.lbl_status = ctk.CTkLabel(
            header_frame, text="Active",
            font=("Roboto", 11),
            text_color="#2ECC71"
        )
        self.lbl_status.grid(row=0, column=2, sticky="e", padx=10)
        
        # Default values frame (shown when disabled)
        self.defaults_frame = ctk.CTkFrame(header_frame, fg_color="#2B2B2B", corner_radius=5)
        self.defaults_frame.grid(row=0, column=3, sticky="e", padx=5)
        
        ctk.CTkLabel(
            self.defaults_frame, text="Defaults:",
            font=("Roboto", 10, "bold"),
            text_color="#888888"
        ).grid(row=0, column=0, padx=(8, 5), pady=5)
        
        ctk.CTkLabel(
            self.defaults_frame, text="Max:",
            font=("Roboto", 10),
            text_color="#2ECC71"
        ).grid(row=0, column=1, padx=2, pady=5)
        
        self.default_max_charge = ctk.CTkEntry(self.defaults_frame, width=45, justify="center")
        self.default_max_charge.grid(row=0, column=2, padx=2, pady=5)
        self.default_max_charge.insert(0, str(DEFAULT_MAX_CHARGE_AMPS))
        
        ctk.CTkLabel(
            self.defaults_frame, text="A",
            font=("Roboto", 10)
        ).grid(row=0, column=3, padx=(0, 8), pady=5)
        
        ctk.CTkLabel(
            self.defaults_frame, text="Grid:",
            font=("Roboto", 10),
            text_color="#3498DB"
        ).grid(row=0, column=4, padx=2, pady=5)
        
        self.default_grid_charge = ctk.CTkEntry(self.defaults_frame, width=45, justify="center")
        self.default_grid_charge.grid(row=0, column=5, padx=2, pady=5)
        self.default_grid_charge.insert(0, str(DEFAULT_GRID_CHARGE_AMPS))
        
        ctk.CTkLabel(
            self.defaults_frame, text="A",
            font=("Roboto", 10)
        ).grid(row=0, column=6, padx=(0, 8), pady=5)
        
        ctk.CTkLabel(
            self.defaults_frame, text="Discharge:",
            font=("Roboto", 10),
            text_color="#E67E22"
        ).grid(row=0, column=7, padx=2, pady=5)
        
        self.default_max_discharge = ctk.CTkEntry(self.defaults_frame, width=45, justify="center")
        self.default_max_discharge.grid(row=0, column=8, padx=2, pady=5)
        self.default_max_discharge.insert(0, str(DEFAULT_MAX_DISCHARGE_AMPS))
        
        ctk.CTkLabel(
            self.defaults_frame, text="A",
            font=("Roboto", 10)
        ).grid(row=0, column=9, padx=(0, 8), pady=5)
        
        # Add button
        self.btn_add = ctk.CTkButton(
            header_frame, text="+ Add Time Slot",
            width=120, height=28,
            fg_color="#27AE60", hover_color="#1E8449",
            command=self._add_row
        )
        self.btn_add.grid(row=0, column=4, sticky="e", padx=(10, 0))
        
        # Container for schedule rows
        self.rows_container = ctk.CTkFrame(self, fg_color="transparent")
        self.rows_container.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        self.rows_container.grid_columnconfigure(0, weight=1)
        
        # Info label
        self.lbl_info = ctk.CTkLabel(
            self, text="Add time slots to automatically adjust charge settings during specific hours.",
            font=("Roboto", 10),
            text_color="#888888"
        )
        self.lbl_info.grid(row=2, column=0, pady=(5, 10))
        
        # Add default schedule rows from .env (SCHEDULE_N variables)
        for sched in default_schedules:
            self._add_row()
            self.schedule_rows[-1].set_schedule(sched)
    
    def _on_enable_toggle(self) -> None:
        """Handle enable/disable toggle."""
        if self.enabled_var.get():
            self.lbl_status.configure(text="Active", text_color="#2ECC71")
        else:
            self.lbl_status.configure(text="Disabled", text_color="gray")
        
        if self.on_schedule_change:
            self.on_schedule_change()
    
    def _on_row_value_change(self) -> None:
        """Called when a row value changes (field loses focus)."""
        # Only trigger re-evaluation if schedule is enabled
        if self.enabled_var.get() and self.on_schedule_change:
            self.on_schedule_change()
    
    def _add_row(self) -> None:
        """Add a new schedule row."""
        index = len(self.schedule_rows)
        row = TimeScheduleRow(self.rows_container, index, self._delete_row, on_value_change=self._on_row_value_change)
        row.grid(row=index, column=0, sticky="ew", pady=3)
        self.schedule_rows.append(row)
        
        # Hide info label when we have rows
        if self.schedule_rows:
            self.lbl_info.grid_forget()
    
    def _delete_row(self, index: int) -> None:
        """Delete a schedule row."""
        if 0 <= index < len(self.schedule_rows):
            self.schedule_rows[index].destroy()
            self.schedule_rows.pop(index)
            
            # Re-index remaining rows
            for i, row in enumerate(self.schedule_rows):
                row.index = i
                row.grid(row=i, column=0, sticky="ew", pady=3)
        
        # Show info label if no rows
        if not self.schedule_rows:
            self.lbl_info.grid(row=2, column=0, pady=(5, 10))
    
    def is_enabled(self) -> bool:
        """Check if scheduling is enabled."""
        return self.enabled_var.get()
    
    def get_active_schedule(self) -> dict:
        """
        Get the currently active schedule based on current time.
        Returns None if no schedule is active or scheduling is disabled.
        """
        if not self.enabled_var.get():
            return None
        
        import datetime
        now = datetime.datetime.now()
        current_minutes = now.hour * 60 + now.minute
        
        for row in self.schedule_rows:
            schedule = row.get_schedule()
            if schedule is None or not schedule["enabled"]:
                continue
            
            start_minutes = schedule["start_hour"] * 60 + schedule["start_min"]
            end_minutes = schedule["end_hour"] * 60 + schedule["end_min"]
            
            # Handle overnight schedules (e.g., 22:00 to 06:00)
            if start_minutes <= end_minutes:
                # Normal case: same day
                if start_minutes <= current_minutes < end_minutes:
                    return schedule
            else:
                # Overnight case
                if current_minutes >= start_minutes or current_minutes < end_minutes:
                    return schedule
        
        return None
    
    def get_all_schedules(self) -> List[dict]:
        """Get all schedule configurations."""
        schedules = []
        for row in self.schedule_rows:
            schedule = row.get_schedule()
            if schedule:
                schedules.append(schedule)
        return schedules
    
    def get_default_values(self) -> dict:
        """Get the default charge values to apply when no schedule is active."""
        try:
            return {
                "max_charge_amps": int(self.default_max_charge.get()),
                "grid_charge_amps": int(self.default_grid_charge.get()),
                "max_discharge_amps": int(self.default_max_discharge.get()),
                "sell": False,
                "sell_power": 0,
            }
        except ValueError:
            return {"max_charge_amps": 60, "grid_charge_amps": 40, "max_discharge_amps": 150, "sell": False, "sell_power": 0}
    
    def update_status(self, active_schedule: dict = None) -> None:
        """Update the status label to show current state."""
        if not self.enabled_var.get():
            self.lbl_status.configure(text="Disabled", text_color="gray")
        elif active_schedule:
            start = f"{active_schedule['start_hour']:02d}:{active_schedule['start_min']:02d}"
            end = f"{active_schedule['end_hour']:02d}:{active_schedule['end_min']:02d}"
            sell_info = f" Sell:{active_schedule['sell_power']}W" if active_schedule.get('sell') else ""
            self.lbl_status.configure(
                text=f"Active: {start}-{end} | Max:{active_schedule['max_charge_amps']}A Grid:{active_schedule['grid_charge_amps']}A Discharge:{active_schedule['max_discharge_amps']}A{sell_info}",
                text_color="#2ECC71"
            )
        else:
            self.lbl_status.configure(text="No active slot (using defaults)", text_color="#F39C12")


class OverpowerProtectionPanel(ctk.CTkFrame):
    """
    Panel for configuring overpower/overvoltage protection.
    
    Automatically increases charging speed when:
    - Export power approaches the max sell power limit
    - Phase voltage exceeds the warning threshold
    
    This helps prevent inverter shutdown due to grid overvoltage or power limits.
    """
    
    def __init__(self, parent, on_settings_change: Callable = None, **kwargs):
        super().__init__(parent, fg_color="#1E1E1E", corner_radius=10, border_width=1, border_color="#333333", **kwargs)
        self.on_settings_change = on_settings_change
        
        self.grid_columnconfigure(0, weight=1)
        
        # Header
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        header_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(
            header_frame, text="⚡ BATTERY BOOST PROTECTION",
            font=("Roboto", 14, "bold"),
            text_color="#E74C3C"
        ).grid(row=0, column=0, sticky="w")
        
        # Enable/Disable switch
        self.enabled_var = ctk.BooleanVar(value=protection_config.enabled_at_startup)
        self.enable_switch = ctk.CTkSwitch(
            header_frame, text="Enable Protection",
            variable=self.enabled_var,
            font=("Roboto", 11, "bold"),
            command=self._on_enable_toggle
        )
        self.enable_switch.grid(row=0, column=1, padx=20)
        if protection_config.enabled_at_startup:
            self.enable_switch.select()
        
        # Status label
        _startup_enabled = protection_config.enabled_at_startup
        self.lbl_status = ctk.CTkLabel(
            header_frame, text="Active" if _startup_enabled else "Disabled",
            font=("Roboto", 11),
            text_color="#2ECC71" if _startup_enabled else "gray"
        )
        self.lbl_status.grid(row=0, column=2, sticky="e", padx=10)
        
        # Settings container
        settings_frame = ctk.CTkFrame(self, fg_color="#2B2B2B", corner_radius=5)
        settings_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        settings_frame.grid_columnconfigure((1, 3, 5, 7, 9), weight=1)
        
        # Max Sell Power (W)
        ctk.CTkLabel(
            settings_frame, text="Max Sell Power:",
            font=("Roboto", 10, "bold"),
            text_color="#E74C3C"
        ).grid(row=0, column=0, padx=(10, 5), pady=8, sticky="w")
        
        self.max_sell_power = ctk.CTkEntry(settings_frame, width=70, justify="center")
        self.max_sell_power.grid(row=0, column=1, padx=5, pady=8)
        self.max_sell_power.insert(0, str(protection_config.max_sell_power))
        
        ctk.CTkLabel(settings_frame, text="W", font=("Roboto", 10)).grid(row=0, column=2, padx=(0, 10), pady=8)
        
        # Power threshold (%)
        ctk.CTkLabel(
            settings_frame, text="Power Threshold:",
            font=("Roboto", 10),
            text_color="#F39C12"
        ).grid(row=0, column=3, padx=5, pady=8, sticky="w")
        
        self.power_threshold = ctk.CTkEntry(settings_frame, width=50, justify="center")
        self.power_threshold.grid(row=0, column=4, padx=5, pady=8)
        self.power_threshold.insert(0, str(protection_config.power_threshold_pct))
        
        ctk.CTkLabel(settings_frame, text="%", font=("Roboto", 10)).grid(row=0, column=5, padx=(0, 10), pady=8)
        
        # Voltage warning threshold (V)
        ctk.CTkLabel(
            settings_frame, text="Voltage Warning:",
            font=("Roboto", 10),
            text_color="#F39C12"
        ).grid(row=0, column=6, padx=5, pady=8, sticky="w")
        
        self.voltage_warning = ctk.CTkEntry(settings_frame, width=60, justify="center")
        self.voltage_warning.grid(row=0, column=7, padx=5, pady=8)
        self.voltage_warning.insert(0, str(protection_config.voltage_warning))
        self.voltage_warning.bind("<FocusOut>", self._on_warning_changed)
        
        ctk.CTkLabel(settings_frame, text="V", font=("Roboto", 10)).grid(row=0, column=8, padx=(0, 10), pady=8)
        
        # Adjustment interval
        ctk.CTkLabel(
            settings_frame, text="Interval:",
            font=("Roboto", 10),
            text_color="#95A5A6"
        ).grid(row=0, column=9, padx=5, pady=8, sticky="w")
        
        self.adjustment_interval = ctk.CTkEntry(settings_frame, width=50, justify="center")
        self.adjustment_interval.grid(row=0, column=10, padx=5, pady=8)
        self.adjustment_interval.insert(0, str(protection_config.adjustment_interval))
        
        ctk.CTkLabel(settings_frame, text="s", font=("Roboto", 10)).grid(row=0, column=11, padx=(0, 10), pady=8)
        
        # Second row: Step size and recovery settings
        ctk.CTkLabel(
            settings_frame, text="Charge Step:",
            font=("Roboto", 10),
            text_color="#2ECC71"
        ).grid(row=1, column=0, padx=(10, 5), pady=8, sticky="w")
        
        self.charge_step = ctk.CTkEntry(settings_frame, width=50, justify="center")
        self.charge_step.grid(row=1, column=1, padx=5, pady=8)
        self.charge_step.insert(0, str(protection_config.charge_step))
        
        ctk.CTkLabel(settings_frame, text="A", font=("Roboto", 10)).grid(row=1, column=2, padx=(0, 10), pady=8)
        
        # Recovery threshold (%) - when to start stepping down
        ctk.CTkLabel(
            settings_frame, text="Recovery at:",
            font=("Roboto", 10),
            text_color="#3498DB"
        ).grid(row=1, column=3, padx=5, pady=8, sticky="w")
        
        self.recovery_threshold = ctk.CTkEntry(settings_frame, width=50, justify="center")
        self.recovery_threshold.grid(row=1, column=4, padx=5, pady=8)
        self.recovery_threshold.insert(0, str(protection_config.recovery_threshold_pct))
        
        ctk.CTkLabel(settings_frame, text="%", font=("Roboto", 10)).grid(row=1, column=5, padx=(0, 10), pady=8)
        
        # Voltage recovery (V)
        ctk.CTkLabel(
            settings_frame, text="Voltage Recovery:",
            font=("Roboto", 10),
            text_color="#3498DB"
        ).grid(row=1, column=6, padx=5, pady=8, sticky="w")
        
        self.voltage_recovery = ctk.CTkEntry(settings_frame, width=55, justify="center")
        self.voltage_recovery.grid(row=1, column=7, padx=5, pady=8)
        self.voltage_recovery.insert(0, str(protection_config.voltage_recovery))
        
        ctk.CTkLabel(settings_frame, text="V", font=("Roboto", 10)).grid(row=1, column=8, padx=(0, 10), pady=8)
        
        # Voltage hold margin (V) - keeps boost while voltage is within this margin of warning
        ctk.CTkLabel(
            settings_frame, text="V Hold:",
            font=("Roboto", 10),
            text_color="#9B59B6"
        ).grid(row=1, column=9, padx=5, pady=8, sticky="w")
        
        self.voltage_hold_margin = ctk.CTkEntry(settings_frame, width=50, justify="center")
        self.voltage_hold_margin.grid(row=1, column=10, padx=5, pady=8)
        self.voltage_hold_margin.insert(0, str(protection_config.voltage_hold_margin))
        
        ctk.CTkLabel(settings_frame, text="V", font=("Roboto", 10)).grid(row=1, column=11, padx=(0, 10), pady=8)
        
        # Current state display
        state_frame = ctk.CTkFrame(self, fg_color="transparent")
        state_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)
        state_frame.grid_columnconfigure((0, 1, 2), weight=1)
        
        self.lbl_power_state = ctk.CTkLabel(
            state_frame, text="Export: -- W / -- W",
            font=("Roboto", 11),
            text_color="#888888"
        )
        self.lbl_power_state.grid(row=0, column=0, sticky="w", padx=10)
        
        self.lbl_voltage_state = ctk.CTkLabel(
            state_frame, text="Max Voltage: -- V",
            font=("Roboto", 11),
            text_color="#888888"
        )
        self.lbl_voltage_state.grid(row=0, column=1)
        
        self.lbl_protection_state = ctk.CTkLabel(
            state_frame, text="Protection: Inactive",
            font=("Roboto", 11),
            text_color="gray"
        )
        self.lbl_protection_state.grid(row=0, column=2, sticky="e", padx=10)
        
        # Info label
        ctk.CTkLabel(
            self, text="Absorbs excess power into battery by increasing charge speed when export or voltage limits are approached.",
            font=("Roboto", 10),
            text_color="#888888"
        ).grid(row=3, column=0, pady=(5, 10))
    
    def _on_enable_toggle(self) -> None:
        """Handle enable/disable toggle."""
        if self.enabled_var.get():
            self.lbl_status.configure(text="Active", text_color="#2ECC71")
        else:
            self.lbl_status.configure(text="Disabled", text_color="gray")
            self.lbl_protection_state.configure(text="Protection: Inactive", text_color="gray")
        
        if self.on_settings_change:
            self.on_settings_change()
    
    def is_enabled(self) -> bool:
        """Check if protection is enabled."""
        return self.enabled_var.get()

    def set_enabled(self, enabled: bool) -> None:
        """Programmatically enable or disable the protection."""
        self.enabled_var.set(enabled)
        if enabled:
            self.enable_switch.select()
            self.lbl_status.configure(text="Active", text_color="#2ECC71")
        else:
            self.enable_switch.deselect()
            self.lbl_status.configure(text="Disabled (Selling)", text_color="#F39C12")
            self.lbl_protection_state.configure(text="Protection: Paused by sell mode", text_color="#F39C12")
        if self.on_settings_change:
            self.on_settings_change()

    def set_max_sell_power(self, power: int) -> None:
        """Set the max sell power value (e.g., from inverter reading)."""
        self.max_sell_power.delete(0, "end")
        self.max_sell_power.insert(0, str(power))
    
    def _on_warning_changed(self, event=None) -> None:
        """
        When voltage warning is modified, auto-adjust recovery to warning - 2V.
        User can then manually adjust recovery if needed.
        """
        try:
            warning = float(self.voltage_warning.get())
            new_recovery = round(warning - 2.0, 1)
            self.voltage_recovery.delete(0, "end")
            self.voltage_recovery.insert(0, str(new_recovery))
        except ValueError:
            pass  # Ignore if value can't be parsed
    
    def get_settings(self) -> dict:
        """Get current protection settings."""
        try:
            return {
                "enabled": self.enabled_var.get(),
                "max_sell_power": int(self.max_sell_power.get()),
                "power_threshold_pct": int(self.power_threshold.get()),
                "recovery_threshold_pct": int(self.recovery_threshold.get()),
                "voltage_warning": float(self.voltage_warning.get()),
                "voltage_recovery": float(self.voltage_recovery.get()),
                "voltage_hold_margin": float(self.voltage_hold_margin.get()),
                "charge_step": int(self.charge_step.get()),
                "adjustment_interval": protection_config.adjustment_interval,
            }
        except ValueError:
            # Return defaults on parse error
            return {
                "enabled": False,
                "max_sell_power": protection_config.max_sell_power,
                "power_threshold_pct": protection_config.power_threshold_pct,
                "recovery_threshold_pct": protection_config.recovery_threshold_pct,
                "voltage_warning": protection_config.voltage_warning,
                "voltage_recovery": protection_config.voltage_recovery,
                "voltage_hold_margin": protection_config.voltage_hold_margin,
                "charge_step": protection_config.charge_step,
                "adjustment_interval": protection_config.adjustment_interval,
            }
    
    def update_state_display(self, export_power: int, max_sell: int, max_voltage: float) -> None:
        """Update the state display labels."""
        # Export power display
        export_pct = (export_power / max_sell * 100) if max_sell > 0 else 0
        power_color = "#E74C3C" if export_pct > 95 else "#F39C12" if export_pct > 85 else "#888888"
        self.lbl_power_state.configure(
            text=f"Export: {export_power} W / {max_sell} W ({export_pct:.0f}%)",
            text_color=power_color
        )
        
        # Voltage display
        voltage_warning = float(self.voltage_warning.get()) if self.voltage_warning.get() else protection_config.voltage_warning
        voltage_color = "#E74C3C" if max_voltage > voltage_warning else "#888888"
        self.lbl_voltage_state.configure(
            text=f"Max Voltage: {max_voltage:.1f} V",
            text_color=voltage_color
        )
    
    def update_protection_state(self, active: bool, boost_amps: int = 0, bms_limited: bool = False) -> None:
        """Update the protection state label."""
        if not self.enabled_var.get():
            self.lbl_protection_state.configure(text="Protection: Disabled", text_color="gray")
        elif active:
            suffix = " BMS_Limit" if bms_limited else ""
            self.lbl_protection_state.configure(
                text=f"Protection: ACTIVE (+{boost_amps}A boost){suffix}",
                text_color="#E74C3C"
            )
        else:
            suffix = " BMS_Limit" if bms_limited else ""
            self.lbl_protection_state.configure(text=f"Protection: Standby{suffix}", text_color="#F39C12" if bms_limited else "#2ECC71")


class SunsetChargingPanel(ctk.CTkFrame):
    """
    Panel for sunset-aware charging.
    
    Calculates sunset time astronomically and dynamically adjusts max charge rate
    to ensure the battery reaches the target SOC by sunset.
    """
    
    def __init__(self, parent, on_settings_change: Callable = None, **kwargs):
        super().__init__(parent, fg_color="#1E1E1E", corner_radius=10, border_width=1, border_color="#333333", **kwargs)
        self.on_settings_change = on_settings_change
        
        self.grid_columnconfigure(0, weight=1)
        
        # Header
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        header_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(
            header_frame, text="\u2600 SUNSET CHARGING",
            font=("Roboto", 14, "bold"),
            text_color="#F39C12"
        ).grid(row=0, column=0, sticky="w")
        
        # Enable/Disable switch
        self.enabled_var = ctk.BooleanVar(value=sunset_config.enabled_at_startup)
        self.enable_switch = ctk.CTkSwitch(
            header_frame, text="Enable",
            variable=self.enabled_var,
            font=("Roboto", 11, "bold"),
            command=self._on_enable_toggle
        )
        self.enable_switch.grid(row=0, column=1, padx=20)
        if sunset_config.enabled_at_startup:
            self.enable_switch.select()
        
        # Status label
        _startup_enabled = sunset_config.enabled_at_startup
        self.lbl_status = ctk.CTkLabel(
            header_frame, text="Active" if _startup_enabled else "Disabled",
            font=("Roboto", 11),
            text_color="#2ECC71" if _startup_enabled else "gray"
        )
        self.lbl_status.grid(row=0, column=2, sticky="e", padx=10)
        
        # Settings container
        settings_frame = ctk.CTkFrame(self, fg_color="#2B2B2B", corner_radius=5)
        settings_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        settings_frame.grid_columnconfigure((1, 3, 5, 7, 9, 11), weight=1)
        
        # Latitude
        ctk.CTkLabel(settings_frame, text="Lat:", font=("Roboto", 10, "bold"),
                      text_color="#F39C12").grid(row=0, column=0, padx=(10, 2), pady=8, sticky="w")
        self.latitude = ctk.CTkEntry(settings_frame, width=65, justify="center")
        self.latitude.grid(row=0, column=1, padx=2, pady=8)
        self.latitude.insert(0, str(sunset_config.latitude))
        
        # Longitude
        ctk.CTkLabel(settings_frame, text="Lon:", font=("Roboto", 10, "bold"),
                      text_color="#F39C12").grid(row=0, column=2, padx=(10, 2), pady=8, sticky="w")
        self.longitude = ctk.CTkEntry(settings_frame, width=65, justify="center")
        self.longitude.grid(row=0, column=3, padx=2, pady=8)
        self.longitude.insert(0, str(sunset_config.longitude))
        
        # Battery Capacity (Ah)
        ctk.CTkLabel(settings_frame, text="Battery:", font=("Roboto", 10),
                      text_color="#3498DB").grid(row=0, column=4, padx=(10, 2), pady=8, sticky="w")
        self.battery_capacity = ctk.CTkEntry(settings_frame, width=55, justify="center")
        self.battery_capacity.grid(row=0, column=5, padx=2, pady=8)
        self.battery_capacity.insert(0, str(sunset_config.battery_capacity_ah))
        ctk.CTkLabel(settings_frame, text="Ah", font=("Roboto", 10)).grid(row=0, column=6, padx=(0, 5), pady=8)
        
        # Target SOC
        ctk.CTkLabel(settings_frame, text="Target:", font=("Roboto", 10),
                      text_color="#2ECC71").grid(row=0, column=7, padx=(10, 2), pady=8, sticky="w")
        self.target_soc = ctk.CTkEntry(settings_frame, width=45, justify="center")
        self.target_soc.grid(row=0, column=8, padx=2, pady=8)
        self.target_soc.insert(0, str(sunset_config.target_soc))
        ctk.CTkLabel(settings_frame, text="%", font=("Roboto", 10)).grid(row=0, column=9, padx=(0, 5), pady=8)
        
        # Buffer time before sunset
        ctk.CTkLabel(settings_frame, text="Buffer:", font=("Roboto", 10),
                      text_color="#95A5A6").grid(row=0, column=10, padx=(10, 2), pady=8, sticky="w")
        self.buffer_minutes = ctk.CTkEntry(settings_frame, width=45, justify="center")
        self.buffer_minutes.grid(row=0, column=11, padx=2, pady=8)
        self.buffer_minutes.insert(0, str(sunset_config.buffer_minutes))
        ctk.CTkLabel(settings_frame, text="min", font=("Roboto", 10)).grid(row=0, column=12, padx=(0, 10), pady=8)
        
        # Second row: Min charge amps + Peak solar hour
        ctk.CTkLabel(settings_frame, text="Min Charge:", font=("Roboto", 10),
                      text_color="#2ECC71").grid(row=1, column=0, padx=(10, 2), pady=8, sticky="w")
        self.min_charge = ctk.CTkEntry(settings_frame, width=45, justify="center")
        self.min_charge.grid(row=1, column=1, padx=2, pady=8)
        self.min_charge.insert(0, str(sunset_config.min_charge_amps))
        ctk.CTkLabel(settings_frame, text="A", font=("Roboto", 10)).grid(row=1, column=2, padx=(0, 5), pady=8, sticky="w")

        # Peak solar hour (0 = auto / solar noon)
        ctk.CTkLabel(settings_frame, text="Peak Hour:", font=("Roboto", 10),
                      text_color="#F39C12").grid(row=1, column=4, padx=(10, 2), pady=8, sticky="w")
        self.peak_solar_hour = ctk.CTkEntry(settings_frame, width=50, justify="center")
        self.peak_solar_hour.grid(row=1, column=5, padx=2, pady=8)
        self.peak_solar_hour.insert(0, str(sunset_config.peak_solar_hour) if sunset_config.peak_solar_hour > 0 else "auto")
        ctk.CTkLabel(settings_frame, text="(0=auto)", font=("Roboto", 9),
                      text_color="#777").grid(row=1, column=6, padx=(0, 5), pady=8, sticky="w")

        # Third row: Cloudy day compensation
        ctk.CTkLabel(settings_frame, text="Peak kW:", font=("Roboto", 10),
                      text_color="#E67E22").grid(row=2, column=0, padx=(10, 2), pady=8, sticky="w")
        self.peak_expected_kw = ctk.CTkEntry(settings_frame, width=50, justify="center")
        self.peak_expected_kw.grid(row=2, column=1, padx=2, pady=8)
        self.peak_expected_kw.insert(0, str(sunset_config.peak_expected_kw) if sunset_config.peak_expected_kw > 0 else "off")
        ctk.CTkLabel(settings_frame, text="kW", font=("Roboto", 10)).grid(row=2, column=2, padx=(0, 5), pady=8, sticky="w")

        ctk.CTkLabel(settings_frame, text="Cloud Thr:", font=("Roboto", 10),
                      text_color="#E67E22").grid(row=2, column=4, padx=(10, 2), pady=8, sticky="w")
        self.cloud_threshold = ctk.CTkEntry(settings_frame, width=40, justify="center")
        self.cloud_threshold.grid(row=2, column=5, padx=2, pady=8)
        self.cloud_threshold.insert(0, str(sunset_config.cloud_threshold_pct))
        ctk.CTkLabel(settings_frame, text="%", font=("Roboto", 10)).grid(row=2, column=6, padx=(0, 5), pady=8, sticky="w")

        ctk.CTkLabel(settings_frame, text="Max Boost:", font=("Roboto", 10),
                      text_color="#E67E22").grid(row=2, column=7, padx=(10, 2), pady=8, sticky="w")
        self.cloud_max_boost = ctk.CTkEntry(settings_frame, width=40, justify="center")
        self.cloud_max_boost.grid(row=2, column=8, padx=2, pady=8)
        self.cloud_max_boost.insert(0, str(sunset_config.cloud_max_boost))
        ctk.CTkLabel(settings_frame, text="x", font=("Roboto", 10)).grid(row=2, column=9, padx=(0, 5), pady=8, sticky="w")
        
        # State display
        state_frame = ctk.CTkFrame(self, fg_color="#2B2B2B", corner_radius=5)
        state_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        state_frame.grid_columnconfigure((0, 1, 2), weight=1)
        
        self.lbl_sunset_time = ctk.CTkLabel(
            state_frame, text="Sunset: --:--",
            font=("Roboto", 11, "bold"), text_color="#F39C12"
        )
        self.lbl_sunset_time.grid(row=0, column=0, padx=10, pady=5, sticky="w")
        
        self.lbl_time_remaining = ctk.CTkLabel(
            state_frame, text="Time left: --h --m",
            font=("Roboto", 11, "bold"), text_color="#95A5A6"
        )
        self.lbl_time_remaining.grid(row=0, column=1, padx=10, pady=5)
        
        self.lbl_required_amps = ctk.CTkLabel(
            state_frame, text="Required: --A",
            font=("Roboto", 11, "bold"), text_color="#3498DB"
        )
        self.lbl_required_amps.grid(row=0, column=2, padx=10, pady=5, sticky="e")
    
    def _on_enable_toggle(self) -> None:
        """Handle enable/disable toggle."""
        enabled = self.enabled_var.get()
        self.lbl_status.configure(
            text="Active" if enabled else "Disabled",
            text_color="#2ECC71" if enabled else "gray"
        )
        if self.on_settings_change:
            self.on_settings_change()
    
    def is_enabled(self) -> bool:
        return self.enabled_var.get()
    
    def _parse_peak_solar_hour(self) -> float:
        """Parse peak solar hour field. Returns 0.0 for 'auto' or empty."""
        raw = self.peak_solar_hour.get().strip().lower()
        if raw in ("", "auto", "0", "0.0"):
            return 0.0
        return float(raw)

    def _parse_peak_expected_kw(self) -> float:
        """Parse peak expected kW field. Returns 0.0 for 'off' or empty."""
        raw = self.peak_expected_kw.get().strip().lower()
        if raw in ("", "off", "0", "0.0"):
            return 0.0
        return float(raw)

    def get_settings(self) -> dict:
        """Get current settings from UI fields."""
        try:
            return {
                "latitude": float(self.latitude.get()),
                "longitude": float(self.longitude.get()),
                "battery_capacity_ah": int(self.battery_capacity.get()),
                "target_soc": int(self.target_soc.get()),
                "buffer_minutes": int(self.buffer_minutes.get()),
                "min_charge_amps": int(self.min_charge.get()),
                "peak_solar_hour": self._parse_peak_solar_hour(),
                "peak_expected_kw": self._parse_peak_expected_kw(),
                "cloud_threshold_pct": int(self.cloud_threshold.get()),
                "cloud_max_boost": float(self.cloud_max_boost.get()),
            }
        except (ValueError, TypeError):
            return {
                "latitude": sunset_config.latitude,
                "longitude": sunset_config.longitude,
                "battery_capacity_ah": sunset_config.battery_capacity_ah,
                "target_soc": sunset_config.target_soc,
                "buffer_minutes": sunset_config.buffer_minutes,
                "min_charge_amps": sunset_config.min_charge_amps,
                "peak_solar_hour": sunset_config.peak_solar_hour,
                "peak_expected_kw": sunset_config.peak_expected_kw,
                "cloud_threshold_pct": sunset_config.cloud_threshold_pct,
                "cloud_max_boost": sunset_config.cloud_max_boost,
            }
    
    def update_state(self, sunset_str: str, hours_left: float, required_amps: int, active: bool,
                      cloud_boost: float = 1.0) -> None:
        """Update the state display labels."""
        self.lbl_sunset_time.configure(text=f"Sunset: {sunset_str}")
        
        if hours_left is not None and hours_left > 0:
            h = int(hours_left)
            m = int((hours_left - h) * 60)
            self.lbl_time_remaining.configure(
                text=f"Time left: {h}h {m:02d}m",
                text_color="#F39C12" if hours_left < 2 else "#95A5A6"
            )
        else:
            self.lbl_time_remaining.configure(text="After sunset", text_color="#E74C3C")
        
        if active:
            color = "#E74C3C" if required_amps > 100 else "#F39C12" if required_amps > 50 else "#2ECC71"
            cloud_str = f" \u2601{cloud_boost:.1f}x" if cloud_boost > 1.05 else ""
            self.lbl_required_amps.configure(text=f"Required: {required_amps}A{cloud_str}", text_color=color)
        else:
            self.lbl_required_amps.configure(text="Standby", text_color="gray")


class EVChargerPanel(ctk.CTkFrame):
    """
    Panel for EV smart charger control via Tuya.

    Provides min/max amps, SOC thresholds, solar-follow mode, and a
    configurable cooldown between changes.
    """

    def __init__(self, parent, on_settings_change: Callable = None, **kwargs):
        super().__init__(parent, fg_color="#1E1E1E", corner_radius=10,
                         border_width=1, border_color="#333333", **kwargs)
        self.on_settings_change = on_settings_change
        self.grid_columnconfigure(0, weight=1)

        # ── Header ──────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header, text="\U0001F50C EV SMART CHARGER",
            font=("Roboto", 14, "bold"), text_color="#1ABC9C"
        ).grid(row=0, column=0, sticky="w")

        self.enabled_var = ctk.BooleanVar(value=ev_charger_config.enabled)
        self.enable_switch = ctk.CTkSwitch(
            header, text="Enable", variable=self.enabled_var,
            font=("Roboto", 11, "bold"), command=self._on_enable_toggle
        )
        self.enable_switch.grid(row=0, column=1, padx=20)
        if ev_charger_config.enabled:
            self.enable_switch.select()

        _startup = ev_charger_config.enabled
        self.lbl_status = ctk.CTkLabel(
            header,
            text="Active" if _startup else "Disabled",
            font=("Roboto", 11),
            text_color="#2ECC71" if _startup else "gray"
        )
        self.lbl_status.grid(row=0, column=2, sticky="e", padx=10)

        # ── Settings row 1: amps, SOC thresholds ────────────────────
        sf = ctk.CTkFrame(self, fg_color="#2B2B2B", corner_radius=5)
        sf.grid(row=1, column=0, sticky="ew", padx=10, pady=5)
        sf.grid_columnconfigure((1, 3, 5, 7, 9, 11, 15), weight=1)

        ctk.CTkLabel(sf, text="Min Amps:", font=("Roboto", 10, "bold"),
                      text_color="#1ABC9C").grid(row=0, column=0, padx=(10, 5), pady=8, sticky="w")
        self.min_amps = ctk.CTkEntry(sf, width=50, justify="center")
        self.min_amps.grid(row=0, column=1, padx=5, pady=8)
        self.min_amps.insert(0, str(ev_charger_config.min_amps))
        ctk.CTkLabel(sf, text="A", font=("Roboto", 10)).grid(row=0, column=2, padx=(0, 10), pady=8)

        ctk.CTkLabel(sf, text="Max Amps:", font=("Roboto", 10, "bold"),
                      text_color="#1ABC9C").grid(row=0, column=3, padx=5, pady=8, sticky="w")
        self.max_amps = ctk.CTkEntry(sf, width=50, justify="center")
        self.max_amps.grid(row=0, column=4, padx=5, pady=8)
        self.max_amps.insert(0, str(ev_charger_config.max_amps))
        ctk.CTkLabel(sf, text="A", font=("Roboto", 10)).grid(row=0, column=5, padx=(0, 10), pady=8)

        ctk.CTkLabel(sf, text="Start SOC:", font=("Roboto", 10)).grid(row=0, column=6, padx=5, pady=8, sticky="w")
        self.start_soc = ctk.CTkEntry(sf, width=50, justify="center")
        self.start_soc.grid(row=0, column=7, padx=5, pady=8)
        self.start_soc.insert(0, str(ev_charger_config.start_soc))
        ctk.CTkLabel(sf, text="%", font=("Roboto", 10)).grid(row=0, column=8, padx=(0, 10), pady=8)

        ctk.CTkLabel(sf, text="Stop SOC:", font=("Roboto", 10)).grid(row=0, column=9, padx=5, pady=8, sticky="w")
        self.stop_soc = ctk.CTkEntry(sf, width=50, justify="center")
        self.stop_soc.grid(row=0, column=10, padx=5, pady=8)
        self.stop_soc.insert(0, str(ev_charger_config.stop_soc))
        ctk.CTkLabel(sf, text="%", font=("Roboto", 10)).grid(row=0, column=11, padx=(0, 10), pady=8)

        ctk.CTkLabel(sf, text="Charge by:", font=("Roboto", 10),
                      text_color="#95A5A6").grid(row=0, column=12, padx=5, pady=8, sticky="w")
        self.charge_by_hour = ctk.CTkEntry(sf, width=50, justify="center")
        self.charge_by_hour.grid(row=0, column=13, padx=5, pady=8)
        self.charge_by_hour.insert(0, f"{ev_charger_config.charge_by_hour}:00")
        ctk.CTkLabel(sf, text="h", font=("Roboto", 10)).grid(row=0, column=14, padx=(0, 10), pady=8)

        # ── Settings row 2: cooldown & solar mode ───────────────────
        ctk.CTkLabel(sf, text="Cooldown:", font=("Roboto", 10),
                      text_color="#95A5A6").grid(row=1, column=0, padx=(10, 5), pady=8, sticky="w")
        self.change_interval = ctk.CTkEntry(sf, width=50, justify="center")
        self.change_interval.grid(row=1, column=1, padx=5, pady=8)
        self.change_interval.insert(0, str(ev_charger_config.change_interval_minutes))
        ctk.CTkLabel(sf, text="min", font=("Roboto", 10)).grid(row=1, column=2, padx=(0, 10), pady=8)

        self.solar_var = ctk.BooleanVar(value=ev_charger_config.solar_mode)
        self.solar_switch = ctk.CTkSwitch(
            sf, text="Solar Follow (ramp amps to solar export)",
            variable=self.solar_var,
            font=("Roboto", 10, "bold"),
            command=self._on_solar_toggle
        )
        self.solar_switch.grid(row=1, column=3, columnspan=5, padx=10, pady=8, sticky="w")
        if ev_charger_config.solar_mode:
            self.solar_switch.select()

        # Grid charge switch + amps (end of row 2)
        self.grid_charge_var = ctk.BooleanVar(value=False)
        self.grid_charge_switch = ctk.CTkSwitch(
            sf, text="Grid charge at",
            variable=self.grid_charge_var,
            font=("Roboto", 10, "bold"),
        )
        self.grid_charge_switch.grid(row=1, column=8, columnspan=3, padx=(15, 5), pady=8, sticky="w")

        self.grid_charge_amps = ctk.CTkEntry(sf, width=50, justify="center")
        self.grid_charge_amps.grid(row=1, column=11, padx=2, pady=8)
        self.grid_charge_amps.insert(0, str(ev_charger_config.grid_charge_amps))
        ctk.CTkLabel(sf, text="A", font=("Roboto", 10)).grid(row=1, column=12, padx=(0, 10), pady=8)

        # ── Settings row 3: solar ramp-down ─────────────────────────
        ctk.CTkLabel(sf, text="Ramp ↓ delay:", font=("Roboto", 10),
                      text_color="#95A5A6").grid(row=2, column=0, padx=(10, 5), pady=8, sticky="w")
        self.ramp_down_delay = ctk.CTkEntry(sf, width=50, justify="center")
        self.ramp_down_delay.grid(row=2, column=1, padx=5, pady=8)
        self.ramp_down_delay.insert(0, str(ev_charger_config.solar_ramp_down_delay))
        ctk.CTkLabel(sf, text="min", font=("Roboto", 10)).grid(row=2, column=2, padx=(0, 10), pady=8)

        ctk.CTkLabel(sf, text="Amp steps:", font=("Roboto", 10),
                      text_color="#95A5A6").grid(row=2, column=3, padx=(10, 5), pady=8, sticky="w")
        self.amp_steps = ctk.CTkEntry(sf, width=100, justify="center")
        self.amp_steps.grid(row=2, column=4, columnspan=3, padx=5, pady=8)
        self.amp_steps.insert(0, ",".join(str(s) for s in ev_charger_config.solar_amp_steps))
        ctk.CTkLabel(sf, text="A", font=("Roboto", 10)).grid(row=2, column=7, padx=(0, 10), pady=8)

        # ── Live state display ──────────────────────────────────────
        state = ctk.CTkFrame(self, fg_color="#2B2B2B", corner_radius=5)
        state.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 5))
        state.grid_columnconfigure((0, 1, 2), weight=1)

        self.lbl_charger_status = ctk.CTkLabel(
            state, text="Charger: --",
            font=("Roboto", 11, "bold"), text_color="#888888"
        )
        self.lbl_charger_status.grid(row=0, column=0, padx=10, pady=5, sticky="w")

        self.lbl_ev_amps = ctk.CTkLabel(
            state, text="Amps: --",
            font=("Roboto", 11, "bold"), text_color="#888888"
        )
        self.lbl_ev_amps.grid(row=0, column=1, padx=10, pady=5)

        self.lbl_ev_result = ctk.CTkLabel(
            state, text="--",
            font=("Roboto", 11, "bold"), text_color="gray"
        )
        self.lbl_ev_result.grid(row=0, column=2, padx=10, pady=5, sticky="e")

        # ── Info ────────────────────────────────────────────────────
        ctk.CTkLabel(
            self,
            text="Controls a Tuya EV charger based on battery SOC and solar export. "
                 "Changes are rate-limited to the configured cooldown.",
            font=("Roboto", 10), text_color="#888888"
        ).grid(row=3, column=0, pady=(5, 10))

    # ── Callbacks ────────────────────────────────────────────────────

    def _on_enable_toggle(self) -> None:
        enabled = self.enabled_var.get()
        self.lbl_status.configure(
            text="Active" if enabled else "Disabled",
            text_color="#2ECC71" if enabled else "gray"
        )
        if self.on_settings_change:
            self.on_settings_change()

    def _on_solar_toggle(self) -> None:
        if self.on_settings_change:
            self.on_settings_change()

    # ── Public API ───────────────────────────────────────────────────

    def is_enabled(self) -> bool:
        return self.enabled_var.get()

    def get_settings(self) -> dict:
        """Return current settings as a dict matching EVSettings fields."""
        try:
            return {
                "enabled": self.enabled_var.get(),
                "min_amps": int(self.min_amps.get()),
                "max_amps": int(self.max_amps.get()),
                "stop_soc": int(self.stop_soc.get()),
                "start_soc": int(self.start_soc.get()),
                "solar_mode": self.solar_var.get(),
                "change_interval": int(self.change_interval.get()),
                "charge_by_hour": max(0, min(23, int(self.charge_by_hour.get().split(":")[0]))),
                "grid_charge": self.grid_charge_var.get(),
                "grid_charge_amps": int(self.grid_charge_amps.get()),
                "solar_ramp_down_delay": int(self.ramp_down_delay.get()),
                "solar_amp_steps": tuple(int(x.strip()) for x in self.amp_steps.get().split(",")),
            }
        except (ValueError, TypeError):
            return {
                "enabled": False,
                "min_amps": ev_charger_config.min_amps,
                "max_amps": ev_charger_config.max_amps,
                "stop_soc": ev_charger_config.stop_soc,
                "start_soc": ev_charger_config.start_soc,
                "solar_mode": ev_charger_config.solar_mode,
                "change_interval": ev_charger_config.change_interval_minutes,
                "charge_by_hour": ev_charger_config.charge_by_hour,
                "grid_charge": False,
                "grid_charge_amps": ev_charger_config.grid_charge_amps,
                "solar_ramp_down_delay": ev_charger_config.solar_ramp_down_delay,
                "solar_amp_steps": ev_charger_config.solar_amp_steps,
            }
    def update_ev_state(self, connected: bool, is_on: bool, charging: bool,
                        error_state: str, current_amps: int, result_text: str,
                        detail: str) -> None:
        """Update the live state display labels."""
        # Charger connection status
        if not connected:
            self.lbl_charger_status.configure(text="Charger: Offline", text_color="#E74C3C")
        elif error_state:
            self.lbl_charger_status.configure(text=f"Charger: Error ({error_state})", text_color="#E74C3C")
        elif charging:
            self.lbl_charger_status.configure(text="Charger: Charging", text_color="#2ECC71")
        elif is_on:
            self.lbl_charger_status.configure(text="Charger: ON (waiting for EV)", text_color="#F39C12")
        else:
            self.lbl_charger_status.configure(text="Charger: Standby", text_color="#888888")

        # Current amps
        if connected:
            self.lbl_ev_amps.configure(
                text=f"Amps: {current_amps}A",
                text_color="#1ABC9C" if charging else "#888888"
            )
        else:
            self.lbl_ev_amps.configure(text="Amps: --", text_color="#888888")

        # Logic result
        full = f"{result_text}: {detail}" if detail else result_text
        color_map = {
            "Battery Paced": "#3498DB",
            "Charging": "#2ECC71",
            "Solar Charging": "#1ABC9C",
            "Grid Charging": "#1ABC9C",
            "Grid Pull Stop": "#E74C3C",
            "Cooldown": "#F39C12",
            "Stopped": "#E74C3C",
            "Battery SOC too low": "#E74C3C",
            "Waiting for SOC": "#95A5A6",
            "Idle": "#888888",
            "EV Disabled": "gray",
            "Charger Offline": "#E74C3C",
        }
        self.lbl_ev_result.configure(text=full, text_color=color_map.get(result_text, "#888888"))


class HeatpumpScheduleRow(ctk.CTkFrame):
    """A single row in the heat pump temperature schedule."""

    def __init__(self, parent, index: int, on_delete: Callable, on_value_change: Callable = None, **kwargs):
        super().__init__(parent, fg_color="#2B2B2B", corner_radius=5, **kwargs)
        self.index = index
        self.on_delete = on_delete
        self.on_value_change = on_value_change
        self._dirty = False

        # Enable checkbox
        self.enabled_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(self, text="", variable=self.enabled_var, width=20).grid(
            row=0, column=0, padx=(5, 10), pady=8)

        # Start time
        ctk.CTkLabel(self, text="From:", font=("Roboto", 10)).grid(row=0, column=1, padx=(0, 2), sticky="e")
        self.start_hour = ctk.CTkEntry(self, width=40, justify="center", placeholder_text="HH")
        self.start_hour.grid(row=0, column=2, padx=0)
        self.start_hour.insert(0, "00")
        ctk.CTkLabel(self, text=":", font=("Roboto", 10, "bold")).grid(row=0, column=3, padx=0)
        self.start_min = ctk.CTkEntry(self, width=40, justify="center", placeholder_text="MM")
        self.start_min.grid(row=0, column=4, padx=0)
        self.start_min.insert(0, "00")

        # End time
        ctk.CTkLabel(self, text="To:", font=("Roboto", 10)).grid(row=0, column=5, padx=(35, 2), sticky="e")
        self.end_hour = ctk.CTkEntry(self, width=40, justify="center", placeholder_text="HH")
        self.end_hour.grid(row=0, column=6, padx=0)
        self.end_hour.insert(0, "23")
        ctk.CTkLabel(self, text=":", font=("Roboto", 10, "bold")).grid(row=0, column=7, padx=0)
        self.end_min = ctk.CTkEntry(self, width=40, justify="center", placeholder_text="MM")
        self.end_min.grid(row=0, column=8, padx=0)
        self.end_min.insert(0, "59")

        # Min temperature
        ctk.CTkLabel(self, text="Min Temp:", font=("Roboto", 10, "bold"),
                      text_color="#E74C3C").grid(row=0, column=9, padx=(50, 2))
        self.min_temp = ctk.CTkEntry(self, width=60, justify="center")
        self.min_temp.grid(row=0, column=10, padx=2)
        self.min_temp.insert(0, "28")
        self.min_temp.bind("<Key>", lambda e: self._mark_dirty())
        self.min_temp.bind("<FocusOut>", lambda e: self._on_field_change())
        ctk.CTkLabel(self, text="°C", font=("Roboto", 10)).grid(row=0, column=11, padx=(0, 20))

        # Max temperature
        ctk.CTkLabel(self, text="Max Temp:", font=("Roboto", 10, "bold"),
                      text_color="#2ECC71").grid(row=0, column=12, padx=(30, 2))
        self.max_temp = ctk.CTkEntry(self, width=60, justify="center")
        self.max_temp.grid(row=0, column=13, padx=2)
        self.max_temp.insert(0, "35")
        self.max_temp.bind("<Key>", lambda e: self._mark_dirty())
        self.max_temp.bind("<FocusOut>", lambda e: self._on_field_change())
        ctk.CTkLabel(self, text="°C", font=("Roboto", 10)).grid(row=0, column=14, padx=(0, 10))

        # Spacer + delete button
        self.grid_columnconfigure(15, weight=1)
        ctk.CTkButton(
            self, text="✕", width=30, height=24,
            fg_color="#E74C3C", hover_color="#C0392B",
            command=lambda: self.on_delete(self.index)
        ).grid(row=0, column=16, padx=(5, 10))

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _on_field_change(self) -> None:
        if self._dirty and self.on_value_change:
            self._dirty = False
            self.on_value_change()

    def get_schedule(self) -> dict:
        try:
            return {
                "enabled": self.enabled_var.get(),
                "start_hour": int(self.start_hour.get()),
                "start_min": int(self.start_min.get()),
                "end_hour": int(self.end_hour.get()),
                "end_min": int(self.end_min.get()),
                "min_temp": float(self.min_temp.get()),
                "max_temp": float(self.max_temp.get()),
            }
        except ValueError:
            return None

    def set_schedule(self, slot: HeatpumpScheduleSlot) -> None:
        self.start_hour.delete(0, "end")
        self.start_hour.insert(0, str(slot.start_hour).zfill(2))
        self.start_min.delete(0, "end")
        self.start_min.insert(0, str(slot.start_min).zfill(2))
        self.end_hour.delete(0, "end")
        self.end_hour.insert(0, str(slot.end_hour).zfill(2))
        self.end_min.delete(0, "end")
        self.end_min.insert(0, str(slot.end_min).zfill(2))
        self.min_temp.delete(0, "end")
        self.min_temp.insert(0, str(slot.min_temp))
        self.max_temp.delete(0, "end")
        self.max_temp.insert(0, str(slot.max_temp))


class HeatpumpPanel(ctk.CTkFrame):
    """
    Panel for Tuya heat pump control with temperature-based scheduling.

    Features:
    - Time-interval temperature schedules (min/max °C per slot)
    - Solar override: keep running when excess solar available
    - Live temperature and state display
    """

    def __init__(self, parent, on_settings_change: Callable = None, **kwargs):
        super().__init__(parent, fg_color="#1E1E1E", corner_radius=10,
                         border_width=1, border_color="#333333", **kwargs)
        self.on_settings_change = on_settings_change
        self.schedule_rows: List[HeatpumpScheduleRow] = []
        self.grid_columnconfigure(0, weight=1)

        # ── Header ──────────────────────────────────────────────────
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header, text="\U0001F525 HEAT PUMP - Socket Thermostat (Tuya)",
            font=("Roboto", 14, "bold"), text_color="#E67E22"
        ).grid(row=0, column=0, sticky="w")

        self.enabled_var = ctk.BooleanVar(value=heatpump_config.enabled)
        self.enable_switch = ctk.CTkSwitch(
            header, text="Enable", variable=self.enabled_var,
            font=("Roboto", 11, "bold"), command=self._on_enable_toggle
        )
        self.enable_switch.grid(row=0, column=1, padx=20)
        if heatpump_config.enabled:
            self.enable_switch.select()

        _startup = heatpump_config.enabled
        self.lbl_status = ctk.CTkLabel(
            header,
            text="Active" if _startup else "Disabled",
            font=("Roboto", 11),
            text_color="#2ECC71" if _startup else "gray"
        )
        self.lbl_status.grid(row=0, column=2, sticky="e", padx=10)

        # ── Settings row: solar override ────────────────────────────
        sf = ctk.CTkFrame(self, fg_color="#2B2B2B", corner_radius=5)
        sf.grid(row=1, column=0, sticky="ew", padx=10, pady=5)

        self.solar_override_var = ctk.BooleanVar(value=heatpump_config.solar_override_enabled)
        self.solar_switch = ctk.CTkSwitch(
            sf, text="Solar Override",
            variable=self.solar_override_var,
            font=("Roboto", 10, "bold"),
        )
        self.solar_switch.grid(row=0, column=0, padx=10, pady=8, sticky="w")
        if heatpump_config.solar_override_enabled:
            self.solar_switch.select()

        ctk.CTkLabel(sf, text="Trigger:", font=("Roboto", 10, "bold"),
                      text_color="#F39C12").grid(row=0, column=1, padx=(15, 2), pady=8, sticky="e")
        self.solar_export_min = ctk.CTkEntry(sf, width=60, justify="center")
        self.solar_export_min.grid(row=0, column=2, padx=2, pady=8, sticky="w")
        self.solar_export_min.insert(0, str(heatpump_config.solar_override_export_min))
        ctk.CTkLabel(sf, text="W export", font=("Roboto", 10)).grid(row=0, column=3, padx=(0, 10), pady=8)

        ctk.CTkLabel(sf, text="HP Power:", font=("Roboto", 10, "bold"),
                      text_color="#E74C3C").grid(row=0, column=4, padx=(10, 2), pady=8, sticky="e")
        self.solar_hp_power = ctk.CTkEntry(sf, width=60, justify="center")
        self.solar_hp_power.grid(row=0, column=5, padx=2, pady=8, sticky="w")
        self.solar_hp_power.insert(0, str(heatpump_config.solar_override_hp_power))
        ctk.CTkLabel(sf, text="W", font=("Roboto", 10)).grid(row=0, column=6, padx=(0, 8), pady=8)

        ctk.CTkLabel(sf, text="Delay:", font=("Roboto", 10, "bold"),
                      text_color="#95A5A6").grid(row=0, column=7, padx=(8, 2), pady=8, sticky="e")
        self.solar_delay = ctk.CTkEntry(sf, width=45, justify="center")
        self.solar_delay.grid(row=0, column=8, padx=2, pady=8, sticky="w")
        self.solar_delay.insert(0, str(heatpump_config.solar_override_delay))
        ctk.CTkLabel(sf, text="s", font=("Roboto", 10)).grid(row=0, column=9, padx=(0, 10), pady=8)

        # ── Settings row: SOC & Voltage overrides ───────────────────
        vf = ctk.CTkFrame(self, fg_color="#2B2B2B", corner_radius=5)
        vf.grid(row=2, column=0, sticky="ew", padx=10, pady=5)

        ctk.CTkLabel(vf, text="SOC ON:", font=("Roboto", 10, "bold"),
                      text_color="#2ECC71").grid(row=0, column=0, padx=(10, 2), pady=8, sticky="e")
        self.soc_on_entry = ctk.CTkEntry(vf, width=45, justify="center")
        self.soc_on_entry.grid(row=0, column=1, padx=2, pady=8, sticky="w")
        self.soc_on_entry.insert(0, str(heatpump_config.soc_on_threshold))
        ctk.CTkLabel(vf, text="%", font=("Roboto", 10)).grid(row=0, column=2, padx=(0, 8), pady=8)

        ctk.CTkLabel(vf, text="SOC OFF:", font=("Roboto", 10, "bold"),
                      text_color="#E74C3C").grid(row=0, column=3, padx=(8, 2), pady=8, sticky="e")
        self.soc_off_entry = ctk.CTkEntry(vf, width=45, justify="center")
        self.soc_off_entry.grid(row=0, column=4, padx=2, pady=8, sticky="w")
        self.soc_off_entry.insert(0, str(heatpump_config.soc_off_threshold))
        ctk.CTkLabel(vf, text="%", font=("Roboto", 10)).grid(row=0, column=5, padx=(0, 8), pady=8)

        ctk.CTkLabel(vf, text="HV ON:", font=("Roboto", 10, "bold"),
                      text_color="#1ABC9C").grid(row=0, column=6, padx=(8, 2), pady=8, sticky="e")
        self.hv_entry = ctk.CTkEntry(vf, width=50, justify="center")
        self.hv_entry.grid(row=0, column=7, padx=2, pady=8, sticky="w")
        self.hv_entry.insert(0, str(heatpump_config.hv_threshold))
        ctk.CTkLabel(vf, text="V", font=("Roboto", 10)).grid(row=0, column=8, padx=(0, 4), pady=8)

        ctk.CTkLabel(vf, text="HV OFF:", font=("Roboto", 10, "bold"),
                      text_color="#3498DB").grid(row=0, column=9, padx=(4, 2), pady=8, sticky="e")
        self.hv_off_entry = ctk.CTkEntry(vf, width=50, justify="center")
        self.hv_off_entry.grid(row=0, column=10, padx=2, pady=8, sticky="w")
        self.hv_off_entry.insert(0, str(heatpump_config.hv_off_threshold))
        ctk.CTkLabel(vf, text="V", font=("Roboto", 10)).grid(row=0, column=11, padx=(0, 8), pady=8)

        ctk.CTkLabel(vf, text="LV OFF:", font=("Roboto", 10, "bold"),
                      text_color="#E67E22").grid(row=0, column=12, padx=(8, 2), pady=8, sticky="e")
        self.lv_entry = ctk.CTkEntry(vf, width=50, justify="center")
        self.lv_entry.grid(row=0, column=13, padx=2, pady=8, sticky="w")
        self.lv_entry.insert(0, str(heatpump_config.lv_threshold))
        ctk.CTkLabel(vf, text="V", font=("Roboto", 10)).grid(row=0, column=14, padx=(0, 4), pady=8)

        ctk.CTkLabel(vf, text="Delay:", font=("Roboto", 10, "bold"),
                      text_color="#E67E22").grid(row=0, column=15, padx=(4, 2), pady=8, sticky="e")
        self.phase_delay_entry = ctk.CTkEntry(vf, width=40, justify="center")
        self.phase_delay_entry.grid(row=0, column=16, padx=2, pady=8, sticky="w")
        self.phase_delay_entry.insert(0, str(heatpump_config.phase_change_delay))
        ctk.CTkLabel(vf, text="s", font=("Roboto", 10)).grid(row=0, column=17, padx=(0, 4), pady=8)

        ctk.CTkLabel(vf, text="LV Recovery:", font=("Roboto", 10, "bold"),
                      text_color="#E67E22").grid(row=0, column=18, padx=(4, 2), pady=8, sticky="e")
        self.lv_recovery_entry = ctk.CTkEntry(vf, width=50, justify="center")
        self.lv_recovery_entry.grid(row=0, column=19, padx=2, pady=8, sticky="w")
        self.lv_recovery_entry.insert(0, str(heatpump_config.lv_recovery_voltage))
        ctk.CTkLabel(vf, text="V", font=("Roboto", 10)).grid(row=0, column=20, padx=(0, 4), pady=8)

        ctk.CTkLabel(vf, text="Recovery Delay:", font=("Roboto", 10, "bold"),
                      text_color="#E67E22").grid(row=0, column=21, padx=(4, 2), pady=8, sticky="e")
        self.lv_recovery_delay_entry = ctk.CTkEntry(vf, width=50, justify="center")
        self.lv_recovery_delay_entry.grid(row=0, column=22, padx=2, pady=8, sticky="w")
        self.lv_recovery_delay_entry.insert(0, str(heatpump_config.lv_recovery_delay))
        ctk.CTkLabel(vf, text="s", font=("Roboto", 10)).grid(row=0, column=23, padx=(0, 10), pady=8)

        # ── Schedule header + Add button ────────────────────────────
        sched_header = ctk.CTkFrame(self, fg_color="transparent")
        sched_header.grid(row=3, column=0, sticky="ew", padx=10, pady=(5, 2))
        sched_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            sched_header, text="Temperature Schedules:",
            font=("Roboto", 11, "bold"), text_color="#E67E22"
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            sched_header, text="+ Add Time Slot", width=120, height=28,
            fg_color="#27AE60", hover_color="#1E8449",
            command=self._add_row
        ).grid(row=0, column=1, sticky="e")

        # ── Container for schedule rows ─────────────────────────────
        self.rows_container = ctk.CTkFrame(self, fg_color="transparent")
        self.rows_container.grid(row=4, column=0, sticky="ew", padx=10, pady=5)
        self.rows_container.grid_columnconfigure(0, weight=1)

        self.lbl_info = ctk.CTkLabel(
            self, text="Add time slots with min/max temperature targets for the heat pump.",
            font=("Roboto", 10), text_color="#888888"
        )
        self.lbl_info.grid(row=5, column=0, pady=(2, 5))

        # ── Live state display ──────────────────────────────────────
        state_frame = ctk.CTkFrame(self, fg_color="#2B2B2B", corner_radius=5)
        state_frame.grid(row=6, column=0, sticky="ew", padx=10, pady=(0, 10))
        state_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.lbl_hp_status = ctk.CTkLabel(
            state_frame, text="Outlet: --",
            font=("Roboto", 11, "bold"), text_color="#888888"
        )
        self.lbl_hp_status.grid(row=0, column=0, padx=10, pady=5, sticky="w")

        self.lbl_hp_temp = ctk.CTkLabel(
            state_frame, text="Temp: --°C",
            font=("Roboto", 11, "bold"), text_color="#888888"
        )
        self.lbl_hp_temp.grid(row=0, column=1, padx=10, pady=5)

        self.lbl_hp_result = ctk.CTkLabel(
            state_frame, text="--",
            font=("Roboto", 11, "bold"), text_color="gray"
        )
        self.lbl_hp_result.grid(row=0, column=2, padx=10, pady=5, sticky="e")

        # Load default schedules from .env
        for slot in heatpump_schedules:
            self._add_row()
            self.schedule_rows[-1].set_schedule(slot)

    # ── Callbacks ────────────────────────────────────────────────────

    def _on_enable_toggle(self) -> None:
        enabled = self.enabled_var.get()
        self.lbl_status.configure(
            text="Active" if enabled else "Disabled",
            text_color="#2ECC71" if enabled else "gray"
        )
        if self.on_settings_change:
            self.on_settings_change()

    def _add_row(self) -> None:
        index = len(self.schedule_rows)
        row = HeatpumpScheduleRow(self.rows_container, index, self._delete_row,
                                  on_value_change=self._on_row_value_change)
        row.grid(row=index, column=0, sticky="ew", pady=3)
        self.schedule_rows.append(row)
        if self.schedule_rows:
            self.lbl_info.grid_forget()

    def _delete_row(self, index: int) -> None:
        if 0 <= index < len(self.schedule_rows):
            self.schedule_rows[index].destroy()
            self.schedule_rows.pop(index)
            for i, row in enumerate(self.schedule_rows):
                row.index = i
                row.grid(row=i, column=0, sticky="ew", pady=3)
        if not self.schedule_rows:
            self.lbl_info.grid(row=5, column=0, pady=(2, 5))

    def _on_row_value_change(self) -> None:
        if self.on_settings_change:
            self.on_settings_change()

    # ── Public API ───────────────────────────────────────────────────

    def is_enabled(self) -> bool:
        return self.enabled_var.get()

    def get_settings(self) -> dict:
        """Return current settings."""
        schedules = []
        for row in self.schedule_rows:
            data = row.get_schedule()
            if data and data["enabled"]:
                schedules.append(HeatpumpScheduleSlot(
                    start_hour=data["start_hour"],
                    start_min=data["start_min"],
                    end_hour=data["end_hour"],
                    end_min=data["end_min"],
                    min_temp=data["min_temp"],
                    max_temp=data["max_temp"],
                ))
        try:
            return {
                "enabled": self.enabled_var.get(),
                "schedules": schedules,
                "solar_override_enabled": self.solar_override_var.get(),
                "solar_override_export_min": int(self.solar_export_min.get()),
                "solar_override_hp_power": int(self.solar_hp_power.get()),
                "solar_override_delay": int(self.solar_delay.get()),
                "soc_on_threshold": int(self.soc_on_entry.get()),
                "soc_off_threshold": int(self.soc_off_entry.get()),
                "hv_threshold": float(self.hv_entry.get()),
                "hv_off_threshold": float(self.hv_off_entry.get()),
                "lv_threshold": float(self.lv_entry.get()),
                "lv_recovery_voltage": float(self.lv_recovery_entry.get()),
                "lv_recovery_delay": int(self.lv_recovery_delay_entry.get()),
                "phase_change_delay": int(self.phase_delay_entry.get()),
            }
        except (ValueError, TypeError):
            return {
                "enabled": False,
                "schedules": schedules,
                "solar_override_enabled": heatpump_config.solar_override_enabled,
                "solar_override_export_min": heatpump_config.solar_override_export_min,
                "solar_override_hp_power": heatpump_config.solar_override_hp_power,
                "solar_override_delay": heatpump_config.solar_override_delay,
                "soc_on_threshold": heatpump_config.soc_on_threshold,
                "soc_off_threshold": heatpump_config.soc_off_threshold,
                "hv_threshold": heatpump_config.hv_threshold,
                "hv_off_threshold": heatpump_config.hv_off_threshold,
                "lv_threshold": heatpump_config.lv_threshold,
                "lv_recovery_voltage": heatpump_config.lv_recovery_voltage,
                "lv_recovery_delay": heatpump_config.lv_recovery_delay,
                "phase_change_delay": heatpump_config.phase_change_delay,
            }

    def update_hp_state(self, connected: bool, is_on: bool, temperature: float,
                        target_temp: float, result_text: str, detail: str) -> None:
        """Update the live state display labels."""
        # Device connection + target status
        if not connected:
            self.lbl_hp_status.configure(text="Outlet: Offline", text_color="#E74C3C")
        elif target_temp is not None:
            self.lbl_hp_status.configure(text=f"Target: {target_temp:.0f}°C", text_color="#2ECC71" if is_on else "#F39C12")
        else:
            self.lbl_hp_status.configure(text="Target: --°C", text_color="#888888")

        # Temperature + target
        if temperature is not None:
            temp_color = "#E74C3C" if temperature > 50 else "#F39C12" if temperature > 40 else "#2ECC71"
            target_str = f" → {target_temp:.0f}°C" if target_temp is not None else ""
            self.lbl_hp_temp.configure(text=f"Temp: {temperature:.1f}°C{target_str}", text_color=temp_color)
        else:
            self.lbl_hp_temp.configure(text="Temp: --°C", text_color="#888888")

        # Logic result
        full = f"{result_text}: {detail}" if detail else result_text
        color_map = {
            "HP: Schedule Active": "#2ECC71",
            "HP: Solar Override": "#1ABC9C",
            "HP: SOC Override": "#2ECC71",
            "HP: HV Override": "#00FFFF",
            "HP: LV Shutdown": "#E74C3C",
            "HP: SOC Low": "#E74C3C",
            "HP: No Active Schedule": "#F39C12",
            "HP: Standby": "#888888",
            "HP: No Temperature": "#95A5A6",
            "HP Offline": "#E74C3C",
            "HP Disabled": "gray",
        }
        self.lbl_hp_result.configure(text=full, text_color=color_map.get(result_text, "#888888"))


class BatteryStatsDialog(ctk.CTkToplevel):
    """Scrollable dialog window showing detailed BMS battery statistics."""
    
    # Color scheme
    SECTION_BG = "#1E1E1E"
    LABEL_COLOR = "#AAAAAA"
    VALUE_COLOR = "#FFFFFF"
    HEADER_COLOR = "#3498DB"
    GOOD_COLOR = "#2ECC71"
    WARN_COLOR = "#F39C12"
    BAD_COLOR = "#E74C3C"
    
    BATTERY_TYPES = {
        0x0000: "Pylon/Solax (CAN)",
        0x0001: "Tianbangda (RS485)",
        0x0002: "KOK",
        0x0003: "Keith",
        0x0004: "Tuopai",
        0x0005: "Pylon (RS485)",
        0x0006: "Jielis (RS485)",
        0x0007: "Xinwangda",
        0x0008: "Xinruineng",
        0x0009: "Tianbangda (RS485)",
        0x000A: "Shenggao (CAN)",
    }
    
    def __init__(self, parent, bms_data, **kwargs):
        super().__init__(parent, **kwargs)
        self.title("Battery Statistics (BMS)")
        self.geometry("700x800")
        self.minsize(600, 400)
        self.configure(fg_color="#1A1A1A")
        
        # Make it modal-like (grab focus)
        self.transient(parent)
        self.grab_set()
        self.focus_force()
        
        # Set icon from parent
        self.after(200, lambda: self._set_icon(parent))
        
        # Main scrollable container
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        scroll.grid_columnconfigure(0, weight=1)
        
        row = 0
        
        if bms_data is None:
            ctk.CTkLabel(
                scroll, text="Failed to read BMS data.\nCheck inverter connection.",
                font=("Roboto", 18, "bold"), text_color=self.BAD_COLOR
            ).grid(row=0, column=0, pady=40)
            self._add_close_button(scroll, 1)
            return
        
        # ── BMS System Overview ──
        # Format current with direction indicator
        current_val = bms_data.realtime_current
        if current_val > 0:
            current_text = f"+{current_val} A  (charging)"
            current_color = self.GOOD_COLOR
        elif current_val < 0:
            current_text = f"{current_val} A  (discharging)"
            current_color = self.WARN_COLOR
        else:
            current_text = "0 A  (idle)"
            current_color = self.VALUE_COLOR
        
        # Format power with direction
        power_val = bms_data.battery_power
        if power_val > 0:
            power_text = f"+{power_val} W  (charging)"
            power_color = self.GOOD_COLOR
        elif power_val < 0:
            power_text = f"{power_val} W  (discharging)"
            power_color = self.WARN_COLOR
        else:
            power_text = "0 W  (idle)"
            power_color = self.VALUE_COLOR
        
        row = self._add_section(scroll, row, "BMS SYSTEM OVERVIEW", [
            ("State of Charge (SOC)", f"{bms_data.realtime_soc}%", self._soc_color(bms_data.realtime_soc)),
            ("Battery Voltage", f"{bms_data.realtime_voltage:.2f} V", self.VALUE_COLOR),
            ("Battery Current", current_text, current_color),
            ("Battery Temperature", f"{bms_data.realtime_temperature:.1f} °C", self._temp_color(bms_data.realtime_temperature)),
            ("Battery Power", power_text, power_color),
            ("Battery Type", self.BATTERY_TYPES.get(bms_data.battery_type, f"Unknown (0x{bms_data.battery_type:04X})"), self.VALUE_COLOR),
            ("Corrected Capacity", f"{bms_data.corrected_ah} Ah", self.VALUE_COLOR),
        ])
        
        # ── BMS Limits ──
        row = self._add_section(scroll, row, "BMS CHARGE/DISCHARGE LIMITS", [
            ("Max Charge Voltage", f"{bms_data.charge_voltage:.2f} V", self.VALUE_COLOR),
            ("Charge Current Limit", f"{bms_data.charge_current_limit} A", self.VALUE_COLOR),
            ("Discharge Current Limit", f"{bms_data.discharge_current_limit} A", self.VALUE_COLOR),
        ])
        
        # ── Alarms & Faults ──
        alarm_color = self.BAD_COLOR if bms_data.alarm else self.GOOD_COLOR
        fault_color = self.BAD_COLOR if bms_data.fault else self.GOOD_COLOR
        row = self._add_section(scroll, row, "ALARMS & FAULTS", [
            ("Alarm Status", "ALARM ACTIVE" if bms_data.alarm else "No Alarms", alarm_color),
            ("Alarm Code", f"0x{bms_data.alarm:04X}" if bms_data.alarm else "—", alarm_color),
            ("Fault Status", "FAULT ACTIVE" if bms_data.fault else "No Faults", fault_color),
            ("Fault Code", f"0x{bms_data.fault:04X}" if bms_data.fault else "—", fault_color),
        ])
        
        # ── Energy Statistics ──
        row = self._add_section(scroll, row, "ENERGY STATISTICS", [
            ("Today Charged", f"{bms_data.today_charge_kwh:.1f} kWh", self.VALUE_COLOR),
            ("Today Discharged", f"{bms_data.today_discharge_kwh:.1f} kWh", self.VALUE_COLOR),
            ("Total Charged", f"{bms_data.total_charge_kwh:.1f} kWh", self.VALUE_COLOR),
            ("Total Discharged", f"{bms_data.total_discharge_kwh:.1f} kWh", self.VALUE_COLOR),
        ])
        
        # Close button
        self._add_close_button(scroll, row)
    
    def _set_icon(self, parent):
        """Copy icon from parent window."""
        try:
            icon = parent.iconbitmap()
            if icon:
                self.iconbitmap(icon)
        except Exception:
            pass
    
    def _add_section(self, parent, start_row, title, items):
        """Add a titled section with key-value pairs."""
        # Section header
        ctk.CTkLabel(
            parent, text=title,
            font=("Roboto", 16, "bold"),
            text_color=self.HEADER_COLOR
        ).grid(row=start_row, column=0, pady=(15, 5), padx=10, sticky="w")
        start_row += 1
        
        # Section frame
        frame = ctk.CTkFrame(parent, fg_color=self.SECTION_BG, corner_radius=8)
        frame.grid(row=start_row, column=0, sticky="ew", padx=10, pady=(0, 5))
        frame.grid_columnconfigure(1, weight=1)
        
        for i, (label, value, color) in enumerate(items):
            ctk.CTkLabel(
                frame, text=label,
                font=("Roboto", 13),
                text_color=self.LABEL_COLOR
            ).grid(row=i, column=0, padx=(15, 10), pady=3, sticky="w")
            
            ctk.CTkLabel(
                frame, text=value,
                font=("Roboto", 13, "bold"),
                text_color=color
            ).grid(row=i, column=1, padx=(10, 15), pady=3, sticky="e")
        
        return start_row + 1
    
    def _add_close_button(self, parent, row):
        """Add a close button at the bottom."""
        ctk.CTkButton(
            parent, text="Close",
            command=self.destroy,
            font=("Roboto", 14, "bold"),
            width=120, height=36,
            fg_color="#2C3E50",
            hover_color="#34495E",
        ).grid(row=row, column=0, pady=(20, 10))
    
    def _soc_color(self, soc):
        if soc >= 60:
            return self.GOOD_COLOR
        elif soc >= 30:
            return self.WARN_COLOR
        return self.BAD_COLOR
    
    def _temp_color(self, temp):
        if 10 <= temp <= 40:
            return self.GOOD_COLOR
        elif 0 <= temp <= 50:
            return self.WARN_COLOR
        return self.BAD_COLOR