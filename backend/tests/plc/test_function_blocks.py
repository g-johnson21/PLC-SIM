"""Standard function blocks (spec §2) and the ET / step .T scan-count convention."""

import pytest

from .helpers import (DTS, action, active, bits, chart, feed, run_st, runtime, sfc, step, trans,
                      var)

# (dt, scan on which a 500 ms delay completes, the starting scan counted as the first)
DELAY_SCANS = [(0.01, 51), (1 / 30, 16)]


def et_on(k, dt):
    """ET (or step .T) on the k-th scan of a running timer."""
    return pytest.approx((k - 1) * dt, abs=1e-9)


def trace(rt, fields, dt=0.01, **series):
    """One scan per element of the input series; the named FB fields after each scan."""
    out = []
    for values in zip(*series.values()):
        rt.write_inputs(dict(zip(series, values)))
        rt.scan(dt)
        out.append(tuple(var(rt, f) for f in fields) if isinstance(fields, tuple) else var(rt, fields))
    return out


@pytest.mark.parametrize("dt,q_scan", DELAY_SCANS)
def test_ton_sets_q_on_the_scan_et_reaches_pt(dt, q_scan):
    rt = run_st("VAR t : TON; END_VAR\nt(IN := DI1, PT := T#500ms);")
    feed(rt, dt, DI1=False)
    rt.write_inputs({"DI1": True})
    for k in range(1, q_scan):
        rt.scan(dt)
        assert (var(rt, "t.Q"), var(rt, "t.ET")) == (False, et_on(k, dt))
    rt.scan(dt)
    assert (var(rt, "t.Q"), var(rt, "t.ET")) == (True, pytest.approx(0.5, abs=1e-9))
    feed(rt, dt, DI1=False)
    assert (var(rt, "t.Q"), var(rt, "t.ET")) == (False, 0.0)


@pytest.mark.parametrize("dt,drop_scan", DELAY_SCANS)
def test_tof_holds_q_for_pt_after_in_falls(dt, drop_scan):
    rt = run_st("VAR t : TOF; END_VAR\nt(IN := DI1, PT := T#500ms);")
    feed(rt, dt, DI1=False)
    assert var(rt, "t.Q") is False
    feed(rt, dt, DI1=True)
    assert (var(rt, "t.Q"), var(rt, "t.ET")) == (True, 0.0)
    rt.write_inputs({"DI1": False})
    for k in range(1, drop_scan):
        rt.scan(dt)
        assert (var(rt, "t.Q"), var(rt, "t.ET")) == (True, et_on(k, dt))
    rt.scan(dt)
    assert var(rt, "t.Q") is False


def test_tof_restarts_when_in_returns_during_the_delay():
    rt = run_st("VAR t : TOF; END_VAR\nt(IN := DI1, PT := T#50ms);")
    q = trace(rt, "t.Q", DI1=bits("1000" "1" "000000"))
    assert q == [True] * 10 + [False]


@pytest.mark.parametrize("dt", DTS)
def test_tp_pulse_lasts_pt_and_ignores_retriggering(dt):
    rt = run_st("VAR t : TP; END_VAR\nt(IN := DI1, PT := T#500ms);")
    n = round(0.5 / dt)
    clk = [True, False, True, True] + [False] * (n + 1) + [True]
    assert trace(rt, "t.Q", dt, DI1=clk) == [True] * n + [False] * 5 + [True]


def test_zero_pt_fires_ton_at_once_and_suppresses_tp_and_tof():
    rt = run_st("VAR on : TON; off : TOF; p : TP; END_VAR\n"
                "on(IN := DI1, PT := T#0s);\noff(IN := DI1, PT := T#0s);\np(IN := DI1, PT := T#0s);")
    got = trace(rt, ("on.Q", "off.Q", "p.Q"), DI1=bits("10"))
    assert got == [(True, True, False), (False, False, False)]


def test_ctu_counts_rising_edges_and_reset_dominates():
    rt = run_st("VAR c : CTU; END_VAR\nc(CU := DI1, R := DI2, PV := 3);")
    got = trace(rt, ("c.CV", "c.Q"), DI1=bits("011010101"), DI2=bits("000000011"))
    assert got == [(0, False), (1, False), (1, False), (1, False), (2, False), (2, False),
                   (3, True), (0, False), (0, False)]


def test_ctd_loads_pv_and_counts_down_to_q():
    rt = run_st("VAR c : CTD; END_VAR\nc(CD := DI1, LD := DI2, PV := 2);")
    got = trace(rt, ("c.CV", "c.Q"), DI1=bits("0010110"), DI2=bits("0100000"))
    assert got == [(0, True), (2, False), (1, False), (1, False), (0, True), (0, True), (0, True)]


def test_ctud_reset_beats_load_and_simultaneous_edges_cancel():
    rt = run_st("VAR c : CTUD; END_VAR\nc(CU := DI1, CD := DI2, R := DI3, LD := DI4, PV := 2);")
    got = trace(rt, ("c.CV", "c.QU", "c.QD"),
                DI1=bits("01010100000"), DI2=bits("00000101000"),
                DI3=bits("00000000101"), DI4=bits("00000000110"))
    assert got == [(0, False, True), (1, False, False), (1, False, False), (2, True, False),
                   (2, True, False), (2, True, False), (2, True, False), (1, False, False),
                   (0, False, True), (2, True, False), (0, False, True)]


def test_r_trig_and_f_trig_pulse_for_one_scan_without_a_power_up_edge():
    rt = run_st("VAR r : R_TRIG; f : F_TRIG; END_VAR\nr(CLK := DI1);\nf(CLK := DI1);")
    got = trace(rt, ("r.Q", "f.Q"), DI1=bits("0110010"))
    assert got == [(False, False), (True, False), (False, False), (False, True), (False, False),
                   (True, False), (False, True)]


@pytest.mark.parametrize("fb,set_in,reset_in,both", [("SR", "S1", "R", True), ("RS", "S", "R1", False)])
def test_sr_is_set_dominant_and_rs_is_reset_dominant(fb, set_in, reset_in, both):
    rt = run_st(f"VAR l : {fb}; q : BOOL; END_VAR\nl({set_in} := DI1, {reset_in} := DI2);\nq := l.Q;")
    got = trace(rt, ("l.Q1", "q"), DI1=bits("100010"), DI2=bits("001011"))
    assert [q1 for q1, _ in got] == [True, True, False, False, both, False]
    assert all(q1 == alias for q1, alias in got)


@pytest.mark.parametrize("dt,second_scan", DELAY_SCANS)
def test_step_t_follows_the_timer_convention(dt, second_scan):
    rt = runtime(chart(sfc(
        [step("ARMED", initial=True),
         step("LEAD", action("DO1 := TRUE;", "S", name="V1")),
         step("MAIN", action("DO2 := TRUE;", "S", name="V2"))],
        [trans("ARMED", "LEAD"), trans("LEAD", "MAIN", "LEAD.T >= T#500ms")])))
    rt.start_sfc("chart")
    rt.scan(dt)
    assert active(rt) == ["LEAD"] and rt.read_outputs()["DO1"] is True
    for k in range(2, second_scan):
        rt.scan(dt)
        assert rt.sfc_state()["chart"]["step_times"] == {"LEAD": et_on(k, dt)}
        assert var(rt, "LEAD.T", "chart") == et_on(k, dt) and rt.read_outputs()["DO2"] is False
    rt.scan(dt)
    assert active(rt) == ["MAIN"] and rt.read_outputs()["DO2"] is True
