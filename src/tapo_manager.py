"""
Tapo smart plug manager with async connection handling using official tapo library.
"""

import asyncio
import threading
from typing import Optional
from tapo import ApiClient

from src.config import tapo_config


class TapoManager:
    """
    Manages Tapo smart plug connection and state control.
    Runs an async event loop in a background thread for non-blocking operation.
    """
    
    def __init__(self):
        self.device = None
        self.target_state: Optional[bool] = None
        self.current_state: bool = False
        self.is_connected: bool = False
        
        # Start async event loop in background thread
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        """Run the async event loop in background thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main_task())

    async def _main_task(self) -> None:
        """Main async task that continuously monitors and controls the device."""
        while True:
            try:
                # Connect if not connected
                if self.device is None:
                    client = ApiClient(tapo_config.username, tapo_config.password)
                    self.device = await client.p110(tapo_config.ip)
                
                # Update device state
                info = await self.device.get_device_info()
                self.current_state = info.device_on
                self.is_connected = True
                
                # Apply target state if set
                if self.target_state is not None:
                    if self.target_state != self.current_state:
                        if self.target_state:
                            await self.device.on()
                        else:
                            await self.device.off()
                    self.target_state = None
                    
            except Exception as e:
                print(f"TAPO Error: {e}")
                self.is_connected = False
                self.device = None
                
            await asyncio.sleep(2)

    def turn_on(self) -> None:
        """Request to turn on the device."""
        self.target_state = True

    def turn_off(self) -> None:
        """Request to turn off the device."""
        self.target_state = False

    def toggle(self) -> None:
        """Toggle the current state."""
        if self.is_connected:
            self.target_state = not self.current_state
