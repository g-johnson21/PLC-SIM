"""docs/protocol.md "Server": subscriptions, concurrent clients, non-finite values,
logging, and the real entry point."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import socket
import sys

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from draco_sim.protocol.codec import dumps, sanitize_nonfinite
from draco_sim.protocol.server import _HandshakeNoiseFilter, parse_args, run_server

from .helpers import Client, async_test, stand, wait_for

SUBSCRIPTION_KEYS = {"type", "t", "scan", "scan_hz", "paused", "abort", "nonfinite"}


@async_test
async def test_subscribe_pushes_state_until_unsubscribe():
    async with stand() as s, s.client() as c:
        await c.ok("subscribe", rate_hz=50, groups=["inputs"])
        first = await c.next_of("state")
        assert set(first) == SUBSCRIPTION_KEYS | {"inputs"} and first["nonfinite"] == []
        s.sim.run_scans(5)
        later = first
        while later["scan"] == first["scan"]:
            later = await c.next_of("state")
        assert later["scan"] == first["scan"] + 5
        await c.ok("unsubscribe")
        await c.drain()
        c.states.clear()
        await c.drain()
        assert c.states == []


@async_test
async def test_the_default_subscription_is_everything_but_raw_and_the_rate_is_clamped():
    async with stand() as s, s.client(name="sub") as c:
        await c.ok("subscribe", rate_hz=1000)
        state = await c.next_of("state")
        assert set(state) == SUBSCRIPTION_KEYS | {"inputs", "outputs", "plc", "hmi", "plant"}
        assert s.connection("sub").rate_hz == 50.0
        await c.ok("subscribe", rate_hz=0, groups=["hmi"])
        assert s.connection("sub").rate_hz == 1.0


@async_test
async def test_a_non_finite_value_is_sent_as_null_and_listed():
    async with stand() as s, s.client() as c:
        s.sim.plant.state.lox_mass_kg = math.inf
        await c.ok("subscribe", rate_hz=50, groups=["plant"])
        state = await c.next_of("state")
        assert state["plant"]["lox_mass_kg"] is None
        assert state["nonfinite"] == ["plant.lox_mass_kg"]


def test_the_codec_names_every_replaced_value_and_writes_strict_json():
    clean, names = sanitize_nonfinite({"a": [1.0, math.nan], "b": {"c": -math.inf, "d": 2}})
    assert clean == {"a": [1.0, None], "b": {"c": None, "d": 2}}
    assert names == ["a[1]", "b.c"]
    with pytest.raises(ValueError):
        dumps({"x": math.nan})


@async_test
async def test_every_client_gets_every_event_but_only_its_own_subscription():
    async with stand() as s, s.client(name="a") as a, s.client(name="b") as b:
        await b.ok("subscribe", rate_hz=50, groups=["hmi"])
        await a.ok("write", values={"hmi.bb.lox.setpoint": 850.0})
        await a.ok("read", names=["PT1"])
        await b.ok("read", names=["PT1"])
        for client in (a, b):
            assert "bang-bang lox: setpoint = 850.0" in client.event_texts("info")
        state = await b.next_of("state")
        while state["hmi"]["bb"]["lox"]["setpoint"] != 850.0:
            state = await b.next_of("state")
        await a.drain()
        assert a.states == []


@async_test
async def test_a_client_leaving_does_not_disturb_the_others():
    async with stand() as s, s.client(name="stay") as stay:
        async with s.client(name="leave") as leave:
            await leave.ok("subscribe", rate_hz=50)
            task = s.connection("leave").subscribe_task
            assert len(s.connections) == 2
        assert await wait_for(lambda: len(s.connections) == 1)
        assert await wait_for(task.done)
        s.sim.run_scans(3)
        await stay.ok("read", names=["PT1"])


@async_test
async def test_a_late_client_gets_only_the_events_after_it_connected():
    async with stand() as s, s.client(name="early") as early:
        await early.ok("plc.run")
        async with s.client(name="late") as late:
            await late.ok("plc.stop")
            await late.ok("read", names=["PT1"])
            assert late.event_texts("info")[0].startswith("PLC STOP")
            assert "PLC RUN" not in late.event_texts()


@async_test
async def test_any_path_but_ws_is_refused_at_the_handshake():
    async with stand() as s:
        with pytest.raises(InvalidStatus) as info:
            async with connect(f"ws://127.0.0.1:{s.port}/other"):
                pass
        assert info.value.response.status_code == 404


def _handshake_record(message: str) -> logging.LogRecord:
    try:
        try:
            raise ValueError("unsupported HTTP method; expected GET; got HEAD")
        except ValueError as inner:
            raise RuntimeError("did not receive a valid HTTP request") from inner
    except RuntimeError:
        exc_info = sys.exc_info()
    return logging.LogRecord("websockets.server", logging.ERROR, __file__, 1, message, (), exc_info)


@pytest.mark.parametrize("verbose, level", [(False, logging.DEBUG), (True, logging.INFO)])
def test_the_handshake_noise_filter_collapses_the_traceback_to_one_line(verbose, level):
    record = _handshake_record("opening handshake failed")
    assert _HandshakeNoiseFilter(verbose).filter(record) is True
    assert (record.levelno, record.exc_info) == (level, None)
    assert record.getMessage() == ("rejected non-WebSocket request from ?: "
                                   "unsupported HTTP method; expected GET; got HEAD")
    other = _handshake_record("connection handler failed")
    assert _HandshakeNoiseFilter(verbose).filter(other) is True
    assert other.levelno == logging.ERROR and other.exc_info is not None


@async_test
async def test_a_plain_http_probe_logs_no_error(caplog):
    logger = logging.getLogger("websockets.server")
    noise = _HandshakeNoiseFilter(verbose=False)
    logger.addFilter(noise)
    caplog.set_level(logging.DEBUG)
    try:
        async with stand() as s:
            reader, writer = await asyncio.open_connection("127.0.0.1", s.port)
            writer.write(b"HEAD / HTTP/1.1\r\nHost: localhost\r\n\r\n")
            await writer.drain()
            with contextlib.suppress(TimeoutError, ConnectionError):
                await asyncio.wait_for(reader.read(), 2.0)
            writer.close()
            await asyncio.sleep(0.1)
    finally:
        logger.removeFilter(noise)
    records = [r for r in caplog.records if r.name.startswith("websockets")]
    assert not [r for r in records if r.levelno >= logging.ERROR]
    assert any(r.getMessage().startswith("rejected non-WebSocket request from 127.0.0.1:")
               for r in records)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@async_test
async def test_the_real_entry_point_serves_the_examples_scans_and_broadcasts():
    port = _free_port()
    server = asyncio.ensure_future(run_server(parse_args(
        ["--port", str(port), "--load-examples", "--no-realtime"])))
    try:
        ws = None
        for _ in range(200):
            try:
                ws = await connect(f"ws://127.0.0.1:{port}/ws")
                break
            except OSError:
                await asyncio.sleep(0.02)
        assert ws is not None
        async with ws:
            c = Client(ws)
            welcome = await c.ok("hello", client="pytest", protocol=1)
            assert len(welcome["programs"]) == 5
            await c.ok("plc.run")
            await c.ok("sequence", action="start", name="hotfire")
            while not any("hotfire OPEN_FUEL_MAIN" in t for t in c.event_texts("sequence")):
                await c.next()
            await c.ok("subscribe", rate_hz=50, groups=[])
            first = await c.next_of("state")
            later = await c.next_of("state")
            assert later["scan"] > first["scan"]
    finally:
        server.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await server
