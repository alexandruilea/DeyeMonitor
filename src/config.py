"""
Configuration management for Deye Inverter EMS.
Loads hardware settings from .env file and provides default EMS parameters.
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
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


@dataclass
class TapoConfig:
    """Tapo smart plug connection configuration."""
    ip: str = field(default_factory=lambda: os.getenv("TAPO_IP", "192.168.0.158"))
    username: str = field(default_factory=lambda: os.getenv("TAPO_USER", ""))
    password: str = field(default_factory=lambda: os.getenv("TAPO_PASS", ""))


@dataclass
class EMSDefaults:
    """Default EMS logic parameters."""
    start_soc: int = 70
    stop_soc: int = 32
    headroom: int = 4000
    phase_max: int = 7000
    safety_lv: float = 185.0
    hv_threshold: float = 252.0
    lv_threshold: float = 210.0
    lv_delay: int = 10
    target_phase: str = "L1"
    export_active: bool = True
    export_limit: int = 5000


# Global config instances
deye_config = DeyeConfig()
tapo_config = TapoConfig()
ems_defaults = EMSDefaults()
