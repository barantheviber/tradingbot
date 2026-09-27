"""Run the API next to the bot:

    python -m api                    # uses API_HOST / API_PORT / API_TOKEN from .env
    python -m api --generate-token   # print a random token to put in .env
"""

from __future__ import annotations

import argparse
import ipaddress
import logging
import secrets
import sys

from config import DEFAULT_SETTINGS, load_config
from logging_setup import setup_logging
from state_manager import LegacyDatabaseError, StateManager

MIN_TOKEN_LENGTH = 16


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="tradingbot HTTP API for the mobile / desktop apps")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--host", help="override API_HOST")
    parser.add_argument("--port", type=int, help="override API_PORT")
    parser.add_argument("--generate-token", action="store_true", help="print a new random API_TOKEN and exit")
    args = parser.parse_args(argv)

    if args.generate_token:
        print(secrets.token_urlsafe(32))
        return 0

    config = load_config(args.env_file)
    log = setup_logging(config.log_dir, config.log_level, secrets=config.secrets())
    if len(config.api_token) < MIN_TOKEN_LENGTH:
        log.error(f"API_TOKEN must be set in .env and be at least {MIN_TOKEN_LENGTH} characters "
                  "(python -m api --generate-token)")
        return 2
    host = args.host or config.api_host
    port = args.port or config.api_port
    if not _is_loopback(host):
        log.warning(f"API is listening on {host}, reachable from other devices. Traffic is plain HTTP: "
                    "use it only on a trusted network or a VPN such as Tailscale/WireGuard.")

    try:
        state = StateManager(config.db_path)
    except LegacyDatabaseError as exc:
        log.error(str(exc))
        return 2
    state.seed_default_settings(DEFAULT_SETTINGS)

    import uvicorn

    from api.server import create_app

    # Route uvicorn through our handlers: they mask API_TOKEN, which WebSocket URLs carry as ?token=.
    for name in ("uvicorn", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = list(log.handlers)
        uv_logger.propagate = False
        uv_logger.setLevel(logging.INFO)

    app = create_app(config, state)
    log.info(f"API listening on http://{host}:{port} (mode={config.mode})")
    uvicorn.run(app, host=host, port=port, access_log=False, log_config=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
