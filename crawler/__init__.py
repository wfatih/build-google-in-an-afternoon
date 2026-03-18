from .parser import tokenize

__all__ = ["Crawler", "CrawlerStats", "tokenize"]


def __getattr__(name):
    if name in ("Crawler", "CrawlerStats"):
        from .engine import Crawler, CrawlerStats
        globals()["Crawler"] = Crawler
        globals()["CrawlerStats"] = CrawlerStats
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
