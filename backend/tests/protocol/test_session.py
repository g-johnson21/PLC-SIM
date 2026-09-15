"""docs/protocol.md: hello, malformed frames, error codes."""

from __future__ import annotations

import pytest

from draco_sim.protocol.handlers import _HANDLERS

from ..runtime.helpers import EXAMPLE_ROLES
from .helpers import async_test, stand

DOCUMENTED_TYPES = {
    "hello", "subscribe", "unsubscribe", "read", "write", "sequence", "abort", "abort.clear",
    "abort.config", "program.compile", "program.load", "program.list", "plc.run", "plc.stop",
    "plc.reset", "plc.clear_faults", "plc.force", "plc.unforce", "sim.reset", "sim.rate",
    "sim.pause", "sim.resume"}


def test_every_documented_client_message_has_a_handler():
    assert set(_HANDLERS) == DOCUMENTED_TYPES


@async_test
async def test_hello_gets_the_welcome_with_its_id():
    async with stand() as s, s.client(hello=False) as c:
        welcome = await c.ok("hello", client="pytest", protocol=1)
        assert (welcome["type"], welcome["id"], welcome["protocol"]) == ("welcome", "r1", 1)
        assert {"PT1", "PB2", "THRUST"} <= {t["tag"] for t in welcome["tags"]}
        assert {p["name"]: p["role"] for p in welcome["programs"]} == EXAMPLE_ROLES
        assert [e["name"] for e in welcome["examples"]] == [
            "bangbang_lox", "bangbang_fuel", "hotfire", "gn2_purge", "abort_monitor"]
        assert "NOT" in welcome["notice"]


@async_test
async def test_a_protocol_mismatch_is_a_bad_request_and_the_connection_stays_open():
    async with stand() as s, s.client(hello=False) as c:
        err = await c.error("bad_request", "hello", client="old", protocol=2)
        assert err["details"] == {"protocol": 2}
        await c.ok("read", names=["PT1"])


@async_test
async def test_malformed_frames_get_bad_request_without_closing_the_connection():
    async with stand() as s, s.client(hello=False) as c:
        for raw in ("{not json", "[1, 2]"):
            await c.send(raw)
            err = await c.next_of("error")
            assert (err["id"], err["code"]) == (None, "bad_request")
        await c.send({"id": "no-type"})
        assert (await c.reply("no-type"))["code"] == "bad_request"
        await c.send({"type": "nope", "id": "unknown-type"})
        assert (await c.reply("unknown-type"))["code"] == "bad_request"
        await c.ok("read", names=["PT1"])


CASES = [
    ("unknown_name", "read", {"names": ["PT1", "nope"]}),
    ("bad_request", "read", {"names": []}),
    ("read_only", "write", {"values": {"PT1": 1}}),
    ("bad_request", "write", {"values": {}}),
    ("rejected", "write", {"values": {"PB2": True}}),
    ("rejected", "abort", {}),
    ("unknown_name", "sequence", {"action": "start", "name": "nope"}),
    ("bad_request", "sequence", {"action": "go", "name": "hotfire"}),
    ("bad_request", "plc.force", {"name": "PT1"}),
    ("unknown_name", "plc.force", {"name": "nope", "value": 1}),
    ("bad_request", "plc.unforce", {}),
    ("bad_request", "subscribe", {"groups": "inputs"}),
    ("bad_request", "subscribe", {"rate_hz": "fast"}),
    ("bad_request", "abort.config", {"thresholds": {}}),
    ("unknown_name", "abort.config", {"thresholds": [{"tag": "NOPE", "op": ">", "value": 1.0}]}),
    ("bad_request", "sim.reset", {"initial": 5}),
    ("unknown_name", "sim.reset", {"initial": {"nope": 1}}),
    ("bad_request", "sim.rate", {"scan_hz": "fast"}),
    ("bad_request", "program.load", {"programs": []}),
    ("bad_request", "program.compile", {"name": "x"}),
]


@pytest.mark.parametrize("code, type_, fields", CASES, ids=[f"{t}-{c}" for c, t, _ in CASES])
@async_test
async def test_error_codes(code, type_, fields):
    async with stand() as s, s.client() as c:
        err = await c.error(code, type_, **fields)
        assert err["message"] and isinstance(err["details"], dict)
        await c.ok("read", names=["PT1"])


@async_test
async def test_an_unexpected_exception_is_internal_and_keeps_the_connection(monkeypatch):
    async with stand() as s, s.client() as c:
        def boom(names):
            raise RuntimeError("boom")
        monkeypatch.setattr(s.sim, "read", boom)
        err = await c.error("internal", "read", names=["PT1"])
        assert err["message"] == "boom"
        monkeypatch.undo()
        await c.ok("read", names=["PT1"])


@async_test
async def test_sim_rate_clamps_and_reconfigures_the_pacer():
    async with stand() as s, s.client() as c:
        await c.ok("sim.rate", scan_hz=1000, realtime=False, speed=2.0)
        assert (s.sim.scan_hz, s.pacer.realtime, s.pacer.speed) == (100.0, False, 2.0)
        await c.ok("sim.rate", scan_hz=1)
        assert s.sim.scan_hz == 10.0
        await c.ok("sim.pause")
        assert s.sim.paused
        await c.ok("sim.resume")
        assert not s.sim.paused
