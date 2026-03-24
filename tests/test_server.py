"""
Integration tests for ui.server — HTTP endpoint behaviour.

Each test class spins up a real ThreadingHTTPServer on a randomly
assigned free port, runs requests against it with urllib (stdlib only),
and shuts it down in tearDownClass.
"""
import json
import os
import socket
import tempfile
import time
import unittest
import urllib.error
import urllib.request

from storage.index import InvertedIndex
from ui.server import WebServer


# ── helpers ───────────────────────────────────────────────────────────────────

def _free_port() -> int:
    """Return a free TCP port on localhost."""
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _get(url: str) -> tuple:
    """HTTP GET → (status_code, body_bytes)."""
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _get_json(url: str) -> tuple:
    """HTTP GET → (status_code, parsed_json)."""
    status, body = _get(url)
    return status, json.loads(body)


# ── base class shared by all server test classes ──────────────────────────────

class _ServerTestBase(unittest.TestCase):
    """Starts one server per test class with a pre-populated index."""

    @classmethod
    def setUpClass(cls):
        cls._db_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._db_tmp.close()
        cls._idx = InvertedIndex(index_path=cls._db_tmp.name)

        # Seed two pages
        cls._idx.add_page(
            "https://python.org",
            "https://python.org",
            0,
            {"python": 50, "language": 10, "programming": 8},
        )
        cls._idx.add_page(
            "https://python.org/docs",
            "https://python.org",
            1,
            {"python": 20, "docs": 5, "reference": 3},
        )
        cls._idx.add_page(
            "https://example.com",
            "https://example.com",
            0,
            {"example": 15, "domain": 7},
        )

        cls._port = _free_port()
        cls._server = WebServer(cls._idx, host="localhost", port=cls._port)
        cls._server.start()
        time.sleep(0.3)   # let the server thread bind and accept

    @classmethod
    def tearDownClass(cls):
        cls._server.stop()
        cls._idx.close()
        os.unlink(cls._db_tmp.name)

    def base(self):
        return f"http://localhost:{self._port}"


# ── root endpoint ─────────────────────────────────────────────────────────────

class TestRootEndpoint(_ServerTestBase):

    def test_get_root_returns_200(self):
        status, _ = _get(self.base() + "/")
        self.assertEqual(status, 200)

    def test_get_root_returns_html(self):
        _, body = _get(self.base() + "/")
        self.assertIn(b"<!DOCTYPE html>", body)

    def test_get_root_contains_mini_google(self):
        _, body = _get(self.base() + "/")
        self.assertIn(b"Mini-Google", body)


# ── /api/stats ────────────────────────────────────────────────────────────────

class TestStatsEndpoint(_ServerTestBase):

    def test_stats_returns_200(self):
        status, _ = _get_json(self.base() + "/api/stats")
        self.assertEqual(status, 200)

    def test_stats_has_pages_indexed(self):
        _, data = _get_json(self.base() + "/api/stats")
        self.assertIn("pages_indexed", data)

    def test_stats_pages_indexed_correct(self):
        _, data = _get_json(self.base() + "/api/stats")
        self.assertEqual(data["pages_indexed"], 3)

    def test_stats_has_words_indexed(self):
        _, data = _get_json(self.base() + "/api/stats")
        self.assertIn("words_indexed", data)

    def test_stats_active_false_when_idle(self):
        _, data = _get_json(self.base() + "/api/stats")
        self.assertFalse(data.get("active", True))


# ── /api/recent ───────────────────────────────────────────────────────────────

class TestRecentEndpoint(_ServerTestBase):

    def test_recent_returns_200(self):
        status, _ = _get_json(self.base() + "/api/recent")
        self.assertEqual(status, 200)

    def test_recent_returns_list(self):
        _, data = _get_json(self.base() + "/api/recent")
        self.assertIsInstance(data, list)

    def test_recent_items_have_url_field(self):
        _, data = _get_json(self.base() + "/api/recent")
        for item in data:
            self.assertIn("url", item)

    def test_recent_items_have_depth_field(self):
        _, data = _get_json(self.base() + "/api/recent")
        for item in data:
            self.assertIn("depth", item)


# ── GET /search ───────────────────────────────────────────────────────────────

class TestGetSearch(_ServerTestBase):

    def test_search_returns_200(self):
        status, _ = _get_json(
            self.base() + "/search?query=python&sortBy=relevance"
        )
        self.assertEqual(status, 200)

    def test_search_has_results_key(self):
        _, data = _get_json(
            self.base() + "/search?query=python&sortBy=relevance"
        )
        self.assertIn("results", data)

    def test_search_has_total_key(self):
        _, data = _get_json(
            self.base() + "/search?query=python&sortBy=relevance"
        )
        self.assertIn("total", data)

    def test_search_results_contain_url(self):
        _, data = _get_json(
            self.base() + "/search?query=python&sortBy=relevance"
        )
        for r in data["results"]:
            self.assertIn("url", r)

    def test_search_results_contain_relevance_score(self):
        _, data = _get_json(
            self.base() + "/search?query=python&sortBy=relevance"
        )
        for r in data["results"]:
            self.assertIn("relevance_score", r)

    def test_search_relevance_score_is_numeric(self):
        _, data = _get_json(
            self.base() + "/search?query=python&sortBy=relevance"
        )
        for r in data["results"]:
            self.assertIsInstance(r["relevance_score"], (int, float))

    def test_search_top_result_is_highest_frequency(self):
        """python.org (freq=50) must rank above python.org/docs (freq=20)."""
        _, data = _get_json(
            self.base() + "/search?query=python&sortBy=relevance"
        )
        self.assertEqual(data["results"][0]["url"], "https://python.org")

    def test_search_scores_sorted_descending(self):
        _, data = _get_json(
            self.base() + "/search?query=python&sortBy=relevance"
        )
        scores = [r["relevance_score"] for r in data["results"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_search_correct_score_formula(self):
        """Score for python.org: (50×10)+1000−(0×5) = 1500."""
        _, data = _get_json(
            self.base() + "/search?query=python&sortBy=relevance"
        )
        top = data["results"][0]
        self.assertEqual(top["url"], "https://python.org")
        self.assertEqual(top["relevance_score"], 1500)

    def test_search_no_query_returns_error(self):
        _, data = _get_json(self.base() + "/search?query=")
        self.assertIn("error", data)

    def test_search_missing_query_param_returns_error(self):
        _, data = _get_json(self.base() + "/search")
        self.assertIn("error", data)

    def test_search_unknown_word_returns_empty_results(self):
        _, data = _get_json(
            self.base() + "/search?query=zzzznotaword&sortBy=relevance"
        )
        self.assertEqual(data["results"], [])

    def test_search_result_has_origin_field(self):
        _, data = _get_json(
            self.base() + "/search?query=python&sortBy=relevance"
        )
        for r in data["results"]:
            self.assertIn("origin", r)

    def test_search_result_has_depth_field(self):
        _, data = _get_json(
            self.base() + "/search?query=python&sortBy=relevance"
        )
        for r in data["results"]:
            self.assertIn("depth", r)


# ── GET /api/export ───────────────────────────────────────────────────────────

class TestExportEndpoint(_ServerTestBase):

    def test_export_returns_200(self):
        status, _ = _get_json(self.base() + "/api/export")
        self.assertEqual(status, 200)

    def test_export_has_ok_true(self):
        _, data = _get_json(self.base() + "/api/export")
        self.assertTrue(data.get("ok"))

    def test_export_returns_entry_count(self):
        _, data = _get_json(self.base() + "/api/export")
        self.assertIn("entries", data)
        self.assertIsInstance(data["entries"], int)
        self.assertGreater(data["entries"], 0)

    def test_export_creates_pdata_file(self):
        _, data = _get_json(self.base() + "/api/export")
        pdata_path = data.get("path", "")
        self.assertTrue(os.path.exists(pdata_path),
                        f"p.data not found at {pdata_path}")

    def test_export_pdata_is_readable_text(self):
        _, data = _get_json(self.base() + "/api/export")
        pdata_path = data.get("path", "")
        if os.path.exists(pdata_path):
            with open(pdata_path, encoding="utf-8") as f:
                first_line = f.readline().strip()
            parts = first_line.split(" ")
            self.assertEqual(len(parts), 5,
                             f"Expected 5 fields, got: {first_line!r}")


# ── unknown routes ────────────────────────────────────────────────────────────

class TestUnknownRoutes(_ServerTestBase):

    def test_unknown_get_path_returns_404(self):
        status, data = _get_json(self.base() + "/api/doesnotexist")
        self.assertEqual(status, 404)
        self.assertIn("error", data)


# ── /api/sessions ─────────────────────────────────────────────────────────────

class TestSessionsEndpoint(_ServerTestBase):

    def test_sessions_returns_200(self):
        status, _ = _get_json(self.base() + "/api/sessions")
        self.assertEqual(status, 200)

    def test_sessions_returns_list(self):
        _, data = _get_json(self.base() + "/api/sessions")
        self.assertIsInstance(data, list)

    def test_invalid_session_id_returns_400(self):
        status, data = _get_json(self.base() + "/api/sessions/notanumber")
        self.assertEqual(status, 400)
        self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main()
