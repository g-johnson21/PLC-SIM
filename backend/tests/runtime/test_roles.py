"""docs/runtime.md §1 "Roles" and decisions.md D10."""

from __future__ import annotations

from dataclasses import replace

import pytest

from draco_sim.runtime import ProgramSource, SimStateError

from .helpers import EXAMPLE_ROLES, enabled, example, make_sim, outputs, refused, texts


def roles(sim):
    return {p["name"]: p["role"] for p in sim.programs()}


def test_example_roles_match_what_their_code_infers():
    sim = make_sim()
    assert roles(sim) == sim.inferred_roles() == EXAMPLE_ROLES
    assert not any("declares role" in t for t in texts(sim, "warn"))


def test_programs_are_installed_monitor_then_sequence_then_regulation():
    sim = make_sim()
    assert [p["name"] for p in sim.programs()] == [
        "abort_monitor", "hotfire", "gn2_purge", "bangbang_lox", "bangbang_fuel"]


def test_a_program_without_a_role_gets_the_inferred_one():
    sim = make_sim(examples=False)
    sim.load_programs([replace(s, role=None) for s in sim.example_sources()])
    assert roles(sim) == EXAMPLE_ROLES
    loaded = texts(sim, "info")[-1]
    assert "bangbang_lox [regulation, inferred]" in loaded and "hotfire [sequence, inferred]" in loaded


@pytest.mark.parametrize("name, role", [("hotfire", "regulation"), ("bangbang_lox", "sequence"),
                                        ("bangbang_lox", "monitor"), ("abort_monitor", "sequence")])
def test_a_role_that_contradicts_the_code_rejects_the_whole_load(name, role):
    sim = make_sim(examples=False)
    sources = [replace(s, role=role) if s.name == name else s for s in sim.example_sources()]
    exc = refused("compile_error", sim.load_programs, sources)
    results = {r["name"]: r for r in exc.details["results"]}
    assert results[name]["ok"] is False
    assert [e["path"] for e in results[name]["errors"]] == ["/role"]
    assert all(r["ok"] for n, r in results.items() if n != name)
    assert sim.programs() == []


def test_other_does_not_exempt_a_valve_writing_program_from_the_abort():
    sim = make_sim(examples=False)
    sim.load_programs([replace(example(sim, "bangbang_lox"), role="other")])
    sim.plc_run()
    sim.write({"hmi.bb.lox.enable": True})
    sim.run_scans(3)
    sim.abort()
    sim.step()
    assert enabled(sim)["bangbang_lox"] is False and outputs(sim)["S1"] is False
    assert any("regulation off: bangbang_lox [other]" in t for t in texts(sim, "abort"))


def test_a_program_labelled_regulation_is_switched_off_even_if_it_drives_no_valve():
    sim = make_sim(examples=False)
    sim.load_programs([replace(example(sim, "abort_monitor"), role="regulation")])
    sim.plc_run()
    sim.step()
    sim.abort()
    sim.step()
    assert enabled(sim)["abort_monitor"] is False


def test_a_monitor_keeps_scanning_through_an_abort():
    sim = make_sim()
    sim.plc_run()
    sim.abort()
    sim.step()
    assert enabled(sim)["abort_monitor"] is True
    assert (enabled(sim)["bangbang_lox"], enabled(sim)["bangbang_fuel"]) == (False, False)


def test_programs_cannot_be_loaded_while_the_plc_runs():
    sim = make_sim()
    sim.plc_run()
    exc = refused("plc_running", sim.load_programs, sim.example_sources())
    assert isinstance(exc, SimStateError)


def test_a_compile_error_loads_nothing():
    sim = make_sim(examples=False)
    bad = ProgramSource("bad", "ST", "PROGRAM bad\nPB2 := ;\nEND_PROGRAM\n")
    exc = refused("compile_error", sim.load_programs, [bad, example(sim, "bangbang_lox")])
    results = {r["name"]: r for r in exc.details["results"]}
    assert results["bad"]["ok"] is False and results["bad"]["errors"][0]["line"] == 2
    assert results["bangbang_lox"]["ok"] is True
    assert sim.programs() == []
