"""
Tests for storage.database.FailedURLDB.

Covers: add_failure, failures_for_session, count_for_session,
        ordering, session isolation.
"""
import os
import tempfile
import time
import unittest

from storage.database import FailedURLDB, SessionDB, init_db


class TestFailedURLDB(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        init_db(self.tmp.name)
        self.db = FailedURLDB(path=self.tmp.name)
        self.sessions = SessionDB(path=self.tmp.name)

    def tearDown(self):
        self.db.close()
        self.sessions.close()
        os.unlink(self.tmp.name)

    # ── add_failure ──────────────────────────────────────────────────────────

    def test_add_failure_does_not_raise(self):
        sid = self.sessions.create_session("https://example.com", 1)
        self.db.add_failure(sid, "https://example.com/404", "HTTP 404")

    def test_failure_persisted(self):
        sid = self.sessions.create_session("https://example.com", 1)
        self.db.add_failure(sid, "https://example.com/bad", "timeout")
        failures = self.db.failures_for_session(sid)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["url"], "https://example.com/bad")

    def test_failure_stores_error_message(self):
        sid = self.sessions.create_session("https://example.com", 1)
        self.db.add_failure(sid, "https://example.com/err", "HTTP 503")
        failures = self.db.failures_for_session(sid)
        self.assertEqual(failures[0]["error"], "HTTP 503")

    def test_failure_stores_failed_at_timestamp(self):
        sid = self.sessions.create_session("https://example.com", 1)
        before = time.time()
        self.db.add_failure(sid, "https://example.com/ts", "err")
        after = time.time()
        failures = self.db.failures_for_session(sid)
        ts = failures[0]["failed_at"]
        self.assertGreaterEqual(ts, before)
        self.assertLessEqual(ts, after)

    # ── failures_for_session ─────────────────────────────────────────────────

    def test_failures_for_session_returns_list(self):
        sid = self.sessions.create_session("https://example.com", 1)
        result = self.db.failures_for_session(sid)
        self.assertIsInstance(result, list)

    def test_empty_session_returns_empty_list(self):
        sid = self.sessions.create_session("https://example.com", 1)
        self.assertEqual(self.db.failures_for_session(sid), [])

    def test_multiple_failures_all_returned(self):
        sid = self.sessions.create_session("https://example.com", 1)
        for i in range(5):
            self.db.add_failure(sid, f"https://example.com/{i}", "err")
        failures = self.db.failures_for_session(sid)
        self.assertEqual(len(failures), 5)

    def test_failures_ordered_newest_first(self):
        sid = self.sessions.create_session("https://example.com", 1)
        self.db.add_failure(sid, "https://example.com/first", "err")
        time.sleep(0.02)
        self.db.add_failure(sid, "https://example.com/second", "err")
        failures = self.db.failures_for_session(sid)
        self.assertEqual(failures[0]["url"], "https://example.com/second")

    def test_failures_limit_respected(self):
        sid = self.sessions.create_session("https://example.com", 1)
        for i in range(10):
            self.db.add_failure(sid, f"https://example.com/{i}", "err")
        failures = self.db.failures_for_session(sid, limit=3)
        self.assertEqual(len(failures), 3)

    # ── count_for_session ────────────────────────────────────────────────────

    def test_count_zero_when_no_failures(self):
        sid = self.sessions.create_session("https://example.com", 1)
        self.assertEqual(self.db.count_for_session(sid), 0)

    def test_count_increments_per_failure(self):
        sid = self.sessions.create_session("https://example.com", 1)
        self.db.add_failure(sid, "https://a.com/1", "err")
        self.assertEqual(self.db.count_for_session(sid), 1)
        self.db.add_failure(sid, "https://a.com/2", "err")
        self.assertEqual(self.db.count_for_session(sid), 2)

    # ── session isolation ─────────────────────────────────────────────────────

    def test_different_sessions_isolated(self):
        sid1 = self.sessions.create_session("https://a.com", 1)
        sid2 = self.sessions.create_session("https://b.com", 1)
        self.db.add_failure(sid1, "https://a.com/bad", "err")
        # sid2 should see no failures
        self.assertEqual(self.db.failures_for_session(sid2), [])
        # sid1 should see exactly one
        self.assertEqual(len(self.db.failures_for_session(sid1)), 1)

    def test_count_scoped_to_session(self):
        sid1 = self.sessions.create_session("https://a.com", 1)
        sid2 = self.sessions.create_session("https://b.com", 1)
        for i in range(3):
            self.db.add_failure(sid1, f"https://a.com/{i}", "err")
        self.assertEqual(self.db.count_for_session(sid1), 3)
        self.assertEqual(self.db.count_for_session(sid2), 0)

    # ── result dict structure ────────────────────────────────────────────────

    def test_failure_dict_has_required_keys(self):
        sid = self.sessions.create_session("https://example.com", 1)
        self.db.add_failure(sid, "https://example.com/x", "HTTP 500")
        failure = self.db.failures_for_session(sid)[0]
        self.assertIn("url", failure)
        self.assertIn("error", failure)
        self.assertIn("failed_at", failure)


if __name__ == "__main__":
    unittest.main()
