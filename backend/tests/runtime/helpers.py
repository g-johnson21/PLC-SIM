"""Builders shared by the scan-loop and protocol tests.

The only stand values fed in are the recorded pre-fire configuration the demo uses
(`draco_sim.runtime.demo.INITIAL`); every trip level is derived from a live reading.
Inline programs use real tag names but invent no stand data.
"""

from __future__ import annotations

import copy
import json
import re

import pytest

from draco_sim.runtime import AbortThreshold, ProgramSource, SimConfig, SimError, Simulator
from draco_sim.runtime.demo import INITIAL

EXAMPLE_ROLES = {"abort_monitor": "monitor", "hotfire": "sequence", "gn2_purge": "sequence",
                 "bangbang_lox": "regulation", "bangbang_fuel": "regulation"}
MONITOR_ENABLE = "plc.globals.abort_monitor_enable"
STAND_SAFE = "abort sequence complete -- stand safe, operator in control"

_TEMPLATES: dict[tuple[float, bool], Simulator] = {}


def make_sim(scan_hz: float = 50.0, examples: bool = True) -> Simulator:
    """A stopped simulator at the recorded initial conditions, optionally with the five
    examples loaded. Built once per variant and deep-copied, which is ~6x cheaper."""
    key = (float(scan_hz), examples)
    if key not in _TEMPLATES:
        sim = Simulator(SimConfig(scan_hz=scan_hz))
        if examples:
            sim.load_examples()
        sim.reset_plant(INITIAL)
        _TEMPLATES[key] = sim
    return copy.deepcopy(_TEMPLATES[key])


def example(sim: Simulator, name: str) -> ProgramSource:
    return next(s for s in sim.example_sources() if s.name == name)


def st(name: str, body: str, decls: str = "") -> ProgramSource:
    return ProgramSource(name, "ST", f"PROGRAM {name}\n{decls}\n{body}\nEND_PROGRAM\n")


def sfc(name: str, steps, transitions, abort_step: str | None = None) -> ProgramSource:
    """steps: [(name, action body)], the first one initial; transitions: [(from, to, cond)]."""
    doc = {"version": 1, "language": "SFC", "name": name, "autostart": False,
           "steps": [{"name": step, "id": f"s.{step.lower()}", "initial": i == 0,
                      "actions": ([{"id": f"a.{step.lower()}", "qualifier": "N", "body": body}]
                                  if body else [])}
                     for i, (step, body) in enumerate(steps)],
           "transitions": [{"id": f"t.{i}", "from": a, "to": b, "condition": cond}
                           for i, (a, b, cond) in enumerate(transitions)]}
    if abort_step is not None:
        doc["abort_step"] = abort_step
    return ProgramSource(name, "SFC", json.dumps(doc))


def refused(code: str, fn, *args, **kwargs) -> SimError:
    with pytest.raises(SimError) as info:
        fn(*args, **kwargs)
    assert info.value.code == code, info.value.message
    return info.value


def run_until(sim: Simulator, predicate, seconds: float) -> bool:
    for _ in range(round(seconds * sim.scan_hz)):
        if predicate(sim):
            return True
        sim.step()
    return predicate(sim)


def latched(sim: Simulator) -> bool:
    return sim.read(["abort.latched"])["abort.latched"]


def outputs(sim: Simulator) -> dict[str, bool]:
    return sim.snapshot(["outputs"])["outputs"]


def open_valves(sim: Simulator) -> set[str]:
    return {tag for tag, value in outputs(sim).items() if value}


def normally_open(sim: Simulator) -> set[str]:
    return {t.tag for t in sim.tag_db.outputs if t.normal_state == "NO"}


def hmi(sim: Simulator) -> dict:
    return sim.snapshot(["hmi"])["hmi"]


def enabled(sim: Simulator) -> dict[str, bool]:
    return sim.snapshot(["plc"])["plc"]["enabled"]


def active_steps(sim: Simulator, chart: str) -> list[str]:
    return sim.snapshot(["plc"])["plc"]["sfc"][chart]["active_steps"]


def texts(sim: Simulator, level: str | None = None) -> list[str]:
    return [e.text for e in sim.events if level is None or e.level == level]


def card_commands(sim: Simulator, after: float) -> list[tuple[float, str, str]]:
    """(t, tag, OPEN|CLOSED) for every valve change the hardware saw after `after`."""
    out = []
    for e in sim.events:
        m = re.search(r"\((\w+)\) -> (OPEN|CLOSED)$", e.text)
        if e.level == "command" and e.source == "plc" and e.t > after and m:
            out.append((e.t, m.group(1), m.group(2)))
    return out


def trip_row(sim: Simulator, tag: str, enabled: bool = True) -> AbortThreshold:
    """A row the current card reading trips: 10 % below it."""
    reading = sim.read([tag])[tag]
    return AbortThreshold(tag, ">", 0.9 * reading, enabled, "test: 10 % below the live reading")


def abort_hotfire(sim: Simulator, burn_s: float = 1.0) -> float:
    """Run, start the hotfire, abort mid-burn; returns the latch time."""
    sim.plc_run()
    sim.sequence_start("hotfire")
    sim.run_for(burn_s)
    sim.abort()
    sim.step()
    assert latched(sim)
    return sim.t


def run_to_return(sim: Simulator, cap_s: float = 10.0) -> None:
    assert run_until(sim, lambda s: not latched(s), cap_s), sim.waiting_on()


def as_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str)
