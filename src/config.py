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
    # Write control registers (model-specific)
    reg_max_charge_amps: int = field(default_factory=lambda: int(os.getenv("DEYE_REG_MAX_CHARGE_AMPS", "108")))
    reg_max_discharge_amps: int = field(default_factory=lambda: int(os.getenv("DEYE_REG_MAX_DISCHARGE_AMPS", "109")))
    reg_grid_charge_enable: int = field(default_factory=lambda: int(os.getenv("DEYE_REG_GRID_CHARGE_ENABLE", "130")))
    reg_grid_charge_current: int = field(default_factory=lambda: int(os.getenv("DEYE_REG_GRID_CHARGE_CURRENT", "128")))
    reg_solar_sell_slot1: int = field(default_factory=lambda: int(os.getenv("DEYE_REG_SOLAR_SELL_SLOT1", "145")))
    reg_grid_charge_slot1: int = field(default_factory=lambda: int(os.getenv("DEYE_REG_GRID_CHARGE_SLOT1", "172")))
    reg_charge_target_soc: int = field(default_factory=lambda: int(os.getenv("DEYE_REG_CHARGE_TARGET_SOC", "166")))
    reg_max_grid_power: int = field(default_factory=lambda: int(os.getenv("DEYE_REG_MAX_GRID_POWER", "143")))
    reg_max_solar_sell_power: int = field(default_factory=lambda: int(os.getenv("DEYE_REG_MAX_SOLAR_SELL_POWER", "143")))
    max_charge_amps_limit: int = field(default_factory=lambda: int(os.getenv("DEYE_MAX_CHARGE_AMPS_LIMIT", "185")))
    max_discharge_amps_limit: int = field(default_factory=lambda: int(os.getenv("DEYE_MAX_DISCHARGE_AMPS_LIMIT", "185")))
    default_max_charge_amps: int = field(default_factory=lambda: int(os.getenv("DEYE_DEFAULT_MAX_CHARGE_AMPS", "60")))
    default_grid_charge_amps: int = field(default_factory=lambda: int(os.getenv("DEYE_DEFAULT_GRID_CHARGE_AMPS", "40")))
    default_max_discharge_amps: int = field(default_factory=lambda: int(os.getenv("DEYE_DEFAULT_MAX_DISCHARGE_AMPS", "150")))
    zero_export_mode: int = field(default_factory=lambda: int(os.getenv("DEYE_ZERO_EXPORT_MODE", "2")))  # 1=Zero Export to Load (internal CT), 2=Zero Export to CT (external CT)
    min_register_write_interval: int = field(default_factory=lambda: int(os.getenv("DEYE_MIN_REGISTER_WRITE_INTERVAL", "30")))  # Minimum seconds between writes to the same register (reduces flash wear)


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
    phase_change_delay: int = 10
    lv_recovery_voltage: float = 220.0  # Voltage must exceed this for recovery
    lv_recovery_delay: int = 300  # Seconds voltage must stay above recovery level (default 5 min)
    headroom: int = 4000
    target_phase: str = "ANY"
    # Trigger enable flags
    soc_enabled: bool = True  # Enable SOC-based trigger
    voltage_enabled: bool = True  # Enable voltage-based trigger (HV/LV)
    export_enabled: bool = True  # Enable export-based trigger
    export_limit: int = 5000
    export_delay: int = 300  # Seconds export must sustain above limit before trigger fires (default 5 min)
    soc_delay: int = 180  # Seconds SOC must stay above start threshold before trigger fires (default 3 min)
    runtime_delay: int = 300  # Seconds lower priority outlets must wait (default 5 min)
    off_grid_mode: bool = False  # Enable off-grid mode (outlet runs without grid connection)
    on_grid_always_on: bool = False  # When on-grid, always keep outlet on regardless of SOC
    restart_delay_enabled: bool = False  # Enable restart delay after outlet turns off
    restart_delay_minutes: int = 30  # Minutes to wait before auto-restarting after turn-off


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
        phase_change_delay = int(os.getenv(f"{prefix}PHASE_CHANGE_DELAY", os.getenv(f"{prefix}LV_DELAY", "10")))
        lv_recovery_voltage = float(os.getenv(f"{prefix}LV_RECOVERY_VOLTAGE", "220.0"))
        lv_recovery_delay = int(os.getenv(f"{prefix}LV_RECOVERY_DELAY", "300"))
        headroom = int(os.getenv(f"{prefix}HEADROOM", "4000"))
        target_phase = os.getenv(f"{prefix}TARGET_PHASE", "L1")
        # Trigger enable flags
        soc_enabled = os.getenv(f"{prefix}SOC_ENABLED", "true").lower() == "true"
        voltage_enabled = os.getenv(f"{prefix}VOLTAGE_ENABLED", "true").lower() == "true"
        export_enabled = os.getenv(f"{prefix}EXPORT_ENABLED", "true").lower() == "true"
        export_limit = int(os.getenv(f"{prefix}EXPORT_LIMIT", "5000"))
        export_delay = int(os.getenv(f"{prefix}EXPORT_DELAY", "300"))
        soc_delay = int(os.getenv(f"{prefix}SOC_DELAY", "180"))
        runtime_delay = int(os.getenv(f"{prefix}RUNTIME_DELAY", "300"))
        off_grid_mode = os.getenv(f"{prefix}OFF_GRID_MODE", "false").lower() == "true"
        on_grid_always_on = os.getenv(f"{prefix}ON_GRID_ALWAYS_ON", "false").lower() == "true"
        restart_delay_enabled = os.getenv(f"{prefix}RESTART_DELAY_ENABLED", "true").lower() == "true"
        restart_delay_minutes = int(os.getenv(f"{prefix}RESTART_DELAY_MINUTES", "30"))
        
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
            phase_change_delay=phase_change_delay,
            lv_recovery_voltage=lv_recovery_voltage,
            lv_recovery_delay=lv_recovery_delay,
            headroom=headroom,
            target_phase=target_phase,
            soc_enabled=soc_enabled,
            voltage_enabled=voltage_enabled,
            export_enabled=export_enabled,
            export_limit=export_limit,
            export_delay=export_delay,
            soc_delay=soc_delay,
            runtime_delay=runtime_delay,
            off_grid_mode=off_grid_mode,
            on_grid_always_on=on_grid_always_on,
            restart_delay_enabled=restart_delay_enabled,
            restart_delay_minutes=restart_delay_minutes
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


@dataclass
class OverpowerProtectionConfig:
    """Configuration for overpower/overvoltage protection."""
    voltage_warning: float = field(default_factory=lambda: float(os.getenv("PROTECTION_VOLTAGE_WARNING", "251.5")))
    voltage_recovery: float = field(default_factory=lambda: float(os.getenv("PROTECTION_VOLTAGE_RECOVERY", "249.0")))
    charge_step: int = field(default_factory=lambda: int(os.getenv("PROTECTION_CHARGE_STEP", "10")))
    max_sell_power: int = field(default_factory=lambda: int(os.getenv("PROTECTION_MAX_SELL_POWER", "8000")))
    power_threshold_pct: int = field(default_factory=lambda: int(os.getenv("PROTECTION_POWER_THRESHOLD_PCT", "95")))
    recovery_threshold_pct: int = field(default_factory=lambda: int(os.getenv("PROTECTION_RECOVERY_THRESHOLD_PCT", "85")))
    adjustment_interval: int = field(default_factory=lambda: int(os.getenv("PROTECTION_ADJUSTMENT_INTERVAL", "30")))
    enabled_at_startup: bool = field(default_factory=lambda: os.getenv("PROTECTION_ENABLED_AT_STARTUP", "false").lower() == "true")
    battery_nominal_voltage: int = field(default_factory=lambda: int(os.getenv("PROTECTION_BATTERY_NOMINAL_VOLTAGE", "52")))  # Nominal battery voltage for proportional amp calculation
    voltage_hold_margin: float = field(default_factory=lambda: float(os.getenv("PROTECTION_VOLTAGE_HOLD_MARGIN", "5.0")))  # Hold boost if voltage within this margin of warning (V)


@dataclass
class EVChargerConfig:
    """Configuration for a Tuya-based EV charger."""
    enabled: bool = field(default_factory=lambda: os.getenv("EV_CHARGER_ENABLED", "false").lower() == "true")
    device_id: str = field(default_factory=lambda: os.getenv("EV_CHARGER_DEVICE_ID", ""))
    ip: str = field(default_factory=lambda: os.getenv("EV_CHARGER_IP", ""))
    local_key: str = field(default_factory=lambda: os.getenv("EV_CHARGER_LOCAL_KEY", ""))
    protocol_version: float = field(default_factory=lambda: float(os.getenv("EV_CHARGER_PROTOCOL_VERSION", "3.3")))
    min_amps: int = field(default_factory=lambda: int(os.getenv("EV_CHARGER_MIN_AMPS", "8")))
    max_amps: int = field(default_factory=lambda: int(os.getenv("EV_CHARGER_MAX_AMPS", "32")))
    stop_soc: int = field(default_factory=lambda: int(os.getenv("EV_CHARGER_STOP_SOC", "20")))
    start_soc: int = field(default_factory=lambda: int(os.getenv("EV_CHARGER_START_SOC", "80")))
    solar_mode: bool = field(default_factory=lambda: os.getenv("EV_CHARGER_SOLAR_MODE", "false").lower() == "true")
    change_interval_minutes: int = field(default_factory=lambda: int(os.getenv("EV_CHARGER_CHANGE_INTERVAL", "5")))
    charge_by_hour: int = field(default_factory=lambda: int(os.getenv("EV_CHARGER_CHARGE_BY_HOUR", "7")))  # Target hour (0-23) for battery-paced charging
    grid_charge_amps: int = field(default_factory=lambda: int(os.getenv("EV_CHARGER_GRID_CHARGE_AMPS", "20")))  # Amps to use when grid-charging EV
    solar_ramp_down_delay: int = field(default_factory=lambda: int(os.getenv("EV_CHARGER_SOLAR_RAMP_DOWN_DELAY", "5")))  # Minutes between solar ramp-down steps
    solar_amp_steps: tuple = field(default_factory=lambda: tuple(int(x) for x in os.getenv("EV_CHARGER_SOLAR_AMP_STEPS", "8,16,24,32").split(",")))
    ev_first: bool = field(default_factory=lambda: os.getenv("EV_CHARGER_EV_FIRST", "false").lower() == "true")
    # Tuya DPS mapping (varies by charger model)
    dp_switch: int = field(default_factory=lambda: int(os.getenv("EV_CHARGER_DP_SWITCH", "1")))
    dp_amps: int = field(default_factory=lambda: int(os.getenv("EV_CHARGER_DP_AMPS", "6")))
    dp_state: int = field(default_factory=lambda: int(os.getenv("EV_CHARGER_DP_STATE", "124")))  # DP for charger state string
    dp_amps_scale: int = field(default_factory=lambda: int(os.getenv("EV_CHARGER_DP_AMPS_SCALE", "1")))  # 1=amps, 10=amps×10, 1000=milliamps


@dataclass
class HeatpumpScheduleSlot:
    """A single time-based temperature schedule slot for the heat pump."""
    start_hour: int = 0
    start_min: int = 0
    end_hour: int = 23
    end_min: int = 59
    min_temp: float = 28.0
    max_temp: float = 35.0


@dataclass
class TuyaHeatpumpConfig:
    """Configuration for a Tuya-based smart outlet controlling a heat pump with temperature sensor."""
    enabled: bool = field(default_factory=lambda: os.getenv("HEATPUMP_ENABLED", "false").lower() == "true")
    device_id: str = field(default_factory=lambda: os.getenv("HEATPUMP_DEVICE_ID", ""))
    ip: str = field(default_factory=lambda: os.getenv("HEATPUMP_IP", ""))
    local_key: str = field(default_factory=lambda: os.getenv("HEATPUMP_LOCAL_KEY", ""))
    protocol_version: float = field(default_factory=lambda: float(os.getenv("HEATPUMP_PROTOCOL_VERSION", "3.3")))
    name: str = field(default_factory=lambda: os.getenv("HEATPUMP_NAME", "Heat Pump"))
    # Tuya DPS mapping
    dp_switch: int = field(default_factory=lambda: int(os.getenv("HEATPUMP_DP_SWITCH", "2")))
    dp_temperature: int = field(default_factory=lambda: int(os.getenv("HEATPUMP_DP_TEMPERATURE", "6")))
    dp_temp_set: int = field(default_factory=lambda: int(os.getenv("HEATPUMP_DP_TEMP_SET", "17")))
    dp_hysteresis: int = field(default_factory=lambda: int(os.getenv("HEATPUMP_DP_HYSTERESIS", "111")))
    dp_mode: int = field(default_factory=lambda: int(os.getenv("HEATPUMP_DP_MODE", "4")))
    dp_temp_scale: int = field(default_factory=lambda: int(os.getenv("HEATPUMP_DP_TEMP_SCALE", "10")))  # 1=°C, 10=°C×10
    standby_target: float = field(default_factory=lambda: float(os.getenv("HEATPUMP_STANDBY_TARGET", "-30")))  # Target when OFF
    solar_override_target: float = field(default_factory=lambda: float(os.getenv("HEATPUMP_SOLAR_OVERRIDE_TARGET", "90")))  # Target when forcing ON
    # Solar override: keep running when excess solar regardless of temperature
    solar_override_enabled: bool = field(default_factory=lambda: os.getenv("HEATPUMP_SOLAR_OVERRIDE", "true").lower() == "true")
    solar_override_production_min: int = field(default_factory=lambda: int(os.getenv("HEATPUMP_SOLAR_OVERRIDE_PRODUCTION_MIN", "0")))  # Min PV production watts to trigger ON (0 = disabled)
    solar_override_export_min: int = field(default_factory=lambda: int(os.getenv("HEATPUMP_SOLAR_OVERRIDE_EXPORT_MIN", "0")))  # Min grid export watts to trigger ON (0 = disabled)
    solar_override_hp_power: int = field(default_factory=lambda: int(os.getenv("HEATPUMP_SOLAR_OVERRIDE_HP_POWER", "3000")))  # Approx heat pump consumption (W)
    solar_override_delay: int = field(default_factory=lambda: int(os.getenv("HEATPUMP_SOLAR_OVERRIDE_DELAY", os.getenv("HEATPUMP_SOLAR_OVERRIDE_OFF_DELAY", "60"))))  # Seconds export/import must sustain before solar override activates/deactivates
    # SOC-based override: turn ON when battery is full
    soc_on_threshold: int = field(default_factory=lambda: int(os.getenv("HEATPUMP_SOC_ON_THRESHOLD", "90")))  # SOC >= this → force ON
    soc_off_threshold: int = field(default_factory=lambda: int(os.getenv("HEATPUMP_SOC_OFF_THRESHOLD", "30")))  # SOC <= this → force OFF
    # Voltage-based overrides
    hv_threshold: float = field(default_factory=lambda: float(os.getenv("HEATPUMP_HV_THRESHOLD", "252.0")))  # High-voltage dump ON
    hv_off_threshold: float = field(default_factory=lambda: float(os.getenv("HEATPUMP_HV_OFF_THRESHOLD", "245.0")))  # HV hysteresis OFF
    lv_threshold: float = field(default_factory=lambda: float(os.getenv("HEATPUMP_LV_THRESHOLD", "210.0")))  # Low-voltage shutdown
    lv_recovery_voltage: float = field(default_factory=lambda: float(os.getenv("HEATPUMP_LV_RECOVERY_VOLTAGE", "220.0")))  # Voltage must exceed this for recovery
    lv_recovery_delay: int = field(default_factory=lambda: int(os.getenv("HEATPUMP_LV_RECOVERY_DELAY", "300")))  # Seconds voltage must stay above recovery level
    phase_change_delay: int = field(default_factory=lambda: int(os.getenv("HEATPUMP_PHASE_CHANGE_DELAY", "10")))  # Seconds before voltage triggers activate
    target_phase: str = field(default_factory=lambda: os.getenv("HEATPUMP_TARGET_PHASE", "ANY"))  # Phase to monitor voltage (L1/L2/L3/ANY)


def load_heatpump_schedules() -> list:
    """Load default heat pump temperature schedule slots from environment variables.

    Format: HEATPUMP_SCHEDULE_N=HH:MM-HH:MM,min_temp,max_temp
    Example: HEATPUMP_SCHEDULE_1=16:00-18:00,40,45
    """
    schedules = []
    i = 1
    while True:
        raw = os.getenv(f"HEATPUMP_SCHEDULE_{i}")
        if not raw:
            break
        try:
            parts = raw.split(",")
            time_range, min_temp, max_temp = parts
            start_str, end_str = time_range.split("-")
            sh, sm = start_str.split(":")
            eh, em = end_str.split(":")
            schedules.append(HeatpumpScheduleSlot(
                start_hour=int(sh), start_min=int(sm),
                end_hour=int(eh), end_min=int(em),
                min_temp=float(min_temp), max_temp=float(max_temp),
            ))
        except (ValueError, IndexError):
            print(f"[CONFIG] Warning: Could not parse HEATPUMP_SCHEDULE_{i}={raw}")
        i += 1
    return schedules


@dataclass
class SunsetChargingConfig:
    """Configuration for sunset-aware charging."""
    latitude: float = field(default_factory=lambda: float(os.getenv("SOLAR_LATITUDE", "47.00")))
    longitude: float = field(default_factory=lambda: float(os.getenv("SOLAR_LONGITUDE", "22.00")))
    battery_capacity_ah: int = field(default_factory=lambda: int(os.getenv("BATTERY_CAPACITY_AH", "600")))
    target_soc: int = field(default_factory=lambda: int(os.getenv("SUNSET_TARGET_SOC", "100")))
    buffer_minutes: int = field(default_factory=lambda: int(os.getenv("SUNSET_BUFFER_MINUTES", "60")))
    min_charge_amps: int = field(default_factory=lambda: int(os.getenv("SUNSET_MIN_CHARGE_AMPS", "10")))
    peak_solar_hour: float = field(default_factory=lambda: float(os.getenv("SUNSET_PEAK_SOLAR_HOUR", "0")))  # 0 = auto (solar noon)
    peak_expected_kw: float = field(default_factory=lambda: float(os.getenv("SUNSET_PEAK_EXPECTED_KW", "0")))  # 0 = disabled (no cloudy compensation)
    cloud_threshold_pct: int = field(default_factory=lambda: int(os.getenv("SUNSET_CLOUD_THRESHOLD_PCT", "60")))  # Below this % of expected → boost
    cloud_max_boost: float = field(default_factory=lambda: float(os.getenv("SUNSET_CLOUD_MAX_BOOST", "3.0")))  # Maximum boost multiplier
    enabled_at_startup: bool = field(default_factory=lambda: os.getenv("SUNSET_CHARGING_ENABLED", "true").lower() == "true")
    weather_enabled: bool = field(default_factory=lambda: os.getenv("SUNSET_WEATHER_ENABLED", "true").lower() == "true")
    weather_refresh_hours: float = field(default_factory=lambda: float(os.getenv("SUNSET_WEATHER_REFRESH_HOURS", "3")))


def load_default_schedules() -> list:
    """Load default schedule rows from environment variables.
    
    Format: SCHEDULE_N=HH:MM-HH:MM,max_charge,grid_charge,max_discharge,sell|nosell,sell_power
    Example: SCHEDULE_1=23:00-06:00,40,40,185,sell,500
    """
    schedules = []
    i = 1
    while True:
        raw = os.getenv(f"SCHEDULE_{i}")
        if not raw:
            break
        try:
            parts = raw.split(",")
            time_range, max_charge, grid_charge, max_discharge, sell_mode, sell_power = parts
            start_str, end_str = time_range.split("-")
            sh, sm = start_str.split(":")
            eh, em = end_str.split(":")
            schedules.append({
                "start_hour": int(sh), "start_min": int(sm),
                "end_hour": int(eh), "end_min": int(em),
                "max_charge_amps": int(max_charge),
                "grid_charge_amps": int(grid_charge),
                "max_discharge_amps": int(max_discharge),
                "sell": sell_mode.strip().lower() == "sell",
                "sell_power": int(sell_power),
            })
        except (ValueError, IndexError):
            print(f"[CONFIG] Warning: Could not parse SCHEDULE_{i}={raw}")
        i += 1
    return schedules


# Global config instances
deye_config = DeyeConfig()
outlet_configs = load_outlet_configs()
ems_defaults = EMSDefaults()
protection_config = OverpowerProtectionConfig()
sunset_config = SunsetChargingConfig()
ev_charger_config = EVChargerConfig()
heatpump_config = TuyaHeatpumpConfig()
heatpump_schedules = load_heatpump_schedules()
default_schedules = load_default_schedules()
