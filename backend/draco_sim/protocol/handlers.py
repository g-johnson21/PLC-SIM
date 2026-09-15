"""Maps every client message type in docs/protocol.md onto the matching
`Simulator` call (docs/runtime.md documents the 1:1 mapping) and builds the
reply. One asyncio event loop drives both the scan loop and every connection
handler, and `Simulator` is only ever touched from that loop, so nothing here
needs a lock.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from draco_sim.runtime import GROUPS, ProgramSource, SimError, SimRejected
from draco_sim.runtime.config import ROLES

from .codec import sanitize_nonfinite
from .connection import ClientConnection

log = logging.getLogger("draco_sim.protocol")

RATE_HZ_MIN, RATE_HZ_MAX = 1.0, 50.0
SCAN_HZ_MIN, SCAN_HZ_MAX = 10.0, 100.0

Handler = Callable[[Any, Any, ClientConnection, dict], Awaitable[dict]]


async def dispatch(sim, pacer, conn: ClientConnection, msg: dict) -> None:
    mtype = msg.get("type")
    mid = msg.get("id")
    if not isinstance(mtype, str):
        await conn.send({"type": "error", "id": mid, "code": "bad_request",
                         "message": "missing or non-string 'type'", "details": {}})
        return
    handler = _HANDLERS.get(mtype)
    if handler is None:
        await conn.send({"type": "error", "id": mid, "code": "bad_request",
                         "message": f"unknown message type {mtype!r}", "details": {}})
        return
    try:
        reply = await handler(sim, pacer, conn, msg)
    except SimError as exc:
        await conn.send({"type": "error", "id": mid, "code": exc.code,
                         "message": exc.message, "details": exc.details})
        return
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, see docs/protocol.md
        log.exception("internal error handling %r from client %d", mtype, conn.id)
        await conn.send({"type": "error", "id": mid, "code": "internal",
                         "message": str(exc), "details": {}})
        return
    reply["id"] = mid
    await conn.send(reply)


# ------------------------------------------------------------------ connection
async def _hello(sim, pacer, conn: ClientConnection, msg: dict) -> dict:
    protocol = msg.get("protocol", 1)
    if "client" in msg:
        conn.client_name = str(msg["client"])
    if protocol != 1:
        raise SimRejected(f"unsupported protocol {protocol!r}; this server speaks 1",
                          code="bad_request", details={"protocol": protocol})
    payload = dict(sim.welcome_payload())
    payload["type"] = "welcome"
    return payload


async def _pump_state(conn: ClientConnection, sim) -> None:
    try:
        while True:
            snapshot = sim.snapshot(conn.groups)
            clean, nonfinite = sanitize_nonfinite(snapshot)
            clean["type"] = "state"
            clean["nonfinite"] = nonfinite
            conn.push_state(clean)
            await asyncio.sleep(1.0 / conn.rate_hz)
    except asyncio.CancelledError:
        pass


async def _subscribe(sim, pacer, conn: ClientConnection, msg: dict) -> dict:
    rate = msg.get("rate_hz", 20)
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        raise SimRejected("'rate_hz' must be a number", code="bad_request")
    conn.rate_hz = max(RATE_HZ_MIN, min(RATE_HZ_MAX, rate))

    groups = msg.get("groups")
    if groups is None:
        groups = [g for g in GROUPS if g != "raw"]
    elif not isinstance(groups, list) or not all(isinstance(g, str) for g in groups):
        raise SimRejected("'groups' must be a list of strings", code="bad_request")
    else:
        groups = [g.lower() for g in groups]
    conn.groups = groups

    conn.restart_subscription(lambda c: _pump_state(c, sim))
    return {"type": "ack"}


async def _unsubscribe(sim, pacer, conn: ClientConnection, msg: dict) -> dict:
    conn.stop_subscription()
    return {"type": "ack"}


# ------------------------------------------------------------------ read / write
async def _read(sim, pacer, conn, msg: dict) -> dict:
    names = msg.get("names")
    if not isinstance(names, list) or not names:
        raise SimRejected("'names' must be a non-empty list", code="bad_request")
    return {"type": "read_result", "values": sim.read(names)}


async def _write(sim, pacer, conn, msg: dict) -> dict:
    values = msg.get("values")
    if not isinstance(values, dict) or not values:
        raise SimRejected("'values' must be a non-empty object", code="bad_request")
    sim.write(values)
    return {"type": "ack"}


# ------------------------------------------------------------------ sequences / abort
async def _sequence(sim, pacer, conn, msg: dict) -> dict:
    action, name = msg.get("action"), msg.get("name")
    if action not in ("start", "stop") or not isinstance(name, str):
        raise SimRejected("'sequence' needs action in {start,stop} and a name",
                          code="bad_request")
    if action == "start":
        sim.sequence_start(name)
    else:
        sim.sequence_stop(name)
    return {"type": "ack"}


async def _abort(sim, pacer, conn, msg: dict) -> dict:
    sim.abort()
    return {"type": "ack"}


async def _abort_clear(sim, pacer, conn, msg: dict) -> dict:
    sim.abort_clear()
    return {"type": "ack"}


async def _abort_config(sim, pacer, conn, msg: dict) -> dict:
    thresholds = msg.get("thresholds")
    if not isinstance(thresholds, list):
        raise SimRejected("'thresholds' must be a list", code="bad_request")
    sim.abort_config(thresholds)
    return {"type": "ack"}


# ------------------------------------------------------------------ programs
async def _program_compile(sim, pacer, conn, msg: dict) -> dict:
    name, language, source = msg.get("name"), msg.get("language"), msg.get("source")
    if not isinstance(name, str) or not isinstance(language, str) or source is None:
        raise SimRejected("'program.compile' needs name, language and source",
                          code="bad_request")
    result = sim.compile_only(ProgramSource(name, language.upper(), source))
    reply = result.as_dict()
    reply["type"] = "compile_result"
    return reply


async def _program_load(sim, pacer, conn, msg: dict) -> dict:
    programs = msg.get("programs")
    if not isinstance(programs, list) or not programs:
        raise SimRejected("'programs' must be a non-empty list", code="bad_request")
    sources = []
    for i, entry in enumerate(programs):
        if not isinstance(entry, dict):
            raise SimRejected(f"programs[{i}] must be an object", code="bad_request",
                              details={"index": i})
        name, language, source = entry.get("name"), entry.get("language"), entry.get("source")
        if not isinstance(name, str) or not name or not isinstance(language, str) or source is None:
            raise SimRejected(f"programs[{i}] needs name, language and source",
                              code="bad_request", details={"index": i})
        if language.upper() not in ("ST", "LD", "SFC"):
            raise SimRejected(f"programs[{i}] ({name}): language must be ST, LD or SFC, "
                              f"got {language!r}", code="bad_request",
                              details={"index": i, "name": name, "language": language})
        # role is optional: absent or null means the server infers it (docs/protocol.md,
        # "Program roles"); a value that is not a role at all is a malformed request
        role = entry.get("role")
        if role is not None and role not in ROLES:
            raise SimRejected(f"programs[{i}] ({name}): role must be one of "
                              f"{', '.join(ROLES)}, got {role!r}", code="bad_request",
                              details={"index": i, "name": name, "role": role})
        sources.append(ProgramSource(name, language.upper(), source, role))
    sim.load_programs(sources)
    return {"type": "program_list", "programs": sim.programs()}


async def _program_list(sim, pacer, conn, msg: dict) -> dict:
    return {"type": "program_list", "programs": sim.programs()}


# ------------------------------------------------------------------ PLC control
async def _plc_run(sim, pacer, conn, msg: dict) -> dict:
    sim.plc_run()
    return {"type": "ack"}


async def _plc_stop(sim, pacer, conn, msg: dict) -> dict:
    sim.plc_stop()
    return {"type": "ack"}


async def _plc_reset(sim, pacer, conn, msg: dict) -> dict:
    sim.plc_reset()
    return {"type": "ack"}


async def _plc_clear_faults(sim, pacer, conn, msg: dict) -> dict:
    sim.plc_clear_faults()
    return {"type": "ack"}


async def _plc_force(sim, pacer, conn, msg: dict) -> dict:
    name = msg.get("name")
    if not isinstance(name, str) or "value" not in msg:
        raise SimRejected("'plc.force' needs 'name' and 'value'", code="bad_request")
    sim.force(name, msg["value"])
    return {"type": "ack"}


async def _plc_unforce(sim, pacer, conn, msg: dict) -> dict:
    name = msg.get("name")
    if not isinstance(name, str):
        raise SimRejected("'plc.unforce' needs 'name'", code="bad_request")
    sim.unforce(name)
    return {"type": "ack"}


# ------------------------------------------------------------------ sim control
async def _sim_reset(sim, pacer, conn, msg: dict) -> dict:
    initial = msg.get("initial") or {}
    if not isinstance(initial, dict):
        raise SimRejected("'initial' must be an object", code="bad_request")
    sim.reset_plant(initial)
    return {"type": "ack"}


async def _sim_rate(sim, pacer, conn, msg: dict) -> dict:
    if "scan_hz" in msg:
        try:
            hz = float(msg["scan_hz"])
        except (TypeError, ValueError):
            raise SimRejected("'scan_hz' must be a number", code="bad_request")
        sim.set_scan_hz(max(SCAN_HZ_MIN, min(SCAN_HZ_MAX, hz)))
    if "realtime" in msg:
        pacer.realtime = bool(msg["realtime"])
        pacer.reset()
    if "speed" in msg:
        try:
            pacer.speed = max(0.0, float(msg["speed"]))
        except (TypeError, ValueError):
            raise SimRejected("'speed' must be a number", code="bad_request")
    return {"type": "ack"}


async def _sim_pause(sim, pacer, conn, msg: dict) -> dict:
    sim.pause()
    return {"type": "ack"}


async def _sim_resume(sim, pacer, conn, msg: dict) -> dict:
    sim.resume()
    return {"type": "ack"}


_HANDLERS: dict[str, Handler] = {
    "hello": _hello,
    "subscribe": _subscribe,
    "unsubscribe": _unsubscribe,
    "read": _read,
    "write": _write,
    "sequence": _sequence,
    "abort": _abort,
    "abort.clear": _abort_clear,
    "abort.config": _abort_config,
    "program.compile": _program_compile,
    "program.load": _program_load,
    "program.list": _program_list,
    "plc.run": _plc_run,
    "plc.stop": _plc_stop,
    "plc.reset": _plc_reset,
    "plc.clear_faults": _plc_clear_faults,
    "plc.force": _plc_force,
    "plc.unforce": _plc_unforce,
    "sim.reset": _sim_reset,
    "sim.rate": _sim_rate,
    "sim.pause": _sim_pause,
    "sim.resume": _sim_resume,
}
