"""
Unit tests for Tapo session handling: reconnect at once after an expired session, but back
off when another client keeps logging in to the plug (it allows one session at a time).
"""

import asyncio
import time
import unittest

import src.tapo_manager as tapo_manager
from src.config import OutletConfig
from src.tapo_manager import OutletDevice, TapoManager, is_session_error

SESSION_TIMEOUT = ('Tapo(Unauthorized { kind: "SESSION_TIMEOUT", description: "Session has expired. '
                   'Re-authentication is required." })')


class FakeOutlet(OutletDevice):
    def __init__(self):
        super().__init__(OutletConfig(outlet_id=1, ip="192.0.2.1", username="u", password="p", name="Fan",
                                      priority=1, power=0))
        self.logins = 0
        self.connect_attempts = 0
        self.fail_next = None  # Exception text raised by the next state read
        self.fail_connect = None  # Exception text raised by every login while set

    async def connect(self) -> None:
        self.connect_attempts += 1
        if self.fail_connect:
            raise Exception(self.fail_connect)
        self.logins += 1
        self.device = object()
        self._connected_at = time.monotonic()

    async def update_state(self) -> None:
        if self.fail_next:
            error, self.fail_next = self.fail_next, None
            raise Exception(error)
        self.is_connected = True


class OfflineTapoManager(TapoManager):
    def _run_loop(self) -> None:
        pass  # No background loop: tests poll by hand


class TestSessionError(unittest.TestCase):
    def test_new_tapo_session_timeout(self):
        self.assertTrue(is_session_error(SESSION_TIMEOUT))

    def test_old_tapo_session_timeout(self):
        self.assertTrue(is_session_error("Tapo(SessionTimeout)"))

    def test_forbidden(self):
        self.assertTrue(is_session_error("Http(reqwest::Error { status: 403 Forbidden })"))

    def test_other_errors_keep_the_backoff(self):
        self.assertFalse(is_session_error('Tapo(Unauthorized { kind: "INVALID_CREDENTIALS" })'))
        self.assertFalse(is_session_error("Http(reqwest::Error { kind: Request, source: ConnectError })"))


class TestSessionLoss(unittest.TestCase):
    def setUp(self):
        self.log = []
        self.manager = OfflineTapoManager(error_callback=self.log.append, configs=[])
        self.outlet = FakeOutlet()

    def poll(self):
        asyncio.run(self.manager._poll_outlet(self.outlet))

    def test_expired_session_reconnects_at_once(self):
        self.poll()
        self.outlet._connected_at -= 3600  # Logged in an hour ago
        self.outlet.fail_next = SESSION_TIMEOUT
        self.poll()
        self.poll()
        self.assertEqual(self.outlet.logins, 2)
        self.assertTrue(self.outlet.is_connected)
        self.assertEqual(self.log, ["[Fan] Session expired, reconnecting..."])

    def test_session_taken_right_after_login_backs_off(self):
        # Another client (e.g. a second DeyeMonitor) logs in to the plug every few seconds
        self.poll()
        self.outlet.fail_next = SESSION_TIMEOUT
        self.poll()
        for _ in range(5):
            self.poll()
        self.assertEqual(self.outlet.logins, 1)  # No login while backing off
        self.assertFalse(self.outlet.is_connected)
        self.assertEqual(len(self.log), 1)
        self.assertIn("another client is logging in to this plug", self.log[0])

        self.outlet._reconnect_after = 0  # Backoff over
        self.poll()
        self.assertEqual(self.outlet.logins, 2)
        self.outlet.fail_next = SESSION_TIMEOUT
        self.poll()
        self.assertEqual(len(self.log), 1)  # Warned at most every CONTENTION_LOG_INTERVAL_SECONDS
        self.assertGreater(self.outlet._reconnect_after, time.monotonic())

    def test_other_errors_use_the_retry_backoff(self):
        self.poll()
        self.outlet.fail_next = "Http(reqwest::Error { kind: Request, source: ConnectError })"
        self.poll()
        self.assertEqual(self.outlet._retry_count, 1)
        self.assertTrue(self.log[0].startswith("[Fan] Offline:"))
        self.assertEqual(self.outlet._reconnect_after, 0.0)

    def test_unreachable_plug_keeps_retrying_and_comes_back(self):
        # Used to give up for good after ~3 failed logins (polls skipped during the delay
        # counted as retries), leaving the outlet "offline" while it worked in the Tapo app
        self.outlet.fail_connect = 'Tapo(HttpError { status_code: 400, description: "Handshake2 failed" })'
        for _ in range(30):
            self.outlet._next_attempt = 0  # Retry delay over
            self.poll()
        self.assertEqual(self.outlet.connect_attempts, 30)
        self.assertFalse(self.outlet.is_connected)

        self.outlet.fail_connect = None
        self.outlet._next_attempt = 0
        self.poll()
        self.assertTrue(self.outlet.is_connected)
        self.assertEqual(self.outlet._retry_count, 0)
        self.assertEqual(len(self.log), 2)
        self.assertTrue(self.log[0].startswith("[Fan] Offline:"))
        self.assertEqual(self.log[1], "[Fan] Back online")

    def test_no_login_during_retry_delay(self):
        self.outlet.fail_connect = "Http(reqwest::Error { kind: Request, source: ConnectError })"
        self.poll()
        for _ in range(5):
            self.poll()
        self.assertEqual(self.outlet.connect_attempts, 1)
        self.assertEqual(self.outlet._retry_count, 1)  # Skipped polls are not failures
        self.assertGreater(self.outlet._next_attempt, time.monotonic())

    def test_retry_delay_is_capped(self):
        self.outlet.fail_connect = "Http(reqwest::Error { kind: Request, source: ConnectError })"
        for _ in range(12):
            self.outlet._next_attempt = 0
            self.poll()
        delay = self.outlet._next_attempt - time.monotonic()
        self.assertLessEqual(delay, tapo_manager.RETRY_MAX_SECONDS)
        self.assertGreater(delay, tapo_manager.RETRY_MAX_SECONDS - 5)

    def test_manual_toggle_retries_at_once(self):
        self.manager.outlets[1] = self.outlet
        self.outlet.fail_connect = "Http(reqwest::Error { kind: Request, source: ConnectError })"
        self.poll()
        self.manager.toggle(1)
        self.assertEqual(self.outlet._next_attempt, 0.0)
        self.assertTrue(self.outlet.target_state)

    def test_failing_log_callback_does_not_break_polling(self):
        # The UI logger raised before the window finished building, which killed the
        # polling thread: every outlet of that manager stayed offline until a restart
        def broken_log(_message):
            raise AttributeError("'_tkinter.tkapp' object has no attribute '_main_loop_started'")
        self.manager.error_callback = broken_log
        self.outlet.fail_connect = 'Tapo(HttpError { status_code: 400, description: "Handshake2 failed" })'
        self.poll()  # Must not raise
        self.assertEqual(self.outlet._retry_count, 1)

        self.outlet.fail_connect = None
        self.outlet._next_attempt = 0
        self.poll()
        self.assertTrue(self.outlet.is_connected)

    def test_backoff_lengths(self):
        self.assertGreaterEqual(tapo_manager.CONTENTION_BACKOFF_SECONDS, 30)
        self.assertGreater(tapo_manager.CONTENTION_LOG_INTERVAL_SECONDS, tapo_manager.CONTENTION_BACKOFF_SECONDS)


if __name__ == "__main__":
    unittest.main()
