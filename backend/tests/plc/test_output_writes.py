"""Static write sets (CompiledProgram.output_writes / abort_writes, spec §7.1) and the per-scan
ScanResult.outputs_written (§7.3)."""

from .helpers import (action, chart, coil, contact, decl, element, feed, lad, ld, run_st, runtime,
                      series, sfc, st, step, trans)


def test_st_output_writes_holds_every_output_assigned_on_any_branch():
    prog = st("VAR x : BOOL; END_VAR\n"
              "IF FALSE THEN do1 := TRUE; ELSE x := DO2; END_IF\n"
              "CASE CNT1 OF 99: AO1 := AI1; END_CASE\n"
              "x := DO3 OR DI1;")
    assert isinstance(prog.output_writes, frozenset)
    assert (prog.output_writes, prog.abort_writes) == ({"DO1", "AO1"}, frozenset())


def test_programs_that_drive_no_output_have_empty_write_sets():
    progs = [st("VAR n : INT; END_VAR\nn := n + 1;"),
             lad(ld(series(contact("DO1"), coil("b")), vars=[decl("b", "BOOL")])),
             chart(sfc([step("A", action("n := n + 1;"), initial=True)], [], vars=[decl("n", "INT")]))]
    assert [(p.output_writes, p.abort_writes) for p in progs] == [(frozenset(), frozenset())] * 3


def test_ladder_output_writes_covers_coils_and_block_destinations():
    prog = lad(ld(
        series(contact("DO4"), coil("DO1"), coil("DO2", "SET")),
        series(element("compare", op="GT", a="AO1", b="AI1"), element("move", src="AI1", dst="AO1")),
        series(contact("DI1"), element("math", op="ADD", a="CNT1", b=1, dst="CNT1")),
        series(contact("DI2"), element("timer", "r3.t", fb="TON", pt="T#1s", q="DO3")),
    ))
    assert (prog.output_writes, prog.abort_writes) == ({"DO1", "DO2", "AO1", "CNT1", "DO3"}, frozenset())


def test_abort_writes_is_restricted_to_the_abort_chain():
    prog = chart(sfc(
        [step("IDLE", initial=True),
         step("RUN", action("DO1 := TRUE; DO2 := TRUE;", "S", name="V")),
         step("ABORT", action("DO2 := FALSE;", "P")),
         step("SAFE", action("DO3 := DO4;"))],
        [trans("IDLE", "RUN", "DO4"), trans("RUN", "ABORT", "AO1 > 1.0"), trans("ABORT", "SAFE")],
        abort_step="ABORT"))
    assert (prog.output_writes, prog.abort_writes) == ({"DO1", "DO2", "DO3"}, {"DO2", "DO3"})
    plain = chart(sfc([step("A", action("DO1 := TRUE;"), initial=True)], []))
    assert (plain.output_writes, plain.abort_writes) == ({"DO1"}, frozenset())


def test_outputs_written_counts_assignments_not_changes():
    rt = run_st("DO1 := FALSE;\nIF AI1 > 10.0 THEN DO2 := TRUE; ELSIF AI1 < 5.0 THEN DO2 := FALSE; END_IF")
    got = []
    for ai1 in (7.0, 12.0, 7.0, 3.0):
        result = feed(rt, AI1=ai1)
        got.append((set(result.outputs_written), set(result.outputs_changed)))
    assert got == [({"DO1"}, set()), ({"DO1", "DO2"}, {"DO2"}), ({"DO1"}, set()),
                   ({"DO1", "DO2"}, {"DO2"})]


def test_set_coils_and_sfc_pulses_write_only_on_the_scans_they_act():
    rt = runtime(lad(ld(series(contact("DI1"), coil("DO1", "SET")))),
                 chart(sfc([step("A", initial=True), step("B", action("DO2 := TRUE;", "S", name="V"))],
                           [trans("A", "B", "DI2")])))
    rt.start_sfc("chart")
    got = []
    for di1, di2 in [(False, False), (True, False), (False, True), (False, True)]:
        got.append(set(feed(rt, DI1=di1, DI2=di2).outputs_written))
    assert got == [set(), {"DO1"}, {"DO2"}, set()]


def test_a_disabled_program_writes_nothing():
    rt = run_st("DO1 := TRUE;")
    rt.set_program_enabled("p", False)
    assert feed(rt).outputs_written == frozenset()
