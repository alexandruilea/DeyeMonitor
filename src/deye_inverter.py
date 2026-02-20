"""
Deye inverter communication module via Modbus/Solarman protocol.
"""

from dataclasses import dataclass, field
from typing import Optional, List
from pysolarmanv5 import PySolarmanV5

from src.config import deye_config


@dataclass
class BMSData:
    """Data structure for complete BMS readings."""
    # BMS system-level data (registers 210-224)
    charge_voltage: float = 0.0       # BMS charge voltage setpoint (V)
    discharge_voltage: float = 0.0    # BMS discharge voltage setpoint (V)
    charge_current_limit: int = 0     # BMS charge current limit (A)
    discharge_current_limit: int = 0  # BMS discharge current limit (A)
    realtime_soc: int = 0             # Real-time SOC (%)
    realtime_voltage: float = 0.0     # Real-time voltage (V)
    realtime_current: int = 0         # Real-time current (A)
    realtime_temperature: float = 0.0 # Real-time temperature (°C)
    max_charge_current_offgrid: int = 0   # Max charge current off-grid (A)
    max_discharge_current_offgrid: int = 0  # Max discharge current off-grid (A)
    alarm: int = 0                    # Alarm bitmask
    fault: int = 0                    # Fault bitmask
    battery_type: int = 0             # Battery type code
    soh: int = 0                      # State of Health (%)
    # Battery summary (registers 586-592)
    battery_temperature: float = 0.0  # Battery temperature (°C)
    battery_voltage: float = 0.0      # Battery voltage (V)
    battery_soc: int = 0              # Battery SOC (%)
    battery_power: int = 0            # Battery power (W)
    battery_current: float = 0.0      # Battery current (A)
    corrected_ah: int = 0             # Corrected capacity (Ah)
    # Daily/total energy (registers 514-519)
    today_charge_kwh: float = 0.0     # Today's charge (kWh)
    today_discharge_kwh: float = 0.0  # Today's discharge (kWh)
    total_charge_kwh: float = 0.0     # Total charge (kWh)
    total_discharge_kwh: float = 0.0  # Total discharge (kWh)


@dataclass
class InverterData:
    """Data structure for inverter readings."""
    soc: int  # State of charge (%)
    battery_power: int  # Battery power (W) - positive = charging, negative = discharging
    pv_power: int  # Solar PV power (W)
    grid_power: int  # Grid power (W) - positive = importing, negative = exporting
    voltages: List[float]  # Phase voltages [L1, L2, L3]
    ups_loads: List[int]  # UPS/Backup port loads per phase [L1, L2, L3] - Backup port output (base 588 R52-54)
    grid_loads: List[int]  # Grid side phase power per phase [L1, L2, L3] - Actual grid power per phase (base 588 R34-36)
    total_loads: List[int]  # Total load consumption per phase [L1, L2, L3] - Total consumption (base 588 R62-64)
    running_state: int  # Running state (0=standby, 1=selfcheck, 2=normal, 3=alarm, 4=fault) - base 500 R0
    is_grid_connected: bool  # Grid relay status from AC relay register (base 552 Bit2)


class DeyeInverter:
    """
    Handles communication with Deye inverter via Solarman/Modbus protocol.
    """
    
    # Register addresses for reading
    REGISTER_START = 588  # Main data registers (SOC, power, voltages, UPS loads, grid CT)
    REGISTER_COUNT = 90
    
    # Status register addresses  
    STATUS_REGISTER_START = 500  # Running state, AC relay status
    STATUS_REGISTER_COUNT = 53  # Read up to register 552 for AC relay status
    
    # Write control registers are loaded from config (deye_config.reg_*)
    
    def __init__(self):
        self._modbus: Optional[PySolarmanV5] = None

    def _connect(self) -> bool:
        """Establish connection to the inverter."""
        try:
            if self._modbus is None:
                self._modbus = PySolarmanV5(
                    deye_config.ip,
                    deye_config.logger_serial,
                    port=deye_config.port,
                    auto_reconnect=True
                )
            return True
        except Exception:
            self._modbus = None
            return False

    def _parse_signed(self, value: int) -> int:
        """Convert unsigned 16-bit register value to signed."""
        return value if value < 32768 else value - 65536

    def read_data(self) -> Optional[InverterData]:
        """
        Read current data from the inverter.
        
        Returns:
            InverterData object with current readings, or None if read failed.
        """
        try:
            if not self._connect():
                return None
                
            # Read main registers (base 588) - Contains SOC, power, voltages, UPS loads, external CT
            raw = self._modbus.read_holding_registers(
                register_addr=self.REGISTER_START,
                quantity=self.REGISTER_COUNT
            )
            
            # Read status registers (base 500) - Running state, relay status
            status_raw = self._modbus.read_holding_registers(
                register_addr=self.STATUS_REGISTER_START,
                quantity=self.STATUS_REGISTER_COUNT
            )
            
            # Extract grid relay status from AC relay register (base 500 + 52 = register 552)
            # Bit2 of register 552 indicates grid relay: 0=off-grid, 1=on-grid
            ac_relay_status = status_raw[52]  # Register 552
            is_grid_connected = bool(ac_relay_status & 0x04)  # Bit2
            
            return InverterData(
                soc=raw[0],  # R0: Battery capacity
                battery_power=self._parse_signed(raw[2]),  # R2: Battery output power
                pv_power=raw[84] + raw[85],  # R84-85: PV power
                grid_power=self._parse_signed(raw[37]),  # R37: Grid side total power
                voltages=[raw[56] / 10, raw[57] / 10, raw[58] / 10],  # R56-58: Load phase voltages
                ups_loads=[raw[52], raw[53], raw[54]],  # R52-54: UPS load-side phase power (backup port output)
                grid_loads=[self._parse_signed(raw[34]), self._parse_signed(raw[35]), self._parse_signed(raw[36])],  # R34-36: Grid side phase power (actual grid import/export per phase)
                total_loads=[self._parse_signed(raw[62]), self._parse_signed(raw[63]), self._parse_signed(raw[64])],  # R62-64: Total load consumption per phase
                running_state=status_raw[0],  # R0 of base 500: Running state
                is_grid_connected=is_grid_connected  # Bit2 of register 552
            )
            
        except Exception:
            self._modbus = None
            return None

    def read_battery_settings(self) -> tuple:
        """
        Read current battery charge and discharge settings from the inverter.
        
        Returns:
            Tuple of (max_charge_amps, grid_charge_amps, max_discharge_amps) or (None, None, None) if read failed.
        """
        try:
            if not self._connect():
                return None, None, None
            
            # Read register 108 (max charge amps), 128 (grid charge amps), and 109 (max discharge amps)
            # They're not contiguous, so read separately
            max_charge = self._modbus.read_holding_registers(deye_config.reg_max_charge_amps, 1)
            grid_charge = self._modbus.read_holding_registers(deye_config.reg_grid_charge_current, 1)
            max_discharge = self._modbus.read_holding_registers(deye_config.reg_max_discharge_amps, 1)
            
            return max_charge[0], grid_charge[0], max_discharge[0]
            
        except Exception as e:
            print(f"[READ] Failed to read charge settings: {e}")
            return None, None, None

    def read_max_sell_power(self) -> int:
        """
        Read the maximum solar sell power limit from the inverter.
        
        Returns:
            Max sell power in Watts, or None if read failed.
        """
        try:
            if not self._connect():
                return None
            
            result = self._modbus.read_holding_registers(deye_config.reg_max_solar_sell_power, 1)
            return result[0] if result else None
            
        except Exception as e:
            print(f"[READ] Failed to read max sell power: {e}")
            return None

    def read_bms_data(self) -> Optional[BMSData]:
        """
        Read complete BMS data including per-pack information.
        
        Returns:
            BMSData object with all battery/BMS readings, or None if read failed.
        """
        try:
            if not self._connect():
                return None
            
            bms = BMSData()
            
            # Read BMS system registers (210-224)
            try:
                bms_raw = self._modbus.read_holding_registers(210, 15)
                bms.charge_voltage = bms_raw[0] * 0.01
                bms.discharge_voltage = bms_raw[1] * 0.01
                bms.charge_current_limit = bms_raw[2]
                bms.discharge_current_limit = bms_raw[3]
                bms.realtime_soc = bms_raw[4]
                bms.realtime_voltage = bms_raw[5] * 0.01
                bms.realtime_current = self._parse_signed(bms_raw[6])
                bms.realtime_temperature = (bms_raw[7] - 1000) / 10.0
                bms.max_charge_current_offgrid = bms_raw[8]
                bms.max_discharge_current_offgrid = bms_raw[9]
                bms.alarm = bms_raw[10]
                bms.fault = bms_raw[11]
                bms.battery_type = bms_raw[13]
                bms.soh = bms_raw[14]
            except Exception as e:
                print(f"[BMS] Failed to read BMS registers 210-224: {e}")
            
            # Read battery daily/total energy (514-519)
            try:
                energy_raw = self._modbus.read_holding_registers(514, 6)
                bms.today_charge_kwh = energy_raw[0] * 0.1
                bms.today_discharge_kwh = energy_raw[1] * 0.1
                bms.total_charge_kwh = (energy_raw[2] + energy_raw[3] * 65536) * 0.1
                bms.total_discharge_kwh = (energy_raw[4] + energy_raw[5] * 65536) * 0.1
            except Exception as e:
                print(f"[BMS] Failed to read energy registers 514-519: {e}")
            
            # Read battery summary (586-592)
            try:
                summary_raw = self._modbus.read_holding_registers(586, 7)
                bms.battery_temperature = (summary_raw[0] - 1000) / 10.0  # Offset 1000 = 0°C
                bms.battery_voltage = summary_raw[1] * 0.01
                bms.battery_soc = summary_raw[2]
                bms.battery_power = self._parse_signed(summary_raw[4])
                bms.battery_current = self._parse_signed(summary_raw[5]) * 0.01
                bms.corrected_ah = summary_raw[6]
            except Exception as e:
                print(f"[BMS] Failed to read summary registers 586-592: {e}")
            
            # Note: Per-pack data registers (600-809) overlap with the main inverter
            # data block (588-677) and are not populated for CAN-connected batteries
            # (e.g. Pylon). Pack-level data is only available with RS485-connected BMS.
            
            return bms
            
        except Exception as e:
            print(f"[BMS] Failed to read BMS data: {e}")
            self._modbus = None
            return None

    def disconnect(self) -> None:
        """Disconnect from the inverter."""
        if self._modbus:
            try:
                self._modbus.disconnect()
            except Exception:
                pass
            self._modbus = None

    def _write_register(self, register: int, value: int, retries: int = 3) -> bool:
        """
        Write a single value to a holding register.
        Uses write_multiple_holding_registers as per deye-controller library.
        
        Args:
            register: Register address to write to
            value: Value to write (16-bit unsigned)
            retries: Number of retry attempts for transient errors
            
        Returns:
            True if write was successful, False otherwise
        """
        import time
        
        for attempt in range(retries):
            try:
                if not self._connect():
                    print(f"  [WRITE] Failed to connect")
                    return False
                print(f"  [WRITE] Writing {value} to register {register}...")
                # Use write_multiple_holding_registers (function code 16) instead of 
                # write_holding_register (function code 6) - this is what deye-controller uses
                self._modbus.write_multiple_holding_registers(register, [value])
                print(f"  [WRITE] Success!")
                return True
            except Exception as e:
                error_msg = str(e)
                # AcknowledgeError means the device accepted but needs time - treat as success
                if "AcknowledgeError" in error_msg or "Acknowledge" in error_msg:
                    print(f"  [WRITE] Acknowledged (device processing) - waiting...")
                    time.sleep(0.5)  # Give device time to process
                    return True
                # Transient communication errors - retry with reconnection
                if ("V5FrameError" in error_msg or "sequence number" in error_msg or 
                    "unpack requires a buffer" in error_msg or "Empty" in error_msg or
                    error_msg.strip() == ""):
                    print(f"  [WRITE] Communication error (attempt {attempt + 1}/{retries}) - retrying...")
                    time.sleep(1.0)  # Delay before retry
                    # Force reconnection on next attempt
                    try:
                        self._modbus.disconnect()
                    except Exception:
                        pass
                    self._modbus = None
                    continue
                print(f"  [WRITE] Exception: {type(e).__name__}: {e}")
                return False
        
        print(f"  [WRITE] Failed after {retries} attempts")
        return False

    def set_grid_charge_current(self, amps: int) -> bool:
        """
        Set the grid charging current in amps.
        This controls how fast the battery charges FROM THE GRID.
        
        Args:
            amps: Charging current in amps (0-185A)
            
        Returns:
            True if successful, False otherwise
        """
        # Clamp value to valid range
        amps = max(0, min(185, amps))
        # Write directly without the 1100 enable/disable sequence
        # This is how deye-controller does it
        return self._write_register(deye_config.reg_grid_charge_current, amps)

    def set_max_charge_current(self, amps: int) -> bool:
        """
        Set the maximum charging current in amps.
        This is the overall max charging speed from any source (PV + Grid).
        
        Args:
            amps: Maximum charging current in amps (0-185A)
            
        Returns:
            True if successful, False otherwise
        """
        amps = max(0, min(185, amps))
        return self._write_register(deye_config.reg_max_charge_amps, amps)

    def set_max_discharge_current(self, amps: int) -> bool:
        """
        Set the maximum discharging current in amps.
        
        Args:
            amps: Maximum discharging current in amps (0-185A)
            
        Returns:
            True if successful, False otherwise
        """
        amps = max(0, min(185, amps))
        return self._write_register(deye_config.reg_max_discharge_amps, amps)
