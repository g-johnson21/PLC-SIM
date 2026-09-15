"""docs/runtime.md §4-§5 and §7: reads, writes, snapshots, determinism, the pacer."""

from __future__ import annotations

import pytest

from draco_sim.runtime import Pacer, SimConfig, SimRejected, Simulator
from draco_sim.runtime.demo import INITIAL

from .helpers import as_json, hmi, latched, make_sim, refused


def test_write_is_atomic():
    sim = make_sim()
    sim.plc_run()
    exc = refused("unknown_name", sim.write,
                  {"PB2": True, "hmi.bb.lox.setpoint": 700.0, "no.such.name": 1})
    assert exc.details == {"names": ["no.such.name"]}
    refused("read_only", sim.write, {"hmi.bb.lox.setpoint": 700.0, "PT1": 1.0})
    assert hmi(sim)["manual"] == {} and hmi(sim)["bb"]["lox"]["setpoint"] == 904.0


@pytest.mark.parametrize("name, code", [
    ("PT1", "read_only"), ("hmi.bb.lox.state", "read_only"), ("plant.lox_mass_kg", "read_only"),
    ("raw.anything", "read_only"), ("hmi.manual_allowed", "read_only"),
    ("abort.thresholds", "rejected"), ("abort.latched", "unknown_name")])
def test_names_that_cannot_be_written(name, code):
    sim = make_sim()
    sim.plc_run()
    refused(code, sim.write, {name: 1})


def test_unknown_reads_are_listed():
    sim = make_sim()
    exc = refused("unknown_name", sim.read, ["PT1", "nope", "plc.globals.nope"])
    assert exc.details == {"names": ["nope", "plc.globals.nope"]}


def test_every_documented_namespace_reads():
    sim = make_sim()
    sim.run_scans(2)
    raw = next(iter(sim.snapshot(["raw"])["raw"]))
    names = ["PT1", "PB2", "plc.globals.setpoint", "hmi.abort", "hmi.bb.fuel.enable",
             "hmi.bb.lox.state", "hmi.manual_allowed", "hmi.active_sequence", "abort.thresholds",
             "abort.tripped", "abort.latched", "abort.waiting_on", "plant.node_p_psig.lox_ullage",
             f"raw.{raw}"]
    values = sim.read(names)
    assert list(values) == names
    assert (values["PB2"], values["hmi.bb.lox.state"], values["abort.waiting_on"]) == (False, "OFF", [])


def test_reading_an_output_returns_the_arbitrated_value():
    sim = make_sim()
    sim.plc_run()
    sim.write({"PB2": True})
    sim.step()
    assert sim.read(["PB2"])["PB2"] is True and sim.plc.read_outputs()["PB2"] is False


def test_the_abort_group_cannot_be_filtered_away():
    sim = make_sim()
    snap = sim.snapshot(["inputs"])
    assert set(snap) == {"t", "scan", "scan_hz", "paused", "inputs", "abort"}
    assert set(snap["abort"]) == {"thresholds", "tripped", "latched", "waiting_on"}


def test_a_full_snapshot_has_every_group_and_the_additive_fields():
    sim = make_sim()
    snap = sim.snapshot()
    assert set(snap) == {"t", "scan", "scan_hz", "paused", "inputs", "outputs", "plc", "hmi",
                         "abort", "plant", "raw"}
    assert (len(snap["inputs"]), len(snap["outputs"])) == (32, 14)
    assert {"enabled", "running", "abort_active", "faults", "halted", "sfc", "globals",
            "forced"} <= set(snap["plc"])
    assert set(snap["hmi"]) == {"abort", "bb", "manual_allowed", "active_sequence", "manual"}
    assert set(snap["hmi"]["bb"]["fuel"]) == {"setpoint", "deadband", "enable", "state", "abort_off"}


def test_bang_bang_entries_are_mirrored_into_the_declared_globals_and_survive_plc_reset():
    sim = make_sim()
    sim.write({"hmi.bb.lox.setpoint": 700.0, "hmi.bb.fuel.deadband": 20.0,
               "hmi.bb.fuel.enable": True})
    names = ["plc.globals.setpoint", "plc.globals.deadband_fuel", "plc.globals.bb_fuel_enable"]
    assert sim.read(names) == dict(zip(names, [700.0, 20.0, True]))
    sim.plc_reset()
    assert sim.read(names) == dict(zip(names, [700.0, 20.0, False]))


def _script(sim, observe):
    def run(seconds):
        for _ in range(round(seconds * sim.scan_hz)):
            sim.step()
            observe(sim)

    sim.plc_run()
    sim.write({"PB1": False, "PB3": False, "hmi.bb.lox.enable": True, "hmi.bb.fuel.enable": True})
    run(3.0)
    sim.sequence_start("hotfire")
    run(1.0)
    sim.abort()
    run(6.0)


def _observe(sim):
    sim.snapshot()
    sim.waiting_on()
    try:
        sim.abort_clear()
    except SimRejected:
        pass


def test_the_same_calls_give_identical_snapshots_and_events_and_reads_do_not_perturb():
    runs = []
    for observe in (lambda sim: None, _observe):
        sim = Simulator(SimConfig(scan_hz=50))
        sim.load_examples()
        sim.reset_plant(INITIAL)
        _script(sim, observe)
        assert not latched(sim)
        runs.append((as_json(sim.snapshot()), [e.as_dict() for e in sim.events]))
    assert runs[0] == runs[1]


def test_realtime_pacing_converts_wall_time_to_scans_and_drops_a_backlog():
    sim = make_sim()
    pacer = Pacer(sim, realtime=True)
    assert pacer.due_scans(100.0) == 0
    assert pacer.due_scans(100.021) == 1
    assert pacer.due_scans(100.121) == 5
    assert pacer.due_scans(101.121) == 10 and pacer.dropped_scans == 40
    pacer.speed = 2.0
    assert pacer.due_scans(101.222) == 10
    pacer.speed = 1.0
    sim.pause()
    assert pacer.due_scans(105.0) == 0
    sim.resume()
    assert pacer.due_scans(105.021) == 1
    assert Pacer(sim, realtime=False, batch=50).due_scans(0.0) == 50
