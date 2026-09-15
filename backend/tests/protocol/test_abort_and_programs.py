"""docs/protocol.md "Abort lifecycle", "Program roles" and compile_result, over the wire."""

from __future__ import annotations

from ..runtime.helpers import EXAMPLE_ROLES, STAND_SAFE, INITIAL
from .helpers import async_test, stand

LATCHED_ABORT_ACTIVE = [
    ("write", {"values": {"PB2": True}}),
    ("write", {"values": {"hmi.bb.lox.enable": True}}),
    ("sequence", {"action": "stop", "name": "hotfire"}),
    ("sequence", {"action": "start", "name": "gn2_purge"}),
    ("plc.reset", {}),
    ("plc.force", {"name": "PB2", "value": True}),
]
LATCHED_ACCEPTED = [
    ("write", {"values": {"hmi.bb.lox.setpoint": 850.0}}),
    ("write", {"values": {"plc.globals.pt0_abort_threshold": 1.0}}),
    ("plc.force", {"name": "PT1", "value": 0.0}),
    ("plc.unforce", {"name": "PT1"}),
    ("abort.config", {"thresholds": []}),
    ("plc.clear_faults", {}),
    ("abort", {}),
]


@async_test
async def test_abort_round_trip():
    async with stand() as s, s.client() as c:
        sim = s.sim
        await c.ok("plc.run")
        await c.ok("sequence", action="start", name="hotfire")
        sim.run_for(1.0)
        await c.ok("abort")
        sim.step()
        values = (await c.ok("read", names=["abort.latched", "abort.waiting_on", "hmi.abort"]))["values"]
        assert values == {"abort.latched": True, "abort.waiting_on": ["hotfire at ABORT"],
                          "hmi.abort": False}

        for type_, fields in LATCHED_ABORT_ACTIVE:
            await c.error("abort_active", type_, **fields)
        err = await c.error("abort_active", "plc.stop")
        assert err["details"]["waiting_on"] == ["hotfire at ABORT"]
        await c.error("abort_active", "program.load",
                      programs=[{"name": "p", "language": "ST", "source": "PROGRAM p\nEND_PROGRAM"}])
        err = await c.error("rejected", "abort.clear")
        assert err["details"]["waiting_on"] == ["hotfire at ABORT"]
        await c.error("rejected", "write", values={"hmi.abort": False})
        for type_, fields in LATCHED_ACCEPTED:
            await c.ok(type_, **fields)

        while sim.read(["abort.latched"])["abort.latched"]:
            sim.step()
        await c.ok("read", names=["PT1"])
        aborts = c.event_texts("abort")
        assert aborts[0] == "manual abort requested (hmi.abort)"
        assert aborts[1].startswith("ABORT LATCHED -- hmi.abort")
        assert STAND_SAFE in aborts

        err = await c.error("rejected", "write", values={"hmi.bb.lox.enable": True})
        assert err["details"]["programs"] == ["bangbang_lox"]
        await c.ok("plc.reset")
        await c.ok("write", values={"hmi.bb.lox.enable": True, "PB2": False})


@async_test
async def test_sim_reset_over_the_wire_clears_a_latch():
    async with stand() as s, s.client() as c:
        await c.ok("plc.run")
        await c.ok("abort")
        s.sim.step()
        await c.ok("sim.reset", initial=INITIAL)
        values = (await c.ok("read", names=["abort.latched", "abort.tripped"]))["values"]
        assert values == {"abort.latched": False, "abort.tripped": None}


@async_test
async def test_a_subscription_reports_the_latch_whatever_its_groups():
    async with stand() as s, s.client() as c:
        await c.ok("plc.run")
        await c.ok("abort")
        s.sim.step()
        await c.ok("subscribe", rate_hz=50, groups=["inputs"])
        state = await c.next_of("state")
        assert state["abort"]["latched"] is True and state["abort"]["tripped"]["source"] == "manual"


def _examples_without_roles(welcome):
    return [{"name": e["name"], "language": e["language"], "source": e["source"]}
            for e in welcome["examples"]]


@async_test
async def test_program_load_infers_missing_or_null_roles():
    async with stand(examples=False) as s, s.client() as c:
        programs = _examples_without_roles(c.welcome)
        programs[0]["role"] = None
        reply = await c.ok("program.load", programs=programs)
        assert reply["type"] == "program_list"
        assert {p["name"]: p["role"] for p in reply["programs"]} == EXAMPLE_ROLES
        assert all(p["compiled_ok"] for p in reply["programs"])
        assert (await c.ok("program.list"))["programs"] == reply["programs"]


@async_test
async def test_a_role_outside_the_four_is_a_bad_request_and_loads_nothing():
    async with stand(examples=False) as s, s.client() as c:
        programs = _examples_without_roles(c.welcome)
        programs[2]["role"] = "boss"
        err = await c.error("bad_request", "program.load", programs=programs)
        assert err["details"] == {"index": 2, "name": "hotfire", "role": "boss"}
        assert (await c.ok("program.list"))["programs"] == []


@async_test
async def test_a_contradictory_role_is_a_compile_error_on_that_program():
    async with stand(examples=False) as s, s.client() as c:
        programs = _examples_without_roles(c.welcome)
        programs[2]["role"] = "regulation"
        err = await c.error("compile_error", "program.load", programs=programs)
        results = {r["name"]: r for r in err["details"]["results"]}
        assert results["hotfire"]["ok"] is False
        assert [e["path"] for e in results["hotfire"]["errors"]] == ["/role"]
        assert sum(not r["ok"] for r in results.values()) == 1
        assert (await c.ok("program.list"))["programs"] == []


@async_test
async def test_program_load_is_refused_while_the_plc_runs():
    async with stand() as s, s.client() as c:
        await c.ok("plc.run")
        err = await c.error("plc_running", "program.load", programs=_examples_without_roles(c.welcome))
        assert err["details"] == {"running": True}
        await c.error("bad_request", "program.load",
                      programs=[{"name": "p", "language": "IL", "source": "x"}])


@async_test
async def test_compile_result_carries_variables_errors_and_ladder_text():
    async with stand(examples=False) as s, s.client() as c:
        examples = {e["name"]: e for e in c.welcome["examples"]}
        st = await c.ok("program.compile", **{k: examples["bangbang_lox"][k]
                                              for k in ("name", "language", "source")})
        assert (st["type"], st["ok"], st["errors"]) == ("compile_result", True, [])
        assert {"name": "setpoint", "type": "REAL", "scope": "VAR_GLOBAL"} in st["variables"]
        assert "ladder_text" not in st

        ld = await c.ok("program.compile", **{k: examples["bangbang_fuel"][k]
                                              for k in ("name", "language", "source")})
        assert ld["ok"] and isinstance(ld["ladder_text"], str) and ld["ladder_text"]

        bad = await c.ok("program.compile", name="bad", language="ST",
                         source="PROGRAM bad\nPB2 := ;\nEND_PROGRAM\n")
        assert bad["ok"] is False
        assert {"message", "line", "col", "path"} <= set(bad["errors"][0])
        assert bad["errors"][0]["line"] == 2
        assert (await c.ok("program.list"))["programs"] == []
