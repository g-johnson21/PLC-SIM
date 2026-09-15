"""docs/runtime.md §2: output arbitration, normal and latched."""

from __future__ import annotations

import pytest

from .helpers import (card_commands, example, hmi, latched, make_sim, normally_open,
                      open_valves, outputs, refused, st, sfc, texts)

PULSE = st("pulse", "IF go THEN PB2 := TRUE; END_IF;", "VAR_GLOBAL go : BOOL := FALSE; END_VAR")
FAULTY = st("faulty", "PB2 := TRUE;\nIF go THEN q := 1 / z; END_IF;",
            "VAR_GLOBAL go : BOOL := FALSE; END_VAR\nVAR z : INT; q : INT; END_VAR")


def test_coils_nothing_drives_sit_at_their_fail_safe_state():
    sim = make_sim()
    sim.plc_run()
    sim.run_for(0.2)
    assert open_valves(sim) == normally_open(sim) == {"PB1", "PB3"}


def test_a_manual_command_drives_a_coil_no_program_writes():
    sim = make_sim()
    sim.plc_run()
    sim.step()
    sim.write({"PB2": True})
    sim.step()
    assert outputs(sim)["PB2"] is True and hmi(sim)["manual"] == {"PB2": True}
    assert sim.plc.read_outputs()["PB2"] is False


def test_a_program_writing_a_coil_every_scan_beats_a_manual_command():
    sim = make_sim(examples=False)
    sim.load_programs([st("hold_pb2", "PB2 := TRUE;")])
    sim.plc_run()
    sim.step()
    sim.write({"PB2": False})
    sim.run_scans(3)
    assert outputs(sim)["PB2"] is True and hmi(sim)["manual"] == {"PB2": False}


LOOPS = [("lox", "S1"), ("fuel", "S2")]


@pytest.mark.parametrize("loop, tag", LOOPS)
def test_a_disabled_loop_leaves_its_solenoid_to_manual_control(loop, tag):
    sim = make_sim()
    sim.plc_run()
    sim.step()
    assert hmi(sim)["bb"][loop]["enable"] is False
    sim.write({tag: True})
    sim.run_scans(3)
    assert outputs(sim)[tag] is True


@pytest.mark.parametrize("loop, tag", LOOPS)
def test_an_enabled_loop_owns_its_solenoid_until_it_is_disabled(loop, tag):
    sim = make_sim()
    sim.plc_run()
    sim.write({f"hmi.bb.{loop}.enable": True})
    sim.run_scans(3)
    assert outputs(sim)[tag] is True
    exc = refused("rejected", sim.write, {tag: False})
    assert exc.details == {"name": tag, "loop": loop}
    refused("rejected", sim.write, {"PB2": True, tag: False})
    assert hmi(sim)["manual"] == {}
    sim.write({f"hmi.bb.{loop}.enable": False, tag: True})
    sim.run_scans(3)
    assert outputs(sim)[tag] is True and hmi(sim)["manual"] == {tag: True}


@pytest.mark.parametrize("loop, tag", LOOPS)
def test_disabling_a_loop_mid_press_closes_its_solenoid_and_lets_go(loop, tag):
    sim = make_sim()
    sim.plc_run()
    sim.write({f"hmi.bb.{loop}.enable": True})
    sim.run_scans(3)
    assert outputs(sim)[tag] is True
    sim.write({f"hmi.bb.{loop}.enable": False})
    sim.step()
    assert outputs(sim)[tag] is False and hmi(sim)["manual"] == {}
    sim.run_for(1.0)
    assert outputs(sim)[tag] is False


def test_enabling_a_loop_releases_a_manual_command_on_its_solenoid():
    sim = make_sim()
    sim.plc_run()
    sim.step()
    sim.write({"S1": True})
    sim.step()
    sim.write({"hmi.bb.lox.enable": True})
    assert hmi(sim)["manual"] == {}
    assert any(t.startswith("manual command released to the lox bang-bang loop") and "(S1)" in t
               for t in texts(sim, "warn"))


def test_a_held_coil_keeps_the_plc_image_until_a_manual_command_overrides_it():
    sim = make_sim(examples=False)
    sim.load_programs([PULSE])
    sim.plc_run()
    sim.write({"plc.globals.go": True})
    sim.step()
    sim.write({"plc.globals.go": False})
    sim.run_scans(3)
    assert outputs(sim)["PB2"] is True
    sim.write({"PB2": False})
    sim.step()
    assert outputs(sim)["PB2"] is False
    sim.write({"plc.globals.go": True})
    sim.step()
    assert outputs(sim)["PB2"] is True


def test_a_forced_output_beats_a_manual_command():
    sim = make_sim()
    sim.plc_run()
    sim.step()
    sim.write({"PB2": False})
    sim.force("PB2", True)
    sim.step()
    assert outputs(sim)["PB2"] is True


def test_a_faulting_scan_writes_nothing_so_the_manual_command_takes_the_coil():
    sim = make_sim(examples=False)
    sim.load_programs([FAULTY])
    sim.plc_run()
    sim.step()
    sim.write({"PB2": False})
    sim.step()
    assert outputs(sim)["PB2"] is True
    sim.write({"plc.globals.go": True})
    sim.step()
    assert outputs(sim)["PB2"] is False
    [fault] = [e for e in sim.events if e.level == "fault"]
    assert "div_zero" in fault.text and fault.scan == sim.scan
    assert sim.snapshot(["plc"])["plc"]["halted"] == ["faulty"]


def test_without_an_abort_chain_a_switched_off_loops_solenoid_closes_on_the_latch_scan():
    sim = make_sim(examples=False)
    sim.load_programs([example(sim, "bangbang_lox")])
    sim.plc_run()
    sim.write({"hmi.bb.lox.enable": True})
    sim.run_scans(3)
    assert outputs(sim)["S1"] is True
    sim.abort()
    sim.step()
    assert outputs(sim)["S1"] is False
    assert any(t.startswith("fail-safe (no abort chain writes them): ") and "(S1) CLOSED" in t
               for t in texts(sim, "abort"))


def test_an_abort_chain_keeps_the_coils_it_writes_until_its_own_step_closes_them():
    sim = make_sim()
    sim.plc_run()
    sim.write({"hmi.bb.lox.enable": True})
    sim.run_scans(3)
    sim.abort()
    sim.step()
    t_latch = sim.t
    assert outputs(sim)["S1"] is True
    sim.run_for(0.5)
    [(t, _, _)] = [c for c in card_commands(sim, t_latch) if c[1] == "S1"]
    assert 0.2 <= t - t_latch <= 0.3


def test_a_chart_without_an_abort_chain_cannot_hold_a_valve_through_an_abort():
    sim = make_sim(examples=False)
    sim.load_programs([sfc("hold_pb2", [("START", ""), ("HOLD_OPEN", "PB2 := TRUE;")],
                           [("START", "HOLD_OPEN", "TRUE")])])
    sim.plc_run()
    sim.sequence_start("hold_pb2")
    sim.run_scans(3)
    assert outputs(sim)["PB2"] is True
    sim.abort()
    sim.step()
    assert outputs(sim)["PB2"] is False


def test_the_latch_drops_manual_commands_and_undriven_vents_go_open():
    sim = make_sim()
    sim.plc_run()
    sim.write({"PB1": False, "PB3": False})
    sim.step()
    assert not outputs(sim)["PB1"]
    sim.sequence_start("hotfire")
    sim.run_for(0.5)
    sim.abort()
    sim.step()
    assert latched(sim) and hmi(sim)["manual"] == {}
    assert outputs(sim)["PB1"] and outputs(sim)["PB3"]
