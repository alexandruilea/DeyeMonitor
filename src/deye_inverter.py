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
    ups_loads: List[int]  # UPS/Backup port loads per phase [L1, L2, L3] - Inverter output (base 588)
    grid_loads: List[int]  # Grid CT loads per phase [L1, L2, L3] - Total consumption (base 160, may be 0 if no smart meter)


class DeyeInverter:
    """
    Handles communication with Deye inverter via Solarman/Modbus protocol.
    """
    
    # Register addresses
    REGISTER_START = 588
    REGISTER_COUNT = 90
    
    # UPS/Load register addresses
    UPS_REGISTER_START = 160
    UPS_REGISTER_COUNT = 35
    
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
                
            # Read main registers (base 588) - Contains UPS loads
            raw = self._modbus.read_holding_registers(
                register_addr=self.REGISTER_START,
                quantity=self.REGISTER_COUNT
            )
            
            # Read grid CT registers (base 160) - May be 0 if smart meter not enabled
            grid_raw = self._modbus.read_holding_registers(
                register_addr=self.UPS_REGISTER_START,
                quantity=self.UPS_REGISTER_COUNT
            )
            
            return InverterData(
                soc=raw[0],
                battery_power=self._parse_signed(raw[2]),
                pv_power=raw[84] + raw[85],
                grid_power=self._parse_signed(raw[37]),
                voltages=[raw[56] / 10, raw[57] / 10, raw[58] / 10],
                ups_loads=[raw[62], raw[63], raw[64]],  # Base 588: UPS output loads (always available)
                grid_loads=[grid_raw[19], grid_raw[20], grid_raw[21]]  # Base 160: Grid CT (0 if no smart meter)
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
