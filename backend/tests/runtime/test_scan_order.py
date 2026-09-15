"""docs/runtime.md §1: the scan order is a safety rule."""

from __future__ import annotations

from .helpers import (active_steps, hmi, latched, make_sim, MONITOR_ENABLE, normally_open,
                      open_valves, outputs, refused, texts, trip_row)


def test_a_trip_latches_before_the_sequencer_runs():
    sim = make_sim()
    sim.plc_run()
    sim.run_scans(2)
    sim.abort_config([trip_row(sim, "PT1")])
    sim.sequence_start("hotfire")
    sim.step()
    assert latched(sim)
    assert active_steps(sim, "hotfire") == ["ABORT"]
    assert not any("OPEN_LOX_MAIN" in t for t in texts(sim, "sequence"))
    assert outputs(sim)["PB2"] is False


def test_thresholds_read_the_cards_while_programs_see_the_force():
    sim = make_sim()
    sim.plc_run()
    sim.run_scans(2)
    row = trip_row(sim, "PT1")
    sim.force("PT1", 0.0)
    sim.step()
    assert sim.read(["PT1"])["PT1"] == 0.0
    sim.abort_config([row])
    sim.step()
    tripped = sim.read(["abort.tripped"])["abort.tripped"]
    assert latched(sim)
    assert (tripped["source"], tripped["tag"], tripped["threshold"]) == ("threshold", "PT1", row.value)
    assert tripped["value"] > row.value
    assert "PT1" in sim.snapshot(["plc"])["plc"]["forced"]


def test_a_program_request_latches_on_the_scan_after_it_is_computed():
    sim = make_sim()
    sim.plc_run()
    sim.step()
    sim.write({MONITOR_ENABLE: True})
    sim.step()
    assert sim.read(["plc.globals.auto_abort_request"])["plc.globals.auto_abort_request"] is True
    assert not latched(sim)
    sim.step()
    assert latched(sim)
    assert sim.read(["abort.tripped"])["abort.tripped"] == {
        "tag": "plc.globals.auto_abort_request", "value": True, "threshold": None,
        "t": sim.t, "source": "program"}


def test_the_manual_abort_bit_is_consumed_by_the_latch():
    sim = make_sim()
    sim.plc_run()
    sim.step()
    sim.abort()
    assert hmi(sim)["abort"] is True
    sim.step()
    assert latched(sim) and hmi(sim)["abort"] is False
    assert sim.read(["abort.tripped"])["abort.tripped"] == {
        "tag": "hmi.abort", "value": True, "threshold": None, "t": sim.t, "source": "manual"}


def test_a_stopped_plc_evaluates_no_trip_and_holds_every_coil_safe():
    sim = make_sim()
    sim.run_scans(1)
    sim.abort_config([trip_row(sim, "PT1")])
    sim.run_for(0.5)
    assert not latched(sim) and sim.read(["abort.tripped"])["abort.tripped"] is None
    assert open_valves(sim) == normally_open(sim)
    assert sim.scan == 26 and abs(sim.t - 0.52) < 1e-12
    sim.plc_run()
    sim.step()
    assert latched(sim)


def test_events_carry_the_scan_that_raised_them_and_its_end_time():
    sim = make_sim()
    sim.plc_run()
    sim.run_scans(3)
    sim.abort()
    sim.step()
    [event] = [e for e in sim.events if e.text.startswith("ABORT LATCHED")]
    assert (event.scan, event.t, event.level, event.source) == (sim.scan, sim.t, "abort", "plc")


def test_scan_rate_changes_keep_simulated_time_continuous():
    sim = make_sim()
    sim.run_scans(10)
    t = sim.t
    sim.set_scan_hz(30)
    sim.run_scans(3)
    assert abs(sim.t - (t + 0.1)) < 1e-12
    refused("bad_request", sim.set_scan_hz, 0)
