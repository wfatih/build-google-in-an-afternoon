"""Tests for storage.database — VisitedDB and SessionDB."""
import os
import tempfile
import time
import unittest

from storage.database import SessionDB, VisitedDB, init_db


class TestVisitedDB(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = VisitedDB(path=self.tmp.name)

    def tearDown(self):
        self.db.close()
        os.unlink(self.tmp.name)

    def test_mark_new_url_returns_true(self):
        self.assertTrue(self.db.mark_visited("https://example.com"))

    def test_mark_same_url_twice_returns_false(self):
        self.db.mark_visited("https://example.com")
        self.assertFalse(self.db.mark_visited("https://example.com"))

    def test_is_visited_after_mark(self):
        self.db.mark_visited("https://a.com")
        self.assertTrue(self.db.is_visited("https://a.com"))

    def test_is_not_visited_before_mark(self):
        self.assertFalse(self.db.is_visited("https://never.com"))

    def test_count_increases(self):
        self.assertEqual(self.db.count(), 0)
        self.db.mark_visited("https://one.com")
        self.assertEqual(self.db.count(), 1)
        self.db.mark_visited("https://two.com")
        self.assertEqual(self.db.count(), 2)

    def test_count_no_duplicate(self):
        self.db.mark_visited("https://dup.com")
        self.db.mark_visited("https://dup.com")
        self.assertEqual(self.db.count(), 1)

    def test_different_urls_independent(self):
        self.assertTrue(self.db.mark_visited("https://a.com"))
        self.assertTrue(self.db.mark_visited("https://b.com"))
        self.assertEqual(self.db.count(), 2)


class TestSessionDB(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = SessionDB(path=self.tmp.name)

    def tearDown(self):
        self.db.close()
        os.unlink(self.tmp.name)

    def test_create_session_returns_int(self):
        sid = self.db.create_session("https://example.com", 2)
        self.assertIsInstance(sid, int)
        self.assertGreater(sid, 0)

    def test_list_sessions_after_create(self):
        self.db.create_session("https://example.com", 3)
        sessions = self.db.list_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["origin"], "https://example.com")
        self.assertEqual(sessions[0]["depth"], 3)
        self.assertEqual(sessions[0]["status"], "running")

    def test_finish_session_updates_status(self):
        sid = self.db.create_session("https://example.com", 1)
        self.db.finish_session(sid, pages_indexed=10, urls_processed=20, urls_failed=1)
        sessions = self.db.list_sessions()
        s = sessions[0]
        self.assertEqual(s["status"], "done")
        self.assertEqual(s["pages_indexed"], 10)
        self.assertEqual(s["urls_processed"], 20)
        self.assertEqual(s["urls_failed"], 1)
        self.assertIsNotNone(s["finished_at"])

    def test_list_sessions_ordered_newest_first(self):
        self.db.create_session("https://first.com", 1)
        time.sleep(0.01)
        self.db.create_session("https://second.com", 1)
        sessions = self.db.list_sessions()
        self.assertEqual(sessions[0]["origin"], "https://second.com")
        self.assertEqual(sessions[1]["origin"], "https://first.com")

    def test_multiple_sessions(self):
        for i in range(5):
            self.db.create_session(f"https://site{i}.com", i)
        self.assertEqual(len(self.db.list_sessions()), 5)

    def test_list_sessions_limit(self):
        for i in range(10):
            self.db.create_session(f"https://s{i}.com", 1)
        self.assertEqual(len(self.db.list_sessions(limit=3)), 3)


if __name__ == "__main__":
    unittest.main()
