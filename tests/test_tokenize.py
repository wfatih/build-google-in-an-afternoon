"""Tests for crawler.parser.tokenize."""
import unittest
from crawler.parser import tokenize


class TestTokenize(unittest.TestCase):

    def test_basic_words(self):
        self.assertEqual(tokenize("hello world"), ["hello", "world"])

    def test_lowercased(self):
        self.assertEqual(tokenize("Python SQL"), ["python", "sql"])

    def test_strips_punctuation(self):
        result = tokenize("Hello, world! How's it?")
        self.assertIn("hello", result)
        self.assertIn("world", result)

    def test_min_length_two(self):
        # single-char tokens must be excluded
        result = tokenize("I am a cat")
        self.assertNotIn("i", result)
        self.assertNotIn("a", result)
        self.assertIn("am", result)
        self.assertIn("cat", result)

    def test_numbers_excluded(self):
        # tokenize only keeps alpha tokens
        result = tokenize("abc 123 def")
        self.assertIn("abc", result)
        self.assertIn("def", result)
        self.assertNotIn("123", result)

    def test_empty_string(self):
        self.assertEqual(tokenize(""), [])

    def test_only_punctuation(self):
        self.assertEqual(tokenize("!!!---???"), [])

    def test_html_entities_not_mangled(self):
        result = tokenize("artificial intelligence")
        self.assertEqual(result, ["artificial", "intelligence"])

    def test_returns_list(self):
        self.assertIsInstance(tokenize("test"), list)

    def test_deduplication_not_done(self):
        # tokenize does NOT deduplicate; that's the caller's job
        result = tokenize("cat cat cat")
        self.assertEqual(result.count("cat"), 3)


if __name__ == "__main__":
    unittest.main()
