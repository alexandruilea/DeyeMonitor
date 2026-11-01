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
        self.fail_next = None  # Exception text raised by the next state read

    async def connect(self) -> None:
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

    def test_backoff_lengths(self):
        self.assertGreaterEqual(tapo_manager.CONTENTION_BACKOFF_SECONDS, 30)
        self.assertGreater(tapo_manager.CONTENTION_LOG_INTERVAL_SECONDS, tapo_manager.CONTENTION_BACKOFF_SECONDS)


if __name__ == "__main__":
    unittest.main()
