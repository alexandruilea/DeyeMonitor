"""
UI Components for Deye Inverter EMS application.
"""

import customtkinter as ctk
from typing import List, Tuple


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
        self.lbl_voltage.grid(row=0, column=0, padx=10)
        
        # Progress bar
        self.bar = ctk.CTkProgressBar(self, height=18)
        self.bar.grid(row=0, column=1, padx=10, sticky="ew")
        self.bar.set(0)
        
        # Load label
        self.lbl_load = ctk.CTkLabel(
            self, text="0 W",
            font=("Roboto", 20, "bold"),
            width=95
        )
        self.lbl_load.grid(row=0, column=2, padx=10)

    def update(self, voltage: float, load: int, max_load: int) -> None:
        """Update the phase display with new values."""
        self.lbl_voltage.configure(text=f"{voltage} V")
        self.lbl_load.configure(text=f"{load} W")
        self.bar.set(min(load / max_load, 1.0) if max_load > 0 else 0)


class SettingsPanel(ctk.CTkFrame):
    """Settings panel for EMS configuration."""
    
    def __init__(self, parent, variables: dict, on_manual_toggle: callable, **kwargs):
        super().__init__(parent, **kwargs)
        self.variables = variables
        self.logic_widgets: List[Tuple[ctk.CTkLabel, ctk.CTkEntry]] = []
        
        self.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1, uniform="ems")
        
        # Title
        ctk.CTkLabel(
            self, text="EMS CONFIGURATION",
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
        
        # SOC Parameters
        self._add_setting_v("Start SOC %", variables["start_soc"], 2, 1)
        self._add_setting_v("Stop SOC %", variables["stop_soc"], 2, 2)
        self._add_setting_v("Headroom W", variables["headroom"], 2, 3)
        
        # Phase & Export row
        ctk.CTkLabel(
            self, text="Monitor Phase:",
            font=("Roboto", 11, "bold")
        ).grid(row=4, column=0, sticky="e", padx=2, pady=15)
        
        self.phase_selector = ctk.CTkSegmentedButton(
            self, values=["L1", "L2", "L3"],
            variable=variables["target_phase"],
            height=28
        )
        self.phase_selector.grid(row=4, column=1, columnspan=2, sticky="w", padx=5, pady=15)
        
        self.export_switch = ctk.CTkSwitch(
            self, text="Export D",
            variable=variables["export_active"],
            font=("Roboto", 11, "bold")
        )
        self.export_switch.grid(row=4, column=3, sticky="e", padx=5, pady=15)
        
        self._add_setting_h("Min Export:", variables["export_limit"], 4, 4)
        
        # Voltage row
        self._add_setting_h("High V (ON):", variables["hv_threshold"], 5, 0)
        self._add_setting_h("Low V (OFF):", variables["lv_threshold"], 5, 2)
        self._add_setting_h("LV Delay (s):", variables["lv_delay"], 5, 4)
        
        # Safety row
        ctk.CTkLabel(
            self, text="SAFETY:",
            font=("Roboto", 11, "bold"),
            text_color="#E74C3C"
        ).grid(row=6, column=0, sticky="e", pady=20)
        
        self._add_setting_h("Max Phase W:", variables["phase_max"], 6, 1, is_safety=True)
        self._add_setting_h("Critical LV:", variables["safety_lv"], 6, 3, is_safety=True)

    def _add_setting_v(self, label: str, var, row: int, col: int, is_safety: bool = False) -> None:
        """Add a vertical setting (label above entry)."""
        lbl = ctk.CTkLabel(self, text=label, font=("Roboto", 11))
        lbl.grid(row=row, column=col, pady=(0, 2))
        
        ent = ctk.CTkEntry(self, textvariable=var, width=85, justify="center")
        ent.grid(row=row + 1, column=col, padx=5, pady=(0, 15))
        
        if not is_safety:
            self.logic_widgets.append((lbl, ent))

    def _add_setting_h(self, label: str, var, row: int, col: int, is_safety: bool = False) -> None:
        """Add a horizontal setting (label left of entry)."""
        lbl = ctk.CTkLabel(self, text=label, font=("Roboto", 11, "bold"))
        lbl.grid(row=row, column=col, sticky="e", padx=2)
        
        ent = ctk.CTkEntry(self, textvariable=var, width=75, justify="center")
        ent.grid(row=row, column=col + 1, sticky="w", padx=2)
        
        if not is_safety:
            self.logic_widgets.append((lbl, ent))

    def set_manual_mode_visuals(self, is_manual: bool) -> None:
        """Update visuals based on manual mode state."""
        color = "#E74C3C" if is_manual else "white"
        state = "disabled" if is_manual else "normal"
        
        for lbl, ent in self.logic_widgets:
            ent.configure(text_color=color, state=state)
            lbl.configure(text_color=color)
        
        self.phase_selector.configure(state=state)
        self.export_switch.configure(state=state)

    def set_invalid_config(self, is_invalid: bool) -> None:
        """Set visual indicator for invalid configuration."""
        color = "#A569BD" if is_invalid else "white"
        for _, ent in self.logic_widgets:
            ent.configure(text_color=color)


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

    def update_status(self, text: str, color: str) -> None:
        """Update the status label."""
        self.lbl_status.configure(text=text, text_color=color)

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
    
    COLORS = {
        STATE_SYNCING: "#3B3B3B",
        STATE_OFFLINE: "#3B3B3B",
        STATE_RUNNING: "#27AE60",
        STATE_STANDBY: "#C0392B",
    }
    
    LABELS = {
        STATE_SYNCING: "HP: SYNCING",
        STATE_OFFLINE: "HP: TAPO OFFLINE",
        STATE_RUNNING: "HEAT PUMP: RUNNING",
        STATE_STANDBY: "HEAT PUMP: STANDBY",
    }
    
    def __init__(self, parent, command, **kwargs):
        super().__init__(
            parent,
            text=self.LABELS[self.STATE_SYNCING],
            command=command,
            font=("Roboto", 20, "bold"),
            height=70,
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
