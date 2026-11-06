"""Open the local Japanese quiz in a browser.

Usage:
    learn-japanese
    learn-japanese --port 8765
    learn-japanese --no-browser
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import content
from build_deck import ensure_deck


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="learn-japanese",
        description="Study hiragana, katakana, kanji, and phrases in a local quiz.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Address to bind (default 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on (default 8765).")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser window.")
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Folder for progress JSON. Defaults to the learn_japanese program folder.",
    )
    args = parser.parse_args(argv)

    if content.CONTENT is None:
        if ensure_deck() is None:
            return 1
        content.activate()

    from engine import Engine, default_data_path
    import server
    from server import make_handler

    if args.data_dir:
        data_path = Path(args.data_dir) / "state.json"
    else:
        data_path = default_data_path()

    server.ENGINE = Engine(data_path)
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
    print(f"learn-japanese  {url}")
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
