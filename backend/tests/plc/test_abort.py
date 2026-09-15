"""Abort model (spec §6.4): latch, safing chain, gated start_sfc, clear_abort and reset."""

import pytest

from draco_sim.plc import PlcStateError

from .helpers import action, active, chart, decl, feed, runtime, scan_n, sfc, st, step, trans, var


def seq_chart():
    return chart(sfc(
        [step("IDLE", initial=True),
         step("RUN1", action("DO1 := TRUE;", "P"), action("DO4 := TRUE;", "P0"),
              action("IF AI1 > 0.5 THEN x := 1 / zero; END_IF")),
         step("RUN2", action("DO2 := TRUE;", "P")),
         step("ABORT", action("DO1 := FALSE; DO2 := FALSE; DO3 := TRUE;", "P"),
              action("na := na + 1;")),
         step("SAFE", action("DO3 := FALSE;", "P"))],
        [trans("IDLE", "RUN1", "DI1"), trans("RUN1", "RUN2", "DI2"),
         trans("ABORT", "SAFE", "ABORT.T >= T#50ms")],
        vars=[decl("na", "INT"), decl("x", "INT"), decl("zero", "INT")],
        name="seq", abort_step="ABORT"))


def rig(start_aux=False):
    aux = chart(sfc([step("A", initial=True), step("B")], [trans("A", "B", "DI3")], name="aux"))
    watcher = st("VAR n : INT; seen : BOOL; END_VAR\nn := n + 1;\nseen := SYS_ABORT;")
    rt = runtime(seq_chart(), aux, watcher)
    rt.start_sfc("seq")
    if start_aux:
        rt.start_sfc("aux")
    return rt


def test_trigger_latches_at_once_and_applies_at_the_top_of_the_next_scan():
    rt = rig()
    feed(rt, DI1=True)
    rt.trigger_abort()
    assert rt.abort_active() and active(rt, "seq") == ["RUN1"]
    feed(rt)
    state = rt.sfc_state()["seq"]
    assert (state["active_steps"], state["step_times"], state["aborted"]) == (["ABORT"], {"ABORT": 0.0}, True)
    out = rt.read_outputs()
    assert (out["DO1"], out["DO3"], out["DO4"]) == (False, True, False)
    assert var(rt, "seen") is True


@pytest.mark.parametrize("where", ["stopped", "IDLE", "RUN1", "RUN2", "SAFE"])
def test_abort_enters_the_chain_from_any_step(where):
    rt = runtime(seq_chart())
    if where != "stopped":
        rt.start_sfc("seq")
        feed(rt, DI1=where.startswith("RUN"))
        feed(rt, DI2=where == "RUN2")
    if where == "SAFE":
        rt.trigger_abort()
        scan_n(rt, 6)
    assert active(rt, "seq") == ([] if where == "stopped" else [where])
    rt.trigger_abort()
    feed(rt)
    assert active(rt, "seq") == ["ABORT"] and rt.read_outputs()["DO3"] is True


def test_chain_advances_while_normal_transitions_stay_blocked():
    rt = rig()
    feed(rt, DI1=True)
    rt.write_inputs({"DI2": True})
    rt.trigger_abort()
    steps = []
    for _ in range(8):
        feed(rt)
        steps.append(active(rt, "seq"))
    assert steps == [["ABORT"]] * 5 + [["SAFE"]] * 3
    out = rt.read_outputs()
    assert (var(rt, "na", "seq"), out["DO1"], out["DO2"], out["DO3"]) == (5, False, False, False)


@pytest.mark.parametrize("sidelined", ["disabled", "halted"])
def test_abort_reaches_a_disabled_or_halted_chart(sidelined):
    rt = rig()
    feed(rt, DI1=True)
    if sidelined == "disabled":
        rt.set_program_enabled("seq", False)
    else:
        assert [f.kind for f in feed(rt, AI1=1.0).faults] == ["div_zero"]
        assert rt.halted_programs() == ["seq"] and active(rt, "seq") == ["RUN1"]
        rt.write_inputs({"AI1": 0.0})
    rt.write_inputs({"DI2": True})
    rt.trigger_abort()
    feed(rt)
    assert active(rt, "seq") == ["ABORT"]
    rt.set_program_enabled("seq", True)
    rt.clear_faults()
    feed(rt)
    assert active(rt, "seq") == ["ABORT"] and rt.read_outputs()["DO3"] is True


def test_start_sfc_raises_while_latched_and_starts_nothing():
    rt = rig()
    feed(rt, DI1=True)
    rt.trigger_abort()
    with pytest.raises(PlcStateError):
        rt.start_sfc("aux")
    feed(rt)
    for name in ("aux", "seq"):
        with pytest.raises(PlcStateError):
            rt.start_sfc(name)
    rt.stop_sfc("aux")
    feed(rt)
    assert rt.sfc_state()["aux"]["active_steps"] == [] and active(rt, "seq") == ["ABORT"]
    assert not issubclass(PlcStateError, ValueError)


def test_chart_without_abort_step_halts_and_st_programs_keep_scanning():
    rt = rig(start_aux=True)
    feed(rt, DI1=True)
    assert active(rt, "aux") == ["A"]
    rt.trigger_abort()
    scan_n(rt, 3)
    assert (active(rt, "aux"), var(rt, "n"), var(rt, "seen")) == ([], 4, True)


def test_clear_abort_drops_the_latch_and_restarts_nothing():
    rt = rig(start_aux=True)
    feed(rt, DI1=True)
    rt.trigger_abort()
    scan_n(rt, 6)
    before = {name: (s["active_steps"], s["running"]) for name, s in rt.sfc_state().items()}
    assert before["seq"][0] == ["SAFE"] and before["aux"][0] == []
    rt.clear_abort()
    assert not rt.abort_active()
    feed(rt, DI3=True)
    scan_n(rt, 3)
    after = {name: (s["active_steps"], s["running"]) for name, s in rt.sfc_state().items()}
    assert after == before and var(rt, "seen") is False
    rt.start_sfc("aux")
    feed(rt, DI3=False)
    assert active(rt, "aux") == ["A"]


def test_reset_clears_the_latch_and_returns_to_construction_state():
    rt = rig()
    feed(rt, DI1=True)
    rt.trigger_abort()
    feed(rt)
    rt.reset()
    state = rt.sfc_state()["seq"]
    assert not rt.abort_active() and rt.scan_index == 0
    assert (state["running"], state["active_steps"]) == (False, [])
    assert not any(rt.read_outputs().values())
    rt.start_sfc("seq")
    feed(rt, DI1=False)
    assert active(rt, "seq") == ["IDLE"] and var(rt, "seen") is False
