"""Task 7 acceptance evidence; run from backend/ with draco_sim importable (installed or PYTHONPATH=.).

Default: deterministic probes. --observe SECONDS: read-only observation of the
real WebSocket server while an operator exercises the browser.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

from websockets.asyncio.client import connect

from draco_sim.plant.calibrate import vent_open_scenario
from draco_sim.plant.config import PlantConfig
from draco_sim.runtime import AbortThreshold
from draco_sim.runtime.demo import INITIAL, new_sim


def probes() -> dict:
    expected = sorted([(0, "PB2", "OPEN"), (.5, "PB4", "OPEN"),
                       (8, "PB2", "CLOSED"), (8.5, "PB4", "CLOSED"),
                       (8.7, "S4", "OPEN"), (8.7, "S5", "OPEN"),
                       (11.7, "S4", "CLOSED"), (11.7, "S5", "CLOSED")])
    timelines = {}
    for hz in (30, 50):
        sim = new_sim(hz)
        sim.plc_run()
        sim.write({"PB1": False, "PB3": False})
        sim.run_for(.5)
        sim.sequence_start("hotfire")
        start = sim.t
        sim.run_for(12.5)
        commands = []
        for e in sim.events:
            match = re.search(r"\((PB2|PB4|S4|S5)\) -> (OPEN|CLOSED)$", e.text)
            if e.level == "command" and e.t > start and match:
                commands.append((round(e.t - start, 6), *match.groups()))
        issued = sorted((round(t - sim.dt, 5), tag, value) for t, tag, value in commands)
        assert issued == expected, issued
        snap = sim.snapshot()
        assert snap["hmi"]["manual"] == {"PB1": False, "PB3": False}
        assert snap["hmi"]["manual_allowed"]
        timelines[str(hz)] = {"card_commands_from_start_s": commands,
                              "card_latency_s": sim.dt,
                              "final_steps": snap["plc"]["sfc"]["hotfire"]["active_steps"]}

    sim = new_sim()
    sim.plc_run()
    sim.write({"PB1": False, "PB3": False, "hmi.bb.lox.enable": True,
               "hmi.bb.fuel.enable": True})
    changed = {"PT3": [], "PT13": []}
    previous = sim.read(list(changed))
    for _ in range(750):
        sim.step()
        values = sim.read(list(changed))
        for tag in changed:
            if sim.t <= 1 and abs(values[tag] - previous[tag]) > .1:
                changed[tag].append(round(sim.t, 3))
        previous = values
    snap = sim.snapshot()
    for tag in changed:
        assert len(changed[tag]) > 10, (tag, changed[tag])
    assert not snap["outputs"]["S1"] and not snap["outputs"]["S2"]
    bangbang = {"settled_15s_psi": sim.read(["PT3", "PT13"]),
                "changes_over_0_1psi_in_first_second": changed,
                "panel": snap["hmi"]["bb"]}

    sim.sequence_start("hotfire")
    sim.run_for(1)
    sim.force("S1", True)
    real_pt1 = sim.read(["PT1"])["PT1"]
    sim.force("PT1", 0)
    sim.abort_config([AbortThreshold("PT1", ">", real_pt1 * .9, True, "live reading minus 10%")])
    sim.step()
    latch = sim.snapshot()
    assert latch["abort"]["latched"] and latch["abort"]["tripped"]["source"] == "threshold"
    assert "S1" not in latch["plc"]["forced"] and not latch["outputs"]["S1"]
    sim.run_for(6)
    held = sim.snapshot()
    assert held["abort"]["latched"]
    assert any("still tripped" in reason for reason in held["abort"]["waiting_on"])
    sim.abort_config([])
    sim.step()
    returned = sim.snapshot()
    assert not returned["abort"]["latched"] and returned["hmi"]["manual_allowed"]
    assert {tag for tag, value in returned["outputs"].items() if value} == {"PB1", "PB3"}
    assert not returned["plc"]["enabled"]["bangbang_lox"]
    assert not returned["plc"]["enabled"]["bangbang_fuel"]
    sim.write({"PB2": True})
    sim.step()
    assert sim.read(["PB2"])["PB2"]
    sim.plc_stop()
    sim.plc_run()
    sim.step()
    stopped = sim.snapshot()
    assert {tag for tag, value in stopped["outputs"].items() if value} == {"PB1", "PB3"}
    abort = {"latch": latch["abort"], "held": held["abort"], "returned": returned["abort"],
             "programs_enabled_after_return": returned["plc"]["enabled"],
             "manual_after_return_accepted": True, "stop_run_safe": True}

    # Same recorded load assumptions as plant-model.md section 6.
    vents = {f"{label}_{'open' if opened else 'closed'}": vent_open_scenario(cfg, 39.5, opened)
             for label, cfg, opened in [("uncalibrated", PlantConfig(), True),
                                        ("calibrated", PlantConfig.calibrated(), True),
                                        ("calibrated", PlantConfig.calibrated(), False)]}
    return {"initial": INITIAL, "hotfire": timelines, "bangbang": bangbang,
            "abort": abort, "vent_open": vents}


async def observe(url: str, duration: float) -> dict:
    events, changes = [], []
    previous = None
    async with connect(url) as ws:
        await ws.send(json.dumps({"type": "hello", "protocol": 1, "client": "task7-review"}))
        welcome = json.loads(await ws.recv())
        assert welcome["type"] == "welcome"
        await ws.send(json.dumps({"type": "subscribe", "rate_hz": 50,
                                  "groups": ["inputs", "outputs", "plc", "hmi"]}))
        end = asyncio.get_running_loop().time() + duration
        while (remaining := end - asyncio.get_running_loop().time()) > 0:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), remaining))
            except TimeoutError:
                break
            if msg["type"] == "event":
                events.append(msg)
            elif msg["type"] == "state":
                key = (msg["outputs"], msg["abort"]["latched"], msg["hmi"]["manual_allowed"],
                       msg["hmi"]["bb"], msg["plc"]["sfc"].keys())
                if key != previous:
                    changes.append({"t": msg["t"], "scan": msg["scan"], "outputs": msg["outputs"],
                                    "inputs": {k: msg["inputs"][k] for k in ("PT1", "PT3", "PT4", "PT11", "PT13", "PT14")},
                                    "abort": msg["abort"], "hmi": msg["hmi"]})
                    previous = key
    return {"url": url, "wall_duration_s": duration,
            "programs": [{"name": p["name"], "role": p["role"]} for p in welcome["programs"]],
            "events": events, "state_changes": changes}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--observe", type=float, default=0)
    parser.add_argument("--url", default="ws://127.0.0.1:8765/ws")
    args = parser.parse_args()
    result = asyncio.run(observe(args.url, args.observe)) if args.observe else probes()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Evidence written to {args.output}")


if __name__ == "__main__":
    main()
