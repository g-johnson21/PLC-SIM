# Architecture decisions (signed off 2026-09-12)

Supplements the orchestrator brief. Where the two disagree, this file wins.

## D1. Tag naming authority
DAQ log columns (`docs/data-survey.md`) are authoritative for what is instrumented. Canonical tag names
are the P&ID tags where a P&ID tag exists; DAQ-only channels keep their DAQ name (e.g. PT0, TC6–TC8).
Every tag records its P&ID tag, its exact DAQ column header, and any command-log alias. Alias lookup
must be unambiguous: load-cell P&ID numbers collide with DAQ numbers, so P&ID LC names are stored in a
`pid_tag` field and are NOT alias-lookup keys.

## D2. Bang-bang feedback
PT3 is the LOX bang-bang board pressure (`bb-ox board psi`); PT13 is the fuel bang-bang board pressure
(`bb-fuel board psi`). Loops: PT3 → S1, PT13 → S2, exactly as in the brief. Setpoint and deadband are
operator-set. The real board also has a `vent` output; the simulator records it from data but the
regulation logic actuates the press solenoid only (vent behaviour is an open item).

## D3. Valve mapping (DAQ discrete channel → P&ID tag)
| DC | Log name | P&ID | Normal state | Function |
|---|---|---|---|---|
| DC1 | SV-LOXBB | S1 | NC | LOX bang-bang press solenoid |
| DC2 | SV-FBB | S2 | NC | Fuel bang-bang press solenoid |
| DC3 | SV-LOXV | PB1 | NO | LOX tank GN2 vent |
| DC4 | SV-FV | PB3 | NO | Fuel tank GN2 vent |
| DC5 | MV-LOX | PB2 | NC | LOX main run valve |
| DC6 | MV-F | PB4 | NC | Fuel main run valve |
| DC7 | SV-FPURGE | S5 | NC | Fuel line purge |
| DC8 | SV-LOXPURGE | S4 | NC | LOX line purge |
| DC9 | SV-LOX-FILL | PB5 | NC | LOX fill / tank outlet isolation |
| DC10 | SV-MBV | S3 | NC | Muscle-bus (actuation air) vent |
| DC11 | SV-GOX-PURGE | PB6 | NC | LOX run-line GOX vent/purge |

Polarity, confirmed from the log: the `DCn (state)` column is the functional state (1 = open).
`Solenoid Command: n | b` is the electrical energize bit. For NO valves (PB1, PB3) open ⇔ b = 0.
For NC valves open ⇔ b = 1. The tag database must carry both `normal_state` and this polarity rule.

## D4. Placeholder sequences
The recorded hotfire and GN2-purge sequences from `Draco_20260911_124919` (see data-survey) may be used
as the SFC placeholders, including the recorded abort chain. They are still placeholders: the human-
supplied procedure replaces them later.

## D5. Load cells
Canonical: LC1/LC2/LC3 = thrust cells A/B/C (P&ID LC-R/LC-G/LC-B), LC4 = LOX tank weight (P&ID LC1),
LC_FUEL = fuel tank weight (P&ID LC2, not present in the 2026-09-11 logs), THRUST = derived sum.

## D6. Repo layout and toolchain
Python 3.13, numpy 2.3, PyYAML available; Node 24 / npm 11 for the frontend. No git repo yet.
```
backend/                    pyproject.toml, package draco_sim
  draco_sim/tags/           task 1  tag database + loader
  draco_sim/data/           task 1  DAQ CSV loader
  draco_sim/hwio/           task 2  NI card simulation
  draco_sim/plant/          task 3  physics
  draco_sim/plc/            task 4  LD/ST/SFC engine
  draco_sim/runtime/        task 5  scan loop
  draco_sim/protocol/       task 6  WebSocket JSON
  examples/                 sample PLC programs
frontend/                   React + Vite + TypeScript (tasks 7, 8)
docs/                       specs and contracts
testdata/                   real DAQ CSVs (read-only)
```

## D7. Cross-task contracts
- Task 1 exposes `TagDatabase.plc_specs()` returning a list of `{name, direction: "in"|"out",
  dtype: "REAL"|"BOOL", units}`. Task 4 consumes exactly that shape via `draco_sim.plc.TagSpec` and
  must not import from `draco_sim.tags`.
- Sensors are read-only inside PLC programs; the 11 valves are the only writable outputs plus
  reserved spare DO channels.
- Scan order (task 5, non-negotiable): auto-abort thresholds → manual-abort bit → abort action
  (skip rest) → sequencer → bang-bang/regulation → write outputs.

## D8. Plant topology corrections found during task 3 (2026-09-12, orchestrator-accepted, user to confirm)
- **PB5 sits on the dewar fill line**, not on the LOX tank outlet: the P&ID draws B1 → PB5 → C5 between
  the dewar and the tank-outlet tee, and the recorded hotfire flowed LOX with PB5 closed for the whole
  run. The LOX tank outlet is therefore unvalved in the model. D3's "tank outlet isolation" wording is
  superseded; PB5 = LOX fill.
- **The GN2 bottles are modelled as two independent banks** (LOX side, fuel side): PT1 and PT11 sit
  900–1350 psi apart for hours in every logged run, which a common manifold cannot do. The brief's
  single-manifold topology is available via `PlantConfig.bottles_common_manifold = 1`.
- **Bang-bang board readings PT3/PT13 are zero-order held** (`bb_board_update`, placeholder 1 s). With
  the recorded 15 psi deadband this makes each loop limit-cycle roughly ±150 psi. Calibrate before
  drawing conclusions about loop tuning.

## D9. Protocol race window (documented behaviour, not a defect)
`abort` is acknowledged when the manual-abort bit is set; the latch engages at the top of the next
scan (≤ one scan period). A `write` to an output that lands inside that window while a sequence is
running is refused with `rejected` ("sequence active") rather than `abort_active`. Either way the
write does not take effect.

## D10. Rules added during integration review (2026-09-13, orchestrator)
- **Program roles come from the code.** SFC → `sequence`; ST/LD that writes any output tag → `regulation`;
  otherwise `monitor` (`CompiledProgram.output_writes` is the compile-time source). An explicit `role` on
  `program.load` may relabel a program but may not contradict its code: an SFC must be `sequence`, a
  non-SFC cannot be `sequence`, and a program that writes outputs cannot be `monitor`.
- **An abort switches off every non-SFC program that writes an output tag**, whatever its label.
- **Fail-safe on abort** (orchestrator decision, reversible, user to confirm). On the latch scan, valves
  last driven by a switched-off program drop to their fail-safe state (NC closed, NO open) unless the
  abort chain of a loaded SFC writes them. The abort chain is the declared `abort_step` and every step
  reachable from it; chain-owned valves follow the chain. Reason: the brief requires the abort action to
  run and the P&ID's normal states define the safe state. Without this rule a press solenoid stayed open
  through an abort when no abort chain was loaded, and the tank kept filling. While latched, a forced
  output keeps its forced value; a valve an abort chain writes, once the PLC has driven it, follows the
  PLC image; every other valve is fail-safe until `abort_clear`. A chain valve in a branch the chain never
  reaches stays under chain control at its last value. `CompiledProgram.abort_writes` holds each chart's
  chain write set.
- **The in-browser mock is a development aid only.** Production builds never fall back to it.
  Development builds fall back after 2 s, say so in a banner, and offer an explicit switch once the
  backend is reachable.
- **Non-WebSocket traffic on the protocol port logs one line** (DEBUG, or INFO with `--verbose`), never
  a traceback.

## D11. Open items for the stand team (as of 2026-09-13; answered in D12)
1. **Fuel identity.** Not stated anywhere; blocks every fuel-side calibration.
2. **Fuel tank pressurisation.** S2 (DC2) is never commanded in the 2026-09-11 recordings, yet the fuel
   tank exceeds 800 psi.
3. **Venturi discrepancy.** The logged ΔP across V1 with CdA 3.22e-5 m² implies about 3 kg/s of LOX,
   which cannot produce the logged 128 lbf.
4. **Vent capacity and procedure.** The PB1 placeholder vents about half as fast as the stand: after the
   12:49 abort, recorded PT4 fell 694 → 285 psi in 5 s against 694 → 505 psi modelled. The simulator
   lets a tank reach setpoint with its vent open, while every recorded press above 300 psi had the vent
   closed. Calibrate the vent, and decide whether PLC programs should interlock pressurisation on vent state.
5. **Confirm** the D8 topology corrections and the D10 abort output rules, including that an operator
   force still holds a valve through an abort, as on a real PLC.
6. **Real hotfire procedure** to replace the placeholder sequences in `backend/examples/`.
7. **Regression suites.** Recommended by every implementation agent; not built, per the house rules.
8. **CODESYS on CompactRIO.** Its current status sets how large the in-app caveat should be.

## D12. Stand-team answers (2026-09-13, user)
- **Fuel is isopropyl alcohol.** Fuel-side properties come from published IPA data.
- **Bang-bang loops ran on the previous system's own controller board.** S1 and S2 openings are therefore
  recorded in the bang-bang board columns, not in DC1/DC2 (which only carry GC manual commands).
- **The 12:49 recording is a failed hotfire.** The engine suffered a RUD, the abort was manual, and the
  thrust load cells and chamber PT failed at that moment. PT0, LC1–LC3 and THRUST are invalid from the RUD
  onward; the venturi data is not in question.
- **Calibrate vent and press-up against the recordings.** With both calibrated, pressurising with a vent
  open should behave realistically.
- **PB5 is the LOX fill valve, and the GN2 bottles form two separate buses.** D8 is confirmed.
- **Abort is absolute.** It overrides every other commanded position, operator forces included. When the
  abort sequence is over the stand is safe and the operator is in control again, with no manual clear.
  Supersedes D10's force precedence and the `abort_clear` requirement.
- **Real hotfire procedure** (replaces the recorded placeholder):
  T+0.00 PB2 open · T+0.50 PB4 open · T+8.00 PB2 close · T+8.50 PB4 close · T+8.70 S4 and S5 open ·
  T+11.70 S4 and S5 close.
- **Build regression suites.**
- **CODESYS on CompactRIO: dropped.** The in-app non-replica notice stays as required by the brief.

Orchestrator refinements to implement D12 (reversible, reported to the user):
- Auto-abort thresholds evaluate real card readings, so a forced input can never mask a trip. PLC
  programs still see forced values.
- Output forces are cleared when an abort latches.
- Control returns when every loaded abort chain is complete and no enabled threshold is still tripped. A
  tripped threshold on a failed sensor can be disabled during the latch, so a broken gauge cannot trap the
  stand in abort. PLC stop, PLC reset and program loads are refused while latched.
- Simulated PT3/PT13 are no longer held for 1 s: that stepping was the old board's telemetry, not the
  transducers the cRIO reads.

## D13. S1/S2 open state in the recordings (2026-09-13, orchestrator, from the data)
S1 and S2 are open when either the old board's telemetry press command (BBD field 3) or the GC's manual
command (DC1/DC2) says so. Both actuate the same solenoids. In the 12:52 safing run the GC alone opened S1
(302.82–330.53 s) and S2 (317.08–337.82 s), bleeding PT1 from 3534 to 6 psi and PT11 from 4826 to 0 psi,
with no board activity. Board pulses in the 12:36 run are about one telemetry sample wide (100 ms), and each
fuel pulse raised PT14 by roughly 110–125 psi. Their true open time is therefore not identifiable from
telemetry, so flow areas are fitted from the pressure-rise rate at 40 Hz.

## D14. Safe state after an abort and with the PLC stopped (2026-09-14, user)
- **After an abort the stand returns to a safe state.** Nothing re-arms itself: programs the abort
  switched off stay off after control returns, until the operator re-arms them with `plc.reset`
  (or `sim.reset` / `program.load`). Enabling a bang-bang loop whose program is still off is
  refused. Outputs hold the abort sequence's end state.
- **A stopped PLC is a safe state.** Every coil is de-energized, so there is nothing to abort:
  `abort` is refused while the PLC is stopped, and `plc.stop` drops an abort request that has not
  latched yet, so it cannot latch later on `plc.run`.

## D15. Plant calibration against the recordings (2026-09-14, orchestrator, from the data)
- **Fitted by a script, not by hand.** `python -m draco_sim.plant.calibrate` writes
  `calibration.yaml` (source `calibrated`), which `Plant()` and the runtime load by default.
  It fits `pb_dead_time`, `cda_pb1`, `cda_pb3`, `cda_s1` and `cda_s2`. Details are in
  `docs/plant-model.md` §6.
- **No fuel run-line fill.** The ~0.4 s gap between PB4 opening and fuel venturi ΔP in the
  12:49 hotfire also appears between PB2 and LOX venturi ΔP (0.392 against 0.390 s). It is
  PB actuation delay, modelled as `pb_dead_time` = 0.23 s once the 0.14 s command-logging
  latency seen on the solenoids is subtracted.
- **Press areas come from the rise rate** (D13), so replaying telemetry pulse widths under-fills
  the tanks. The bang-bang loops in the simulator are unaffected.
- **Vent-open pressurisation is improved but not yet realistic.** The tanks no longer reach relief
  with the vents open. Against the 12:52 GC-only opens, though, the model still holds the tank
  2× (fuel) to 4× (LOX) too high relative to supply. The areas were not bent to match, because
  that would break the closed-vent rise rates.
- **Bottle split left open.** The LOX-bus mass balance implies 2.6–2.9 bottles at the placeholder
  200 K ullage temperature, which is not identifiable from these runs.
- **The demo closes PB1/PB3 before pre-press,** as the 12:49 recording does. With calibrated vents,
  pre-press against open vents never reaches the bands. Since D16 that manual close stays in force through
  the hotfire.

## D16. Manual commands across a sequence start; no temperature physics (2026-09-14, user)
- **Starting a sequence does not release manual commands.** Only an abort does. A stopped PLC still
  holds every coil safe (D14) and also drops them. New manual writes stay refused while a sequence
  is active.
- **Orchestrator refinement (reversible):** when a running chart writes a coil, the manual command
  on that coil is released, with a `[warn]` event. Without it a manual `PB2 = open` set before the
  hotfire would re-open the LOX main valve right after the chart's one-scan close at T+8.
  Abort-chain-only coils such as PB1/PB3 keep their manual commands until the abort clears them.
- **No tank or line temperature physics.** The vent-open mismatch in D15 stays a documented
  limitation.

## D17. A stopped PLC stays safe; a bang-bang loop owns its solenoid only while enabled (2026-09-15, user)
- **A stopped PLC returns the stand to its safe state and keeps it there when it runs again.** Every
  valve goes to its default state. In the user's words: "Things shouldn't be happening without the
  ground controller being aware and in control." `plc.stop` therefore clears everything that could
  command a valve on the next `plc.run`: manual commands, output forces, running sequences, both
  bang-bang enables and the PLC output image. D16 already said a stop drops manual commands, but
  the code did not (task 5, defect 1).
- **Orchestrator refinement (reversible):** the stop is a cold restart of the PLC runtime.
  - Program variables return to their declared values, so an armed `abort_monitor` is disarmed and
    operator-written `plc.globals` are lost.
  - Faults clear, and halted programs restart on run.
  - Kept: the program set, input forces, the HMI setpoints and deadbands (re-mirrored), and the
    programs an abort switched off (D14).
  - A program that writes an output unconditionally still drives it once the ground controller runs
    the PLC.
- **A bang-bang loop controls its solenoid only while enabled; disabled, the ground controller can
  actuate it.** Both example loops write the solenoid only while enabled. On the scan they are
  disabled they close it once, so a loop disabled mid-press does not leave S1/S2 held open.
- **Orchestrator refinement (reversible):** while a loop is enabled, manual writes to its solenoid
  are refused with `rejected` and `details.loop`, and enabling a loop releases a manual command on
  its solenoid with a `[warn]` event. Inside the hysteresis band the loop writes nothing, so a
  left-over manual open would otherwise keep pressing.
