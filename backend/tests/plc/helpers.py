"""Builders shared by the PLC engine tests. Tag names are synthetic, not stand data."""

from __future__ import annotations

import pytest

from draco_sim.plc import CompileError, PlcRuntime, TagSpec, compile_program

TAGS = [
    TagSpec("AI1", "in", "REAL", ""),
    TagSpec("AI2", "in", "REAL", ""),
    TagSpec("DI1", "in", "BOOL", ""),
    TagSpec("DI2", "in", "BOOL", ""),
    TagSpec("DI3", "in", "BOOL", ""),
    TagSpec("DI4", "in", "BOOL", ""),
    TagSpec("DO1", "out", "BOOL", ""),
    TagSpec("DO2", "out", "BOOL", ""),
    TagSpec("DO3", "out", "BOOL", ""),
    TagSpec("DO4", "out", "BOOL", ""),
    TagSpec("AO1", "out", "REAL", ""),
    TagSpec("CNT1", "out", "INT", ""),
]

DTS = [0.01, 1 / 30]


def st(src, name="p", tags=TAGS):
    return compile_program(src, "ST", tags, name=name)


def run_st(src, name="p"):
    return PlcRuntime(TAGS, [st(src, name)])


def scan_n(rt, n, dt=0.01):
    result = None
    for _ in range(n):
        result = rt.scan(dt)
    return result


def feed(rt, dt=0.01, **inputs):
    """Write the given input tags, then run one scan."""
    if inputs:
        rt.write_inputs(inputs)
    return rt.scan(dt)


def runtime(*programs, tags=TAGS):
    return PlcRuntime(tags, list(programs))


def bits(pattern):
    return [c == "1" for c in pattern]


def var(rt, name, prog="p"):
    return rt.variables()[prog][name]


def compile_error(source, language="ST", name="bad", tags=TAGS):
    with pytest.raises(CompileError) as info:
        compile_program(source, language, tags, name=name)
    return info.value


def st_value(expr, type_="REAL"):
    """Evaluate one ST expression through a scan and return the assigned value."""
    rt = run_st(f"VAR r : {type_}; END_VAR\nr := {expr};")
    assert rt.scan(0.01).faults == []
    return var(rt, "r")


def same(actual, expected):
    if isinstance(expected, float):
        return actual == pytest.approx(expected, rel=1e-12, abs=1e-12)
    return actual == expected and type(actual) is type(expected)


def decl(name, type_, init=None, scope=None):
    d = {"name": name, "type": type_}
    if init is not None:
        d["init"] = init
    if scope:
        d["scope"] = scope
    return d


# Ladder

def ld(*logics, vars=(), name="lad"):
    return {"version": 1, "language": "LD", "name": name, "vars": list(vars),
            "rungs": [{"id": f"r{i}", "logic": lg} for i, lg in enumerate(logics)]}


def series(*elements):
    return {"type": "series", "elements": list(elements)}


def parallel(*branches):
    return {"type": "parallel", "branches": list(branches)}


def element(type_, id=None, **fields):
    d = {"type": type_, **fields}
    if id:
        d["id"] = id
    return d


def contact(operand, kind="NO", id=None):
    return element("contact", id, kind=kind, operand=operand)


def coil(operand, kind="COIL", id=None):
    return element("coil", id, kind=kind, operand=operand)


def lad(doc, tags=TAGS):
    return compile_program(doc, "LD", tags)


# SFC

def sfc(steps, transitions, vars=(), name="chart", **extra):
    return {"version": 1, "language": "SFC", "name": name, "vars": list(vars),
            "steps": steps, "transitions": transitions, **extra}


def step(name, *actions, initial=False):
    s = {"name": name, "actions": list(actions)}
    if initial:
        s["initial"] = True
    return s


def action(body, qualifier="N", **extra):
    return {"qualifier": qualifier, "body": body, **extra}


def trans(frm, to, condition="TRUE"):
    return {"from": frm, "to": to, "condition": condition}


def chart(doc, tags=TAGS):
    return compile_program(doc, "SFC", tags)


def active(rt, name="chart"):
    return sorted(rt.sfc_state()[name]["active_steps"])
