"""Backend entry point.

Normally started by the desktop app, which passes the port and session token
through environment variables. It can also be started by hand for development:

    python -m claw.main --port 8765

In that case a token is generated and printed once to the console (never to
the log file).
"""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import sys

import uvicorn

from claw import __version__
from claw.api.app import create_app
from claw.config import default_data_dir
from claw.logging_setup import configure_logging, log_event, register_secret

BIND_HOST = "127.0.0.1"  # never 0.0.0.0: the agent must not be reachable from the network


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claw-backend")
    parser.add_argument("--port", type=int, default=int(os.environ.get("CLAW_PORT", "8765")))
    parser.add_argument("--log-level", default=os.environ.get("CLAW_LOG_LEVEL", "INFO"))
    args = parser.parse_args(argv)

    if not (1024 <= args.port <= 65535):
        print(f"Port {args.port} is not allowed; choose 1024-65535.", file=sys.stderr)
        return 2

    data_dir = default_data_dir()
    log_file = configure_logging(data_dir / "logs", args.log_level.upper())

    token = os.environ.get("CLAW_SESSION_TOKEN", "")
    if not token:
        token = secrets.token_urlsafe(32)
        print(f"[dev] session token for this run: {token}", flush=True)
    register_secret(token)

    log = logging.getLogger("claw.main")
    log_event(log, "backend starting", version=__version__, port=args.port, data_dir=str(data_dir), log_file=str(log_file))
    app = create_app(data_dir, token)
    # The desktop shell waits for readiness by polling GET /health.
    config = uvicorn.Config(app, host=BIND_HOST, port=args.port, log_config=None, access_log=False)
    server = uvicorn.Server(config)
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
