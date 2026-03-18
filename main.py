#!/usr/bin/env python3
"""
main.py — CLI entry point for Mini-Google.

Commands
--------
  python main.py server [--port 8080]    Start the web UI (recommended)
  python main.py index  <url> <depth>    Start a crawl (CLI mode)
  python main.py search <query>          Search the index
  python main.py status                  Print index statistics
"""

import argparse
import os
import sys
import time

from storage.database import DB_PATH
from storage.index import InvertedIndex

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_index() -> InvertedIndex:
    return InvertedIndex(index_path=DB_PATH)


def _clear():
    os.system("cls" if os.name == "nt" else "clear")


def _render_dashboard(s: dict, pages: int, words: int, max_q: int):
    status = "● ACTIVE" if s["active"] else "■  IDLE"
    throttle = "YES ⚠" if s["throttled"] else "no"
    qbar_width = 30
    filled = int(qbar_width * min(1.0, s["queue_depth"] / max(1, max_q)))
    qbar = "█" * filled + "░" * (qbar_width - filled)
    print("╔══════════════════════════════════════════════════╗")
    print("║          Mini-Google  —  Crawler Dashboard       ║")
    print("╠══════════════════════════════════════════════════╣")
    print(f"║  Status           : {status:<28}║")
    print(f"║  Elapsed          : {s['elapsed_s']:<26.1f} s  ║")
    print("╠══════════════════════════════════════════════════╣")
    print(f"║  URLs processed   : {s['urls_processed']:<28}║")
    print(f"║  URLs failed      : {s['urls_failed']:<28}║")
    print(f"║  Dropped (BP)     : {s['urls_dropped_backpressure']:<28}║")
    print("╠══════════════════════════════════════════════════╣")
    print(f"║  Queue depth      : {s['queue_depth']:<28}║")
    print(f"║  Queue bar        : [{qbar}] ║")
    print(f"║  Throttled        : {throttle:<28}║")
    print("╠══════════════════════════════════════════════════╣")
    print(f"║  Pages indexed    : {pages:<28}║")
    print(f"║  Unique words     : {words:<28}║")
    print("╚══════════════════════════════════════════════════╝")
    print("\nPress Ctrl+C to stop.")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_server(args):
    """Start the web UI and keep running."""
    from ui.server import WebServer
    idx = _make_index()
    srv = WebServer(idx, host="localhost", port=args.port)
    print(f"\nMini-Google Web UI")
    srv.start()
    print("  Press Ctrl+C to stop.\n")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        srv.stop()


def cmd_index(args):
    """CLI crawl with live dashboard."""
    from crawler.engine import Crawler

    idx = _make_index()
    crawler = Crawler(
        index=idx,
        max_workers=args.workers,
        max_queue=args.max_queue,
        rate=args.rate,
        timeout=args.timeout,
        db_path=DB_PATH,
    )

    print(f"\n[index] origin={args.url}  depth={args.depth}  "
          f"workers={args.workers}  rate={args.rate} req/s  "
          f"max_queue={args.max_queue}\n")

    crawler.start(args.url, args.depth)

    if args.dashboard:
        try:
            while crawler.is_active():
                _clear()
                _render_dashboard(
                    crawler.stats.snapshot(), idx.page_count(),
                    idx.word_count(), args.max_queue,
                )
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n[index] Interrupted — saving state…")
            crawler.stop()
    else:
        try:
            while crawler.is_active():
                s = crawler.stats.snapshot()
                print(
                    f"\r  processed={s['urls_processed']:5d}  "
                    f"queued={s['queue_depth']:4d}  "
                    f"indexed={idx.page_count():5d}  "
                    f"{'[throttled]' if s['throttled'] else '           '}",
                    end="", flush=True,
                )
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n[index] Interrupted.")
            crawler.stop()

    crawler.wait(timeout=5)
    s = crawler.stats.snapshot()
    print(f"\n\n[done]  processed={s['urls_processed']}  "
          f"failed={s['urls_failed']}  "
          f"dropped={s['urls_dropped_backpressure']}  "
          f"indexed={idx.page_count()}")


def cmd_search(args):
    """Search and print results."""
    idx = _make_index()
    results = idx.search(args.query)
    if not results:
        print("No results found.")
        return
    limit = args.limit
    print(f"\nResults for '{args.query}'  ({len(results)} total, "
          f"showing {min(limit, len(results))}):\n")
    for i, (url, origin, depth) in enumerate(results[:limit], 1):
        print(f"  {i:3d}. {url}")
        print(f"       origin={origin}  depth={depth}")
    print()


def cmd_status(args):
    """Print index statistics."""
    from storage.database import VisitedDB
    idx = _make_index()
    visited = VisitedDB(path=DB_PATH)
    print(f"\n[status] Indexed pages : {idx.page_count()}")
    print(f"[status] Unique words  : {idx.word_count()}")
    print(f"[status] Visited URLs  : {visited.count()}")
    print(f"[status] Database      : {os.path.abspath(DB_PATH)}")
    recent = idx.recent_pages(5)
    if recent:
        print("\n[status] Recently indexed:")
        for p in recent:
            print(f"           depth={p['depth']}  {p['url']}")
    print()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mini-google",
        description="Mini-Google — Web Crawler & Search Engine",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # server
    ps = sub.add_parser("server", help="Start the web UI (default: localhost:8080)")
    ps.add_argument("--port", type=int, default=8080)

    # index
    pi = sub.add_parser("index", help="Crawl from a URL to depth k (CLI mode)")
    pi.add_argument("url")
    pi.add_argument("depth", type=int)
    pi.add_argument("--workers", type=int, default=8)
    pi.add_argument("--rate", type=float, default=10.0)
    pi.add_argument("--max-queue", type=int, default=500)
    pi.add_argument("--timeout", type=float, default=10.0)
    pi.add_argument("--dashboard", action="store_true")

    # search
    psr = sub.add_parser("search", help="Search the index")
    psr.add_argument("query")
    psr.add_argument("--limit", type=int, default=20)

    # status
    sub.add_parser("status", help="Print index statistics")

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    {"server": cmd_server, "index": cmd_index,
     "search": cmd_search, "status": cmd_status}[args.command](args)


if __name__ == "__main__":
    main()
