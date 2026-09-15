"""decisions.md D14: nothing re-arms after an abort, and a stopped PLC is safe."""

from __future__ import annotations

import pytest

from draco_sim.runtime.demo import INITIAL

from .helpers import (STAND_SAFE, abort_hotfire, enabled, hmi, latched, make_sim, normally_open,
                      open_valves, outputs, refused, run_to_return, st, texts)


def test_programs_an_abort_switched_off_stay_off_until_plc_reset():
    sim = make_sim()
    abort_hotfire(sim)
    run_to_return(sim)
    bb = hmi(sim)["bb"]
    assert (bb["lox"]["abort_off"], bb["fuel"]["abort_off"]) == (["bangbang_lox"], ["bangbang_fuel"])
    assert bb["lox"]["state"] == "OFF"
    exc = refused("rejected", sim.write, {"hmi.bb.lox.enable": True})
    assert exc.details == {"name": "hmi.bb.lox.enable", "programs": ["bangbang_lox"]}
    refused("rejected", sim.write, {"hmi.bb.lox.setpoint": 700.0, "hmi.bb.lox.enable": True})
    assert hmi(sim)["bb"]["lox"]["setpoint"] == 904.0
    sim.run_for(1.0)
    assert enabled(sim)["bangbang_lox"] is False

    sim.plc_reset()
    assert hmi(sim)["bb"]["lox"]["abort_off"] == [] and sim.read(["abort.tripped"])["abort.tripped"] is None
    sim.write({"hmi.bb.lox.enable": True})
    sim.run_scans(3)
    assert hmi(sim)["bb"]["lox"]["state"] == "PRESS" and outputs(sim)["S1"] is True


@pytest.mark.parametrize("rearm", ["plc_reset", "sim_reset", "program_load"])
def test_each_documented_reset_rearms_the_loops(rearm):
    sim = make_sim()
    abort_hotfire(sim)
    run_to_return(sim)
    if rearm == "plc_reset":
        sim.plc_reset()
    elif rearm == "sim_reset":
        sim.reset_plant(INITIAL)
    else:
        sim.plc_stop()
        sim.load_examples()
        sim.plc_run()
    assert all(enabled(sim).values())
    assert [hmi(sim)["bb"][loop]["abort_off"] for loop in ("lox", "fuel")] == [[], []]
    sim.write({"hmi.bb.lox.enable": True, "hmi.bb.fuel.enable": True})


def test_a_program_with_no_enable_gate_does_not_reopen_its_valve_after_an_abort():
    sim = make_sim(examples=False)
    sim.load_programs([st("open_pb2", "PB2 := TRUE;")])
    sim.plc_run()
    sim.step()
    assert outputs(sim)["PB2"] is True
    sim.abort()
    sim.step()
    # no chart to wait on: control returns at the end of the latch scan
    assert not latched(sim) and outputs(sim)["PB2"] is False
    latch = [e.scan for e in sim.events if e.text.startswith("ABORT LATCHED")]
    back = [e.scan for e in sim.events if e.text == STAND_SAFE]
    assert latch == back == [sim.scan]
    assert "programs left off until plc.reset re-arms them: open_pb2" in texts(sim, "abort")
    sim.run_for(1.0)
    assert outputs(sim)["PB2"] is False
    sim.write({"PB2": True})
    sim.step()
    assert outputs(sim)["PB2"] is True
    sim.plc_reset()
    sim.step()
    assert outputs(sim)["PB2"] is True and hmi(sim)["manual"] == {}


def test_a_second_abort_after_return_latches_and_returns_again():
    sim = make_sim()
    t_first = abort_hotfire(sim)
    run_to_return(sim)
    sim.run_for(0.5)
    sim.abort()
    sim.step()
    assert latched(sim) and sim.waiting_on() == ["hotfire at ABORT"]
    assert sim.read(["abort.tripped"])["abort.tripped"]["t"] > t_first
    run_to_return(sim)
    assert texts(sim, "abort").count(STAND_SAFE) == 2


def test_abort_is_refused_while_the_plc_is_stopped():
    sim = make_sim()
    refused("rejected", sim.abort)
    refused("rejected", sim.write, {"hmi.abort": True, "hmi.bb.lox.setpoint": 700.0})
    assert hmi(sim)["bb"]["lox"]["setpoint"] == 904.0 and hmi(sim)["abort"] is False
    sim.run_for(0.2)
    assert not latched(sim)


def test_plc_stop_drops_an_abort_request_that_has_not_latched():
    sim = make_sim()
    sim.plc_run()
    sim.step()
    sim.abort()
    assert hmi(sim)["abort"] is True
    sim.plc_stop()
    assert hmi(sim)["abort"] is False
    assert any(t.startswith("pending abort request dropped") for t in texts(sim, "abort"))
    sim.run_for(0.5)
    sim.plc_run()
    sim.run_for(1.0)
    assert not latched(sim) and sim.read(["abort.tripped"])["abort.tripped"] is None


def test_a_stopped_plc_holds_every_coil_safe_and_refuses_manual_writes():
    sim = make_sim()
    sim.plc_run()
    sim.write({"PB1": False, "hmi.bb.lox.enable": True})
    sim.run_scans(3)
    assert outputs(sim)["S1"] is True and outputs(sim)["PB1"] is False
    sim.plc_stop()
    sim.step()
    assert open_valves(sim) == normally_open(sim) and hmi(sim)["manual_allowed"] is False
    refused("rejected", sim.write, {"PB2": True})


def test_after_a_stop_the_stand_stays_safe_when_the_plc_runs_again():
    sim = make_sim()
    sim.plc_run()
    sim.write({"PB1": False, "PB3": False, "hmi.bb.lox.enable": True,
               "hmi.bb.lox.setpoint": 700.0})
    sim.force("S4", True)
    sim.force("PT1", 0.0)
    sim.sequence_start("hotfire")
    sim.run_for(1.0)
    assert {"PB2", "PB4", "S1", "S4"} <= open_valves(sim) and not outputs(sim)["PB1"]

    sim.plc_stop()
    snap = sim.snapshot(["hmi", "plc"])
    assert snap["hmi"]["manual"] == {} and set(snap["plc"]["forced"]) == {"PT1"}
    assert snap["hmi"]["bb"]["lox"]["enable"] is False and snap["hmi"]["bb"]["lox"]["setpoint"] == 700.0
    assert snap["plc"]["sfc"]["hotfire"]["running"] is False
    [cleared] = [t for t in texts(sim, "warn") if t.startswith("cleared so nothing moves on plc.run")]
    assert all(part in cleared for part in ("PB1", "S4", "hotfire", "lox"))

    sim.plc_run()
    for _ in range(round(10.0 * sim.scan_hz)):
        sim.step()
        assert open_valves(sim) == normally_open(sim)
    assert sim.read(["plc.globals.setpoint"])["plc.globals.setpoint"] == 700.0
    assert sim.active_sequence() is None and hmi(sim)["manual_allowed"] is True


def test_a_stop_is_a_cold_restart_of_the_program_variables():
    latch = st("latch_pb2", "IF go THEN held := TRUE; END_IF;\nPB2 := held;",
               "VAR_GLOBAL go : BOOL := FALSE; END_VAR\nVAR held : BOOL := FALSE; END_VAR")
    sim = make_sim(examples=False)
    sim.load_programs([latch])
    sim.plc_run()
    sim.write({"plc.globals.go": True})
    sim.step()
    sim.write({"plc.globals.go": False})
    sim.run_scans(3)
    assert outputs(sim)["PB2"] is True
    sim.plc_stop()
    sim.plc_run()
    sim.run_scans(3)
    assert outputs(sim)["PB2"] is False


def test_programs_an_abort_switched_off_stay_off_across_a_stop():
    sim = make_sim()
    abort_hotfire(sim)
    run_to_return(sim)
    sim.plc_stop()
    sim.plc_run()
    sim.run_scans(3)
    assert enabled(sim)["bangbang_lox"] is False
    assert hmi(sim)["bb"]["lox"]["abort_off"] == ["bangbang_lox"]
    refused("rejected", sim.write, {"hmi.bb.lox.enable": True})
