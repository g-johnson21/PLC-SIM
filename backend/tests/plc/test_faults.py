"""Runtime faults (spec §7.5): halt, rollback, outputs_written and clear_faults."""

import pytest

from .helpers import (action, chart, contact, decl, element, feed, lad, ld, run_st, runtime,
                      scan_n, series, sfc, st, step, trans, var)

DIVIDE = {
    "INT": "VAR n : INT; z : INT; q : INT; END_VAR\nn := n + 1;\nDO2 := DI1;\n"
           "IF DI1 THEN q := n / z; END_IF",
    "REAL": "VAR n : INT; z : REAL; q : REAL; END_VAR\nn := n + 1;\nDO2 := DI1;\n"
            "IF DI1 THEN q := AI1 / z; END_IF",
}

LOOPS = {
    "WHILE": "n := 0; WHILE n < {count} DO n := n + 1; END_WHILE",
    "FOR": "n := 0; FOR i := 1 TO {count} DO n := n + 1; END_FOR",
    "REPEAT": "n := 0; REPEAT n := n + 1; UNTIL n >= {count} END_REPEAT",
}


@pytest.mark.parametrize("kind", sorted(DIVIDE))
def test_division_by_zero_halts_the_program_and_rolls_back_its_scan(kind):
    rt = run_st(DIVIDE[kind])
    assert feed(rt).faults == []
    [fault] = feed(rt, DI1=True).faults
    assert (fault.program, fault.kind, fault.line, fault.scan_index) == ("p", "div_zero", 4, 2)
    assert rt.faults() == [fault] and rt.halted_programs() == ["p"]
    assert (var(rt, "n"), rt.read_outputs()["DO2"]) == (1, False)
    assert feed(rt).faults == [] and var(rt, "n") == 1


def test_other_programs_still_run_and_the_faulting_writes_are_not_reported():
    first = st("DO2 := TRUE;", name="first")
    bad = st("VAR q : INT; z : INT; END_VAR\nDO1 := DI1;\nDO2 := FALSE;\nIF DI1 THEN q := 1 / z; END_IF",
             name="bad")
    last = st("VAR n : INT; END_VAR\nn := n + 1;\nDO3 := TRUE;", name="last")
    rt = runtime(first, bad, last)
    assert feed(rt).outputs_written == {"DO1", "DO2", "DO3"}
    result = feed(rt, DI1=True)
    assert [f.program for f in result.faults] == ["bad"]
    assert result.outputs_written == {"DO2", "DO3"}
    out = rt.read_outputs()
    assert (out["DO1"], out["DO2"], out["DO3"], var(rt, "n", "last")) == (False, True, True, 2)


AT_THE_CAP = pytest.mark.xfail(strict=True, reason=(
    "engine bug: For/While/Repeat in plc/nodes.py do `n += 1; if n >= cap` with cap 10000, so the "
    "10 000th iteration already faults; spec §4.2 and §7.5 fault only when a loop exceeds 10 000"))


@pytest.mark.parametrize("loop", sorted(LOOPS))
@pytest.mark.parametrize("count,faults", [pytest.param(10_000, False, marks=AT_THE_CAP), (10_001, True)])
def test_each_loop_is_capped_at_ten_thousand_iterations(loop, count, faults):
    rt = run_st("VAR n : INT; i : INT; END_VAR\n" + LOOPS[loop].format(count=count))
    assert [f.kind for f in rt.scan(0.01).faults] == (["loop"] if faults else [])
    assert var(rt, "n") == (0 if faults else count)


def test_the_loop_cap_counts_each_loop_separately():
    rt = run_st("VAR n : INT; i : INT; END_VAR\nn := 0;\n"
                "FOR i := 1 TO 6000 DO n := n + 1; END_FOR\nFOR i := 1 TO 6000 DO n := n + 1; END_FOR")
    assert rt.scan(0.01).faults == [] and var(rt, "n") == 12000


def test_clear_faults_restarts_from_the_state_before_the_faulting_scan():
    rt = run_st(DIVIDE["INT"])
    feed(rt)
    feed(rt, DI1=True)
    scan_n(rt, 3)
    assert var(rt, "n") == 1
    rt.write_inputs({"DI1": False})
    rt.clear_faults()
    assert rt.faults() == [] and rt.halted_programs() == []
    assert feed(rt).faults == [] and var(rt, "n") == 2
    assert [f.kind for f in feed(rt, DI1=True).faults] == ["div_zero"]


def test_rollback_restores_globals_and_function_block_state():
    rt = run_st("VAR_GLOBAL g : INT; END_VAR\nVAR t : TON; z : INT; q : INT; END_VAR\n"
                "g := g + 1;\nt(IN := TRUE, PT := T#1s);\nIF DI1 THEN q := 1 / z; END_IF")
    scan_n(rt, 3)
    assert len(feed(rt, DI1=True).faults) == 1
    assert (rt.globals()["g"], var(rt, "t.ET")) == (3, pytest.approx(0.02, abs=1e-9))


def test_a_faulting_chart_rolls_back_its_transition_and_stored_actions():
    rt = runtime(chart(sfc(
        [step("A", initial=True), step("B", action("DO1 := TRUE;\nq := 1 / z;", "S", name="V1"))],
        [trans("A", "B", "DI1")], vars=[decl("q", "INT"), decl("z", "INT")])))
    rt.start_sfc("chart")
    feed(rt)
    [fault] = feed(rt, DI1=True).faults
    state = rt.sfc_state()["chart"]
    assert (fault.program, fault.kind) == ("chart", "div_zero")
    assert (state["active_steps"], state["stored_actions"], rt.read_outputs()["DO1"]) == (["A"], [], False)


def test_ladder_division_by_zero_faults_only_while_powered():
    rt = runtime(lad(ld(series(contact("DI1"),
                               element("math", "r0.div", op="DIV", a="AI1", b="AI2", dst="AO1")))))
    assert feed(rt, AI1=1.0, AI2=0.0).faults == []
    [fault] = feed(rt, DI1=True).faults
    assert (fault.program, fault.kind) == ("lad", "div_zero")
