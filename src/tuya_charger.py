"""
Tuya-based EV charger manager.
Controls an EV charger via tinytuya, supporting on/off and amperage control.
Runs an async-safe polling loop in a background thread.
"""

import json
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
    is_cloud: bool = False       # True when connected via cloud fallback
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
        self._permanent_failure_time: float = 0.0  # When permanent failure was set
        self._recovery_interval: float = 300.0     # Retry connection every 5 min after permanent failure
        self._last_error_logged = False
        self._known_dps: dict = {}  # Merged DPS state across partial reads
        self._write_grace_until: float = 0.0  # Don't overwrite amps from poll until this time

        # Cloud fallback
        self._cloud: Optional[tinytuya.Cloud] = None
        self._use_cloud: bool = False
        self._cloud_retry_count: int = 0
        self._max_cloud_retries: int = 5
        self._cloud_error_logged: bool = False
        if config.cloud_api_key and config.cloud_api_secret:
            try:
                self._cloud = tinytuya.Cloud(
                    apiRegion=config.cloud_api_region,
                    apiKey=config.cloud_api_key,
                    apiSecret=config.cloud_api_secret,
                    apiDeviceID=config.device_id,
                )
                self._max_retries = 3  # Fail over to cloud faster
                print("[EV Charger] Cloud fallback ready")
            except Exception as e:
                self._cloud = None
                print(f"[EV Charger] Cloud init failed: {e}")

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
                # --- Cloud fallback mode ---
                if self._use_cloud:
                    try:
                        self._cloud_poll_status()
                        self._cloud_apply_pending()
                        self._cloud_retry_count = 0
                        self._cloud_error_logged = False
                    except Exception as e:
                        self._cloud_retry_count += 1
                        if not self._cloud_error_logged:
                            if self.error_callback:
                                self.error_callback(f"[EV Charger] Cloud error: {str(e)[:100]}")
                            self._cloud_error_logged = True
                        if self._cloud_retry_count >= self._max_cloud_retries:
                            # Cloud also failing — fall back to local retry
                            self._use_cloud = False
                            self.state.is_cloud = False
                            self._permanent_failure = False
                            self._retry_count = 0
                            self._last_error_logged = False
                            self._device = None
                            self._cloud_retry_count = 0
                            self._cloud_error_logged = False
                            if self.error_callback:
                                self.error_callback("[EV Charger] Cloud failed - retrying local")
                    time.sleep(120)
                    continue

                if self._permanent_failure:
                    # Switch to cloud fallback if available
                    if self._cloud is not None:
                        self._use_cloud = True
                        self.state.is_cloud = True
                        self._cloud_retry_count = 0
                        self._cloud_error_logged = False
                        if self.error_callback:
                            self.error_callback("[EV Charger] Switched to cloud control")
                        continue
                    # No cloud — periodically retry local
                    if time.time() - self._permanent_failure_time >= self._recovery_interval:
                        self._permanent_failure = False
                        self._retry_count = 0
                        self._last_error_logged = False
                        if self.error_callback:
                            self.error_callback("[EV Charger] Retrying connection...")
                    else:
                        time.sleep(5)
                    continue

                # --- Local connection mode ---
                if self._device is None:
                    if self._retry_count >= self._max_retries:
                        self._permanent_failure = True
                        self._permanent_failure_time = time.time()
                        self.state.is_connected = False
                        if self.error_callback and not self._last_error_logged:
                            if self._cloud is not None:
                                self.error_callback(
                                    "[EV Charger] Local failed - switching to cloud"
                                )
                            else:
                                self.error_callback(
                                    f"[EV Charger] FAILED - Retrying in "
                                    f"{int(self._recovery_interval)}s"
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
            dev.set_socketTimeout(5)
            # Quick status check to verify connection
            status = dev.status()
            if "Error" in status:
                raise ConnectionError(status["Error"])
            self._device = dev
            self.state.is_connected = True
            self.state.is_cloud = False
            self._use_cloud = False
            self._permanent_failure = False
            if self.error_callback and (self._retry_count > 0 or self._use_cloud):
                self.error_callback("[EV Charger] Reconnected (local)")
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

        # Snapshot and clear pending values under the lock, then release
        # before doing any I/O so the main thread is never blocked.
        with self._lock:
            pending_amps = self._pending_amps
            pending_on_off = self._pending_on_off
            self._pending_amps = None
            self._pending_on_off = None

        if pending_on_off is None and pending_amps is None:
            return  # Nothing to do

        switch_dp = str(self.config.dp_switch)
        amps_dp = str(self.config.dp_amps)
        desc_parts = []

        if pending_amps is not None:
            desired_amps = pending_amps
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

        if pending_on_off is not None:
            desired_on = pending_on_off
            if desired_on != self.state.is_on:
                self._device.set_value(switch_dp, desired_on)
                desc_parts.append("ON" if desired_on else "OFF")
                self.state.is_on = desired_on

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
        # Force-close stale socket before reconnect
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
        self._device = None
        self._retry_count += 1

    # ------------------------------------------------------------------
    # Cloud fallback methods
    # ------------------------------------------------------------------

    def _cloud_poll_status(self) -> None:
        """Read charger status via Tuya Cloud API shadow endpoint."""
        devid = self.config.device_id
        result = self._cloud.cloudrequest(
            f'v2.0/cloud/thing/{devid}/shadow/properties'
        )
        if not result.get("success"):
            self.state.is_connected = False
            return

        props = {}
        for p in result.get("result", {}).get("properties", []):
            props[p["code"]] = p.get("value")

        # Switch state
        if "switch" in props:
            self.state.is_on = bool(props["switch"])

        # DeviceState: "charing" = actively providing power (feyree misspelling)
        device_state = str(props.get("DeviceState", "")).lower()
        self.state.error_state = device_state if "error" in device_state or "fault" in device_state else ""
        dp101_charging = "char" in device_state

        # ChargingOperation: OpenCharging / CloseCharging / WaitOperation
        charging_op = str(props.get("ChargingOperation", "")).lower()
        dp124_active = "close" not in charging_op and charging_op != ""

        if dp101_charging:
            self.state.is_on = True
        self.state.is_charging = dp101_charging and dp124_active

        # Read amps from the matching SetXXA code
        amps_code = self.config.cloud_amps_code
        if amps_code in props and time.time() > self._write_grace_until:
            self.state.current_amps = int(props[amps_code])

        self.state.is_connected = True
        self.state.is_cloud = True

    def _cloud_apply_pending(self) -> None:
        """Apply pending commands via Tuya Cloud API."""
        if self.state.error_state:
            return

        # Snapshot and clear pending values under the lock, then release
        # before doing any I/O so the main thread is never blocked.
        with self._lock:
            pending_amps = self._pending_amps
            pending_on_off = self._pending_on_off
            self._pending_amps = None
            self._pending_on_off = None

        if pending_on_off is None and pending_amps is None:
            return

        devid = self.config.device_id
        amps_code = self.config.cloud_amps_code
        desc_parts = []

        if pending_amps is not None:
            desired_amps = pending_amps
            if desired_amps != self.state.current_amps:
                # Cloud: OFF → set amps → ON (same safe sequence)
                lowering = desired_amps < self.state.current_amps
                if lowering and self.state.is_on:
                    self._cloud.sendcommand(devid, {'commands': [{'code': 'switch', 'value': False}]})
                    time.sleep(5)
                self._cloud.cloudrequest(
                    f'v2.0/cloud/thing/{devid}/shadow/properties/issue',
                    post={'properties': json.dumps({amps_code: desired_amps})}
                )
                if lowering and self.state.is_on:
                    time.sleep(5)
                    self._cloud.sendcommand(devid, {'commands': [{'code': 'switch', 'value': True}]})
                desc_parts.append(f"{desired_amps}A")
                self.state.current_amps = desired_amps
                self._write_grace_until = time.time() + 30

        if pending_on_off is not None:
            desired_on = pending_on_off
            if desired_on != self.state.is_on:
                self._cloud.sendcommand(devid, {'commands': [{'code': 'switch', 'value': desired_on}]})
                desc_parts.append("ON" if desired_on else "OFF")
                self.state.is_on = desired_on

        if not desc_parts:
            return

        now = time.time()
        self.state.last_change_time = now
        desc = ", ".join(desc_parts)
        print(f"[EV Charger] Cloud applied: {desc}")
        if self.error_callback:
            self.error_callback(f"[EV Charger] Cloud set {desc}")
