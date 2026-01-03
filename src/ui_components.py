"""
UI Components for Deye Inverter EMS application.
"""

import customtkinter as ctk
from typing import List, Tuple, Callable
# Default charge current limits (Amps)
DEFAULT_MAX_CHARGE_AMPS = 60
DEFAULT_GRID_CHARGE_AMPS = 40

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
        self.bar.grid(row=0, column=1, padx=10, sticky="ew")
        self.bar.set(0)
        
        # UPS load label (primary - always available)
        self.lbl_ups_load = ctk.CTkLabel(
            self, text="UPS: 0 W",
            font=("Roboto", 20, "bold"),
            text_color="#FFA500",
            width=95
        )
        self.lbl_ups_load.grid(row=0, column=2, padx=10)
        
        # Grid load label (secondary - may be 0 if no smart meter)
        self.lbl_load = ctk.CTkLabel(
            self, text="Grid: 0 W",
            font=("Roboto", 11),
            text_color="#888888",
            width=95
        )
        self.lbl_load.grid(row=1, column=2, padx=10, sticky="n")

    def update(self, voltage: float, load: int, ups_load: int, max_load: int) -> None:
        """Update the phase display with new values."""
        self.lbl_voltage.configure(text=f"{voltage} V")
        self.lbl_ups_load.configure(text=f"UPS: {ups_load} W")
        self.lbl_load.configure(text=f"Grid: {load} W")
        # Use UPS load for progress bar (the actual inverter output)
        self.bar.set(min(ups_load / max_load, 1.0) if max_load > 0 else 0)


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
            self, values=["L1", "L2", "L3"],
            variable=variables["target_phase"],
            height=24
        )
        self.phase_selector.grid(row=5, column=2, sticky="w", padx=5, pady=8)
        
        self._add_setting_h("High V (ON):", variables["hv_threshold"], 5, 3)
        
        # Row 6: Voltage OFF parameters
        self._add_setting_h("Low V (OFF):", variables["lv_threshold"], 6, 1)
        self._add_setting_h("LV Delay (s):", variables["lv_delay"], 6, 3)
        
        # Row 7: Low Voltage Recovery parameters (with slight extra spacing)
        self._add_setting_h("LV Recovery V:", variables["lv_recovery_voltage"], 7, 1, pady=(12, 10))
        self._add_setting_h("LV Recovery (s):", variables["lv_recovery_delay"], 7, 3, pady=(12, 10))
    
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
        
        self.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="ems")
        
        # Title
        ctk.CTkLabel(
            self, text="GLOBAL SAFETY CONFIGURATION",
            font=("Roboto", 14, "bold")
        ).grid(row=0, column=0, columnspan=4, pady=10)
        
        # Manual override switch
        self.man_switch = ctk.CTkSwitch(
            self, text="MANUAL OVERRIDE MODE",
            variable=variables["manual_mode"],
            command=on_manual_toggle,
            progress_color="#E74C3C",
            font=("Roboto", 12, "bold")
        )
        self.man_switch.grid(row=1, column=0, columnspan=4, pady=(0, 20))
        
        # Safety row
        ctk.CTkLabel(
            self, text="SAFETY:",
            font=("Roboto", 11, "bold"),
            text_color="#E74C3C"
        ).grid(row=2, column=0, sticky="e", pady=20)
        
        self._add_setting_h("Max Phase W:", variables["phase_max"], 2, 1, is_safety=True)
        self._add_setting_h("Max UPS Total:", variables["max_ups_total_power"], 2, 3, is_safety=True)
        
        # Row 3: Critical voltage
        self._add_setting_h("Critical LV:", variables["safety_lv"], 3, 1, is_safety=True)

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
    
    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        
        self.grid_columnconfigure((0, 1, 2), weight=1)
        
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
    
    def __init__(self, parent, index: int, on_delete: Callable, **kwargs):
        super().__init__(parent, fg_color="#2B2B2B", corner_radius=5, **kwargs)
        self.index = index
        self.on_delete = on_delete
        
        self.grid_columnconfigure((1, 2, 3, 4, 5, 6), weight=1)
        
        # Enable checkbox
        self.enabled_var = ctk.BooleanVar(value=True)
        self.chk_enabled = ctk.CTkCheckBox(
            self, text="",
            variable=self.enabled_var,
            width=20
        )
        self.chk_enabled.grid(row=0, column=0, padx=5, pady=8)
        
        # Start time
        ctk.CTkLabel(self, text="From:", font=("Roboto", 10)).grid(row=0, column=1, padx=2)
        self.start_hour = ctk.CTkEntry(self, width=40, justify="center", placeholder_text="HH")
        self.start_hour.grid(row=0, column=2, padx=2)
        self.start_hour.insert(0, "00")
        
        ctk.CTkLabel(self, text=":", font=("Roboto", 10)).grid(row=0, column=3, padx=0)
        self.start_min = ctk.CTkEntry(self, width=40, justify="center", placeholder_text="MM")
        self.start_min.grid(row=0, column=4, padx=2)
        self.start_min.insert(0, "00")
        
        # End time
        ctk.CTkLabel(self, text="To:", font=("Roboto", 10)).grid(row=0, column=5, padx=2)
        self.end_hour = ctk.CTkEntry(self, width=40, justify="center", placeholder_text="HH")
        self.end_hour.grid(row=0, column=6, padx=2)
        self.end_hour.insert(0, "23")
        
        ctk.CTkLabel(self, text=":", font=("Roboto", 10)).grid(row=0, column=7, padx=0)
        self.end_min = ctk.CTkEntry(self, width=40, justify="center", placeholder_text="MM")
        self.end_min.grid(row=0, column=8, padx=2)
        self.end_min.insert(0, "59")
        
        # Max Charge Amps
        ctk.CTkLabel(self, text="Max Charge:", font=("Roboto", 10), text_color="#2ECC71").grid(row=0, column=9, padx=(10, 2))
        self.max_charge = ctk.CTkEntry(self, width=50, justify="center")
        self.max_charge.grid(row=0, column=10, padx=2)
        self.max_charge.insert(0, str(DEFAULT_MAX_CHARGE_AMPS))
        ctk.CTkLabel(self, text="A", font=("Roboto", 10)).grid(row=0, column=11, padx=(0, 5))
        
        # Grid Charge Amps
        ctk.CTkLabel(self, text="Grid Charge:", font=("Roboto", 10), text_color="#3498DB").grid(row=0, column=12, padx=(10, 2))
        self.grid_charge = ctk.CTkEntry(self, width=50, justify="center")
        self.grid_charge.grid(row=0, column=13, padx=2)
        self.grid_charge.insert(0, str(DEFAULT_GRID_CHARGE_AMPS))
        ctk.CTkLabel(self, text="A", font=("Roboto", 10)).grid(row=0, column=14, padx=(0, 5))
        
        # Delete button
        self.btn_delete = ctk.CTkButton(
            self, text="✕", width=30, height=24,
            fg_color="#E74C3C", hover_color="#C0392B",
            command=lambda: self.on_delete(self.index)
        )
        self.btn_delete.grid(row=0, column=15, padx=5)
    
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
            header_frame, text="⏰ CHARGE SCHEDULE",
            font=("Roboto", 14, "bold"),
            text_color="#F39C12"
        ).grid(row=0, column=0, sticky="w")
        
        # Enable/Disable switch
        self.enabled_var = ctk.BooleanVar(value=False)
        self.enable_switch = ctk.CTkSwitch(
            header_frame, text="Enable Schedule",
            variable=self.enabled_var,
            font=("Roboto", 11, "bold"),
            command=self._on_enable_toggle
        )
        self.enable_switch.grid(row=0, column=1, padx=20)
        
        # Status label
        self.lbl_status = ctk.CTkLabel(
            header_frame, text="Disabled",
            font=("Roboto", 11),
            text_color="gray"
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
        
        # Add a default row (00:00 to 23:59)
        self._add_row()
    
    def _on_enable_toggle(self) -> None:
        """Handle enable/disable toggle."""
        if self.enabled_var.get():
            self.lbl_status.configure(text="Active", text_color="#2ECC71")
        else:
            self.lbl_status.configure(text="Disabled", text_color="gray")
        
        if self.on_schedule_change:
            self.on_schedule_change()
    
    def _add_row(self) -> None:
        """Add a new schedule row."""
        index = len(self.schedule_rows)
        row = TimeScheduleRow(self.rows_container, index, self._delete_row)
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
            }
        except ValueError:
            return {"max_charge_amps": 60, "grid_charge_amps": 40}
    
    def update_status(self, active_schedule: dict = None) -> None:
        """Update the status label to show current state."""
        if not self.enabled_var.get():
            self.lbl_status.configure(text="Disabled", text_color="gray")
        elif active_schedule:
            start = f"{active_schedule['start_hour']:02d}:{active_schedule['start_min']:02d}"
            end = f"{active_schedule['end_hour']:02d}:{active_schedule['end_min']:02d}"
            self.lbl_status.configure(
                text=f"Active: {start}-{end} | Max:{active_schedule['max_charge_amps']}A Grid:{active_schedule['grid_charge_amps']}A",
                text_color="#2ECC71"
            )
        else:
            self.lbl_status.configure(text="No active slot (using defaults)", text_color="#F39C12")