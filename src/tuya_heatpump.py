"""
Tuya-based heat pump thermostat manager.
Controls a smart outlet with thermostat via tinytuya, setting target temperature
and hysteresis so the device firmware handles relay switching internally.
Runs a polling loop in a background thread.
"""

import threading
import time
from typing import Optional, Callable
from dataclasses import dataclass

import tinytuya

from src.config import TuyaHeatpumpConfig


@dataclass
class HeatpumpState:
    """Current state of the Tuya heat pump thermostat."""
    is_connected: bool = False
    is_on: bool = False           # Relay state (read-only, controlled by thermostat firmware)
    temperature: Optional[float] = None  # Current temperature reading (°C)
    target_temp: Optional[float] = None  # Current target temperature on device (°C)
    hysteresis: Optional[float] = None   # Current hysteresis on device (°C)
    mode: Optional[str] = None           # Current thermostat mode (heat/cool)


class TuyaHeatpumpManager:
    """
    Manages a Tuya thermostat outlet controlling a heat pump.
    Instead of toggling the relay directly, sets target temperature and hysteresis
    on the device so its firmware handles on/off with zero delay.
    """

    def __init__(self, config: TuyaHeatpumpConfig,
                 error_callback: Optional[Callable[[str], None]] = None):
        self.config = config
        self.error_callback = error_callback
        self.state = HeatpumpState()

        self._device: Optional[tinytuya.OutletDevice] = None
        self._lock = threading.Lock()
        self._pending_target: Optional[float] = None   # Desired target temp (°C)
        self._pending_hysteresis: Optional[float] = None  # Desired hysteresis (°C)
        self._pending_mode: Optional[str] = None  # Desired mode (heat/cool)
        self._retry_count = 0
        self._max_retries = 10
        self._permanent_failure = False
        self._last_error_logged = False
        self._known_dps: dict = {}

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------
    # Public API (thread-safe, non-blocking)
    # ------------------------------------------------------------------

    def set_target_temp(self, temp_c: float) -> None:
        """Request a target temperature change (°C). Device relay follows automatically."""
        with self._lock:
            self._pending_target = temp_c

    def set_hysteresis(self, value_c: float) -> None:
        """Request a hysteresis change (°C). E.g. 7.0 means relay ON at target-7."""
        with self._lock:
            self._pending_hysteresis = value_c

    def set_mode(self, mode: str) -> None:
        """Request thermostat mode change ('heat' or 'cool')."""
        with self._lock:
            self._pending_mode = mode

    def get_state(self) -> HeatpumpState:
        """Return a snapshot of the current state."""
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

                if self._device is None:
                    if self._retry_count >= self._max_retries:
                        self._permanent_failure = True
                        self.state.is_connected = False
                        if self.error_callback and not self._last_error_logged:
                            self.error_callback(
                                f"[{self.config.name}] FAILED - Stopped retrying after "
                                f"{self._max_retries} attempts."
                            )
                            self._last_error_logged = True
                        continue
                    self._connect()

                if self._device is None:
                    time.sleep(min(2 ** self._retry_count, 60))
                    continue

                self._poll_status()
                self._apply_pending()

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
            status = dev.status()
            if "Error" in status:
                raise ConnectionError(status["Error"])
            self._device = dev
            self.state.is_connected = True
            if self.error_callback and self._retry_count > 0:
                self.error_callback(f"[{self.config.name}] Reconnected")
        except Exception as e:
            self._device = None
            self.state.is_connected = False
            self._retry_count += 1
            if not self._last_error_logged:
                msg = str(e)[:100]
                if self.error_callback:
                    self.error_callback(f"[{self.config.name}] Connection failed: {msg}")
                self._last_error_logged = True

    def _poll_status(self) -> None:
        """Read current thermostat status from tinytuya."""
        status = self._device.status()
        if "Error" in status:
            raise ConnectionError(status["Error"])

        dps = status.get("dps", {})
        self._known_dps.update(dps)

        scale = self.config.dp_temp_scale
        switch_dp = str(self.config.dp_switch)
        temp_dp = str(self.config.dp_temperature)
        target_dp = str(self.config.dp_temp_set)
        hyst_dp = str(self.config.dp_hysteresis)
        mode_dp = str(self.config.dp_mode)

        if switch_dp in self._known_dps:
            self.state.is_on = bool(self._known_dps[switch_dp])

        if temp_dp in self._known_dps:
            try:
                self.state.temperature = float(self._known_dps[temp_dp]) / scale
            except (ValueError, TypeError):
                pass

        if target_dp in self._known_dps:
            try:
                self.state.target_temp = float(self._known_dps[target_dp]) / scale
            except (ValueError, TypeError):
                pass

        if hyst_dp in self._known_dps:
            try:
                self.state.hysteresis = float(self._known_dps[hyst_dp]) / scale
            except (ValueError, TypeError):
                pass

        if mode_dp in self._known_dps:
            self.state.mode = str(self._known_dps[mode_dp])

        self.state.is_connected = True

    def _apply_pending(self) -> None:
        """Apply any pending target temp, hysteresis, or mode changes."""
        with self._lock:
            pending_target = self._pending_target
            pending_hyst = self._pending_hysteresis
            pending_mode = self._pending_mode

        scale = self.config.dp_temp_scale

        # Apply mode change
        if pending_mode is not None:
            mode_dp = str(self.config.dp_mode)
            if self.state.mode != pending_mode:
                self._device.set_value(mode_dp, pending_mode)
                self.state.mode = pending_mode
                print(f"[{self.config.name}] Mode -> {pending_mode}")
                if self.error_callback:
                    self.error_callback(f"[{self.config.name}] Mode: {pending_mode}")
            with self._lock:
                self._pending_mode = None

        # Apply hysteresis change
        if pending_hyst is not None:
            hyst_dp = str(self.config.dp_hysteresis)
            raw_hyst = int(round(pending_hyst * scale))
            current_raw = int(round((self.state.hysteresis or 0) * scale))
            if raw_hyst != current_raw:
                self._device.set_value(hyst_dp, raw_hyst)
                self.state.hysteresis = pending_hyst
                print(f"[{self.config.name}] Hysteresis -> {pending_hyst}°C")
            with self._lock:
                self._pending_hysteresis = None

        # Apply target temperature change
        if pending_target is not None:
            target_dp = str(self.config.dp_temp_set)
            raw_target = int(round(pending_target * scale))
            current_raw = int(round((self.state.target_temp or -999) * scale))
            if raw_target != current_raw:
                self._device.set_value(target_dp, raw_target)
                old = self.state.target_temp
                self.state.target_temp = pending_target
                print(f"[{self.config.name}] Target -> {pending_target}°C (was {old}°C)")
                if self.error_callback:
                    self.error_callback(f"[{self.config.name}] Target: {pending_target}°C")
            with self._lock:
                self._pending_target = None

    def _handle_error(self, e: Exception) -> None:
        """Handle connection or command errors."""
        error_msg = str(e)
        if not self._last_error_logged:
            summary = error_msg[:100]
            if self.error_callback:
                self.error_callback(f"[{self.config.name}] Error: {summary}")
            self._last_error_logged = True
        self.state.is_connected = False
        self._device = None
        self._retry_count += 1
