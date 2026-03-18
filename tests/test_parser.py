"""Tests for crawler.parser.LinkParser and TextParser."""
import unittest
from crawler.parser import LinkParser, TextParser


class TestLinkParser(unittest.TestCase):

    def _parse(self, html, base="https://example.com"):
        p = LinkParser(base)
        p.feed(html)
        return p.links

    def test_absolute_link(self):
        links = self._parse('<a href="https://other.com/page">click</a>')
        self.assertIn("https://other.com/page", links)

    def test_relative_link_resolved(self):
        links = self._parse('<a href="/about">about</a>', "https://example.com")
        self.assertIn("https://example.com/about", links)

    def test_fragment_stripped(self):
        links = self._parse('<a href="https://example.com/page#section">x</a>')
        # fragments should be stripped
        self.assertNotIn("https://example.com/page#section", links)
        self.assertIn("https://example.com/page", links)

    def test_non_http_ignored(self):
        links = self._parse('<a href="mailto:a@b.com">mail</a>')
        self.assertEqual(links, [])

    def test_javascript_ignored(self):
        links = self._parse('<a href="javascript:void(0)">js</a>')
        self.assertEqual(links, [])

    def test_no_links_empty(self):
        links = self._parse("<p>no links here</p>")
        self.assertEqual(links, [])

    def test_multiple_links(self):
        html = '<a href="/a">a</a><a href="/b">b</a>'
        links = self._parse(html, "https://example.com")
        self.assertIn("https://example.com/a", links)
        self.assertIn("https://example.com/b", links)

    def test_duplicate_links_appear_multiple_times(self):
        # LinkParser returns ALL discovered links (no dedup); dedup happens
        # at the crawler level via the visited-URL SQLite table.
        html = '<a href="/page">1</a><a href="/page">2</a>'
        links = self._parse(html, "https://example.com")
        self.assertEqual(links.count("https://example.com/page"), 2)


class TestTextParser(unittest.TestCase):

    def _parse(self, html):
        p = TextParser()
        p.feed(html)
        return p.word_counts()

    def test_basic_text(self):
        counts = self._parse("<p>hello world hello</p>")
        self.assertEqual(counts.get("hello"), 2)
        self.assertEqual(counts.get("world"), 1)

    def test_script_excluded(self):
        counts = self._parse("<script>var secret = 'hidden';</script><p>visible</p>")
        self.assertNotIn("secret", counts)
        self.assertNotIn("hidden", counts)
        self.assertIn("visible", counts)

    def test_style_excluded(self):
        counts = self._parse("<style>.fancy { color: red; }</style><p>text</p>")
        self.assertNotIn("fancy", counts)
        self.assertIn("text", counts)

    def test_returns_dict(self):
        self.assertIsInstance(self._parse("<p>test</p>"), dict)

    def test_empty_html(self):
        self.assertEqual(self._parse(""), {})

    def test_word_counts_positive(self):
        counts = self._parse("<p>cat cat dog</p>")
        for v in counts.values():
            self.assertGreater(v, 0)


if __name__ == "__main__":
    unittest.main()
