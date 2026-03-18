"""Tests for storage.index.InvertedIndex."""
import os
import tempfile
import unittest

from storage.index import InvertedIndex


class TestInvertedIndex(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.idx = InvertedIndex(index_path=self.tmp.name)

    def tearDown(self):
        self.idx.close()
        os.unlink(self.tmp.name)

    def test_add_page_returns_true_for_new(self):
        result = self.idx.add_page(
            "https://example.com", "https://example.com", 0,
            {"hello": 3, "world": 1}
        )
        self.assertTrue(result)

    def test_add_page_returns_false_for_duplicate(self):
        self.idx.add_page("https://example.com", "https://example.com", 0, {"x": 1})
        result = self.idx.add_page("https://example.com", "https://example.com", 0, {"x": 1})
        self.assertFalse(result)

    def test_page_count_increments(self):
        self.assertEqual(self.idx.page_count(), 0)
        self.idx.add_page("https://a.com", "https://a.com", 0, {"hi": 1})
        self.assertEqual(self.idx.page_count(), 1)
        self.idx.add_page("https://b.com", "https://a.com", 1, {"hi": 1})
        self.assertEqual(self.idx.page_count(), 2)

    def test_word_count_counts_unique_words(self):
        self.idx.add_page("https://a.com", "https://a.com", 0, {"python": 2, "sql": 1})
        self.idx.add_page("https://b.com", "https://a.com", 1, {"sql": 3, "java": 4})
        # unique words: python, sql, java
        self.assertEqual(self.idx.word_count(), 3)

    def test_search_returns_matching_url(self):
        self.idx.add_page("https://a.com", "https://a.com", 0, {"python": 5})
        results = self.idx.search("python")
        urls = [r[0] for r in results]
        self.assertIn("https://a.com", urls)

    def test_search_ranked_by_frequency(self):
        self.idx.add_page("https://low.com", "https://a.com", 0, {"python": 1})
        self.idx.add_page("https://high.com", "https://a.com", 0, {"python": 10})
        results = self.idx.search("python")
        self.assertEqual(results[0][0], "https://high.com")

    def test_search_multi_word_query(self):
        self.idx.add_page("https://a.com", "https://a.com", 0, {"machine": 2, "learning": 3})
        self.idx.add_page("https://b.com", "https://a.com", 0, {"machine": 1})
        results = self.idx.search("machine learning")
        # a.com matches both words, should rank higher
        self.assertEqual(results[0][0], "https://a.com")

    def test_search_no_results(self):
        self.assertEqual(self.idx.search("zzzznotaword"), [])

    def test_search_returns_triples(self):
        self.idx.add_page("https://a.com", "https://origin.com", 2, {"test": 1})
        results = self.idx.search("test")
        self.assertEqual(len(results), 1)
        url, origin, depth = results[0]
        self.assertEqual(url, "https://a.com")
        self.assertEqual(origin, "https://origin.com")
        self.assertEqual(depth, 2)

    def test_recent_pages_newest_first(self):
        self.idx.add_page("https://old.com", "https://a.com", 0, {"x": 1})
        self.idx.add_page("https://new.com", "https://a.com", 0, {"x": 1})
        recent = self.idx.recent_pages(2)
        self.assertEqual(recent[0]["url"], "https://new.com")

    def test_recent_pages_limit(self):
        for i in range(5):
            self.idx.add_page(f"https://s{i}.com", "https://a.com", 0, {"x": 1})
        self.assertEqual(len(self.idx.recent_pages(3)), 3)

    def test_save_is_noop(self):
        # save() must not raise
        self.idx.save()

    def test_partial_search_matches_prefix(self):
        self.idx.add_page("https://a.com", "https://a.com", 0,
                          {"artificial": 3, "intelligence": 2})
        # "artif" should match "artificial" via prefix
        results = self.idx.search("artif", partial=True)
        urls = [r[0] for r in results]
        self.assertIn("https://a.com", urls)

    def test_partial_search_exact_ranks_higher(self):
        self.idx.add_page("https://exact.com", "https://a.com", 0,
                          {"python": 2})
        self.idx.add_page("https://prefix.com", "https://a.com", 0,
                          {"pythonic": 2})
        results = self.idx.search("python", partial=True)
        self.assertEqual(results[0][0], "https://exact.com")

    def test_partial_false_no_prefix_match(self):
        self.idx.add_page("https://a.com", "https://a.com", 0,
                          {"artificial": 5})
        # exact-only: "artif" should NOT match
        results = self.idx.search("artif", partial=False)
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
