"""
Configuration management for Deye Inverter EMS.
Loads hardware settings from .env file and provides default EMS parameters.
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
from dotenv import load_dotenv


def get_app_path() -> Path:
    """Get the application path, works both for dev and PyInstaller bundle."""
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        return Path(sys.executable).parent
    else:
        # Running as script
        return Path(__file__).parent.parent


# Load environment variables from .env file
_env_path = get_app_path() / ".env"
load_dotenv(_env_path)


@dataclass
class DeyeConfig:
    """Deye inverter connection configuration."""
    ip: str = field(default_factory=lambda: os.getenv("DEYE_IP", "192.168.0.122"))
    logger_serial: int = field(default_factory=lambda: int(os.getenv("DEYE_LOGGER_SERIAL", "3127036880")))
    port: int = field(default_factory=lambda: int(os.getenv("DEYE_PORT", "8899")))
    model: str = field(default_factory=lambda: os.getenv("DEYE_MODEL", "SUN-12K-SG04LP3-EU"))


@dataclass
class OutletConfig:
    """Configuration for a single outlet."""
    outlet_id: int
    ip: str
    username: str
    password: str
    name: str
    priority: int
    power: int  # Estimated power consumption in watts (for display only)
    start_soc: int = 70
    stop_soc: int = 32
    hv_threshold: float = 252.0
    lv_threshold: float = 210.0
    lv_delay: int = 10
    lv_recovery_voltage: float = 220.0  # Voltage must exceed this for recovery
    lv_recovery_delay: int = 300  # Seconds voltage must stay above recovery level (default 5 min)
    headroom: int = 4000
    target_phase: str = "L1"
    # Trigger enable flags
    soc_enabled: bool = True  # Enable SOC-based trigger
    voltage_enabled: bool = True  # Enable voltage-based trigger (HV/LV)
    export_enabled: bool = True  # Enable export-based trigger
    export_limit: int = 5000
    runtime_delay: int = 300  # Seconds lower priority outlets must wait (default 5 min)
    off_grid_mode: bool = False  # Enable off-grid mode (outlet runs without grid connection)


def load_outlet_configs() -> List[OutletConfig]:
    """Load all outlet configurations from environment variables."""
    outlets = []
    i = 1
    
    while True:
        prefix = f"OUTLET_{i}_"
        ip = os.getenv(f"{prefix}IP")
        
        if not ip:
            break
        
        # Required fields
        username = os.getenv(f"{prefix}USER", "")
        password = os.getenv(f"{prefix}PASS", "")
        name = os.getenv(f"{prefix}NAME", f"Outlet {i}")
        priority = int(os.getenv(f"{prefix}PRIORITY", str(i)))
        power = int(os.getenv(f"{prefix}POWER", "2000"))
        
        # Optional fields with defaults
        start_soc = int(os.getenv(f"{prefix}START_SOC", "70"))
        stop_soc = int(os.getenv(f"{prefix}STOP_SOC", "32"))
        hv_threshold = float(os.getenv(f"{prefix}HV_THRESHOLD", "252.0"))
        lv_threshold = float(os.getenv(f"{prefix}LV_THRESHOLD", "210.0"))
        lv_delay = int(os.getenv(f"{prefix}LV_DELAY", "10"))
        lv_recovery_voltage = float(os.getenv(f"{prefix}LV_RECOVERY_VOLTAGE", "220.0"))
        lv_recovery_delay = int(os.getenv(f"{prefix}LV_RECOVERY_DELAY", "300"))
        headroom = int(os.getenv(f"{prefix}HEADROOM", "4000"))
        target_phase = os.getenv(f"{prefix}TARGET_PHASE", "L1")
        # Trigger enable flags
        soc_enabled = os.getenv(f"{prefix}SOC_ENABLED", "true").lower() == "true"
        voltage_enabled = os.getenv(f"{prefix}VOLTAGE_ENABLED", "true").lower() == "true"
        export_enabled = os.getenv(f"{prefix}EXPORT_ENABLED", "true").lower() == "true"
        export_limit = int(os.getenv(f"{prefix}EXPORT_LIMIT", "5000"))
        runtime_delay = int(os.getenv(f"{prefix}RUNTIME_DELAY", "300"))
        off_grid_mode = os.getenv(f"{prefix}OFF_GRID_MODE", "false").lower() == "true"
        
        outlets.append(OutletConfig(
            outlet_id=i,
            ip=ip,
            username=username,
            password=password,
            name=name,
            priority=priority,
            power=power,
            start_soc=start_soc,
            stop_soc=stop_soc,
            hv_threshold=hv_threshold,
            lv_threshold=lv_threshold,
            lv_delay=lv_delay,
            lv_recovery_voltage=lv_recovery_voltage,
            lv_recovery_delay=lv_recovery_delay,
            headroom=headroom,
            target_phase=target_phase,
            soc_enabled=soc_enabled,
            voltage_enabled=voltage_enabled,
            export_enabled=export_enabled,
            export_limit=export_limit,
            runtime_delay=runtime_delay,
            off_grid_mode=off_grid_mode
        ))
        
        i += 1
    
    # Sort by priority (lower number = higher priority)
    outlets.sort(key=lambda x: x.priority)
    return outlets


@dataclass
class EMSDefaults:
    """Default EMS logic parameters."""
    phase_max: int = 7000
    safety_lv: float = 185.0
    max_ups_total_power: int = 16000  # Maximum UPS/Backup port output across all phases


# Global config instances
deye_config = DeyeConfig()
outlet_configs = load_outlet_configs()
ems_defaults = EMSDefaults()
