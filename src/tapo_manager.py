"""
Tapo smart plug manager with async connection handling using official tapo library.
Supports multiple outlets with individual control.
"""

import asyncio
import threading
import time
from typing import Optional, Dict, Callable, List
from tapo import ApiClient

from src.config import outlet_configs, OutletConfig

# A plug allows one session at a time: another client logging in ends ours. Losing the
# session this soon after logging in means another client keeps using the plug (e.g. a
# second DeyeMonitor), so wait instead of taking it straight back in a login tug-of-war.
SESSION_CONTENTION_SECONDS = 60
CONTENTION_BACKOFF_SECONDS = 60
CONTENTION_LOG_INTERVAL_SECONDS = 600

# An unreachable plug is retried after 2, 4, 8, ... seconds, then every RETRY_MAX_SECONDS,
# for as long as it stays unreachable: a plug that comes back is picked up again.
RETRY_MAX_SECONDS = 60


def is_session_error(error_msg: str) -> bool:
    """Expired session: the plug wants a fresh login, not a backoff.

    tapo 0.8.8 says "SessionTimeout"; newer versions say
    'Unauthorized { kind: "SESSION_TIMEOUT", description: "Session has expired..." }'.
    Other Unauthorized kinds (wrong credentials) are not matched, so they keep the backoff.
    """
    text = error_msg.lower()
    return any(marker in text for marker in ("sessiontimeout", "session_timeout", "session has expired",
                                             "403", "forbidden"))


class OutletDevice:
    """Represents a single outlet device with its state."""
    
    def __init__(self, config: OutletConfig):
        self.config = config
        self.device = None
        self.target_state: Optional[bool] = None
        self.current_state: bool = False
        self.is_connected: bool = False
        self._last_error_logged: bool = False  # Track if we've already logged an error
        self._retry_count: int = 0  # Consecutive failed attempts (sets the retry delay)
        self._next_attempt: float = 0.0  # time.monotonic() before which no reconnect is tried
        self._connected_at: Optional[float] = None  # time.monotonic() of the last login
        self._reconnect_after: float = 0.0  # No login before this (another client has the plug)
        self._last_contention_log: Optional[float] = None

    async def connect(self) -> None:
        """Connect to the outlet device."""
        client = ApiClient(self.config.username, self.config.password)
        self.device = await client.p110(self.config.ip)
        self._connected_at = time.monotonic()
    
    async def update_state(self) -> None:
        """Update the current state from the device."""
        info = await self.device.get_device_info()
        self.current_state = info.device_on
        self.is_connected = True
    
    async def apply_target_state(self) -> None:
        """Apply the target state if set."""
        if self.target_state is not None:
            try:
                if self.target_state != self.current_state:
                    if self.target_state:
                        await self.device.on()
                    else:
                        await self.device.off()
                # Clear target state after successful application
                self.target_state = None
            except Exception:
                # If toggle fails, clear target state to prevent endless retry loop
                # The outlet will be read again on next cycle to get actual state
                self.target_state = None
                raise  # Re-raise to be caught by outer exception handler


class TapoManager:
    """
    Manages multiple Tapo smart plug connections and state control.
    Runs an async event loop in a background thread for non-blocking operation.
    """
    
    def __init__(self, error_callback: Optional[Callable[[str], None]] = None,
                 configs: Optional[List[OutletConfig]] = None):
        # Create outlet devices from config (defaults to the EMS outlets from .env)
        self.outlets: Dict[int, OutletDevice] = {
            cfg.outlet_id: OutletDevice(cfg) 
            for cfg in (outlet_configs if configs is None else configs)
        }
        
        # Error callback for UI logging
        self.error_callback = error_callback
        
        # Start async event loop in background thread
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        """Run the async event loop in background thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main_task())

    async def _main_task(self) -> None:
        """Main async task that continuously monitors and controls all devices."""
        while True:
            for outlet in self.outlets.values():
                try:
                    await self._poll_outlet(outlet)
                except Exception as e:
                    # Never let one outlet (or a logging failure) end the loop: every outlet
                    # of this manager would then stay "offline" until the app restarts.
                    print(f"[TAPO] Unexpected error polling {outlet.config.name}: {e}")
            await asyncio.sleep(2)

    def _report(self, message: str) -> None:
        """Send a message to the UI log; a failing callback must not break the polling."""
        if self.error_callback is None:
            return
        try:
            self.error_callback(message)
        except Exception as e:
            print(f"{message} (log callback failed: {e})")

    async def _poll_outlet(self, outlet: OutletDevice) -> None:
        """One cycle for one outlet: connect if needed, read its state, apply a pending on/off."""
        try:
            # Connect if not connected
            if outlet.device is None:
                now = time.monotonic()
                # Another client had the plug moments after our last login: let it be for a while
                if now < outlet._reconnect_after:
                    return
                # Still waiting out the retry delay after a failed attempt
                if now < outlet._next_attempt:
                    return

                await outlet.connect()

            # Update device state
            await outlet.update_state()

            # Apply target state if set
            await outlet.apply_target_state()

            if outlet._last_error_logged:
                self._report(f"[{outlet.config.name}] Back online")
            outlet._retry_count = 0
            outlet._last_error_logged = False

        except Exception as e:
            error_msg = str(e)

            # Force reconnection on session errors (expired session, 403 Forbidden)
            session_error = is_session_error(error_msg)
            if session_error:
                outlet.device = None
                self._on_session_lost(outlet)
            else:
                # Only log error once when state changes from connected to disconnected
                if not outlet._last_error_logged:
                    error_summary = error_msg[:100] if len(error_msg) > 100 else error_msg
                    self._report(f"[{outlet.config.name}] Offline: {error_summary}")
                    outlet._last_error_logged = True

            outlet.is_connected = False
            if not session_error:
                outlet.device = None
                outlet._retry_count += 1
                outlet._next_attempt = time.monotonic() + min(2 ** outlet._retry_count, RETRY_MAX_SECONDS)

    def _on_session_lost(self, outlet: OutletDevice) -> None:
        """Reconnect at once after a normal expiry; back off when another client keeps taking the plug."""
        now = time.monotonic()
        held_for = None if outlet._connected_at is None else now - outlet._connected_at
        if held_for is None or held_for >= SESSION_CONTENTION_SECONDS:
            if not outlet._last_error_logged:
                self._report(f"[{outlet.config.name}] Session expired, reconnecting...")
            return

        outlet._reconnect_after = now + CONTENTION_BACKOFF_SECONDS
        if outlet._last_contention_log is None or now - outlet._last_contention_log >= CONTENTION_LOG_INTERVAL_SECONDS:
            outlet._last_contention_log = now
            self._report(
                f"[{outlet.config.name}] Lost the session {int(held_for)}s after logging in: another client is "
                f"logging in to this plug, which allows one session at a time (a second DeyeMonitor running?). "
                f"Retrying every {CONTENTION_BACKOFF_SECONDS}s")

    def turn_on(self, outlet_id: int) -> None:
        """Request to turn on a specific outlet."""
        if outlet_id in self.outlets:
            self.outlets[outlet_id].target_state = True

    def turn_off(self, outlet_id: int) -> None:
        """Request to turn off a specific outlet."""
        if outlet_id in self.outlets:
            self.outlets[outlet_id].target_state = False

    def toggle(self, outlet_id: int) -> None:
        """Toggle the current state of a specific outlet."""
        if outlet_id in self.outlets:
            outlet = self.outlets[outlet_id]
            # Allow toggle even if not connected - will attempt to apply when connection is restored.
            # A manual toggle retries an offline outlet right away instead of waiting out the delay.
            outlet._next_attempt = 0.0
            outlet.target_state = not outlet.current_state
    
    def get_outlet(self, outlet_id: int) -> Optional[OutletDevice]:
        """Get an outlet device by ID."""
        return self.outlets.get(outlet_id)
    
    def get_all_outlets(self) -> Dict[int, OutletDevice]:
        """Get all outlet devices."""
        return self.outlets
