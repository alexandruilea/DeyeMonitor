"""
UI Components for Deye Inverter EMS application.
"""

import customtkinter as ctk
from typing import List, Tuple, Callable


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
