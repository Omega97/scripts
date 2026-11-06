"""Open the local heads-up frequency trainer in a browser.

Usage:
    learn-poker
    learn-poker --port 8775
    learn-poker --no-browser
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import server
from engine import Engine, default_db_path, default_library_path
from pokerbench import ensure_library
from server import make_handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="learn-poker",
        description="Practice no-limit hold'em action frequencies in a local browser trainer.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Address to bind (default 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8775, help="Port to listen on (default 8775).")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser window.")
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Folder for poker_trainer.db and spots.sqlite. Defaults to the learn_poker program folder.",
    )
    args = parser.parse_args(argv)

    if args.data_dir:
        db_path = Path(args.data_dir) / "poker_trainer.db"
        library = Path(args.data_dir) / "spots.sqlite"
    else:
        db_path = default_db_path()
        library = default_library_path()

    library = ensure_library(library)
    server.ENGINE = Engine(db_path, library=library)
    if server.ENGINE.library:
        print(f"{server.ENGINE.library.total:,} PokerBench spots")
    handler = make_handler(BaseHTTPRequestHandler)
    httpd = None
    bound_port = args.port
    last_error = None
    for candidate in range(args.port, args.port + 20):
        try:
            httpd = ThreadingHTTPServer((args.host, candidate), handler)
            bound_port = candidate
            break
        except OSError as exc:
            last_error = exc
    if httpd is None:
        print(f"Could not listen on {args.host}:{args.port} ({last_error})", file=sys.stderr)
        return 1

    httpd.daemon_threads = True
    url = f"http://{args.host}:{bound_port}/"
    print(f"learn-poker  {url}")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
