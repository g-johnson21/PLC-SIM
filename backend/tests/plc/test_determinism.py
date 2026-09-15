"""Determinism and simulated time (spec §1.6): identical runtimes, exact time, reset replay."""

import pytest

from .helpers import (action, chart, coil, contact, decl, element, lad, ld, run_st, runtime,
                      series, sfc, st, step, trans, var)

DT_CYCLE = [0.01, 1 / 30, 0.005, 0.02, 1 / 60, 0.0125]

ST_SRC = """VAR t : TON; f : TOF; c : CTU; acc : REAL; now : REAL; END_VAR
t(IN := DI1, PT := T#70ms);
f(IN := t.Q, PT := T#45ms);
c(CU := f.Q, R := DI2, PV := 5);
acc := acc + AI1 * SYS_SCAN_TIME - acc * 0.05;
now := SYS_TIME;
AO1 := acc;
DO1 := f.Q;
CNT1 := c.CV;
"""


def build():
    ladder = lad(ld(
        series(contact("DI1", "P", id="r0.p"), element("timer", "r0.t", fb="TP", pt="T#30ms"),
               coil("DO2")),
        series(contact("DI2", "NC"), element("math", "r1.m", op="MUL", a="AI2", b=1.5, dst="k")),
        vars=[decl("k", "REAL")]))
    seq = chart(sfc(
        [step("S0", initial=True),
         step("S1", action("DO3 := TRUE;", "P")),
         step("S2", action("DO3 := FALSE;", "P0"), action("DO4 := NOT DO4;"))],
        [trans("S0", "S1", "DI1"), trans("S1", "S2", "S1.T >= T#40ms"),
         trans("S2", "S0", "S2.T >= T#25ms")],
        autostart=True))
    return runtime(st(ST_SRC), ladder, seq)


def history(rt, scans=300, abort_at=100):
    records, changes = [], 0
    for k in range(scans):
        if k == abort_at:
            rt.trigger_abort()
        rt.write_inputs({"DI1": k % 23 < 11, "DI2": k % 31 == 0,
                         "AI1": (k * 37 % 101) / 7.0, "AI2": (k * 13 % 17) - 8.0})
        r = rt.scan(DT_CYCLE[k % len(DT_CYCLE)])
        changes += bool(r.outputs_changed)
        records.append(repr((r.scan_index, r.dt_s, r.sim_time_s, r.faults,
                             sorted(r.outputs_changed.items()), sorted(r.outputs_written),
                             sorted(rt.read_outputs().items()), rt.variables(), rt.sfc_state())))
    return records, changes


def test_two_runtimes_fed_the_same_inputs_and_dts_are_bit_identical():
    first, changes = history(build())
    assert changes > 20
    assert history(build())[0] == first


def test_reset_returns_to_construction_state_and_replays_identically():
    rt = build()
    first, _ = history(rt, scans=150)
    rt.reset()
    assert history(rt, scans=150)[0] == first


@pytest.mark.parametrize("dt,scans,total", [(0.01, 50, 0.5), (1 / 30, 30, 1.0)])
def test_simulated_time_uses_compensated_summation(dt, scans, total):
    rt = run_st("VAR start : REAL; first : BOOL; END_VAR\nstart := SYS_TIME;\nfirst := SYS_FIRST_SCAN;")
    firsts, previous = [], 0.0
    for _ in range(scans):
        result = rt.scan(dt)
        assert var(rt, "start") == previous
        previous = result.sim_time_s
        firsts.append(var(rt, "first"))
    assert (result.sim_time_s, rt.sim_time_s, rt.scan_index) == (total, total, scans)
    assert firsts == [True] + [False] * (scans - 1)
