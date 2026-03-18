from .database import DB_PATH, init_db

__all__ = ["InvertedIndex", "DB_PATH", "init_db"]


def __getattr__(name):
    if name == "InvertedIndex":
        from .index import InvertedIndex
        return InvertedIndex
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
