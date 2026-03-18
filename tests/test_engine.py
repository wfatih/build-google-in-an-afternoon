"""Tests for crawler.engine — _RateLimiter and CrawlerStats."""
import threading
import time
import unittest

from crawler.engine import CrawlerStats, _RateLimiter


class TestRateLimiter(unittest.TestCase):

    def test_first_acquire_succeeds(self):
        rl = _RateLimiter(rate=10.0)
        self.assertTrue(rl.try_acquire())

    def test_bucket_empties(self):
        rl = _RateLimiter(rate=1.0)
        rl.try_acquire()  # drain the one token
        self.assertFalse(rl.try_acquire())

    def test_refills_over_time(self):
        rl = _RateLimiter(rate=100.0)
        for _ in range(100):
            rl.try_acquire()
        time.sleep(0.2)
        # after 0.2s at 100/s should have ~20 tokens
        self.assertTrue(rl.try_acquire())

    def test_wait_and_acquire_returns(self):
        rl = _RateLimiter(rate=50.0)  # fast enough to not block long
        start = time.monotonic()
        rl.wait_and_acquire()
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 1.0)

    def test_thread_safety(self):
        rl = _RateLimiter(rate=1000.0)
        successes = []
        lock = threading.Lock()

        def worker():
            if rl.try_acquire():
                with lock:
                    successes.append(1)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # At rate=1000 and burst=1000, all 20 should succeed
        self.assertEqual(len(successes), 20)


class TestCrawlerStats(unittest.TestCase):

    def test_initial_snapshot(self):
        s = CrawlerStats()
        snap = s.snapshot()
        self.assertFalse(snap["active"])
        self.assertEqual(snap["urls_processed"], 0)
        self.assertEqual(snap["urls_failed"], 0)
        self.assertEqual(snap["urls_dropped_backpressure"], 0)
        self.assertEqual(snap["queue_depth"], 0)
        self.assertFalse(snap["throttled"])

    def test_set_active(self):
        s = CrawlerStats()
        s._set(active=True, start_time=time.time())
        self.assertTrue(s.snapshot()["active"])

    def test_inc_processed(self):
        s = CrawlerStats()
        s._inc("urls_processed")
        s._inc("urls_processed")
        self.assertEqual(s.snapshot()["urls_processed"], 2)

    def test_inc_failed(self):
        s = CrawlerStats()
        s._inc("urls_failed", 3)
        self.assertEqual(s.snapshot()["urls_failed"], 3)

    def test_elapsed_increases(self):
        s = CrawlerStats()
        s._set(active=True, start_time=time.time())
        time.sleep(0.05)
        elapsed = s.snapshot()["elapsed_s"]
        self.assertGreater(elapsed, 0)

    def test_snapshot_thread_safe(self):
        s = CrawlerStats()
        errors = []

        def worker():
            try:
                for _ in range(50):
                    s._inc("urls_processed")
                    s.snapshot()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(s.snapshot()["urls_processed"], 250)


if __name__ == "__main__":
    unittest.main()
