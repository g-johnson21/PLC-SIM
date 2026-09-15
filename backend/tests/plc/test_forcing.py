"""Forcing (spec §7.4)."""

import pytest

from .helpers import feed, run_st, var


def test_forced_input_overrides_write_inputs_until_unforce():
    rt = run_st("VAR x : REAL; END_VAR\nx := AI1;")
    feed(rt, AI1=1.0)
    rt.force("AI1", 5.0)
    feed(rt, AI1=2.0)
    assert (var(rt, "x"), rt.read_inputs()["AI1"], rt.forced()) == (5.0, 5.0, {"AI1": 5.0})
    rt.unforce("AI1")
    feed(rt)
    assert (var(rt, "x"), rt.read_inputs()["AI1"], rt.forced()) == (2.0, 2.0, {})


def test_forced_output_wins_at_the_scan_boundary_but_the_program_sees_its_own_write():
    rt = run_st("VAR seen : BOOL; END_VAR\nDO1 := FALSE;\nseen := DO1;")
    rt.force("DO1", True)
    result = feed(rt)
    assert (rt.read_outputs()["DO1"], var(rt, "seen")) == (True, False)
    assert result.outputs_written == {"DO1"}


def test_forcing_an_output_is_not_a_program_write():
    rt = run_st("VAR n : INT; END_VAR\nn := n + 1;")
    rt.force("DO2", True)
    assert feed(rt).outputs_written == frozenset()
    assert rt.read_outputs()["DO2"] is True


def test_globals_and_program_locals_can_be_forced():
    rt = run_st("VAR_GLOBAL g : INT; END_VAR\nVAR n : INT; m : INT; END_VAR\n"
                "g := g + 1;\nn := n + 1;\nm := n;")
    rt.force("G", 100)
    rt.force("P.N", 7)
    feed(rt)
    assert (rt.globals()["g"], var(rt, "n"), var(rt, "m")) == (100, 7, 8)
    assert rt.forced() == {"g": 100, "p.n": 7}


@pytest.mark.parametrize("name", ["SYS_ABORT", "SYS_TIME", "p.t", "nope", "p.nope", "other.n"])
def test_system_variables_fb_instances_and_unknown_names_cannot_be_forced(name):
    rt = run_st("VAR t : TON; n : INT; END_VAR\nt(IN := TRUE, PT := T#1s);\nn := 1;")
    with pytest.raises(ValueError):
        rt.force(name, True)
    assert rt.forced() == {}


def test_reset_keeps_and_reapplies_forces():
    rt = run_st("VAR n : INT; END_VAR\nn := n + 1;\nDO1 := FALSE;")
    rt.force("DO1", True)
    rt.force("p.n", 40)
    feed(rt)
    rt.reset()
    assert rt.forced() == {"DO1": True, "p.n": 40}
    feed(rt)
    assert (rt.read_outputs()["DO1"], var(rt, "n")) == (True, 40)
