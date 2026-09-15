"""Scripted acceptance runner for the scan loop: `python -m draco_sim.runtime.demo`.

Six blocks (the shipped abort monitor, nominal hotfire, auto-abort mid-burn, manual
arbitration, PLC stopped, a latch held by a still-tripped threshold), all deterministic
and all driven by step() alone. Every number printed comes
from the simulation; the only stand values fed in are the recorded pre-fire
configuration from the brief and the plant config defaults.
"""
from __future__ import annotations

import json
import logging
import re

from draco_sim.runtime import AbortThreshold, SimConfig, SimError, Simulator
from draco_sim.runtime.pacer import Pacer, perf_counter

# The recorded pre-fire configuration of 2026-09-11 (the brief's initial conditions).
INITIAL = {"bottle_psi": 4000.0, "lox_ullage_psi": 0.0, "fuel_ullage_psi": 0.0,
           "lox_mass_lbm": 60.0, "fuel_mass_lbm": 40.0, "muscle_bus_psi": 100.0}

PREPRESS_CAP_S = 120.0

# examples/abort_monitor.st keeps its three thresholds at the placeholder 0.0 and ships
# disarmed (abort_monitor_enable := FALSE), so loading the examples and pressing run
# does nothing until an operator configures and arms it. No source material gives a
# trip pressure and the demo will not invent one: scenario 0 arms the monitor with the
# placeholders untouched to show what that costs, and the other scenarios leave it
# disarmed and exercise the scan loop's own threshold table instead.
MONITOR_ENABLE = "plc.globals.abort_monitor_enable"

# the valves the D12 hotfire procedure commands
HOTFIRE_TAGS = ("PB2", "PB4", "S4", "S5")

VALVES = ("PB1", "PB2", "PB3", "PB4", "S1", "S2", "S4", "S5")

ROW = ("{t:>7} {tplus:>7} {steps:<16} {valves} "
       "PT3={PT3:>7.1f} PT13={PT13:>7.1f} PT21={PT21:>7.1f} PT22={PT22:>7.1f} "
       "PT0={PT0:>7.1f} THR={THRUST:>7.1f} bb={bb}")

HEAD = "{:>7} {:>7} {:<16} {} {:>11} {:>12} {:>12} {:>12} {:>11} {:>11} {}".format(
    "t", "T+", "active steps", " ".join(f"{v:<{len(v) + 2}}" for v in VALVES),
    "PT3", "PT13", "PT21", "PT22", "PT0", "THRUST", "bb lox/fuel")


def banner(text: str) -> None:
    print()
    print("=" * 108)
    print(text)
    print("=" * 108)


def new_sim(scan_hz: float = 50.0) -> Simulator:
    sim = Simulator(SimConfig(scan_hz=scan_hz))
    sim.load_examples()
    sim.reset_plant(INITIAL)
    return sim


def scenario_zero() -> None:
    banner("SCENARIO 0 -- the shipped abort monitor: disarmed on load, armed by the operator")
    sim = new_sim()
    sim.plc_run()
    sim.run_for(2.0)
    snap = sim.snapshot(["plc", "abort"])
    g = snap["plc"]["globals"]
    print("load the examples and press run -- nothing happens, because abort_monitor.st")
    print("ships disarmed:")
    print(f"  abort_monitor_enable = {g['abort_monitor_enable']}, "
          f"auto_abort_request = {g['auto_abort_request']}, "
          f"abort_active = {snap['plc']['abort_active']}, "
          f"tripped = {snap['abort']['tripped']}")
    print(f"  thresholds as shipped: pt0={g['pt0_abort_threshold']:g}, "
          f"pt5={g['pt5_abort_threshold']:g}, pt15={g['pt15_abort_threshold']:g} "
          f"(PLACEHOLDER -- operator-set)")
    print(f"  live readings at t={sim.t:.2f}: " +
          ", ".join(f"{k}={v:.4f}" for k, v in sim.read(["PT0", "PT5", "PT15"]).items()))
    print()
    print("now the operator arms it through the ordinary global -- with the placeholder")
    print("thresholds still at 0.0, so any positive reading trips:")
    sim.write({MONITOR_ENABLE: True})
    sim.run_for(0.5)
    snap = sim.snapshot(["plc", "abort"])
    print(f"  auto_abort_request = {snap['plc']['globals']['auto_abort_request']}, "
          f"abort_active = {snap['plc']['abort_active']}")
    print(f"  tripped: {snap['abort']['tripped']}")
    print(f"  waiting_on: {snap['abort']['waiting_on']}")
    print(sim.events.render(e for e in sim.events if e.level in ("abort", "sequence")))
    print()
    print("That is why the thresholds must be configured before the monitor is armed.")
    print("The remaining scenarios leave it disarmed and arm the scan loop's own")
    print("threshold table instead -- no forces, no invented trip pressure.")


def _steps(sim: Simulator) -> str:
    sfc = sim.snapshot(["plc"])["plc"]["sfc"]
    return ",".join(s for chart in sfc.values() for s in chart["active_steps"]) or "-"


def row(sim: Simulator, t0: float | None) -> str:
    v = sim.read(list(VALVES) + ["PT3", "PT13", "PT21", "PT22", "PT0", "THRUST"])
    hmi = sim.snapshot(["hmi"])["hmi"]["bb"]
    return ROW.format(
        t=f"{sim.t:.2f}", tplus="-" if t0 is None else f"{sim.t - t0:+.2f}",
        steps=_steps(sim), valves=" ".join(f"{tag}={int(v[tag])}" for tag in VALVES),
        PT3=v["PT3"], PT13=v["PT13"], PT21=v["PT21"], PT22=v["PT22"], PT0=v["PT0"],
        THRUST=v["THRUST"], bb=f"{hmi['lox']['state']}/{hmi['fuel']['state']}")


def prepress(sim: Simulator, timer: list | None = None) -> dict:
    """Enable both loops at the recorded pre-fire setpoints and run until both
    readings have reached their bands, or the cap expires.

    Two criteria are tracked. `both` is the strict one -- PT3 and PT13 inside their
    bands in the same scan -- and the calibrated plant does not reach it: each loop
    enters its band, then the gas left in its pressurant line equalises into the tank
    after the solenoid closes and parks the reading 8-13 psi above the band, where it
    stays because the model has no boil-off, leak or board vent output. `reached` is
    the practical one the run stops on: each loop has been inside its band at least once."""
    sim.plc_run()
    # the normally-open tank vents are closed before pressurising, as in the 12:49 log
    sim.write({"PB1": False, "PB3": False})
    sim.write({"hmi.bb.lox.enable": True, "hmi.bb.fuel.enable": True})
    bb = sim.snapshot(["hmi"])["hmi"]["bb"]
    lox, fuel = bb["lox"], bb["fuel"]
    out = {"both": None, "lox": None, "fuel": None, "reached": None}
    for _ in range(int(PREPRESS_CAP_S * sim.scan_hz)):
        t = perf_counter()
        sim.step()
        if timer is not None:
            timer.append(perf_counter() - t)
        v = sim.read(["PT3", "PT13"])
        in_lox = abs(v["PT3"] - lox["setpoint"]) <= lox["deadband"]
        in_fuel = abs(v["PT13"] - fuel["setpoint"]) <= fuel["deadband"]
        if in_lox and out["lox"] is None:
            out["lox"] = (sim.t, v["PT3"])
        if in_fuel and out["fuel"] is None:
            out["fuel"] = (sim.t, v["PT13"])
        if in_lox and in_fuel and out["both"] is None:
            out["both"] = (sim.t, v["PT3"], v["PT13"])
        if out["lox"] and out["fuel"]:
            out["reached"] = sim.t
            break
    return out


def scenario_a(quiet: bool = False) -> dict:
    if not quiet:
        banner("SCENARIO A -- nominal: pre-press on both bang-bang loops, then the 11.7 s hotfire")
    sim = new_sim()
    timer: list[float] = []
    band = prepress(sim, timer)
    lox = sim.snapshot(["hmi"])["hmi"]["bb"]["lox"]
    fuel = sim.snapshot(["hmi"])["hmi"]["bb"]["fuel"]
    if not quiet:
        print(f"bands: PT3 {lox['setpoint'] - lox['deadband']:.0f}..{lox['setpoint'] + lox['deadband']:.0f} psi, "
              f"PT13 {fuel['setpoint'] - fuel['deadband']:.0f}..{fuel['setpoint'] + fuel['deadband']:.0f} psi "
              "(recorded pre-fire configuration)")
        for name, hit in (("PT3", band["lox"]), ("PT13", band["fuel"])):
            print(f"  {name} first inside its band at t={hit[0]:.2f} s ({hit[1]:.1f} psi)"
                  if hit else f"  {name} never entered its band")
        if band["both"]:
            print(f"  both inside their bands in the same scan at t={band['both'][0]:.2f} s")
        else:
            print("  both inside their bands in the SAME scan: not observed. After each solenoid\n"
                  "  closes, the gas left in its pressurant line equalises into the tank and\n"
                  "  parks the reading 8-13 psi above the band; with no boil-off, leak or board\n"
                  "  vent output in the model, nothing brings it back down")
        print(f"  pre-press complete (each loop has reached its band) at "
              f"t={band['reached'] if band['reached'] else sim.t:.2f} s, "
              f"cap {PREPRESS_CAP_S:.0f} s")

    sim.sequence_start("hotfire")
    t0 = sim.t
    if not quiet:
        print()
        print(HEAD)
        print(row(sim, t0))
    grid, pt0_at_1s, last_steps = 1, None, _steps(sim)
    for _ in range(int(12.0 * sim.scan_hz)):
        t = perf_counter()
        sim.step()
        timer.append(perf_counter() - t)
        elapsed = sim.t - t0
        if abs(elapsed - 1.0) < sim.dt / 2:
            pt0_at_1s = sim.read(["PT0"])["PT0"]
        steps = _steps(sim)
        due = elapsed + 1e-9 >= grid * 0.25
        if due:
            grid += 1
        if (due or steps != last_steps) and not quiet:
            print(row(sim, t0))
        last_steps = steps
    mean_ms = 1000.0 * sum(timer) / len(timer)
    if not quiet:
        print()
        print(f"PT0 at T+1.00 s = {pt0_at_1s:.2f} psi  ->  scenario B arms PT0 > "
              f"{0.9 * pt0_at_1s:.2f} psi (that value minus 10 %, computed here, not hard-coded)")
        print(f"mean scan wall time over {len(timer)} scans: {mean_ms:.3f} ms "
              f"(scan period {1000.0 / sim.scan_hz:.1f} ms)")
        print()
        print(f"hotfire commands at the cards, T+ from sequence_start(). Each is issued on the "
              f"first scan that starts at or\nafter its T+ and reaches the card at the end of "
              f"that scan, {sim.dt:.3f} s later:")
        for e in sim.events:
            m = re.search(r"\((\w+)\) -> ", e.text)
            if (e.level == "command" and e.source == "plc" and e.t > t0 and m
                    and m.group(1) in HOTFIRE_TAGS):
                print(f"  T+{e.t - t0:6.3f}  {e.text}")
        print()
        print("--- event log ---")
        print(sim.events.render())
    return {"sim": sim, "pt0_at_1s": pt0_at_1s, "mean_scan_ms": mean_ms,
            "snapshot": sim.snapshot()}


def snapshot_at_2s() -> dict:
    """Scenario A re-run to sim t = 2.00 s, for the snapshot shape check."""
    sim = new_sim()
    sim.plc_run()
    sim.write({"hmi.bb.lox.enable": True, "hmi.bb.fuel.enable": True})
    sim.run_for(2.0)
    return sim.snapshot()


def _try_while_latched(sim: Simulator) -> None:
    setpoint = sim.read(["hmi.bb.lox.setpoint"])["hmi.bb.lox.setpoint"]
    for call, fn in (("write PB2=True", lambda: sim.write({"PB2": True})),
                     ("sequence_start('gn2_purge')", lambda: sim.sequence_start("gn2_purge")),
                     ("plc_stop()", sim.plc_stop),
                     ("force PB2=True", lambda: sim.force("PB2", True)),
                     ("write hmi.bb.lox.enable=True",
                      lambda: sim.write({"hmi.bb.lox.enable": True})),
                     ("abort_clear()", sim.abort_clear),
                     (f"write hmi.bb.lox.setpoint={setpoint:g} (same value)",
                      lambda: sim.write({"hmi.bb.lox.setpoint": setpoint}))):
        try:
            fn()
            print(f"    {call}: accepted")
        except SimError as exc:
            print(f"    {call}: rejected [{exc.code}] {exc.message}")


def scenario_b(pt0_at_1s: float) -> None:
    banner("SCENARIO B -- auto-abort mid-burn: the abort chain runs, then control returns by itself")
    value = 0.9 * pt0_at_1s
    sim = new_sim()
    sim.abort_config([AbortThreshold("PT0", ">", value, True,
                                     "derived at runtime from scenario A: PT0 at T+1.0 s minus 10 %")])
    print(f"armed: PT0 > {value:.2f} psi (enabled)")
    prepress(sim)
    sim.sequence_start("hotfire")
    t0 = sim.t
    print()
    print(HEAD)
    print(row(sim, t0))
    grid, latch_t, returned = 1, None, False
    last_steps = _steps(sim)
    for _ in range(int(20.0 * sim.scan_hz)):
        sim.step()
        elapsed = sim.t - t0
        abort = sim.snapshot(["abort"])["abort"]
        if abort["latched"] and latch_t is None:
            latch_t = sim.t
            print(row(sim, t0) + "   <-- ABORT")
            print(f"    tripped: {abort['tripped']}")
            print(f"    regulation enabled flags: {sim.snapshot(['plc'])['plc']['enabled']}")
            _try_while_latched(sim)
            grid = int(elapsed / 0.25) + 1
        elif latch_t is not None and not abort["latched"]:
            print(row(sim, t0) + "   <-- CONTROL RETURNED")
            returned = True
            break
        elif latch_t is not None and abort["waiting_on"] and elapsed + 1e-9 >= grid * 0.25:
            print(f"{'':>16}waiting_on: {abort['waiting_on']}")
        steps = _steps(sim)
        due = elapsed + 1e-9 >= grid * 0.25
        if due:
            grid += 1
        if due or steps != last_steps:
            print(row(sim, t0))
        last_steps = steps
    print()
    if latch_t is None:
        print("the threshold never tripped")
        return
    if not returned:
        print(f"still latched, waiting on: {sim.snapshot(['abort'])['abort']['waiting_on']}")
        return
    snap = sim.snapshot(["hmi", "outputs", "plc"])
    print(f"control returned {sim.t - latch_t:.2f} s after the latch with no clear command: "
          f"manual_allowed={snap['hmi']['manual_allowed']}, hotfire running="
          f"{snap['plc']['sfc']['hotfire']['running']} (its next start begins at START)")
    print(f"  outputs where the abort left them: {snap['outputs']}")
    print(f"  bang-bang entries (setpoints kept, loops OFF): {snap['hmi']['bb']}")
    try:
        sim.write({"PB2": False})
        sim.step()
        print(f"  write PB2=False (main valve stays closed): accepted, PB2={sim.read(['PB2'])['PB2']}")
    except SimError as exc:
        print(f"  write PB2=False: rejected [{exc.code}] {exc.message}")
    try:
        sim.write({"hmi.bb.lox.enable": True})
        print("  write hmi.bb.lox.enable=True: accepted (unexpected: the abort switched the loop off)")
    except SimError as exc:
        print(f"  write hmi.bb.lox.enable=True: rejected [{exc.code}] {exc.message}")
    sim.plc_reset()
    sim.write({"hmi.bb.lox.enable": True})
    sim.step()
    print(f"  after plc_reset(): write hmi.bb.lox.enable=True accepted, loop state="
          f"{sim.read(['hmi.bb.lox.state'])['hmi.bb.lox.state']}")
    print()
    print("--- event log (abort onward) ---")
    print(sim.events.render(e for e in sim.events if e.t >= latch_t - sim.dt / 2))


def scenario_c() -> None:
    banner("SCENARIO C -- manual commands, bang-bang solenoid ownership and sequences")
    sim = new_sim()
    sim.plc_run()
    sim.run_for(0.5)
    print(f"manual_allowed={sim.manual_allowed()}")
    sim.write({"PB2": True})
    sim.run_for(0.2)
    print(f"after write PB2=True:  PB2={sim.read(['PB2'])['PB2']}, "
          f"plant valve_pos PB2={sim.plant.state.valve_pos['PB2']:.2f}")

    sim.write({"hmi.bb.lox.enable": True})
    sim.run_for(0.2)
    print(f"LOX loop enabled, state={sim.read(['hmi.bb.lox.state'])['hmi.bb.lox.state']}, "
          f"S1={sim.read(['S1'])['S1']}")
    try:
        sim.write({"S1": False})
        print("write S1=False while the LOX loop is enabled: ACCEPTED (unexpected)")
    except SimError as exc:
        print(f"write S1=False while the LOX loop is enabled: rejected [{exc.code}] {exc.message}")
    sim.write({"hmi.bb.lox.enable": False})
    sim.step()
    print(f"LOX loop disabled mid-press: S1={sim.read(['S1'])['S1']} (the loop closes it once, "
          f"then leaves it to the operator)")
    sim.write({"S1": True})
    sim.run_for(0.2)
    snap = sim.snapshot(["hmi", "outputs"])
    print(f"write S1=True with the loop disabled: accepted, S1={snap['outputs']['S1']}, "
          f"manual={snap['hmi']['manual']}")
    sim.write({"S1": False})
    sim.step()

    sim.sequence_start("gn2_purge")
    sim.run_for(0.2)
    try:
        sim.write({"PB2": False})
        print("write PB2=False during gn2_purge: ACCEPTED (unexpected)")
    except SimError as exc:
        print(f"write PB2=False during gn2_purge: rejected [{exc.code}] {exc.message}")
    print(f"  active_sequence={sim.active_sequence()}, "
          f"S4/S5={sim.read(['S4', 'S5'])}")
    sim.run_for(2.5)
    print(f"after the purge finishes: active_sequence={sim.active_sequence()}, "
          f"manual_allowed={sim.manual_allowed()}, S4/S5={sim.read(['S4', 'S5'])}")
    try:
        sim.write({"PB2": False})
        sim.run_for(0.1)
        print(f"write PB2=False after completion: accepted, PB2={sim.read(['PB2'])['PB2']}")
    except SimError as exc:
        print(f"write PB2=False after completion: rejected [{exc.code}] {exc.message}")
    print()
    print("--- event log ---")
    print(sim.events.render())


def scenario_d() -> None:
    banner("SCENARIO D -- PLC stopped: outputs at their fail-safe state, plant still runs")
    sim = new_sim()
    sim.plc_run()
    sim.write({"hmi.bb.lox.enable": True, "hmi.bb.fuel.enable": True})
    sim.run_for(3.0)
    print(f"running: outputs={sim.snapshot(['outputs'])['outputs']}")
    print(f"         PT3={sim.read(['PT3'])['PT3']:.1f}  PT4={sim.read(['PT4'])['PT4']:.1f}")
    sim.plc_stop()
    sim.run_for(0.1)
    print(f"stopped: outputs={sim.snapshot(['outputs'])['outputs']}")
    print("         (S1/S2 closed, PB1/PB3 -- the normally-open tank vents -- open)")
    try:
        sim.abort()
        print("  abort() while stopped: accepted (unexpected)")
    except SimError as exc:
        print(f"  abort() while stopped: rejected [{exc.code}] {exc.message}")
    print(f"  {'t':>6} {'scan':>6} {'PT4':>9} {'PT14':>9} {'LOX ullage':>11} "
          f"{'fuel ullage':>12} {'LOX kg':>8}   (plant and cards keep running)")
    for _ in range(6):
        sim.run_for(1.0)
        v = sim.read(["PT4", "PT14"])
        st = sim.plant.state
        print(f"  {sim.t:6.2f} {sim.scan:6d} {v['PT4']:9.2f} {v['PT14']:9.2f} "
              f"{st.node_p_psig['lox_ullage']:11.2f} {st.node_p_psig['fuel_ullage']:12.2f} "
              f"{st.lox_mass_kg:8.3f}")
    sim.plc_run()
    sim.run_for(1.0)
    snap = sim.snapshot(["outputs", "hmi"])
    print(f"run again: open={sorted(t for t, v in snap['outputs'].items() if v)}, loops enabled="
          f"{[loop for loop, vals in snap['hmi']['bb'].items() if vals['enable']]}, "
          f"manual={snap['hmi']['manual']} -- nothing moves until the operator commands it")
    print()
    print("--- event log (stop onward) ---")
    print(sim.events.render(e for e in sim.events if e.level != "info" or "STOP" in e.text))


def scenario_e() -> None:
    banner("SCENARIO E -- a threshold still tripped when the abort chain ends holds the latch")
    sim = new_sim()
    sim.plc_run()
    sim.run_for(1.0)
    tag = "PT1"
    reading = sim.read([tag])[tag]
    value = 0.9 * reading
    print(f"{tag} ({sim.tag_db.by_tag[tag].description}) reads {reading:.1f}, and an abort does "
          f"not vent it. A row {tag} > {value:.1f}")
    print("(that reading minus 10 %, computed here) stands in for a failed gauge stuck above its "
          "limit, as PT0 was after the 12:49 RUD.")
    sim.abort_config([AbortThreshold(tag, ">", value, True, "demo: stands in for a failed gauge")])
    for _ in range(int(10.0 * sim.scan_hz)):
        if any(e.text.startswith("abort sequence complete but") for e in sim.events):
            break
        sim.step()
    abort = sim.snapshot(["abort"])["abort"]
    print(f"  t={sim.t:.2f}: latched={abort['latched']}, waiting_on={abort['waiting_on']}")
    sim.force(tag, 0.5 * reading)
    sim.run_for(1.0)
    print(f"  forced {tag} := {0.5 * reading:.1f}: the PLC sees {sim.read([tag])[tag]:.1f}, the "
          f"threshold still reads the card, latched={sim.read(['abort.latched'])['abort.latched']}")
    sim.unforce(tag)
    sim.abort_config([AbortThreshold(tag, ">", value, False, "demo: stands in for a failed gauge")])
    sim.step()
    print(f"  row disabled with abort_config: latched={sim.read(['abort.latched'])['abort.latched']}, "
          f"manual_allowed={sim.manual_allowed()}")
    print()
    print("--- event log (abort level) ---")
    print(sim.events.render(e for e in sim.events if e.level == "abort"))


def elide(snapshot: dict) -> dict:
    out = dict(snapshot)
    for group in ("plant", "raw"):
        if group in out:
            out[group] = f"<{len(out[group])} entries elided>"
    return out


def determinism_check() -> None:
    banner("DETERMINISM -- scenario A run twice, final snapshots compared")
    a = scenario_a(quiet=True)["snapshot"]
    b = scenario_a(quiet=True)["snapshot"]
    same = json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    print(f"snapshots identical: {same}")
    if not same:
        for key in a:
            if json.dumps(a[key], sort_keys=True, default=str) != json.dumps(
                    b[key], sort_keys=True, default=str):
                print(f"  differs: {key}")


def pacer_demo() -> None:
    banner("PACER -- the only clock in the package")
    sim = new_sim()
    sim.plc_run()
    pacer = Pacer(sim, realtime=True, speed=1.0)
    now = 1000.0
    pacer.due_scans(now)
    for offset in (0.0, 0.021, 0.10, 1.0):
        now += offset
        print(f"  +{offset:.3f} s of wall time -> due_scans = {pacer.due_scans(now)} "
              f"(dt = {sim.dt:.3f} s, dropped so far = {pacer.dropped_scans})")


class _Notices(logging.Handler):
    """Collect the hardware layer's one-shot warnings instead of letting them land in
    the middle of a table."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        line = f"{record.name}: {record.getMessage()}"
        if line not in self.lines:
            self.lines.append(line)


def main() -> None:
    notices = _Notices()
    logging.basicConfig(level=logging.WARNING, handlers=[notices], force=True)
    print("Draco scan-loop acceptance run -- draco_sim.runtime")
    print("initial conditions (recorded pre-fire configuration): " +
          ", ".join(f"{k}={v:g}" for k, v in INITIAL.items()))
    print("abort thresholds default to disabled at 0.0, labelled PLACEHOLDER -- operator-set")
    scenario_zero()
    result = scenario_a()
    scenario_b(result["pt0_at_1s"])
    scenario_c()
    scenario_d()
    scenario_e()
    banner("SNAPSHOT -- scenario A at t = 2.00 s (plant and raw groups elided)")
    print(json.dumps(elide(snapshot_at_2s()), indent=2, default=str))
    determinism_check()
    pacer_demo()
    banner("HARDWARE / PLANT NOTICES collected during the run")
    for line in notices.lines:
        print(f"  {line}")


if __name__ == "__main__":
    main()
