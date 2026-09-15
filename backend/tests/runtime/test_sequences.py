"""Hotfire timing (D12) and manual commands across a sequence start (D16)."""

from __future__ import annotations

import pytest

from .helpers import (active_steps, card_commands, hmi, make_sim, outputs, refused,
                      run_to_return, texts)

PROCEDURE = [(0.0, "PB2", "OPEN"), (0.5, "PB4", "OPEN"), (8.0, "PB2", "CLOSED"),
             (8.5, "PB4", "CLOSED"), (8.7, "S4", "OPEN"), (8.7, "S5", "OPEN"),
             (11.7, "S4", "CLOSED"), (11.7, "S5", "CLOSED")]


@pytest.mark.parametrize("hz", [50, 30])
def test_each_hotfire_command_reaches_the_cards_one_scan_after_its_t_plus(hz):
    sim = make_sim(hz)
    sim.plc_run()
    sim.run_scans(7)
    sim.sequence_start("hotfire")
    t0 = sim.t
    sim.run_for(12.5)
    seen = sorted((round(t - t0 - sim.dt, 6), tag, state) for t, tag, state in card_commands(sim, t0))
    assert seen == sorted(PROCEDURE)
    assert active_steps(sim, "hotfire") == ["COMPLETE"]
    assert sim.active_sequence() is None and sim.manual_allowed()


def test_a_manual_vent_close_stays_in_force_through_the_hotfire():
    sim = make_sim()
    sim.plc_run()
    sim.write({"PB1": False, "PB3": False})
    sim.step()
    sim.sequence_start("hotfire")
    assert texts(sim, "sequence")[-1] == (
        "T+0.000 hotfire STARTED (manual commands stay in force: PB1, PB3)")
    vents_ever_open = False
    for _ in range(round(12.5 * sim.scan_hz)):
        sim.step()
        vents_ever_open |= outputs(sim)["PB1"] or outputs(sim)["PB3"]
    assert not vents_ever_open
    assert hmi(sim)["manual"] == {"PB1": False, "PB3": False}


def test_a_stale_manual_command_is_released_when_the_chart_writes_that_coil():
    sim = make_sim()
    sim.plc_run()
    sim.write({"PB2": True})
    sim.step()
    sim.sequence_start("hotfire")
    t0 = sim.t
    sim.run_for(12.5)
    released = [t for t in texts(sim, "warn") if t.startswith("manual command released")]
    assert released == ["manual command released to the running sequence: MV-LOX (PB2)"]
    assert hmi(sim)["manual"] == {} and outputs(sim)["PB2"] is False
    assert [(round(t - t0, 3), state) for t, tag, state in card_commands(sim, t0)
            if tag == "PB2"] == [(8.02, "CLOSED")]


def test_an_abort_still_clears_every_manual_command():
    sim = make_sim()
    sim.plc_run()
    sim.write({"PB1": False, "PB3": False})
    sim.step()
    sim.sequence_start("hotfire")
    sim.run_for(1.0)
    sim.abort()
    sim.step()
    assert hmi(sim)["manual"] == {} and outputs(sim)["PB1"] and outputs(sim)["PB3"]
    run_to_return(sim)
    assert hmi(sim)["manual"] == {}


def test_manual_writes_wait_for_the_sequence_to_park_on_its_final_step():
    sim = make_sim()
    sim.plc_run()
    sim.sequence_start("gn2_purge")
    sim.step()
    exc = refused("rejected", sim.write, {"PB2": True})
    assert exc.details == {"name": "PB2", "active_sequence": "gn2_purge"}
    assert hmi(sim)["manual_allowed"] is False
    exc = refused("rejected", sim.sequence_start, "hotfire")
    assert exc.details == {"active_sequence": "gn2_purge"}
    sim.run_for(2.5)
    assert sim.active_sequence() is None and sim.manual_allowed()
    assert sim.snapshot(["plc"])["plc"]["sfc"]["gn2_purge"]["running"] is True
    sim.write({"PB2": True})


def test_a_sequence_cannot_start_with_the_plc_stopped():
    sim = make_sim()
    refused("rejected", sim.sequence_start, "hotfire")
    refused("unknown_name", sim.sequence_start, "nope")
    refused("rejected", sim.sequence_start, "bangbang_lox")
