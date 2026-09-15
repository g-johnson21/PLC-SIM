"""SFC evolution rules (spec §6.2) and action qualifiers (§6.3)."""

import pytest

from .helpers import action, active, bits, chart, decl, feed, runtime, sfc, step, trans, var


def started(doc):
    rt = runtime(chart(doc))
    rt.start_sfc("chart")
    return rt


def walk(rt, **series):
    """One scan per element of the input series; the active steps after each scan."""
    out = []
    for values in zip(*series.values()):
        feed(rt, **dict(zip(series, values)))
        out.append(active(rt))
    return out


def cvar(rt, name):
    return var(rt, name, "chart")


@pytest.mark.parametrize("autostart", [False, True])
def test_chart_waits_for_start_sfc_unless_autostart(autostart):
    rt = runtime(chart(sfc([step("A", action("n := n + 1;"), initial=True)], [],
                           vars=[decl("n", "INT")], autostart=autostart)))
    feed(rt)
    state = rt.sfc_state()["chart"]
    assert (state["running"], state["active_steps"]) == (autostart, ["A"] if autostart else [])
    assert cvar(rt, "n") == int(autostart)


def test_sequence_advances_as_conditions_become_true():
    rt = started(sfc([step("A", initial=True), step("B"), step("C")],
                     [trans("A", "B", "DI1"), trans("B", "C", "DI2")]))
    assert walk(rt, DI1=bits("00110"), DI2=bits("01101")) == [["A"], ["A"], ["B"], ["B"], ["C"]]


@pytest.mark.parametrize("reverse", [False, True])
def test_a_step_activated_this_scan_waits_a_scan_before_its_transitions(reverse):
    ts = [trans("A", "B"), trans("B", "C"), trans("C", "D")]
    rt = started(sfc([step(s, initial=s == "A") for s in "ABCD"], ts[::-1] if reverse else ts))
    assert walk(rt, DI1=bits("0000")) == [["B"], ["C"], ["D"], ["D"]]


@pytest.mark.parametrize("di1,di2,reverse,winner", [
    (True, True, False, "B"),
    (True, True, True, "C"),
    (False, True, False, "C"),
    (True, False, True, "B"),
])
def test_alternative_divergence_first_true_transition_in_document_order_wins(di1, di2, reverse,
                                                                             winner):
    ts = [trans("A", "B", "DI1"), trans("A", "C", "DI2")]
    rt = started(sfc([step("A", initial=True), step("B"), step("C")], ts[::-1] if reverse else ts))
    feed(rt, DI1=di1, DI2=di2)
    assert active(rt) == [winner]


def test_simultaneous_divergence_and_convergence():
    rt = started(sfc(
        [step("A", initial=True), step("B1"), step("B2"), step("C1"), step("D")],
        [trans("A", ["B1", "C1"]), trans("B1", "B2", "DI1"), trans(["B2", "C1"], "D")]))
    assert walk(rt, DI1=bits("00101")) == [["B1", "C1"], ["B1", "C1"], ["B2", "C1"], ["D"], ["D"]]


def test_loop_back_to_an_earlier_step_until_the_exit_condition():
    rt = started(sfc(
        [step("A", action("laps := laps + 1;", "P"), initial=True), step("B"), step("DONE")],
        [trans("A", "B"), trans("B", "A", "laps < 3"), trans("B", "DONE", "laps >= 3")],
        vars=[decl("laps", "INT")]))
    assert walk(rt, DI1=bits("0000000")) == [["B"], ["A"], ["B"], ["A"], ["B"], ["DONE"], ["DONE"]]
    assert cvar(rt, "laps") == 3


def test_actions_run_entry_exit_new_entry_then_n_in_step_document_order():
    def log(digit, qualifier="N"):
        return action(f"log := log * 10 + {digit};", qualifier)

    rt = started(sfc(
        [step("A", log(1, "P"), log(2, "P0"), log(9), initial=True),
         step("C", log(5)),
         step("B", log(3, "P"), log(4))],
        [trans("A", ["B", "C"])], vars=[decl("log", "DINT")]))
    feed(rt)
    assert cvar(rt, "log") == 12354
    feed(rt)
    assert cvar(rt, "log") == 1235454


def test_n_runs_on_every_active_scan_including_the_activation_scan():
    rt = started(sfc([step("A", action("na := na + 1;"), initial=True), step("B", action("nb := nb + 1;"))],
                     [trans("A", "B", "DI1")], vars=[decl("na", "INT"), decl("nb", "INT")]))
    counts = []
    for di1 in bits("0010"):
        feed(rt, DI1=di1)
        counts.append((cvar(rt, "na"), cvar(rt, "nb")))
    assert counts == [(1, 0), (2, 0), (2, 1), (2, 2)]


def test_p_runs_once_on_entry_and_p0_once_on_exit():
    rt = started(sfc(
        [step("A", initial=True), step("B", action("p := p + 1;", "P"), action("q := q + 1;", "P0"))],
        [trans("A", "B", "DI1"), trans("B", "A", "DI2")], vars=[decl("p", "INT"), decl("q", "INT")]))
    got = []
    for di1, di2 in zip(bits("100001"), bits("000110")):
        feed(rt, DI1=di1, DI2=di2)
        got.append((active(rt), cvar(rt, "p"), cvar(rt, "q")))
    assert got == [(["B"], 1, 0), (["B"], 1, 0), (["B"], 1, 0), (["A"], 1, 1), (["A"], 1, 1),
                   (["B"], 2, 1)]


def test_s_and_r_pulse_on_entry_and_maintain_the_stored_action_list():
    rt = started(sfc(
        [step("A", initial=True),
         step("OPEN", action("DO1 := TRUE; ns := ns + 1;", "S", name="V1")),
         step("HOLD"),
         step("CLOSE", action("DO1 := FALSE;", "R", name="V1"))],
        [trans("A", "OPEN"), trans("OPEN", "HOLD", "DI1"), trans("HOLD", "CLOSE", "DI2")],
        vars=[decl("ns", "INT")]))
    got = []
    for di1, di2 in zip(bits("0010"), bits("0001")):
        feed(rt, DI1=di1, DI2=di2)
        state = rt.sfc_state()["chart"]
        got.append((state["active_steps"], state["stored_actions"], rt.read_outputs()["DO1"],
                    cvar(rt, "ns")))
    assert got == [(["OPEN"], ["V1"], True, 1), (["OPEN"], ["V1"], True, 1),
                   (["HOLD"], ["V1"], True, 1), (["CLOSE"], [], False, 1)]


@pytest.mark.parametrize("delay", ["T#50ms", 0.05])
def test_d_runs_every_scan_once_step_time_reaches_the_delay(delay):
    rt = started(sfc(
        [step("A", initial=True), step("B", action("nd := nd + 1;", "D", delay=delay)), step("C")],
        [trans("A", "B"), trans("B", "C", "DI1")], vars=[decl("nd", "INT")]))
    counts = []
    for di1 in bits("000000010"):
        feed(rt, DI1=di1)
        counts.append(cvar(rt, "nd"))
    assert counts == [0, 0, 0, 0, 0, 1, 2, 2, 2]
