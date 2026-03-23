"""
Tuya-based EV charger manager.
Controls an EV charger via tinytuya, supporting on/off and amperage control.
Runs an async-safe polling loop in a background thread.
"""

import threading
import time
from typing import Optional, Callable
from dataclasses import dataclass, field

import tinytuya

from src.config import EVChargerConfig


@dataclass
class ChargerState:
    """Current state of the EV charger."""
    is_connected: bool = False
    is_on: bool = False          # Switch is on (DP 123) — charger offering power
    is_charging: bool = False    # Car is actually drawing power (DP 124)
    error_state: str = ""        # DP 101 — "normal" or error description
    current_amps: int = 0
    # Timestamps for rate-limiting
    last_change_time: float = 0.0


class TuyaChargerManager:
    """
    Manages a Tuya-based EV charger.
    Polls device status in a background thread and applies commands with rate-limiting.
    """

    def __init__(self, config: EVChargerConfig,
                 error_callback: Optional[Callable[[str], None]] = None):
        self.config = config
        self.error_callback = error_callback
        self.state = ChargerState()

        self._device: Optional[tinytuya.OutletDevice] = None
        self._lock = threading.Lock()
        self._pending_amps: Optional[int] = None
        self._pending_on_off: Optional[bool] = None  # True=on, False=off, None=no change
        self._retry_count = 0
        self._max_retries = 10
        self._permanent_failure = False
        self._last_error_logged = False
        self._known_dps: dict = {}  # Merged DPS state across partial reads
        self._write_grace_until: float = 0.0  # Don't overwrite amps from poll until this time

        # Start background polling thread
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------
    # Public API (thread-safe, non-blocking)
    # ------------------------------------------------------------------

    def set_amps(self, amps: int) -> None:
        """Request an amperage change (applied on next poll cycle respecting rate limit)."""
        amps = max(self.config.min_amps, min(amps, self.config.max_amps))
        with self._lock:
            self._pending_amps = amps

    def turn_on(self) -> None:
        """Request charger to start charging."""
        with self._lock:
            self._pending_on_off = True

    def turn_off(self) -> None:
        """Request charger to stop charging."""
        with self._lock:
            self._pending_on_off = False

    def get_state(self) -> ChargerState:
        """Return a snapshot of the current charger state."""
        return self.state

    def stop(self) -> None:
        """Stop the background thread."""
        self._running = False

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Background thread: connect, poll status, apply pending commands."""
        while self._running:
            try:
                if self._permanent_failure:
                    time.sleep(5)
                    continue

                # Connect if needed
                if self._device is None:
                    if self._retry_count >= self._max_retries:
                        self._permanent_failure = True
                        self.state.is_connected = False
                        if self.error_callback and not self._last_error_logged:
                            self.error_callback(
                                f"[EV Charger] FAILED - Stopped retrying after "
                                f"{self._max_retries} attempts. Check configuration."
                            )
                            self._last_error_logged = True
                        continue
                    self._connect()

                if self._device is None:
                    time.sleep(min(2 ** self._retry_count, 60))
                    continue

                # Poll status
                self._poll_status()

                # Apply pending commands if rate-limit allows
                self._apply_pending()

                # Reset retry counters on success
                self._retry_count = 0
                self._last_error_logged = False

            except Exception as e:
                self._handle_error(e)

            time.sleep(2)

    def _connect(self) -> None:
        """Create a tinytuya device connection."""
        try:
            dev = tinytuya.OutletDevice(
                dev_id=self.config.device_id,
                address=self.config.ip,
                local_key=self.config.local_key,
                version=self.config.protocol_version,
            )
            dev.set_socketPersistent(True)
            # Quick status check to verify connection
            status = dev.status()
            if "Error" in status:
                raise ConnectionError(status["Error"])
            self._device = dev
            self.state.is_connected = True
            if self.error_callback and self._retry_count > 0:
                self.error_callback("[EV Charger] Reconnected")
        except Exception as e:
            self._device = None
            self.state.is_connected = False
            self._retry_count += 1
            if not self._last_error_logged:
                msg = str(e)[:100]
                if self.error_callback:
                    self.error_callback(f"[EV Charger] Connection failed: {msg}")
                self._last_error_logged = True

    def _poll_status(self) -> None:
        """Read current charger status from tinytuya."""
        status = self._device.status()
        if "Error" in status:
            raise ConnectionError(status["Error"])

        dps = status.get("dps", {})
        # Merge partial reads into full known state
        self._known_dps.update(dps)

        switch_dp = str(self.config.dp_switch)
        amps_dp = str(self.config.dp_amps)
        state_dp = str(self.config.dp_state)

        # DP 123 (switch): is the charger switched on?
        if switch_dp in self._known_dps:
            self.state.is_on = bool(self._known_dps[switch_dp])

        # DP 101 (error/status): "error" = fault, "charing" = actively
        # providing power (feyree misspelling), "normal" = idle/standby.
        error_str = str(self._known_dps.get("101", "normal")).lower()
        self.state.error_state = error_str if "error" in error_str else ""
        dp101_charging = "char" in error_str  # "charing" or "charging"

        # DP 124 (state string): car/charger interaction state
        state_str = self._known_dps.get(state_dp, "")
        if state_str:
            lower = state_str.lower()
            # "Charging" = active draw, "WaitOperation" = on & providing pilot
            # "CloseCharging" = off/stopped
            dp124_active = "close" not in lower and lower != ""
        else:
            dp124_active = False

        # Combine signals: charger is on if switch says so, OR if DP 101
        # confirms it's actively providing power
        if dp101_charging:
            self.state.is_on = True

        # is_charging: car is actually drawing power
        self.state.is_charging = dp101_charging and dp124_active

        if amps_dp in self._known_dps and time.time() > self._write_grace_until:
            raw_amps = self._known_dps[amps_dp]
            self.state.current_amps = int(raw_amps) // self.config.dp_amps_scale
        self.state.is_connected = True

    def _apply_pending(self) -> None:
        """Apply any pending on/off or amp changes immediately.

        Rate-limiting is handled upstream by EVChargingLogic; this method
        executes commands as soon as they are queued.

        When changing amps while the charger is on, we do a safe sequence:
        OFF → set amps → ON.  This prevents overcurrent trips caused by
        the car continuing to draw the old (higher) current for a few
        seconds after the limit is lowered.
        """
        # Don't send commands while charger is in error state
        if self.state.error_state:
            return

        now = time.time()

        with self._lock:
            pending_on_off = self._pending_on_off
            pending_amps = self._pending_amps

        if pending_on_off is None and pending_amps is None:
            return  # Nothing to do

        switch_dp = str(self.config.dp_switch)
        amps_dp = str(self.config.dp_amps)
        desc_parts = []

        with self._lock:
            if self._pending_amps is not None:
                desired_amps = self._pending_amps
                scaled = desired_amps * self.config.dp_amps_scale
                if desired_amps != self.state.current_amps:
                    # When lowering amps while on: OFF → set → ON to avoid
                    # overcurrent from the car still drawing the old rate.
                    lowering = desired_amps < self.state.current_amps
                    if lowering and self.state.is_on:
                        self._device.set_value(switch_dp, False)
                        time.sleep(5)
                    self._device.set_value(amps_dp, scaled)
                    if lowering and self.state.is_on:
                        time.sleep(5)
                        self._device.set_value(switch_dp, True)
                    desc_parts.append(f"{desired_amps}A")
                    self.state.current_amps = desired_amps
                    self._write_grace_until = time.time() + 30
                self._pending_amps = None

            if self._pending_on_off is not None:
                desired_on = self._pending_on_off
                if desired_on != self.state.is_on:
                    self._device.set_value(switch_dp, desired_on)
                    desc_parts.append("ON" if desired_on else "OFF")
                    self.state.is_on = desired_on
                self._pending_on_off = None

        if not desc_parts:
            return  # Values already match

        self.state.last_change_time = now
        desc = ", ".join(desc_parts)
        print(f"[EV Charger] Applied: {desc}")
        if self.error_callback:
            self.error_callback(f"[EV Charger] Set {desc}")

    def _handle_error(self, e: Exception) -> None:
        """Handle connection or command errors."""
        error_msg = str(e)
        if not self._last_error_logged:
            summary = error_msg[:100]
            if self.error_callback:
                self.error_callback(f"[EV Charger] Error: {summary}")
            self._last_error_logged = True
        self.state.is_connected = False
        self._device = None
        self._retry_count += 1
