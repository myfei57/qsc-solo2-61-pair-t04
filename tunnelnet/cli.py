"""Command line entry point for the control service."""

from __future__ import annotations

import argparse
import logging
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server

from tunnelnet.chain import load_config
from tunnelnet.chain.validation import InvalidChain
from .console.server import ChainConfigurationError, Server
from .console.version import version_string
from .store import Store

LOGGER = logging.getLogger("tunnelnet")


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    """Serve concurrent control requests from a pool of worker threads."""

    daemon_threads = True


def parse_address(value: str) -> tuple[str, int]:
    host, separator, port = value.rpartition(":")
    if not separator or not port.isdigit():
        raise argparse.ArgumentTypeError("address must look like host:port")
    return host or "0.0.0.0", int(port)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tunnelnet", description="control service")
    parser.add_argument("--store", default="data", help="directory holding the persistent records")
    parser.add_argument("--web-dir", default="web", help="directory holding the console pages")
    parser.add_argument(
        "--chain-config",
        default="",
        help="JSON file assembling the control chain stages for this tunnel",
    )
    parser.add_argument("--addr", default=":8080", help="listen address as host:port")
    parser.add_argument("--version", action="store_true", help="print the build version and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        print(version_string())
        return 0

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    store = Store.open(args.store)
    chain_config = None
    if args.chain_config:
        try:
            with open(args.chain_config, encoding="utf-8") as handle:
                chain_config = load_config(handle.read())
        except (OSError, ValueError) as exc:
            LOGGER.error("cannot load chain config %s: %s", args.chain_config, exc)
            return 2
    host, port = parse_address(args.addr)
    try:
        application = Server(store, args.web_dir, chain_config)
    except (ChainConfigurationError, InvalidChain) as exc:
        LOGGER.error("refusing to start: %s", exc)
        return 2
    try:
        with make_server(host, port, application, server_class=ThreadingWSGIServer) as httpd:
            LOGGER.info("control console listening on %s:%d", host, port)
            httpd.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("control console stopped")
    return 0
