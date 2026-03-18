"""
parser.py — HTML parsing utilities (stdlib html.parser only).

No third-party libraries (no BeautifulSoup, lxml, etc.).
"""

import re
import urllib.parse
from collections import defaultdict
from html.parser import HTMLParser
from typing import Dict, List


def tokenize(text: str) -> List[str]:
    """Return lower-case alphabetic tokens of length >= 2."""
    return re.findall(r"[a-z]{2,}", text.lower())


class LinkParser(HTMLParser):
    """Collect absolute <a href="…"> links from an HTML page."""

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self._base = base_url
        self.links: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href", "")
        if not href:
            return
        abs_url = urllib.parse.urljoin(self._base, href)
        parsed = urllib.parse.urlparse(abs_url)
        if parsed.scheme in ("http", "https"):
            # Normalise: strip fragment, lower-case host
            normed = parsed._replace(
                fragment="", netloc=parsed.netloc.lower()
            ).geturl()
            self.links.append(normed)


class TextParser(HTMLParser):
    """Extract human-readable text; skip script/style/head."""

    _SKIP: frozenset = frozenset(
        {"script", "style", "head", "noscript", "template", "svg", "math"}
    )

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data):
        if self._skip_depth == 0:
            s = data.strip()
            if s:
                self._parts.append(s)

    def word_counts(self) -> Dict[str, int]:
        words = tokenize(" ".join(self._parts))
        counts: Dict[str, int] = defaultdict(int)
        for w in words:
            counts[w] += 1
        return dict(counts)
