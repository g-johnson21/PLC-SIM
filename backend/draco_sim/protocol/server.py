"""The WebSocket protocol server: `python -m draco_sim.protocol.server`.

One `Simulator` (docs/runtime.md), one asyncio event loop. The loop hosts the
scan loop (paced by `draco_sim.runtime.pacer.Pacer`) and every client
connection; `Simulator.step()` is only ever called from this loop, and every
message handler in `handlers.py` runs to completion before the next `step()`
can run, so nothing here needs a lock (see docs/protocol.md, Server ->
"Concurrency model").
"""
from __future__ import annotations

import argparse
import asyncio
import functools
import http.server
import json
import logging
import threading

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from draco_sim.runtime import Pacer, SimConfig, Simulator
from draco_sim.runtime.pacer import monotonic

from .codec import dumps
from .connection import ClientConnection
from .handlers import dispatch

log = logging.getLogger("draco_sim.protocol")

# The scan loop wakes this often to check for due scans and to let other tasks
# (client I/O) run; it never sleeps for a whole scan period, so a client's
# message is handled within a couple of milliseconds even at 20 Hz.
TICK_S = 0.0015
WARN_INTERVAL_S = 1.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m draco_sim.protocol.server",
        description="Draco test stand simulator -- WebSocket protocol server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--scan-hz", type=float, default=50.0)
    p.add_argument("--load-examples", action="store_true",
                   help="load the five programs in backend/examples on startup")
    p.add_argument("--speed", type=float, default=1.0,
                   help="simulated-time multiplier for realtime pacing")
    p.add_argument("--no-realtime", action="store_true",
                   help="run scans as fast as possible instead of pacing to wall time")
    p.add_argument("--static", default=None, metavar="DIR",
                   help="also serve a built frontend directory over plain HTTP")
    p.add_argument("--http-port", type=int, default=8080,
                   help="port for --static (default 8080)")
    p.add_argument("--verbose", action="store_true",
                   help="log every message type in and out")
    return p.parse_args(argv)


def build_simulator(args: argparse.Namespace) -> Simulator:
    sim = Simulator(SimConfig(scan_hz=args.scan_hz))
    if args.load_examples:
        sim.load_examples()
        names = ", ".join(p["name"] for p in sim.programs())
        log.info("loaded examples: %s", names)
    return sim


def start_static_server(directory: str, port: int) -> http.server.ThreadingHTTPServer:
    handler_cls = functools.partial(http.server.SimpleHTTPRequestHandler,
                                    directory=directory)
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", port), handler_cls)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True,
                              name="draco-static-http")
    thread.start()
    log.info("static frontend served from %s at http://localhost:%d/", directory, port)
    return httpd


async def scan_loop(sim: Simulator, pacer: Pacer) -> None:
    last_warned_at = 0
    last_warn_t = 0.0
    while True:
        now = monotonic()
        n = pacer.due_scans(now)
        for _ in range(n):
            sim.step()
        if pacer.dropped_scans != last_warned_at and now - last_warn_t >= WARN_INTERVAL_S:
            log.warning("scan loop is behind real time: %d scans dropped so far",
                       pacer.dropped_scans)
            last_warned_at = pacer.dropped_scans
            last_warn_t = now
        await asyncio.sleep(TICK_S if pacer.realtime else 0)


def _process_request(connection, request):
    path = request.path.split("?", 1)[0]
    if path not in ("/ws", "/"):
        return connection.respond(404, "not found -- connect to /ws\n")
    return None


class _HandshakeNoiseFilter(logging.Filter):
    """A plain HTTP probe on the WebSocket port -- a load balancer's health
    check, the desktop preview tool's HEAD request, a bare TCP connect-and-close
    -- makes `websockets` log "opening handshake failed" at ERROR with a full
    traceback (websockets/asyncio/server.py). That happens on every probe, is
    not an application error, and drowns out real ones. This collapses that one
    message to a single line with no traceback, at DEBUG normally and INFO
    under --verbose; everything else this logger emits (including a failure
    *after* a successful handshake) passes through exactly as raised."""

    def __init__(self, verbose: bool) -> None:
        super().__init__()
        self._levelno = logging.INFO if verbose else logging.DEBUG

    def filter(self, record: logging.LogRecord) -> bool:
        if record.msg != "opening handshake failed":
            return True
        exc = record.exc_info[1] if record.exc_info else None
        cause = exc.__cause__ if exc is not None and exc.__cause__ is not None else exc
        peer = _peer_address(getattr(record, "websocket", None))
        record.levelno = self._levelno
        record.levelname = logging.getLevelName(self._levelno)
        record.msg = f"rejected non-WebSocket request from {peer}: {cause or exc}"
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        return True


def _peer_address(ws) -> str:
    addr = getattr(ws, "remote_address", None) if ws is not None else None
    return f"{addr[0]}:{addr[1]}" if addr else "?"


async def handle_client(ws, *, sim: Simulator, pacer: Pacer,
                        connections: set[ClientConnection]) -> None:
    remote = f"{ws.remote_address[0]}:{ws.remote_address[1]}" if ws.remote_address else "?"
    conn = ClientConnection(ws, remote)
    connections.add(conn)
    log.info("client %d connected from %s", conn.id, remote)
    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
                if not isinstance(msg, dict):
                    raise ValueError("top-level JSON value must be an object")
            except (json.JSONDecodeError, ValueError) as exc:
                log.info("client %d sent malformed JSON: %s", conn.id, exc)
                await conn.send({"type": "error", "id": None, "code": "bad_request",
                                "message": f"malformed JSON: {exc}", "details": {}})
                continue
            log.debug("client %d -> %s", conn.id, msg.get("type"))
            await dispatch(sim, pacer, conn, msg)
    except ConnectionClosed:
        pass
    except Exception:
        log.exception("client %d handler crashed", conn.id)
    finally:
        connections.discard(conn)
        conn.close()
        log.info("client %d (%s) disconnected", conn.id, conn.client_name)


async def run_server(args: argparse.Namespace) -> None:
    sim = build_simulator(args)
    pacer = Pacer(sim, realtime=not args.no_realtime, speed=args.speed)
    connections: set[ClientConnection] = set()

    def broadcast_event(event) -> None:
        # Runs synchronously inside sim.step() (see draco_sim.runtime.events); it
        # must not await, so every connection's own queue is filled directly.
        text = dumps({"type": "event", **event.as_dict()})
        for conn in list(connections):
            conn.enqueue_event_text(text)

    sim.on_event(broadcast_event)

    if args.static:
        start_static_server(args.static, args.http_port)

    handler = functools.partial(handle_client, sim=sim, pacer=pacer, connections=connections)
    async with serve(handler, args.host, args.port, process_request=_process_request):
        log.info("draco_sim protocol server listening on ws://%s:%d/ws "
                 "(scan_hz=%g, realtime=%s, speed=%g%s)",
                 args.host, args.port, args.scan_hz, not args.no_realtime, args.speed,
                 ", examples loaded" if args.load_examples else "")
        await scan_loop(sim, pacer)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    # basicConfig() sets the root logger's level but leaves its handler at
    # NOTSET, which passes every record regardless of level; the handshake
    # noise filter below downgrades records to DEBUG/INFO and relies on the
    # handler actually enforcing that, so give it the same level explicitly.
    for handler in logging.getLogger().handlers:
        handler.setLevel(level)
    logging.getLogger("websockets").setLevel(
        logging.INFO if args.verbose else logging.WARNING)
    logging.getLogger("websockets.server").addFilter(_HandshakeNoiseFilter(args.verbose))
    try:
        asyncio.run(run_server(args))
    except KeyboardInterrupt:
        log.info("shutting down")


if __name__ == "__main__":
    main()
