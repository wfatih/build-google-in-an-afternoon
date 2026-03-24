"""
Tests for InvertedIndex.search_scored() and InvertedIndex.export_pdata().

search_scored() implements the assignment scoring formula:
    score = (frequency × 10) + 1000 (exact match bonus) − (depth × 5)
"""
import os
import tempfile
import unittest

from storage.index import InvertedIndex


class TestSearchScoredFormula(unittest.TestCase):
    """Verify that search_scored() applies the correct numeric formula."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.idx = InvertedIndex(index_path=self.tmp.name)

    def tearDown(self):
        self.idx.close()
        os.unlink(self.tmp.name)

    # ── return type ──────────────────────────────────────────────────────────

    def test_returns_list(self):
        self.idx.add_page("https://a.com", "https://a.com", 0, {"python": 1})
        result = self.idx.search_scored("python")
        self.assertIsInstance(result, list)

    def test_returns_4_tuples(self):
        self.idx.add_page("https://a.com", "https://a.com", 0, {"python": 5})
        result = self.idx.search_scored("python")
        self.assertEqual(len(result), 1)
        url, origin, depth, score = result[0]   # must unpack cleanly
        self.assertIsInstance(url, str)
        self.assertIsInstance(origin, str)
        self.assertIsInstance(depth, int)
        self.assertIsInstance(score, (int, float))

    def test_empty_query_returns_empty(self):
        self.idx.add_page("https://a.com", "https://a.com", 0, {"python": 1})
        self.assertEqual(self.idx.search_scored(""), [])

    def test_no_match_returns_empty(self):
        self.idx.add_page("https://a.com", "https://a.com", 0, {"python": 1})
        self.assertEqual(self.idx.search_scored("zzzznotaword"), [])

    # ── formula verification ─────────────────────────────────────────────────

    def test_exact_formula_depth0(self):
        # freq=10, depth=0  →  (10×10)+1000−(0×5) = 1100
        self.idx.add_page("https://a.com", "https://a.com", 0, {"python": 10})
        _, _, _, score = self.idx.search_scored("python")[0]
        self.assertEqual(score, 1100)

    def test_exact_formula_depth1(self):
        # freq=10, depth=1  →  (10×10)+1000−(1×5) = 1095
        self.idx.add_page("https://a.com", "https://a.com", 1, {"python": 10})
        _, _, _, score = self.idx.search_scored("python")[0]
        self.assertEqual(score, 1095)

    def test_exact_formula_depth2(self):
        # freq=20, depth=2  →  (20×10)+1000−(2×5) = 1190
        self.idx.add_page("https://a.com", "https://a.com", 2, {"python": 20})
        _, _, _, score = self.idx.search_scored("python")[0]
        self.assertEqual(score, 1190)

    def test_depth_penalty_reduces_score(self):
        """Deeper pages score lower for the same frequency."""
        self.idx.add_page("https://shallow.com", "https://a.com", 0, {"test": 5})
        self.idx.add_page("https://deep.com",    "https://a.com", 3, {"test": 5})
        results = self.idx.search_scored("test")
        urls = [r[0] for r in results]
        # shallow must rank above deep
        self.assertLess(urls.index("https://shallow.com"),
                        urls.index("https://deep.com"))

    def test_frequency_increases_score(self):
        """Higher frequency → higher score (same depth)."""
        self.idx.add_page("https://low.com",  "https://a.com", 0, {"word": 1})
        self.idx.add_page("https://high.com", "https://a.com", 0, {"word": 50})
        results = self.idx.search_scored("word")
        self.assertEqual(results[0][0], "https://high.com")

    def test_exact_match_bonus_1000(self):
        """The +1000 exact-match bonus is applied once per entry."""
        # freq=0 edge-case: only the bonus minus depth penalty should show
        # Use freq=1 at depth=0: score = (1×10)+1000 = 1010
        self.idx.add_page("https://a.com", "https://a.com", 0, {"python": 1})
        _, _, _, score = self.idx.search_scored("python")[0]
        self.assertEqual(score, 1010)

    def test_sorted_descending(self):
        """Results are sorted from highest to lowest score."""
        self.idx.add_page("https://a.com", "https://a.com", 0, {"word": 1})
        self.idx.add_page("https://b.com", "https://a.com", 0, {"word": 5})
        self.idx.add_page("https://c.com", "https://a.com", 0, {"word": 3})
        results = self.idx.search_scored("word")
        scores = [r[3] for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_origin_and_depth_preserved(self):
        """Returned origin and depth match what was indexed."""
        self.idx.add_page("https://page.com", "https://origin.com", 2,
                          {"hello": 4})
        url, origin, depth, _ = self.idx.search_scored("hello")[0]
        self.assertEqual(url,    "https://page.com")
        self.assertEqual(origin, "https://origin.com")
        self.assertEqual(depth,  2)


class TestSearchScoredPartial(unittest.TestCase):
    """Verify partial=True/False behaviour in search_scored()."""

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.idx = InvertedIndex(index_path=self.tmp.name)

    def tearDown(self):
        self.idx.close()
        os.unlink(self.tmp.name)

    def test_partial_false_no_prefix_match(self):
        """partial=False must not return prefix-only matches."""
        self.idx.add_page("https://a.com", "https://a.com", 0,
                          {"artificial": 5})
        self.assertEqual(self.idx.search_scored("artif", partial=False), [])

    def test_partial_true_includes_prefix(self):
        """partial=True must return pages with words that start with the query."""
        self.idx.add_page("https://a.com", "https://a.com", 0,
                          {"artificial": 5})
        results = self.idx.search_scored("artif", partial=True)
        urls = [r[0] for r in results]
        self.assertIn("https://a.com", urls)

    def test_partial_true_exact_gets_bonus(self):
        """With partial=True, the exact match still receives the +1000 bonus."""
        self.idx.add_page("https://exact.com",  "https://a.com", 0,
                          {"python": 2})
        self.idx.add_page("https://prefix.com", "https://a.com", 0,
                          {"pythonic": 2})
        results = self.idx.search_scored("python", partial=True)
        # exact.com has the +1000 bonus; prefix.com does not
        self.assertEqual(results[0][0], "https://exact.com")

    def test_partial_true_prefix_score_no_bonus(self):
        """With partial=True, a prefix-only match scores (freq×10)−(depth×5)."""
        # freq=3, depth=0 prefix-only → score = 3×10 = 30 (no +1000)
        self.idx.add_page("https://p.com", "https://p.com", 0,
                          {"pythonic": 3})
        results = self.idx.search_scored("python", partial=True)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][3], 30)

    def test_default_is_partial_false(self):
        """search_scored() without arguments must use exact-only matching."""
        self.idx.add_page("https://a.com", "https://a.com", 0,
                          {"artificial": 5})
        # should NOT match "artif" by default
        self.assertEqual(self.idx.search_scored("artif"), [])

    def test_multi_word_query_scored(self):
        """Multi-token queries sum contributions from all matching words."""
        self.idx.add_page("https://a.com", "https://a.com", 0,
                          {"machine": 2, "learning": 3})
        self.idx.add_page("https://b.com", "https://a.com", 0,
                          {"machine": 1})
        results = self.idx.search_scored("machine learning")
        # a.com matches both words → higher combined score
        self.assertEqual(results[0][0], "https://a.com")


class TestExportPdata(unittest.TestCase):
    """Tests for InvertedIndex.export_pdata()."""

    def setUp(self):
        self.db_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_tmp.close()
        self.idx = InvertedIndex(index_path=self.db_tmp.name)

        self.data_dir = tempfile.mkdtemp()
        self.pdata_path = os.path.join(self.data_dir, "p.data")

    def tearDown(self):
        self.idx.close()
        os.unlink(self.db_tmp.name)
        if os.path.exists(self.pdata_path):
            os.unlink(self.pdata_path)
        os.rmdir(self.data_dir)

    def test_creates_file(self):
        self.idx.add_page("https://a.com", "https://a.com", 0, {"hello": 3})
        self.idx.export_pdata(self.pdata_path)
        self.assertTrue(os.path.exists(self.pdata_path))

    def test_returns_entry_count(self):
        self.idx.add_page("https://a.com", "https://a.com", 0,
                          {"hello": 1, "world": 2})
        count = self.idx.export_pdata(self.pdata_path)
        self.assertEqual(count, 2)

    def test_empty_index_creates_empty_file(self):
        count = self.idx.export_pdata(self.pdata_path)
        self.assertEqual(count, 0)
        with open(self.pdata_path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "")

    def test_line_has_five_fields(self):
        self.idx.add_page("https://a.com", "https://a.com", 0, {"python": 5})
        self.idx.export_pdata(self.pdata_path)
        with open(self.pdata_path, encoding="utf-8") as f:
            line = f.readline().strip()
        fields = line.split(" ")
        self.assertEqual(len(fields), 5)

    def test_line_format_word_url_origin_depth_frequency(self):
        """Each line must be: word url origin depth frequency"""
        self.idx.add_page("https://page.com", "https://origin.com", 2,
                          {"python": 7})
        self.idx.export_pdata(self.pdata_path)
        with open(self.pdata_path, encoding="utf-8") as f:
            line = f.readline().strip()
        word, url, origin, depth, freq = line.split(" ")
        self.assertEqual(word,   "python")
        self.assertEqual(url,    "https://page.com")
        self.assertEqual(origin, "https://origin.com")
        self.assertEqual(depth,  "2")
        self.assertEqual(freq,   "7")

    def test_multiple_pages_all_exported(self):
        self.idx.add_page("https://a.com", "https://a.com", 0, {"x": 1})
        self.idx.add_page("https://b.com", "https://a.com", 1, {"y": 2})
        count = self.idx.export_pdata(self.pdata_path)
        self.assertEqual(count, 2)
        with open(self.pdata_path, encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        self.assertEqual(len(lines), 2)

    def test_file_is_readable_utf8_text(self):
        self.idx.add_page("https://a.com", "https://a.com", 0, {"test": 1})
        self.idx.export_pdata(self.pdata_path)
        with open(self.pdata_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIsInstance(content, str)
        self.assertGreater(len(content), 0)

    def test_overwrite_on_second_call(self):
        """A second export_pdata call overwrites the previous file."""
        self.idx.add_page("https://a.com", "https://a.com", 0, {"x": 1})
        self.idx.export_pdata(self.pdata_path)
        # Add another page and re-export
        self.idx.add_page("https://b.com", "https://a.com", 0, {"y": 1})
        count = self.idx.export_pdata(self.pdata_path)
        with open(self.pdata_path, encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]
        self.assertEqual(len(lines), count)


if __name__ == "__main__":
    unittest.main()
