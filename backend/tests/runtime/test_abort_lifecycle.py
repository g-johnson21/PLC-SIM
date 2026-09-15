"""docs/runtime.md §3 and decisions.md D12: trip, latch, chain, return of control."""

from __future__ import annotations

from dataclasses import replace
import json

import pytest

from draco_sim.runtime.demo import INITIAL

from .helpers import (STAND_SAFE, MONITOR_ENABLE, abort_hotfire, active_steps, as_json, enabled,
                      hmi, latched, make_sim, open_valves, outputs, refused, run_to_return,
                      sfc, st, texts, trip_row)

REFUSED = {
    "write an output": ("abort_active", lambda s: s.write({"PB2": True})),
    "start a sequence": ("abort_active", lambda s: s.sequence_start("gn2_purge")),
    "stop the safing chart": ("abort_active", lambda s: s.sequence_stop("hotfire")),
    "plc stop": ("abort_active", lambda s: s.plc_stop()),
    "plc reset": ("abort_active", lambda s: s.plc_reset()),
    "load programs": ("abort_active", lambda s: s.load_programs(s.example_sources())),
    "force an output": ("abort_active", lambda s: s.force("PB2", True)),
    "enable a loop": ("abort_active", lambda s: s.write({"hmi.bb.lox.enable": True})),
    "abort_clear": ("rejected", lambda s: s.abort_clear()),
    "write hmi.abort false": ("rejected", lambda s: s.write({"hmi.abort": False})),
}
WITH_WAITING_ON = {"plc stop", "plc reset", "abort_clear"}


def _force_then_unforce(sim):
    sim.force("PT1", 0.0)
    sim.unforce("PT1")


def _pause_resume(sim):
    sim.pause()
    sim.resume()


ACCEPTED = {
    "setpoint edit": lambda s: s.write({"hmi.bb.lox.setpoint": 850.0}),
    "deadband edit": lambda s: s.write({"hmi.bb.fuel.deadband": 20.0}),
    "loop enable false": lambda s: s.write({"hmi.bb.lox.enable": False}),
    "plc global write": lambda s: s.write({"plc.globals.pt0_abort_threshold": 1.0}),
    "input force and unforce": _force_then_unforce,
    "abort_config": lambda s: s.abort_config([]),
    "clear faults": lambda s: s.plc_clear_faults(),
    "pause and resume": _pause_resume,
    "scan rate": lambda s: s.set_scan_hz(50),
    "abort again": lambda s: s.abort(),
}


def test_the_latch_records_the_cause_and_switches_off_the_valve_writers():
    sim = make_sim()
    t_latch = abort_hotfire(sim)
    abort = sim.snapshot(["abort"])["abort"]
    assert abort["tripped"] == {"tag": "hmi.abort", "value": True, "threshold": None,
                                "t": t_latch, "source": "manual"}
    assert abort["waiting_on"] == ["hotfire at ABORT"]
    assert (enabled(sim)["bangbang_lox"], enabled(sim)["bangbang_fuel"]) == (False, False)
    assert hmi(sim)["manual_allowed"] is False
    [latch] = [t for t in texts(sim, "abort") if t.startswith("ABORT LATCHED")]
    assert "regulation off: bangbang_lox, bangbang_fuel; manual commands cleared" in latch


@pytest.mark.parametrize("action", sorted(REFUSED))
def test_refused_while_latched_and_nothing_changes(action):
    sim = make_sim()
    abort_hotfire(sim)
    code, fn = REFUSED[action]
    before = as_json(sim.snapshot())
    exc = refused(code, fn, sim)
    if action in WITH_WAITING_ON:
        assert exc.details["waiting_on"] == ["hotfire at ABORT"]
    assert as_json(sim.snapshot()) == before


@pytest.mark.parametrize("action", sorted(ACCEPTED))
def test_accepted_while_latched_without_releasing_it(action):
    sim = make_sim()
    abort_hotfire(sim)
    ACCEPTED[action](sim)
    assert latched(sim) and sim.waiting_on() == ["hotfire at ABORT"]
    assert texts(sim, "abort").count("manual abort requested (hmi.abort)") == 1


def test_output_forces_are_cleared_at_the_latch_and_input_forces_stay():
    sim = make_sim()
    sim.plc_run()
    sim.force("PB2", True)
    sim.force("PT1", 0.0)
    sim.step()
    assert outputs(sim)["PB2"] is True
    sim.abort()
    sim.step()
    forced = sim.snapshot(["plc"])["plc"]["forced"]
    assert "PB2" not in forced and "PT1" in forced
    assert "output forces cleared: MV-LOX (PB2)" in texts(sim, "abort")
    assert outputs(sim)["PB2"] is False


@pytest.mark.parametrize("hz", [50, 30])
def test_control_returns_by_itself_when_the_abort_chain_completes(hz):
    sim = make_sim(hz)
    t_latch = abort_hotfire(sim)
    sim.write({"hmi.bb.lox.setpoint": 850.0})
    seen = set()
    while latched(sim):
        seen.update(sim.waiting_on())
        sim.step()
        assert sim.t - t_latch < 6.0
    # 0.1 + 0.1 + 0.1 + 5.0 s of chain, plus the scan ABORT_5 takes to reach ABORT_DONE
    assert sim.t - t_latch == pytest.approx(5.3 + sim.dt)
    assert "hotfire at ABORT_4" in seen

    snap = sim.snapshot(["outputs", "hmi", "plc", "abort"])
    assert {tag for tag, v in snap["outputs"].items() if v} == {"PB1", "PB3"}
    assert snap["hmi"]["manual"] == {} and snap["hmi"]["manual_allowed"] is True
    assert snap["plc"]["sfc"]["hotfire"]["running"] is False and snap["plc"]["abort_active"] is False
    assert snap["abort"]["waiting_on"] == [] and snap["abort"]["tripped"]["t"] == t_latch
    lox, fuel = snap["hmi"]["bb"]["lox"], snap["hmi"]["bb"]["fuel"]
    assert (lox["enable"], lox["setpoint"], fuel["enable"], fuel["setpoint"]) == (False, 850.0, False, 870.0)
    assert snap["plc"]["globals"]["setpoint"] == 850.0
    events = texts(sim, "abort")
    assert STAND_SAFE in events
    assert "programs left off until plc.reset re-arms them: bangbang_lox, bangbang_fuel" in events
    assert not any(t.startswith("held as manual commands") for t in events)

    sim.write({"PB2": False})
    sim.sequence_start("hotfire")
    sim.step()
    assert not any(step.startswith("ABORT") for step in active_steps(sim, "hotfire"))


def test_outputs_an_abort_chain_leaves_off_their_safe_state_are_held_as_manual_commands():
    chart = sfc("open_at_safe", [("IDLE", ""), ("SAFE", "PB2 := TRUE;"), ("SAFE_DONE", "")],
                [("SAFE", "SAFE_DONE", "SAFE.T >= T#100ms")], abort_step="SAFE")
    sim = make_sim(examples=False)
    sim.load_programs([chart])
    sim.plc_run()
    sim.abort()
    sim.step()
    run_to_return(sim, 1.0)
    assert hmi(sim)["manual"] == {"PB2": True} and outputs(sim)["PB2"] is True
    assert "held as manual commands: MV-LOX (PB2) OPEN" in texts(sim, "abort")


def test_a_threshold_still_tripped_at_chain_end_holds_the_latch_until_its_row_is_disabled():
    sim = make_sim()
    sim.plc_run()
    sim.run_scans(2)
    row = trip_row(sim, "PT1")
    sim.abort_config([row])
    sim.step()
    assert latched(sim)
    sim.run_for(6.0)
    expected = f"PT1 > {row.value:g} still tripped"
    assert latched(sim) and sim.waiting_on() == [expected]
    held = [t for t in texts(sim, "abort") if t.startswith("abort sequence complete but the latch is held")]
    assert len(held) == 1 and expected in held[0]
    sim.force("PT1", 0.0)
    sim.run_scans(5)
    assert latched(sim)
    sim.abort_config([replace(row, enabled=False)])
    sim.step()
    assert not latched(sim) and sim.manual_allowed()


def test_a_program_request_still_set_holds_the_latch_until_the_monitor_is_disarmed():
    sim = make_sim()
    sim.plc_run()
    sim.write({MONITOR_ENABLE: True})
    sim.run_scans(2)
    assert latched(sim)
    sim.run_for(6.0)
    assert sim.waiting_on() == ["plc.globals.auto_abort_request still set"]
    sim.write({MONITOR_ENABLE: False})
    sim.step()
    assert not latched(sim)


def test_control_waits_for_every_loaded_abort_chain():
    slow = sfc("slow_safe", [("IDLE", ""), ("SAFE", ""), ("SAFE_DONE", "")],
               [("SAFE", "SAFE_DONE", "SAFE.T >= T#8s")], abort_step="SAFE")
    sim = make_sim()
    sim.load_programs(sim.example_sources() + [slow])
    sim.plc_run()
    sim.abort()
    sim.step()
    assert sorted(sim.waiting_on()) == ["hotfire at ABORT", "slow_safe at SAFE"]
    sim.run_for(6.0)
    assert sim.waiting_on() == ["slow_safe at SAFE"]
    run_to_return(sim, 3.0)


def test_an_abort_chain_with_no_final_step_never_returns_control():
    chart = sfc("cycle", [("IDLE", ""), ("SAFE_A", "PB2 := FALSE;"), ("SAFE_B", "")],
                [("SAFE_A", "SAFE_B", "SAFE_A.T >= T#100ms"), ("SAFE_B", "SAFE_A", "SAFE_B.T >= T#100ms")],
                abort_step="SAFE_A")
    sim = make_sim(examples=False)
    sim.load_programs([chart])
    sim.plc_run()
    sim.abort()
    sim.run_for(1.0)
    [entry] = sim.waiting_on()
    assert entry.startswith("cycle at ") and "never completes" in entry
    sim.reset_plant(INITIAL)
    assert not latched(sim)


def test_an_abort_during_the_purge_runs_the_hotfire_chain_and_closes_the_purges():
    sim = make_sim()
    sim.plc_run()
    sim.sequence_start("gn2_purge")
    sim.run_for(0.5)
    assert outputs(sim)["S4"] and outputs(sim)["S5"]
    sim.abort()
    sim.step()
    assert sim.waiting_on() == ["hotfire at ABORT"]
    run_to_return(sim)
    assert open_valves(sim) == {"PB1", "PB3"}


def test_an_abort_while_a_valve_writer_is_faulted_switches_it_off_and_returns():
    faulty = st("faulty", "PB2 := TRUE;\nIF go THEN q := 1 / z; END_IF;",
                "VAR_GLOBAL go : BOOL := FALSE; END_VAR\nVAR z : INT; q : INT; END_VAR")
    sim = make_sim(examples=False)
    sim.load_programs([faulty])
    sim.plc_run()
    sim.step()
    sim.write({"plc.globals.go": True})
    sim.step()
    assert sim.snapshot(["plc"])["plc"]["halted"] == ["faulty"]
    sim.abort()
    sim.step()
    assert not latched(sim) and outputs(sim)["PB2"] is False and enabled(sim)["faulty"] is False
    sim.write({"plc.globals.go": False})
    sim.plc_clear_faults()
    sim.run_scans(3)
    assert outputs(sim)["PB2"] is False


@pytest.mark.parametrize("fault_step", ["RUN", "ABORT"])
def test_chart_fault_recovery_and_abort_return_of_control(fault_step):
    source = sfc("seq", [("START", "PB2 := TRUE;"), ("RUN", ""),
                         ("ABORT", "PB2 := FALSE;"), ("SAFE", "PB1 := TRUE;")],
                 [("START", "RUN", "START.T >= T#20ms"),
                  ("ABORT", "SAFE", "ABORT.T >= T#40ms")], abort_step="ABORT")
    doc = json.loads(source.source)
    doc["vars"] = [{"name": "trip", "type": "BOOL", "scope": "VAR_GLOBAL", "init": True},
                   {"name": "z", "type": "INT"}, {"name": "q", "type": "INT"}]
    target = next(s for s in doc["steps"] if s["name"] == fault_step)
    target["actions"].append({"qualifier": "N", "body": "IF trip THEN q := 1 / z; END_IF"})
    sim = make_sim(examples=False)
    sim.load_programs([replace(source, source=json.dumps(doc))])
    sim.plc_run()
    sim.sequence_start("seq")
    sim.run_scans(2)
    assert outputs(sim)["PB2"] is True
    assert sim.snapshot(["plc"])["plc"]["halted"] == (["seq"] if fault_step == "RUN" else [])
    sim.abort()
    sim.step()
    assert latched(sim) and active_steps(sim, "seq") == ["ABORT"]
    if fault_step == "ABORT":
        assert sim.snapshot(["plc"])["plc"]["halted"] == ["seq"]
        sim.run_scans(5)
        assert latched(sim) and sim.waiting_on() == ["seq at ABORT"]
        sim.write({"plc.globals.trip": False})
        sim.plc_clear_faults()
        sim.step()
    assert outputs(sim)["PB2"] is False
    run_to_return(sim)
    assert outputs(sim)["PB1"] is True and outputs(sim)["PB2"] is False
    assert sim.snapshot(["plc"])["plc"]["halted"] == []


def test_sim_reset_is_the_instructor_reset_that_clears_a_latch():
    sim = make_sim()
    abort_hotfire(sim)
    sim.reset_plant(INITIAL)
    snap = sim.snapshot(["plc", "abort", "hmi"])
    assert snap["abort"]["latched"] is False and snap["abort"]["tripped"] is None
    assert all(snap["plc"]["enabled"].values()) and snap["plc"]["running"] is True
    assert (sim.t, sim.scan) == (0.0, 0)
    assert "abort cleared by sim.reset (instructor action)" in texts(sim, "abort")
    sim.write({"hmi.bb.lox.enable": True})


def test_abort_clear_does_nothing_when_no_abort_is_latched():
    sim = make_sim()
    sim.plc_run()
    sim.step()
    before = as_json(sim.snapshot())
    sim.abort_clear()
    assert as_json(sim.snapshot()) == before
