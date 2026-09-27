"""Single entry point for the bundled bot + API executable (tradingbot-core).

The desktop app ships this as a PyInstaller build so the user needs no Python
install. It starts two processes from the same executable:

    tradingbot-core run --data-dir <dir>   # bot + API in one process (what the app uses)
    tradingbot-core bot --data-dir <dir>   # the trading loop only (python main.py)
    tradingbot-core api --data-dir <dir>   # the HTTP API only (python -m api)
    tradingbot-core generate-token         # print a random API token
    tradingbot-core version                # print versions as JSON (smoke test)

``--data-dir`` becomes the working directory, so the relative DB_PATH, LOG_DIR
and .env defaults land in the app's own data folder instead of Program Files.

With ``--stop-on-stdin-close`` the process shuts down gracefully (the same path
as Ctrl+C) when its parent writes ``stop`` or closes stdin. Windows has no
SIGTERM a parent can send, and this also stops the child if the parent dies.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
from typing import List, Optional


def _watch_stdin() -> None:
    def watch() -> None:
        try:
            for line in sys.stdin:
                if line.strip().lower() == "stop":
                    break
        except (OSError, ValueError):
            pass
        signal.raise_signal(signal.SIGINT)

    threading.Thread(target=watch, name="stdin-watch", daemon=True).start()


def _run_local(rest: List[str]) -> int:
    from local_runtime import LocalRuntime, RuntimeStartError

    parser = argparse.ArgumentParser(prog="tradingbot-core run")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(rest)

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    runtime = LocalRuntime(args.env_file)
    try:
        runtime.start()
    except RuntimeStartError as exc:
        print(f"STARTUP_ERROR: {exc}", file=sys.stderr, flush=True)
        return 2
    while runtime.running and not stop.wait(0.5):
        pass
    runtime.stop()
    status = runtime.status()
    if status["error"]:
        print(f"RUNTIME_ERROR: {status['error']}", file=sys.stderr, flush=True)
        return 1
    return 0


def _version() -> int:
    import ccxt

    info = {"python": sys.version.split()[0], "ccxt": ccxt.__version__, "frozen": bool(getattr(sys, "frozen", False))}
    try:
        import fastapi
        import uvicorn

        info.update(fastapi=fastapi.__version__, uvicorn=uvicorn.__version__)
    except ImportError:
        pass
    print(json.dumps(info))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="tradingbot-core")
    parser.add_argument("command", choices=["run", "bot", "api", "generate-token", "version"])
    parser.add_argument("--data-dir", help="working directory for .env, data/ and logs/")
    parser.add_argument("--stop-on-stdin-close", action="store_true")
    args, rest = parser.parse_known_args(argv)

    if args.data_dir:
        os.makedirs(args.data_dir, exist_ok=True)
        os.chdir(args.data_dir)

    if args.command == "version":
        return _version()
    if args.command == "generate-token":
        import secrets

        print(secrets.token_urlsafe(32))
        return 0

    if args.stop_on_stdin_close:
        _watch_stdin()

    if args.command == "run":
        return _run_local(rest)
    if args.command == "bot":
        import main as bot_main

        return bot_main.main(rest)

    from api.__main__ import main as api_main

    return api_main(rest)


if __name__ == "__main__":
    sys.exit(main())
