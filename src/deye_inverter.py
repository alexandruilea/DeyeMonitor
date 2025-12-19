"""
Deye inverter communication module via Modbus/Solarman protocol.
"""

from dataclasses import dataclass
from typing import Optional, List
from pysolarmanv5 import PySolarmanV5

from src.config import deye_config


@dataclass
class InverterData:
    """Data structure for inverter readings."""
    soc: int  # State of charge (%)
    battery_power: int  # Battery power (W) - positive = charging, negative = discharging
    pv_power: int  # Solar PV power (W)
    grid_power: int  # Grid power (W) - positive = importing, negative = exporting
    voltages: List[float]  # Phase voltages [L1, L2, L3]
    ups_loads: List[int]  # UPS/Backup port loads per phase [L1, L2, L3] - Inverter output (base 588 R62-64)
    grid_loads: List[int]  # External CT loads per phase [L1, L2, L3] - Total consumption (base 588 R30-32, may be 0 if no CT)
    running_state: int  # Running state (0=standby, 1=selfcheck, 2=normal, 3=alarm, 4=fault) - base 500 R0
    is_grid_connected: bool  # Grid relay status from AC relay register (base 552 Bit2)


class DeyeInverter:
    """
    Handles communication with Deye inverter via Solarman/Modbus protocol.
    """
    
    # Register addresses
    REGISTER_START = 588  # Main data registers (SOC, power, voltages, UPS loads, grid CT)
    REGISTER_COUNT = 90
    
    # Status register addresses  
    STATUS_REGISTER_START = 500  # Running state, AC relay status
    STATUS_REGISTER_COUNT = 53  # Read up to register 552 for AC relay status
    
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
                ups_loads=[raw[62], raw[63], raw[64]],  # R62-64: UPS load-side phase power (always available)
                grid_loads=[self._parse_signed(raw[30]), self._parse_signed(raw[31]), self._parse_signed(raw[32])],  # R30-32: External CT power (0 if no CT)
                running_state=status_raw[0],  # R0 of base 500: Running state
                is_grid_connected=is_grid_connected  # Bit2 of register 552
            )
            
        except Exception:
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
