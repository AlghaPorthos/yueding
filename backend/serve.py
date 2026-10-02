"""Development WSGI entry point for the contract reader backend (stdlib only).

Address resolution is a pure function so tests can cover defaults, environment
overrides, and argv precedence without binding a socket.
"""

import argparse
import os
import socketserver
import sys
from collections.abc import Mapping
from wsgiref.simple_server import WSGIServer, make_server

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def _parse_port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError(f"port must be between 1 and 65535, got {value}")
    return port


def resolve_address(
    argv: list[str] | None = None, environ: Mapping[str, str] | None = None
) -> tuple[str, int]:
    """Return (host, port): argv --host/--port wins over env, then defaults."""
    env = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(description="Run the contract reader backend server.")
    parser.add_argument("--host", default=None, help="bind host (default: %(default)s or CONTRACT_READER_HOST)")
    parser.add_argument("--port", type=_parse_port, default=None, help="bind port (default: 8000 or CONTRACT_READER_PORT)")
    args = parser.parse_args(argv)
    host = args.host or env.get("CONTRACT_READER_HOST") or DEFAULT_HOST
    env_port = env.get("CONTRACT_READER_PORT")
    port = args.port if args.port is not None else (_parse_port(env_port) if env_port else DEFAULT_PORT)
    return host, port


def main(argv: list[str] | None = None) -> int:
    from app.main import app

    class DevServer(WSGIServer):
        """WSGIServer without the reverse-DNS lookup in server_bind.

        HTTPServer.server_bind resolves socket.getfqdn(host), which can stall
        for tens of seconds on hosts with slow reverse DNS before the server
        can accept a single request.
        """

        def server_bind(self):
            socketserver.TCPServer.server_bind(self)
            host, port = self.server_address[:2]
            self.server_name = host
            self.server_port = port
            self.setup_environ()

    host, port = resolve_address(argv)
    with make_server(host, port, app, server_class=DevServer) as server:
        print(
            f"Serving on http://{host}:{port} | healthz: http://{host}:{port}/healthz | Ctrl-C to stop",
            file=sys.stderr,
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Shutting down.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
