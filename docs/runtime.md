# Scan loop (task 5)

`backend/draco_sim/runtime/` drives the three accepted components — `draco_sim.hwio`
(card simulation), `draco_sim.plant` (physics) and `draco_sim.plc` (the LD/ST/SFC
engine) — from one scan. `Simulator` is the whole backend behind one synchronous,
deterministic object; task 6 maps its methods one-to-one onto the messages in
`docs/protocol.md`.

```python
from draco_sim.runtime import Simulator, SimConfig, ProgramSource, AbortThreshold

sim = Simulator(SimConfig(scan_hz=50))
sim.load_examples()                 # the five programs in backend/examples
sim.reset_plant({"bottle_psi": 4000, "lox_mass_lbm": 60, "fuel_mass_lbm": 40,
                 "muscle_bus_psi": 100})
sim.plc_run()
sim.write({"hmi.bb.lox.enable": True})
sim.run_for(10.0)                   # 500 scans at 50 Hz
sim.sequence_start("hotfire")
sim.snapshot()                      # exactly the protocol `state` object
```

Nothing in `Simulator` reads a clock. Simulated time is `scan_count * dt`, `dt` comes
from `SimConfig.scan_hz`, and the same call sequence produces bit-identical snapshots
every run (the acceptance run checks this). The only module in the package that may
import `time` is `pacer.py`.

---

## 1. The scan order

This order is a safety rule, not an implementation detail: it is what the training is
for. It implements `docs/decisions.md` D7 and the arbitration rules in
`docs/protocol.md`. `Simulator.step()` runs exactly one pass of it.

1. **Input image.** `hw.read_inputs()` → `rt.write_inputs()`. The PLC sees the card
   simulation's held/quantised engineering values, not the plant's internal truth.
   Forces are applied by the PLC runtime on top of this, so the programs see the forced
   image. The threshold table in step 2 does not: it reads the card values from before
   the forces (D12).
2. **Auto-abort evaluation, every scan while the PLC runs.** First the threshold table
   (`abort.thresholds`, operators `> >= < <=`, only `enabled` rows), in table order,
   against the real card readings, so a forced input can never mask a trip; then any
   loaded program's `auto_abort_request` global (that is what `examples/abort_monitor.st`
   computes while it is armed). The source that tripped is recorded in `abort.tripped`.
   This runs before the sequencer and before regulation because a trip must not have to
   wait for a step to finish.
3. **Manual abort bit.** `hmi.abort`, set by `abort()` or by `write({"hmi.abort":
   true})`. The latch consumes it: it reads `false` again from the latch scan on. It
   cannot be written `false`; an abort ends by itself (§3). It cannot be set while the
   PLC is stopped (below).
4. **Abort action.** If 2 or 3 tripped and the abort is not already latched, the abort
   latches (§3): `rt.trigger_abort()`, the output-writing non-SFC programs are disabled,
   output forces and manual commands are dropped, and an `[abort]` event names the cause.
   Until control returns, the abort owns every output (§2) and the operator actions
   listed in §3 are refused with `abort_active`.
5. **PLC scan.** `rt.scan(dt)` — always, latched or not, so the abort chains advance.
   Programs run in role order: monitor, then sequence, then regulation, then other
   (the runtime executes programs in construction order, and `load_programs()` sorts
   them into it; D7 and `docs/plc-language.md` §7.1).
6. **Output arbitration** (table below), producing the final output image. While
   latched, the scan then checks whether control can return to the operator (§3,
   "Return of control"); if it can, the latch drops at the end of this scan and the
   normal table applies from the next one.
7. **Hardware and plant.** `hw.write_outputs(final)` → `hw.step(dt)` →
   `plant.step(dt, hw.valve_states())` → `hw.set_physical(plant.sensors())`, then the
   scan counter and `t` advance. Valve changes seen at the *hardware* (after the
   NI-9476's 500 µs latency and the polarity mapping) become `[command]` events.

With the PLC stopped, steps 2–6 are skipped, the outputs are held at the stand's
normal state (NC closed, NO open — every coil de-energized), and step 7 still runs so
the plant keeps evolving. A stopped PLC holds the stand safe, so there is nothing to
abort (D14): no threshold is evaluated, `abort()` and `write({"hmi.abort": true})` are
refused with `rejected`, and `plc_stop()` drops an abort request that has not latched
yet, so it cannot latch later on `plc_run()`. Step 1 also still runs: a real scan engine in STOP freezes
its input image, but freezing the operator's tank-pressure display is a worse lie than
keeping it live, and a runtime that is not scanning does nothing with the values.

**A stop stays safe on the next run (D17).** `plc_stop()` leaves nothing behind that could command a
valve when the PLC runs again:
* it drops manual commands and output forces, stops every chart and turns both bang-bang enables off;
* it gives the PLC runtime a cold restart, so variables return to their declared values, faults clear
  and the output image and held coils are forgotten;
* it keeps the program set, input forces, the HMI setpoints and deadbands, and the programs an abort
  switched off.

One `[warn]` event lists what was cleared. After `plc_run()` every valve stays in its default state
until the operator commands one, except where a program writes an output unconditionally.

**One scan of latency on the program-computed request.** `auto_abort_request` is
computed by a program during step 5 and read by step 2 of the *next* scan — 20 ms at
50 Hz. That is inherent to a monitor program that publishes a bit; the threshold table
in step 2 has no such delay.

**Roles.** Every loaded program has a role, whether or not the loader was told one.
Step 5 orders the scan by it and the event log and IDE show it — but no safety rule
trusts it on its own: the abort in step 4 disables programs by what their code writes,
and "a sequence is active" is decided by the chart itself. When no role is given:

| Program | Role when none is given |
|---|---|
| SFC | `sequence` |
| ST / LD that writes any output tag | `regulation` |
| ST / LD that writes no output tag | `monitor` |

"Writes" is the compiler's record (`CompiledProgram.output_writes`,
`docs/plc-language.md` §7.1), not a guess from the name, so the same bang-bang loop gets
the same role whether it arrives through `load_examples()` or the IDE's `program.load`.
An explicit role on a `ProgramSource` (or a `program.load` entry) overrides the
inference, but it must not contradict the code. `load_programs()` rejects the whole
load, with a compile-result-style error (`path: "/role"`) on each offending program,
when an SFC is given any role but `sequence`, a non-SFC is given `sequence`, or a
program that writes an output tag is given `monitor`. `other` is only ever explicit
and stays allowed — it simply does not exempt a valve-writing program from the abort. `load_examples()` passes the examples' roles
explicitly and cross-checks each against the inference, logging a `warn` event on any
disagreement. `sim.inferred_roles()` returns the inference for every loaded program, and
the "programs loaded" event marks inferred roles as `[regulation, inferred]`.

## 2. Output arbitration

Per output tag, the first row that matches wins.

| # | Condition | Final value |
|---|---|---|
| 1 | an enabled program wrote the coil during this scan, or the tag is forced | PLC output image |
| 2 | an operator manual command is set for it | the manual command |
| 3 | the PLC has driven it since the last reset (a held/latched coil) | PLC output image |
| 4 | nothing has ever driven it | its fail-safe state (NC closed, NO open) |

While an abort is latched this table applies instead. The abort is absolute (D12): manual
commands and output forces were dropped at the latch, new ones are refused, and no non-SFC
program that writes outputs is running.

| # | Condition (abort latched) | Final value |
|---|---|---|
| A1 | a loaded chart's abort chain writes the tag, and the PLC has driven it | PLC output image |
| A2 | anything else | its fail-safe state (NC closed, NO open) |

A2 applies from the latch scan until control returns, whichever program last drove the
tag. "Abort chain" means the declared `abort_step` and every step reachable from it — not
the chart as a whole — and the tags it writes are fixed at compile time
(`CompiledProgram.abort_writes`, `docs/plc-language.md` §7.1). A1 still requires the PLC
to have driven the tag, for the same reason as row 4: hotfire's chain opens the tank vents
PB1/PB3 in `ABORT_4`, and until it does they must sit open, not at the all-false image.

Row 1 needs to know which coils were *written*, not which changed: a bang-bang loop
re-writing `S1 := FALSE` every scan owns S1 even though nothing changes. The PLC
engine now reports that as `ScanResult.outputs_written` (see `docs/plc-language.md`
§7.3); it is never inferred from value changes.

Row 4 is an addition to the protocol's rules, and it exists because a
cleared PLC output image is all-`false`, and `false` means *commanded closed*. Without
row 4, the moment an abort cleared the manual commands the two normally-open tank
vents (PB1, PB3) would be commanded shut — a transient seal of a tank that is
mid-safing. A coil nothing has driven sits de-energized, the way the hardware does.

Manual commands are accepted only when `hmi.manual_allowed` is true: the PLC is
running, no abort is latched, and no sequence is active.

* while an abort is latched → `abort_active`
* while a sequence is active → `rejected` ("sequence active")
* while the PLC is stopped → `rejected` (outputs are held safe; a write that silently
  took effect on the next `plc.run` would be a trap)
* to a bang-bang loop's solenoid while that loop is enabled → `rejected`, with `details.loop` (§4).
  A write that disables the loop in the same call is accepted

Existing manual commands **stay in force when a sequence starts** (D16): closing the tank
vents before a hotfire keeps them closed through the burn. Only an abort latch (or a
stopped PLC, which holds every coil safe) drops them all. One narrower release protects
the sequence: when a running chart writes a coil during a scan, the manual command on
that coil is dropped and a `[warn]` event names it. Without it, a hazard appears. The
hotfire chart sets `PB2 := FALSE` *once* in CLOSE_LOX_MAIN, so a manual `PB2 = open` left
over from before the sequence would take the coil back under row 2 on the very next scan
and re-open the LOX main valve after shutdown. Coils the chart only writes in its abort
chain, such as the vents in `ABORT_4`, keep their manual commands until an abort clears
them anyway.

A sequence is *active* while its chart is running and not parked on a final step (a
step with no outgoing transition, e.g. `COMPLETE`, `DONE`, `ABORT_DONE`). That is what
lets manual control return after a sequence finishes without stopping the chart.

## 3. Abort lifecycle

An abort is absolute and ends by itself (`docs/decisions.md` D12). It overrides every
commanded position, operator forces included, and control returns to the operator when the
abort sequence is over, with no manual clear.

```
   trip ──► latch ──► chain ──► return of control
```

**Trip** (step 2/3): an enabled threshold row tripped by the real card reading, a program's
`auto_abort_request`, or `hmi.abort`. Trips are only evaluated while the PLC runs.

**Latch** (step 4): `rt.trigger_abort()` sets `SYS_ABORT` and, at the top of the scan
that follows in the same `step()`, drops every chart out of its current steps (no exit
actions — an abort is not a normal step exit) and starts every chart that declares an
`abort_step` at that step. Every non-SFC program whose compiled code writes an output
tag (`CompiledProgram.output_writes`) is disabled, whatever its role, plus anything
explicitly labelled `regulation`; the rule keys off the code so that labelling a
bang-bang loop `other` cannot keep it pressing through an abort. The `[abort]` event
lists them, and names the label of any program disabled despite it
(`regulation off: bangbang_lox [other]`). Manual commands are dropped. Output forces are
cleared, and a second `[abort]` event lists them (`output forces cleared: MV-LOX (PB2)`);
input forces stay, since the thresholds read the cards anyway. `abort.latched` becomes
true and `abort.tripped` records `{tag, value, threshold, t, source}`.

**Outputs at the latch.** Every output tag that no loaded abort chain writes goes to its
fail-safe state on the latch scan and stays there until control returns (rows A1–A2 in
§2). A disabled program's coils therefore do not hold: `bangbang_lox` loaded on its own
and aborted mid-press closes S1 on the latch scan. A chart that opened PB2 in a normal step
cannot keep it open either, unless its abort chain writes PB2. A tag an abort chain does
write stays under that chain's control for the whole latch: hotfire's chain writes S1 and
S2 in `ABORT_3`, so a pressing loop's solenoids stay open until that step closes them
0.2 s after the latch, as the recorded chain does. One `[abort]` event lists the tags that
changed to fail-safe at the latch; when none changed there is no event. No force
survives the latch, and new output forces are refused until control returns.

**Chain**: the scan loop keeps calling `rt.scan(dt)` every scan, so the safing chain
runs at full speed while the normal chain stays frozen. `[sequence] T+<s> <step>`
events track it.

**While latched.** The abort owns the stand, and the operator actions that could fight it
are refused:

| Action | While latched |
|---|---|
| `write` to an output tag | refused, `abort_active` |
| `sequence_start()`, `sequence_stop()` | refused, `abort_active` (the safing chain must run) |
| `plc_stop()`, `plc_reset()` | refused, `abort_active`, with `details.waiting_on` |
| `load_programs()` | refused, `abort_active` |
| `force()` on an output tag | refused, `abort_active` |
| `write hmi.bb.<loop>.enable = true` | refused, `abort_active` |
| `abort_clear()` | refused, `rejected`, with `details.waiting_on` |
| `write hmi.abort = false` | refused, `rejected` (latched or not) |
| `abort()` | accepted and ignored: the running abort already serves it |
| setpoint and deadband edits, `enable = false`, `plc.globals.*` writes, input forces, `unforce()`, `abort_config()`, `plc_clear_faults()`, pause, resume, scan rate | accepted |
| `reset_plant()` | accepted, and clears the latch (instructor reset, below) |

**Waiting on.** `waiting_on()` (`abort.waiting_on`, and `waiting_on` in the snapshot's
`abort` group) lists why control has not returned yet, and is `[]` when nothing is latched:

* `"<chart> at <step>"` for each chart with an abort chain that has not finished. A chain
  has finished when every active step of the chart is a terminal step of the chain
  (`ABORT_DONE`), or the chart is not running. A chain with no terminal step never
  finishes, and its entry says so.
* `"<tag> <op> <value> still tripped"` for each enabled threshold row the current card
  reading trips.
* `"plc.globals.auto_abort_request still set"` while a program's request is true.

**Return of control.** At the end of the first scan whose `waiting_on()` is empty, the
scan loop:

1. calls `rt.clear_abort()` and stops every chart, so the next `sequence_start()` begins
   at the chart's initial step;
2. leaves the programs the latch disabled switched off, because nothing re-arms itself
   after an abort (D14). `plc_reset()`, `reset_plant()` or `load_programs()` re-arms them.
   Until then, `write hmi.bb.<loop>.enable = true` for a loop whose program is still off
   is refused with `rejected`;
3. forces both bang-bang `enable` entries OFF and re-mirrors them, keeping setpoints and
   deadbands, so the loops stay off until the operator re-arms them;
4. leaves PLC variables alone (there is no `rt.reset()`);
5. holds the outputs where the abort left them: every output tag not at its fail-safe
   state becomes a manual command. With hotfire loaded nothing needs holding, because its
   chain ends with only the normally-open vents PB1/PB3 open, which is their fail-safe
   state;
6. emits `[abort] abort sequence complete -- stand safe, operator in control`, then
   `[abort] programs left off until plc.reset re-arms them: …` if step 2 left any off,
   and `[abort] held as manual commands: …` if step 5 held anything.

From the next scan the normal arbitration table applies and `hmi.manual_allowed` is true.
In demo scenario B, control returns 5.32 s after the latch (hotfire's chain is
0.1 + 0.1 + 0.1 + 5.0 s plus the scans between steps).

**Held latch.** If the chains finish but a threshold is still tripped or a request is
still set, the latch holds, and an `[abort] abort sequence complete but the latch is
held: …` event is emitted each time the list of holds changes. A failed sensor must not
trap the stand (the 12:49 RUD froze PT0), so disable its row with `abort_config()`;
forcing the input does not help, because thresholds read the cards. A program request is
released by clearing what sets it: for `examples/abort_monitor.st`, write
`plc.globals.abort_monitor_enable` false.

**Instructor reset.** `reset_plant()` is the one reset allowed while latched. It clears the
latch and `abort.tripped` the way `plc_reset()` does, re-enables every program, logs
`[abort] abort cleared by sim.reset (instructor action)`, and leaves the PLC running.

**`abort_clear()`** is kept for protocol compatibility. It does nothing when no abort is
latched; otherwise it is rejected with `rejected` and `details.waiting_on`.

**Nothing resumes by itself.** A program without an enable gate cannot reopen a valve
after an abort. An IDE program that is only `PB2 := TRUE;` closes PB2 at the latch, and
PB2 stays closed after control returns. Manual valve commands work in the meantime, and
the program drives PB2 again only once the operator re-arms it with `plc_reset()`.

## 4. HMI bang-bang mapping

`hmi.bb.<loop>.{setpoint,deadband,enable}` for `lox` and `fuel` are operator entries
held by the scan loop and mirrored into PLC globals on every write, using
`SimConfig.bb_globals`. The defaults are the globals the shipped examples declare:

| HMI entry | LOX (`bangbang_lox.st`) | fuel (`bangbang_fuel.ld.json`) |
|---|---|---|
| setpoint | `setpoint` | `setpoint_fuel` |
| deadband | `deadband` | `deadband_fuel` |
| enable | `bb_lox_enable` | `bb_fuel_enable` |
| solenoid | S1 (SV-LOXBB) | S2 (SV-FBB) |

Startup values: LOX 904 / 15, fuel 870 / 15, both disabled — the recorded pre-fire
configuration of 2026-09-11, labelled as such in `SimConfig.bb_defaults`, not a
calibrated setpoint. Feedback is PT3 → S1 and PT13 → S2 (D2).

**Solenoid ownership (D17).** A loop controls its solenoid only while enabled.
* **The example programs** write S1/S2 only while their enable is true, and once more, closed, on
  the scan it goes false. A loop disabled mid-press therefore closes its solenoid and then leaves it
  to the operator.
* **While a loop is enabled,** the scan loop refuses manual writes to its solenoid.
* **Enabling a loop** drops any manual command left on the solenoid, with a
  `[warn] manual command released to the <loop> bang-bang loop` event. Inside its band the loop
  writes nothing, so a manual open would otherwise keep pressing.

`hmi.bb.<loop>.state` is derived, read-only: `OFF` when the enable is false or the
loop's program has been switched off by an abort and not yet re-armed, `PRESS`
when the loop's solenoid is open in the final output image, `HOLD` otherwise.

Mirroring writes only globals that exist, so the HMI entries survive a program set
that does not declare them. `plc_reset()` re-mirrors after the PLC runtime returns its
globals to their declared initial values, and return of control re-mirrors the enables
it turns off.

## 5. Reading and writing

`read(names)` and `write(values)` cover every namespace in `docs/protocol.md`: the 32
input tags, the 14 output tags, `plc.globals.<name>`, `hmi.abort`, `hmi.bb.*`,
`abort.thresholds`, `plant.<field>[.<key>]` and `raw.<module>.<index>.<channel>`, plus
the read-only `abort.tripped`, `abort.latched` and `abort.waiting_on`.
`write` is atomic — every name is validated before anything is applied — and raises
`SimRejected(code, message, details)` with the protocol error codes (`read_only`,
`unknown_name`, `rejected`, `abort_active`, `plc_running`, `compile_error`).
`load_programs` raises `SimStateError` (code `plc_running`) while the PLC is running.

Reading an output tag returns the **final arbitrated image** — what is actually
commanded at the cards — which equals the PLC output image whenever no manual command
applies.

`snapshot(groups=None)` returns exactly the protocol `state` object; see
`docs/protocol.md` for the field-by-field shape. Groups are `inputs`, `outputs`,
`plc`, `hmi`, `plant`, `raw`; `t`, `scan`, `scan_hz`, `paused` and the whole `abort`
group are always present, because abort state is the one thing a client must not be
able to filter away. `plant` is `PlantState` flattened to plain JSON types; `raw` is
keyed `"<module>.<index>.<channel>"`.

Additive fields beyond the protocol draft: `plc.enabled` (per-program enable flags),
`hmi.manual` (the current manual commands) and `hmi.bb.<loop>.abort_off` (the programs
driving that loop's solenoid that an abort switched off and no reset has re-armed; `[]`
otherwise). `role` on program entries and the
`source` of `abort.tripped` are now part of `docs/protocol.md`.

## 6. Events

`sim.events` is a ring buffer of `Event(t, scan, level, text, source)` and
`sim.on_event(cb)` subscribes. Texts follow the stand's own log style:

```
[command]  MV-LOX (PB2) -> OPEN                 alias from the tag database (D1/D3)
[sequence] T+8.020 hotfire CLOSE_LOX_MAIN       T+ is measured from sequence_start()
[abort]    ABORT LATCHED -- PT0=191.2 > 187.1 (…); regulation off: …
[abort]    abort sequence complete -- stand safe, operator in control
[fault]    [div_zero] bangbang_lox:7:9: … (scan 412, t=8.240s)
```

Every event raised during a scan carries that scan's index and the simulated time at
the *end* of the scan, so an event and the snapshot that follows it agree.

## 7. Pacer

`draco_sim.runtime.pacer` is the only module allowed to look at a clock.

```python
from draco_sim.runtime import Pacer
from draco_sim.runtime.pacer import monotonic

pacer = Pacer(sim, realtime=True, speed=1.0)
while True:
    for _ in range(pacer.due_scans(monotonic())):
        sim.step()
    await asyncio.sleep(pacer.sleep_time(monotonic()))
```

`due_scans(now)` converts elapsed wall time into a number of `step()` calls.
`realtime=False` returns a fixed batch (run as fast as the caller can). `speed`
multiplies simulated against wall time. A backlog larger than `max_batch` scans is
dropped, not chased, and counted in `pacer.dropped_scans`: a slow host falls behind in
simulated time instead of spiralling. `sim.pause()` makes `due_scans` return 0 and
re-anchors.

## 8. Demo / acceptance runner

```
cd backend && python -m draco_sim.runtime.demo
```

Six scripted, deterministic blocks:

* **0** the shipped abort monitor: disarmed on load, then armed by the operator on its
  own placeholder thresholds. Its request stays set, so `waiting_on` still names it
  after the chain.
* **A** nominal: pre-press both loops at the recorded setpoints, then the 11.7 s D12
  hotfire, printing when each command reaches the cards.
* **B** auto-abort mid-burn: a PT0 threshold derived at runtime from scenario A's own
  output trips at T+0.74 s. While latched, the manual write, sequence start, PLC stop,
  output force, loop enable and `abort_clear` are refused and a setpoint edit is
  accepted. Control returns 5.32 s after the latch with no clear command. The LOX loop
  cannot be enabled again until `plc_reset()`.
* **C** manual arbitration: a manual valve command, a manual S1 write refused while the LOX loop
  is enabled and accepted once it is disabled, and a sequence locking manual control out and
  handing it back.
* **D** the PLC stopped: outputs at their fail-safe state, `abort()` refused, plant still
  integrating, and nothing moving when the PLC runs again.
* **E** a held latch: a PT1 row standing in for a failed gauge holds the latch after the
  chain ends. Forcing PT1 does not release it; disabling the row does.

It also prints the snapshot shape, a determinism check and the mean scan wall time.

Things the run makes visible that are worth knowing:

* **Hotfire timing does not drift with scan rate.** Every timed transition compares
  `SYS_TIME - t_start` with the procedure's T+ (`docs/plc-language.md` §6.5). Each command
  is issued on the first scan that starts at or after its T+ and reaches the cards at the
  end of that scan. At 50 Hz the cards see T+0.020, 0.520, 8.020, 8.520, 8.720 and
  11.720 s, one scan after the procedure times.

* Pre-press closes the normally-open tank vents PB1/PB3 first, as the stand does in the
  12:49 recording; with the calibrated vents, holding S1/S2 open against open vents
  never reaches the bands. The two bang-bang readings then **never sit inside their
  bands in the same scan**. PT3 and PT13 read the pressurant lines directly (no board
  hold since D12). Each loop reaches its band (PT13 at t≈2.0 s, PT3 at t≈2.5 s), then
  the gas left in its pressurant line equalises into the tank after the solenoid closes
  and parks the reading 8–13 psi above the band (PT3 927, PT13 898), where it stays
  because the plant has no boil-off, leak or board vent output. This is a property of
  the plant model and the recorded deadband, not of the scan loop.
* **The vents stay closed through the hotfire.** The pre-press manual PB1/PB3 close stays in
  force when the sequence starts (D16), as in the 12:49 recording, until the abort chain
  opens them.
* `examples/abort_monitor.st` ships **disarmed** — `abort_monitor_enable : BOOL :=
  FALSE` — so loading the examples and pressing run changes nothing. Its three
  thresholds are still `0.0` placeholders, which means arming it without configuring
  them first makes `auto_abort_request` go true on any positive reading and latches an
  abort on the next scan. Scenario 0 shows both halves: disarmed on load, then the
  operator arming it through the ordinary `plc.globals.abort_monitor_enable` path with
  the placeholders untouched. The other scenarios leave it disarmed and arm the scan
  loop's own threshold table instead — no forces and no invented trip pressure. Every
  threshold in `SimConfig` likewise defaults to disabled at 0.0 with a
  `PLACEHOLDER -- operator-set` label.
* A mean `step()` costs about 0.4 ms on the development machine, against a 20 ms scan
  period at 50 Hz — roughly 2 % duty, with the plant sub-stepping dominating.
