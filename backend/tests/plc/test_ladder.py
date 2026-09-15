"""Ladder power flow (spec §5.2-5.4) and the text renderer (§5.5)."""

import pytest

from draco_sim.plc import TagSpec, ladder_to_text

from .helpers import (TAGS, bits, coil, contact, decl, element, feed, lad, ld, parallel, runtime,
                      series, var)

BOTH = [(False, False), (False, True), (True, False), (True, True)]


def rig(*logics, vars=()):
    return runtime(lad(ld(*logics, vars=vars)))


def outs(rt, *names):
    image = rt.read_outputs()
    return tuple(image[n] for n in names)


@pytest.mark.parametrize("a,b", BOTH)
def test_series_ands_contacts_and_nc_inverts(a, b):
    rt = rig(series(contact("DI1"), contact("DI2"), coil("DO1")),
             series(contact("DI1"), contact("DI2", "NC"), coil("DO2")))
    feed(rt, DI1=a, DI2=b)
    assert outs(rt, "DO1", "DO2") == (a and b, a and not b)


def test_parallel_ors_branches_and_runs_every_branch():
    rt = rig(series(
        parallel(contact("DI1"),
                 series(contact("DI2"), coil("DO2")),
                 element("counter", "r0.cnt", fb="CTU", pv=100, cu="DI2", cv="CNT1")),
        coil("DO1")))
    got = []
    for a, b in zip(bits("111100"), bits("010110")):
        feed(rt, DI1=a, DI2=b)
        got.append(outs(rt, "DO1", "DO2", "CNT1"))
    assert got == [(True, False, 0), (True, True, 1), (True, False, 1), (True, True, 2),
                   (True, True, 2), (False, False, 2)]


@pytest.mark.parametrize("a,b", BOTH)
def test_coils_pass_power_to_what_follows_them(a, b):
    rt = rig(series(contact("DI1"), coil("DO1"), contact("DI2"),
                    parallel(coil("DO2"), coil("DO3", "NEGATED")), coil("DO4")))
    feed(rt, DI1=a, DI2=b)
    assert outs(rt, "DO1", "DO2", "DO3", "DO4") == (a, a and b, not (a and b), a and b)


def test_set_and_reset_coils_write_only_while_powered():
    rt = rig(series(contact("DI1"), coil("DO1", "SET")),
             series(contact("DI2"), coil("DO1", "RESET")))
    got = []
    for a, b in zip(bits("010001"), bits("000101")):
        feed(rt, DI1=a, DI2=b)
        got.append(rt.read_outputs()["DO1"])
    assert got == [False, True, True, False, False, False]


def test_edge_contacts_update_their_memory_even_without_power():
    rt = rig(series(contact("DI2"), contact("DI1", "P", id="r0.p"), coil("DO1")),
             series(contact("DI2"), contact("DI1", "N", id="r1.n"), coil("DO2")))
    got = []
    for a, b in zip(bits("01101100"), bits("11110101")):
        feed(rt, DI1=a, DI2=b)
        got.append(outs(rt, "DO1", "DO2"))
    assert got == [(False, False), (True, False), (False, False), (False, True),
                   (False, False), (False, False), (False, False), (False, False)]


@pytest.mark.parametrize("op,expected", [
    ("GT", (False, False, True)), ("GE", (False, True, True)), ("EQ", (False, True, False)),
    ("NE", (True, False, True)), ("LE", (True, True, False)), ("LT", (True, False, False)),
])
def test_compare_blocks_and_power(op, expected):
    rt = rig(series(contact("DI1"), element("compare", op=op, a="AI1", b=2.0), coil("DO1")))
    got = []
    for a in (1.0, 2.0, 3.0):
        feed(rt, DI1=True, AI1=a)
        got.append(rt.read_outputs()["DO1"])
    assert tuple(got) == expected
    feed(rt, DI1=False, AI1=(1.0, 2.0, 3.0)[expected.index(True)])
    assert rt.read_outputs()["DO1"] is False


@pytest.mark.parametrize("op,expected", [("ADD", 12.5), ("SUB", 7.5), ("MUL", 25.0), ("DIV", 4.0)])
def test_math_blocks_compute_only_while_powered(op, expected):
    rt = rig(series(contact("DI1"), element("math", op=op, a="AI1", b=2.5, dst="AO1")))
    feed(rt, DI1=True, AI1=10.0)
    assert rt.read_outputs()["AO1"] == expected
    feed(rt, DI1=False, AI1=20.0)
    assert rt.read_outputs()["AO1"] == expected


def test_move_writes_only_while_powered_and_accepts_every_operand_form():
    rt = rig(series(contact("DI1"),
                    element("move", src={"var": "AI1"}, dst="AO1"),
                    element("move", src={"const": 904.0}, dst="r"),
                    element("move", src="T#1s500ms", dst="t1"),
                    element("move", src={"time": "T#250ms"}, dst="t2"),
                    element("move", src=3, dst="n"),
                    element("move", src=True, dst="b")),
             vars=[decl("r", "REAL"), decl("t1", "TIME"), decl("t2", "TIME"), decl("n", "INT"),
                   decl("b", "BOOL")])
    feed(rt, DI1=False, AI1=5.0)
    assert (rt.read_outputs()["AO1"], var(rt, "n", "lad")) == (0.0, 0)
    feed(rt, DI1=True)
    v = rt.variables()["lad"]
    assert (rt.read_outputs()["AO1"], v["r"], v["t1"], v["t2"], v["n"], v["b"]) == \
        (5.0, 904.0, 1.5, 0.25, 3, True)


def test_timer_block_takes_rung_power_and_outputs_q():
    rt = rig(series(contact("DI1"),
                    element("timer", "r0.t", fb="TON", pt="T#50ms", instance="t1"),
                    coil("DO1")))
    q = []
    for _ in range(7):
        feed(rt, DI1=True)
        q.append(rt.read_outputs()["DO1"])
    assert q == [False] * 5 + [True] * 2 and var(rt, "t1.Q", "lad") is True


WORKED_RUNG = {
    "id": "r3",
    "comment": "Above the band, or loop disabled: close it",
    "logic": {"type": "series", "elements": [
        {"id": "r3.par", "type": "parallel", "branches": [
            {"type": "series", "elements": [
                {"id": "r3.en", "type": "contact", "kind": "NO", "operand": "bb_fuel_enable"},
                {"id": "r3.gt", "type": "compare", "op": "GT", "a": "PT13", "b": "hi"},
            ]},
            {"id": "r3.dis", "type": "contact", "kind": "NC", "operand": "bb_fuel_enable"},
        ]},
        {"id": "r3.rst", "type": "coil", "kind": "RESET", "operand": "S2"},
    ]},
}

WORKED_TEXT = [
    "Rung 0 [r3]  Above the band, or loop disabled: close it",
    "        bb_fuel_enable    PT13 > hi      S2",
    "  |--+-------] [-------------[GT]----+--(R)----|",
    "     |  bb_fuel_enable               |",
    "     +-------]/[---------------------+",
]


def test_ladder_to_text_renders_the_worked_rung():
    doc = {"version": 1, "language": "LD", "name": "bb", "rungs": [WORKED_RUNG],
           "vars": [decl("bb_fuel_enable", "BOOL"), decl("hi", "REAL")]}
    lad(doc, tags=TAGS + [TagSpec("PT13", "in", "REAL", ""), TagSpec("S2", "out", "BOOL", "")])
    lines = [line.rstrip() for line in ladder_to_text(doc).splitlines()]
    assert WORKED_TEXT[0] in lines
    assert lines[lines.index(WORKED_TEXT[0]):] == WORKED_TEXT
