# Draco simulator handoff

Paused 2026-09-14 at the user's request. No agents are running. Resume from this file.

## Snapshot

- **Phase 1** (build stages 1–9) is complete and was reviewed on 2026-09-13. The published review is now
  outdated by phase 2: https://claude.ai/code/artifact/ec3bb330-2764-4300-aa59-98860f7d38c2
- **Phase 2** implements the stand team's answers of 2026-09-13 (`docs/decisions.md` D12) and the S1/S2
  rule derived from the data (D13).
- **Backend tests:** task 3 completion run on 2026-09-15: `python -m pytest -q` from `backend/` gives
  568 passed, 2 xfailed in 28.87 s. Only the two task 6 plant guards remain xfailed; all 219 PLC cases pass.
- **Frontend:** `npm test` gives 105 passed. `npm run build` passes. `npm run lint` shows one existing
  warning in `src/gc/useSeriesBuffer.ts`.
- **Demo:** `python -m draco_sim.runtime.demo` exits 0 with the new hotfire procedure.
- **Calibration:** `python -m draco_sim.plant.calibrate` (about 70 s) writes
  `backend/draco_sim/plant/calibration.yaml`, which `Plant()` and the runtime load by default.
- **Authority:** `docs/decisions.md` D1–D17 overrides the original orchestrator brief wherever they differ.

| # | Task | Status |
|---|---|---|
| 1 | Absolute abort and automatic return of control | Done 2026-09-14: docs updated, code reviewed and probed, user decision D14 implemented |
| 2 | Plant phase 2: IPA, board hold removal, calibration | Done 2026-09-14: five constants calibrated, vent-open answer, docs, D15 |
| 3 | PLC engine regression suite | Done 2026-09-15: both engine bugs and the abort-test finding fixed; 219 passed, no PLC xfails |
| 4 | Control panel update for the new abort semantics | Done 2026-09-15: panel, IDE toolbar, mock and 12 vitest cases; browser-checked against the real backend |
| 5 | Scan-loop and protocol regression tests | Done 2026-09-15; both defects it found fixed by user decision D17 the same day |
| 6 | Plant regression tests | Done 2026-09-15: 116 tests, 2 strict xfails for divide-by-zero configs awaiting the user |
| 7 | Integration re-review and republish | Queued, unblocked by task 3 completion |

## Working rules for whoever resumes

- **Agents:** give each task one fresh agent with a compact, self-contained brief. That brief should hold
  the state on disk, an end-state checklist, exact names and scope, and only the doc sections to read. Tell
  agents to grep and read line ranges, never dump whole files, docs or CSVs, keep command output short, and
  report compactly. Resuming long agent transcripts hit the session limit repeatedly (2026-09-12, 09-13
  twice, 09-14 twice), which is why this rule exists.
- **Model tier:** Opus for the plant and calibration, the scan loop and abort logic, and the PLC engine.
  Sonnet for data and loader work, the frontend, protocol plumbing and most tests.
- **House rules:** minimal organic comments. Never invent component values; every plant constant carries
  a source of P&ID, user, datasheet, physical-constant, PLACEHOLDER or calibrated. Test fixtures are slices
  of the real recordings.
- **Keep the backend importable after every edit**, so a cutoff never leaves it broken.
- **Environment:** git repo on `main`, public at https://github.com/g-johnson21/PLC-SIM (created
  2026-09-15). `testdata/` (raw DAQ CSVs) is gitignored and exists only locally. The backend listens on port 8765 by default. The `backend-server`
  entry in `.claude/launch.json` pins this machine's Python path. pytest 9.1.1 is installed.

---

## Task 1: Absolute abort and automatic return of control

### 1. Current goal
Implement D12. An abort overrides every commanded position, including operator forces. Control returns to
the operator automatically when the abort sequence is over. The real hotfire procedure runs on time at any
scan rate, and the panel state and the docs match all of this.

### 2. Current development status
The code landed on 2026-09-14 in `backend/draco_sim/runtime/simulator.py`,
`backend/draco_sim/runtime/demo.py` and `backend/examples/hotfire.sfc.json`. The agent that wrote it hit
the session limit before reporting. The orchestrator probed the current code with a scratch script that was
not committed:

| Behaviour | Result |
|---|---|
| Hotfire commands at 50 Hz and 30 Hz | Every command lands exactly at T+0.00, 0.50, 8.00, 8.50, 8.70 and 11.70 |
| Abort mid-burn | Latches with `waiting_on: ["hotfire at ABORT"]`. Control returns by itself when the chain completes. PB1 and PB3 are open, and a manual valve write is accepted afterwards |
| Output force at the latch | Cleared. New output forces are refused with `abort_active` |
| Forced input against a threshold | PT1 forced to 0 while the real reading is 4000 psi still trips `PT1 > 100` |
| Threshold still tripped at chain end | Holds the latch with `"PT1 > 100 still tripped"`. Disabling the threshold returns control |
| `bangbang_lox` alone | S1 closes at the latch. Control returns within two scans, the setpoint survives, and the enable and panel state read OFF |
| Refusals while latched | `plc.stop`, `plc.reset` and enabling a loop are refused. A setpoint edit is accepted |
| `abort.clear` | Acknowledged when not latched. While latched it is rejected with the pending reasons |

Finished on 2026-09-14 (second pass):
- **Docs.** `docs/runtime.md` covers scan steps 1–6, the latched arbitration table (the force row is
  gone), §3 lifecycle (refusal table, `waiting_on`, return of control, held latch, instructor reset,
  `abort_clear`), events and the six demo scenarios. `docs/protocol.md` has the namespace rows,
  message comments, `state.abort.latched`/`waiting_on`, a new "Abort lifecycle" section and
  arbitration rules 1 and 4. `docs/plc-language.md` §6.4 has a pointer, and §6.5 is now the new
  procedure's START / OPEN_LOX_MAIN / OPEN_FUEL_MAIN excerpt.
- **Review probe** (scratch, not committed). Every result matches the docs:
  - `program.load` while latched is refused with `abort_active`.
  - `sim.reset` while latched clears the latch and `tripped`, re-enables every program, keeps the
    PLC running and sets t to 0.
  - Snapshots, `abort.waiting_on` reads and `abort_clear` calls do not perturb the run.
  - At 30 Hz, control returns 5.333 s after the latch with only PB1 and PB3 open.
  - The engine at dt = 10 ms fires PB2 on scan 1, PB4 on 51, PB2 close on 801, S4 and S5 on 871,
    and the close on 1171.
  - Writing `abort_monitor_enable` false releases a latch held by the monitor's request.
  - The backend suite gives 273 passed and 6 xfailed.
- **D14, the user's answers, implemented** in `simulator.py` and `demo.py`, with the docs updated:
  1. **Nothing re-arms after an abort.** Programs the latch switched off stay off after control returns,
     and an `[abort] programs left off until plc.reset re-arms them` event names them. `plc.reset`,
     `sim.reset` or `program.load` re-arms them. Until then, enabling a bang-bang loop whose program
     is off is rejected with `rejected`. A `PB2 := TRUE;` program now leaves PB2 closed after return.
  2. **A stopped PLC is safe.** `abort` and writing `hmi.abort` true are rejected with `rejected`
     while stopped. `plc.stop` drops an abort request that has not latched yet.
  - Probed with a scratch script: a second abort after return, re-arming after `plc.reset`, and
    abort, stop, run with no late latch. The backend suite gives 273 passed and 6 xfailed, and the
    demo exits 0.
- `handlers.py` needs no change: every refusal is raised by the Simulator.
- Runtime and protocol tests are task 5.

### 3. Key decisions made
- **D10:** program roles come from the code. An abort switches off every non-SFC program that writes an
  output, whatever its label. On the latch, outputs go fail-safe unless a loaded SFC's abort chain writes
  them (`CompiledProgram.abort_writes`).
- **D12, from the user:** abort is absolute, including over operator forces. Control returns
  automatically once the abort sequence is over. The user supplied the real hotfire procedure.
- **D12, orchestrator refinements (not yet user-confirmed):**
  - Thresholds evaluate the real card readings, while programs still see forced values.
  - Output forces are cleared at the latch.
  - Control return waits until no enabled threshold is tripped, and a tripped threshold can be disabled
    during the latch. The RUD froze PT0, so a broken gauge must not trap the stand.
  - PLC stop, PLC reset and program loads are refused while latched. `sim.reset` stays allowed as an
    instructor action.
- **On return of control:** PLC variables are not reset, charts are stopped, and outputs hold where the
  abort left them. The panel's bang-bang enables are forced OFF. `abort.clear` stays for compatibility.
- **Hotfire timing:** transitions compare `SYS_TIME - t_start` against T+, with `t_start` captured at
  T+0, so timing does not drift with scan rate. No engine change was needed. The abort chain is unchanged:
  it is the stand's recorded abort sequence.

### 4. What worked and what failed
- **Worked:**
  - The 2026-09-13 fail-safe rule passed a browser end-to-end check: an IDE-loaded loop's S1 closed on
    the latch scan.
  - Keying transitions to `SYS_TIME` gives exact timing at 30 and 50 Hz.
  - Probing behaviour directly caught what agent reports missed.
- **Failed:** four agent runs on this task were cut off by session limits. Resuming them with long
  transcripts burned the quota, and the final run landed its code without a report.

### 5. Immediate next steps
1. **Start tasks 4 and 5.** The docs are current, including D14, so their briefs can cite them.

### 6. Open risks, questions, or blockers
- **Tested since tasks 3 and 5.** An abort during `gn2_purge`, two charts with abort chains, a chain
  with no final step and an abort while a valve writer is faulted are covered. Task 3 also verifies
  a faulted SFC entering its abort chain, and a fault inside an abort chain holding the latch until
  its cause is fixed and `plc.clear_faults` lets the chain finish.
- **Hold before return.** The real GC logged "Abort cleared — stand is DISARMED" 3.0 s after its abort
  sequence ended. The simulator returns control immediately at chain end and does not model arming. Ask
  the stand team.
- **Stale panel.** Resolved by task 4 on 2026-09-15: "Clear abort" is gone from the panel and the IDE toolbar.

---

## Task 2: Plant phase 2 (IPA, board hold removal, calibration)

### 1. Current goal
- Apply the confirmed facts: isopropyl alcohol fuel, two separate GN2 buses, and PB5 as the LOX fill valve.
- Remove the simulated 1 s hold on PT3 and PT13.
- Calibrate the vents, press-up and fuel run-line fill against the recordings with a reproducible script.
- Answer the user's question, with numbers, of whether pressurising with a vent open now behaves
  realistically.

### 2. Current development status
Done 2026-09-14, inline with no agents. On disk:
- **`plant/config.py`:**
  - IPA properties: `rho_fuel` 785 kg/m³ and `pvap_fuel` 0.68 psia, source physical-constant,
    anhydrous assumed.
  - `bottles_common_manifold` has source user, and PB5 is noted as the LOX fill valve.
  - New source `calibrated` and new constant `pb_dead_time`. `bb_board_update` is removed.
  - New `PlantConfig.calibrated()`.
- **`plant/plant.py`:**
  - PT3/PT13 read the press-line nodes directly, and PB valves apply the dead time.
  - `set_initial` gains `valves=` (starts valves settled) and `lox_press_up_psi=`.
  - `Plant()` defaults to the calibrated config, and so does `SimConfig`.
- **`plant/calibrate.py`** writes `plant/calibration.yaml`: `pb_dead_time` 0.23 s, `cda_pb1` 2.7e-5,
  `cda_pb3` 4.57e-5, `cda_s1` 8.04e-6 and `cda_s2` 7.83e-6 m².
- **`plant/replay.py`:**
  - New `--uncalibrated` option.
  - Seeds from PT4/PT14/PT2 with valves settled in their logged state.
  - Excludes annotated invalid windows, and compares held columns (board PT3/PT13) like for like.
  - `simulate()` and `compare()` are reusable.
- **Demo:** pre-press now closes PB1/PB3 first. The demo and `docs/runtime.md` text describe the new
  bang-bang behaviour.
- **Docs:**
  - `docs/plant-model.md` §1, §3 and §5, plus §6 (calibration table, vent-open answer, replay RMS before
    and after). §7 is regenerated.
  - README "Calibration status" and D15.
- **Checks:** backend 273 passed and 6 xfailed; the demo exits 0.

### 3. Key decisions made
- **D12:**
  - The fuel is isopropyl alcohol. Use published properties with source physical-constant, and state an
    anhydrous assumption.
  - The two separate GN2 buses make `bottles_common_manifold` source user.
  - PB5 as the LOX fill valve keeps its current placement.
  - Calibrate the vents and press-up from the data.
- **The 12:49 recording is a failed start** with a RUD. Throat area, c* and Cf stay placeholders, and the
  RUD is not modelled. The 128 lbf reading was a start transient, which resolves the venturi discrepancy.
- **Remove the 1 s board hold** from simulated PT3 and PT13. It was the old board's telemetry, not the
  transducers the cRIO reads. Keep a hold only inside the replay comparison, and only if the logged
  board-psi column is visibly stepped.
- **New constant source `calibrated`**, written by a deterministic least-squares script. Each value's notes
  carry its window, method and residual. `calibration.yaml` loads by default, with an option for
  uncalibrated values.
- **D13:** S1 or S2 is open when either the board or the GC commands it. Board pulses are about one 100 ms
  telemetry sample wide, so fit flow areas on the 40 Hz pressure-rise rate or on area × duration, never on
  telemetry duration.
- **D15:**
  - PB actuation delay replaces the planned "fuel run-line fill": PB2 and PB4 lag equally, 0.390 and
    0.392 s.
  - Areas are fitted on rise rate.
  - Vent-open behaviour was checked against 12:52 but not tuned to it.
  - The bottle split stays a placeholder.

### 4. What worked and what failed
- **Worked:**
  - The replay harness baseline: correlations of 0.86 to 0.95 on the tank, pressurant-line and LOX
    venturi transducers in the 12:49 recording.
  - The vent check. After the 12:49 abort opened PB1, recorded PT4 fell from 694 to 285 psi in 5 s; the
    model fell only to 505 psi, so the placeholder vent is roughly half as fast.
  - Every recorded press above 300 psi had its vent closed.
- **Failed:** the first plant agent concluded that S2 was never commanded. The loader was dropping the
  board columns, and the fuel press column is all zeros. Board telemetry parsing fixed it. Both phase-2
  launches were cut off before editing.
- **Worked (2026-09-14):**
  - Fitting only on rows where the transducer updated (about 10 Hz).
  - Rise-rate fits: 20 pulses agree within about 2×.
  - The two LOX vent windows alone give 3.5e-5 and 2.4e-5.
  - The 12:49 fuel channels' RMS fell from 107 to 35 psi.
  - Doing the work inline avoided cutoffs.
- **Failed (2026-09-14):**
  - Vent-open realism: against the 12:52 GC opens the model is still 2× (fuel) to 4× (LOX) too high.
  - The 12:52 trapped-line decay fits poorly (bus RMS 256–340 psi).
  - The planned run-line fill fit was based on a wrong premise.

### 5. Immediate next steps
1. **Task 6 is unblocked.** Test `calibrate` piece by piece rather than through the 70 s full run.
   `fit_dead_time`, `_observed_rate`, `fit_gas_volumes` and one short vent window are fast and
   deterministic. Take replay error ceilings from the calibrated config.
2. **Ask the stand team** open questions 7 to 9 below.
3. **Tasks 4 and 7** should expect no bang-bang limit cycle: readings settle 8–13 psi above the band.
   Manual commands now survive a sequence start (D16), so the panel must not assume a start clears
   them.

### 6. Open risks, questions, or blockers
- **Vent-open realism.** It is improved, but still 2× (fuel) to 4× (LOX) too high against 12:52. On
  2026-09-14 the user decided against tank and line temperature physics (D16), so this stays a documented
  limitation.
- **Manual commands across sequences (D16)** are pinned by `tests/runtime/test_sequences.py`. Task 5
  found that a stopped PLC does not drop them as D16 says (defect 1 in task 5).
- **Replay under-fills pressurant pulses.** Telemetry pulse widths are shorter than the true open time,
  so the 12:36 fuel RMS rose from 211 to 288 psi. The simulator's own bang-bang loops are unaffected.
- **Identifiability.**
  - The bottle split and the ullage temperature trade off: the data implies 2.6–2.9 LOX bottles at 200 K.
  - The fuel vent and S2 areas scale with the 39.5 lbm fuel load estimated from 12:36.
- **No boil-off or flashing.** The 12:36 LOX channels stay near 310 psi RMS, and vent windows stop above
  about 250 psi.
- **IPA concentration** is assumed anhydrous.
- **Engine performance** stays uncalibrated until a successful hotfire is recorded.

---

## Task 3: PLC engine regression suite (done 2026-09-15)

### 1. Current goal
Pin the documented semantics of `draco_sim.plc` with a fast, deterministic pytest suite that imports
only the engine.

### 2. Current development status
Reviewed against `docs/plc-language.md` and completed on 2026-09-15. `backend/tests/plc/` now holds
97 test functions in 10 files plus `helpers.py`, covering ST parsing, function blocks, SFC evolution
and aborts, ladder and `ladder_to_text`, faults, forcing, determinism, write sets and diagnostics.

**All three issues resolved:**
1. **Diagnostic rendering:** `plc/errors.py` now renders `CompileError.__str__()` from the current
   fields, so program names and JSON pointers attached after parsing appear in the text. Tests cover
   ST, SFC action bodies and transition conditions, and individual/aggregate syntax diagnostics.
2. **Loop cap:** `For`, `While` and `Repeat` in `plc/nodes.py` check the cap before entering an
   iteration. Exactly 10,000 iterations are allowed; iteration 10,001 faults before its body runs.
   Tests cover 9,999/10,000/10,001 and `EXIT`/`RETURN` at and beyond the cap. All six old xfails removed.
3. **Disabled/halted abort charts (review finding P2):** the old test restored execution before
   checking outputs, hiding an abort scan that reported `ABORT` while leaving `DO1` open and running
   no actions. `plc/runtime.py` now lets these charts execute their abort chains on the latch scan.
   The strengthened test checks output writes and actions immediately, then chain completion without
   manual recovery, for disabled, halted and combined states. Additional tests cover disabled-state
   preservation, faults inside the chain, explicit recovery, and unaffected halted programs without
   an abort chain.

**Integration and docs:**
- `tests/runtime/test_abort_lifecycle.py` verifies a faulted SFC safes and returns control, and a
  fault inside an abort chain holds the latch until its cause is fixed and faults are cleared.
- `tests/protocol/test_abort_and_programs.py` checks ST and SFC syntax diagnostics over WebSocket,
  including program, pointer and fragment-relative line/column. The IDE's problems list and editor
  markers were checked in source: they consume these structured fields, not `str(CompileError)`.
- `docs/plc-language.md` §6.4, §7.2 and §7.5, `docs/runtime.md` §3 and README are updated.

**Validation:** PLC **219 passed in 0.44 s**, no xfails; full backend **568 passed, 2 xfailed in
28.87 s** (only task 6 plant guards); frontend **105 passed**; `npm run build` passes with its bundle-size
warning. The new assertions first reproduced the failures before the engine fixes.

### 3. Key decisions made
- The original pass was tests only. The user authorized completion, including engine fixes, on 2026-09-15.
- Engine tests build programs inline and import only the engine; they do not depend on stand examples.
- The documented cap permits 10,000 iterations; check before executing an extra body so `EXIT` and
  `RETURN` cannot bypass it.
- An explicit abort starts the safing chain even after a prior program fault: clear that chart's
  execution halt once, retain fault history and variables, and override a disabled setting only while
  latched. Preserve the setting itself. New faults inside the chain still halt it; later scans do not
  automatically retry. `clear_faults()` allows a retry; a new explicit engine `trigger_abort()` starts
  the chain again. Other halted programs are unaffected.

### 4. What worked and what failed
- **Worked:** comparing assertions with the contract and probing outputs before test recovery calls
  exposed the masked abort discrepancy. Tests now check both successful safing and fault containment.
- **Failed historically:** three launches were cut off, and the original test agent left no report.

### 5. Immediate next steps
None for task 3. Task 7 is unblocked.

### 6. Open risks, questions, or blockers
No outstanding task 3 findings. A fault in an abort chain still requires explicit recovery as documented;
the simulator test verifies recovery from a nonterminal abort step through automatic return of control.

---

## Task 4: Control panel update for the new abort semantics (done 2026-09-15)

### 1. Current goal
Make the control panel reflect D12:
- Remove the manual clear.
- Show `state.abort.latched`, the `waiting_on` reasons, and a clear notice when control returns to the
  operator.
- Lock out every action the backend refuses while latched, and explain why: valve writes, sequence
  starts, PLC stop and reset, output forces, and enabling a loop.
- Keep setpoint edits and threshold editing usable during the latch, so an operator can disable a
  broken-sensor threshold.
- Apply D14:
  - Disable ABORT while the PLC is stopped; the backend rejects it.
  - After an abort, show the bang-bang loops as switched off until a PLC reset, and say that
    `plc.reset` re-arms them.
- Update the mock transport to carry the new fields.

### 2. Current development status
Done 2026-09-15, inline with no agents. On disk:
- **`frontend/src/gc/abortUi.ts`** (new, pure): `isLatched`, `waitingOn`, `abortOff`/`allAbortOff`,
  `lockoutReason(state, action, loop?)` mirroring every backend refusal, and `showReturnNotice`.
  Every panel takes its lockouts from here.
- **`AbortPanel`:** no manual clear. Shows ABORT LATCHED with the `waiting_on` strings, then OPERATOR IN
  CONTROL with a dismissable "stand safe" notice and the programs left off. ABORT is disabled with a
  reason while the PLC is stopped, and stays live while latched.
- **Lockouts with reasons:** valve clicks (`ValveSymbol`), sequence Start/Stop, PLC Stop/Reset
  (`PlcSimPanel` and the IDE `Toolbar`), Load to PLC, output-tag forces (`WatchTable`), and loop enable
  (`BangBangPanel`, only enabling; turning a loop off stays allowed). Setpoint, deadband and threshold
  editing stay usable; `ThresholdsPanel` explains how to release a failed-sensor latch.
- **D14:** `BangBangPanel` says "Switched off by the abort (…). PLC Reset re-arms it", and `PlcSimPanel`
  lists what Reset re-arms. `TopBar` banner shows `waiting_on`; the IDE toolbar lost "Clear abort".
- **Backend, additive:** `state.hmi.bb.<loop>.abort_off` (from `_abort_switched_off`), because the panel
  cannot tell which program drives which loop. Documented in `docs/protocol.md` (state shape and
  "Return of control") and `docs/runtime.md` §5.
- **Types and mock:** `AbortInfo.latched`/`waiting_on`, `BbLoopState.abort_off`, `PlcState.enabled`,
  `HmiState.manual`. The mock latches, refuses what the server refuses, returns control on the scan
  after the latch (no charts), rejects ABORT while stopped and `hmi.abort=false`, and `plc.reset` re-arms.
  Its `abort_off` stays `[]` because it compiles nothing.
- **Tests:** `gc/abortUi.test.ts` (9) and `protocol/mock.test.ts` (3). Frontend 102 passed, build
  passes, lint shows only the existing `useSeriesBuffer.ts` warning. Backend 273 passed, 6 xfailed.
- **Browser check against the real backend** (examples loaded): ABORT greyed while stopped; run, enable
  LOX, abort mid-press gave the banner and "waiting on hotfire at ABORT_4", locked sequence buttons and
  loop/threshold notes; control returned by itself with the notice, "left off: bangbang_lox,
  bangbang_fuel" and a greyed LOX enable; PLC Reset cleared the trip and re-enabled the loop button. No
  console errors.

### 3. Key decisions made
- The panel is a reference client of `docs/protocol.md` with no privileged shortcuts. The ABORT button
  never asks for confirmation.
- The return notice keys on `abort.tripped` (kept until `plc.reset`/`sim.reset`) rather than a latch
  edge, so a latch that drops between two 10 Hz updates (no chart loaded) is still announced.
- `waiting_on` strings are displayed, never parsed.

### 4. What worked and what failed
- **Worked:** pure lockout helpers tested in vitest's node environment (no DOM library needed); the
  real-backend browser check.
- **Failed:** the first browser ABORT click missed because the abort panel resizes when the PLC starts;
  clicking by element ref fixed it.

### 5. Immediate next steps
None for task 4. Task 5 can pin `hmi.bb.<loop>.abort_off` alongside the D14 cases.

### 6. Open risks, questions, or blockers
- Unexercised in the browser: a latch held by a tripped threshold (covered by unit tests and the
  backend probe only) and PLC Stop/Reset lockouts seen on screen (they were below the fold).
- The frontend's generated example copies regenerate on build and carry the new hotfire step names.

---

## Task 5: Scan-loop and protocol regression tests (done 2026-09-15)

### 1. Current goal
Pytest suites for `draco_sim.runtime` and `draco_sim.protocol` that pin the D10, D12, D13, D14 and D16
behaviour.

### 2. Current development status
Done 2026-09-15, inline with no agents. No production code changed. On disk:
- **`backend/tests/runtime/`** (94 passed, 3 strict xfails): `helpers.py` plus
  - `test_scan_order.py`: trip before the sequencer, thresholds on cards under a force, the one-scan
    program-request latency, the manual bit consumed at the latch, a stopped PLC, event stamping, and
    scan-rate continuity.
  - `test_arbitration.py`: rows 1–4, a forced output, a faulting scan writing nothing, and A1/A2 at the
    latch (no chain, a chain's own coils, a chart without a chain, vents going open).
  - `test_roles.py`: inference, install order, the four conflicts, `other`, the regulation label, the
    monitor staying on, and loads refused while running or on a compile error.
  - `test_abort_lifecycle.py`: the latch record, all 10 refusals (snapshot unchanged) and 10 accepted
    actions, output forces cleared, return at 50 and 30 Hz (5.3 s plus one scan), outputs held as
    manual commands, held latches (threshold and program request), two chains, a chain with no final
    step, an abort during `gn2_purge` or with a faulted program, `sim.reset` and `abort_clear`.
  - `test_safe_state.py` (D14): programs off until `plc.reset`, the three re-arm paths, a gateless
    `PB2 := TRUE;`, a second abort, `abort` refused while stopped, a dropped pending request, and a
    stopped PLC's outputs.
  - `test_sequences.py`: hotfire cards at T+ plus one scan at 50 and 30 Hz; D16 vent close surviving
    the hotfire, stale PB2 released once and never reopened, abort clearing manuals, the lockout
    until the chart parks.
  - `test_io_and_determinism.py`: atomic writes, read-only and unknown names, every namespace,
    snapshot shape and the always-present abort group, bang-bang mirroring, determinism with and
    without interleaved reads, and the pacer.
- **`backend/tests/protocol/`** (46 passed): `helpers.py` plus
  - `test_session.py`: the handler set matches the doc, welcome, protocol mismatch, malformed frames,
    20 error-code cases, `internal`, and `sim.rate`.
  - `test_abort_and_programs.py`: the abort round trip over the wire, `sim.reset` clearing a latch,
    the latch in a filtered subscription, role inference, `bad_request` and `compile_error` roles,
    `plc_running`, and `compile_result` (ST, LD `ladder_text`, errors).
  - `test_server.py`: subscribe and unsubscribe, the default groups and rate clamp, non-finite values
    and the codec, events to every client, a disconnect, a late joiner, 404 on other paths, the
    handshake-noise filter (unit and a real HEAD probe), and the real `run_server` entry point.
- **Housekeeping:** renamed to `test_s1_s2_valves_are_board_telemetry_or_gc_command`.
- **Checks:** backend 413 passed and 9 xfailed in 8.7 s; the protocol suite passed three runs in a
  row; pyflakes clean.

**Two defects found.** Both were resolved on 2026-09-15 by user decision D17, and their xfails are gone.
- **The fix, backend.** `plc_stop()` now cold-restarts the PLC and clears manual commands, output
  forces, charts and loop enables. Both example loops write their solenoid only while enabled and
  close it once on disable. While a loop is enabled, manual writes to its solenoid are refused, and
  enabling a loop releases a manual command on its solenoid.
- **The fix, panel and mock.** The panel lockouts and the mock mirror all of this.
- **Checks.** Tests were added in `test_arbitration.py` and `test_safe_state.py`. The demo's scenarios C and D
  were updated, and the docs (`runtime.md` §1/§2/§4/§8, `protocol.md` rule 3 and `plc.stop`,
  `plc-language.md` §4.3/§5.5/§7.3) were revised. It was browser-checked against the real backend:
  the S1 lockout while LOX is enabled, Stop and Run leaving everything closed and disabled, and a
  manual S1 open afterwards.

The defects as originally found:
1. **A stopped PLC does not drop manual commands.** `docs/runtime.md` §2 and D16 say it does, but the
   drop sits in `Simulator._arbitrate`, which never runs while stopped. A manual PB1 close made before
   `plc.stop` stays in `hmi.manual` and re-seals the vent on `plc.run`, the trap §2 warns about. The
   fix is to clear `_manual` in `plc_stop()`. (`test_safe_state.py::test_a_manual_command_does_not_survive_a_plc_stop`)
2. **A disabled bang-bang loop still owns its solenoid.** `docs/protocol.md` rule 3 says to disable
   the loop to move S1/S2 by hand, but `bangbang_lox.st` and `bangbang_fuel.ld.json` write the
   solenoid FALSE every scan while disabled, so a manual open never reaches the cards (the 12:52 GC
   bleeds of D13 are impossible with the examples loaded). Changing the programs to write nothing
   when disabled would let row 3 hold S1 open if a loop is disabled mid-press. That makes this a user
   decision, not a one-line fix. (`test_arbitration.py::test_a_disabled_loop_leaves_its_solenoid_to_manual_control`)

### 3. Key decisions made
- **Deterministic server tests.** The harness serves an injected `Simulator` on port 0 without the scan
  loop, and tests call `sim.step()` between messages. One smoke test runs the real `run_server` with
  `--no-realtime` on a free port. The harness repeats `run_server`'s three-line event fan-out.
- **No pytest-asyncio.** An `async_test` wrapper runs each coroutine with `asyncio.run` and a 30 s cap.
- **No invented stand data.** Initial conditions come from `demo.INITIAL`, and every trip level is 90 %
  of a live reading. Inline programs use real tags but no stand values.
- **Speed.** One template `Simulator` per variant is deep-copied per test (8 ms against 50 ms to build).
- **Defects stay as strict xfails** with exact reasons; the scope was tests only.

### 4. What worked and what failed
- **Worked:** probing each behaviour before writing its assertion; the probe caught the
  `protocol.md` rule 3 contradiction. Stepping the simulator between messages made the WebSocket
  tests stable.
- **Failed:** the first draft asserted D16's documented stop behaviour and failed, which is how
  defect 1 was found.

### 5. Immediate next steps
None for task 5. Confirm the two D17 orchestrator refinements with the user:
- a stop cold-restarts program variables, which disarms `abort_monitor` and drops operator-written
  `plc.globals`;
- manual writes to an enabled loop's solenoid are refused.

### 6. Open risks, questions, or blockers
- The entry-point test picks a free port and releases it before the server binds; another process
  could take it in between.
- The HEAD-probe test depends on `websockets` 15 logging `"opening handshake failed"`; a library upgrade
  that renames it fails that test (and would also break the filter, which is the point).

---

## Task 6: Plant regression tests (done 2026-09-15)

### 1. Current goal
Cover:
- mass conservation when nothing vents
- the no-overshoot limiter never inverting a pressure pair
- step-size invariance between 1 ms and 100 ms
- finite outputs under adversarial configs
- the config YAML round trip and its validators
- a deterministic `calibrate` script
- calibrated replay error ceilings on real fixture slices

Do not add golden-value tests on placeholder constants.

### 2. Current development status
Done 2026-09-15, inline with no agents. No production code changed. The suite runs in about 15 s
without `testdata/`. On disk, `backend/tests/plant/` (116 passed, 2 strict xfails):
- **`conftest.py`:** a session `runs` fixture that copies the 12:36, 12:49 and 12:52 fixture slices
  under their real recording names, so `calibrate.Runs` and the annotated RUD windows work.
- **`helpers.py`:** `CALIBRATED`/`UNCALIBRATED`, `with_values`, `make_plant` (from
  `demo.INITIAL`), `gas_mass`, and `FUEL_LBM` 39.5 (plant-model.md §6).
- **`test_conservation.py`:** GN2 conserved to 1e-12 while pressing with the vents settled shut; gas
  lost while venting equals exactly the PB1 + PB3 flow; venting never adds gas.
- **`test_limiter.py`:** a `_move` sweep over volumes 1e-6–1 m³, areas and dt up to 10 s (no inversion,
  mass conserved), vents never drop below the sink, no reverse flow, and the pressurant chain stays
  ordered through a press and vent at 2 ms and 100 ms sub-steps.
- **`test_step_size.py`:** a press, burn and vent scenario. 1 ms and 100 ms steps are identical at a 1 ms
  sub-step, 10 ms and 100 ms are identical at the default, and 1 ms stays within 5 % of each channel's
  swing.
- **`test_adversarial.py`:** 16 extreme configs, dry and overfilled, keep sensors, masses, pressures,
  flows and levels finite; meaningless dt is a no-op; the sub-step cap warns; negative initial pressures
  clamp.
- **`test_config.py`:** YAML round trips, partial and empty files, six rejection cases, source and unit
  validators, unit conversions, no default claiming `calibrated`, `calibration.yaml` provenance, the
  overlay touching only fitted constants, and `Plant()` defaulting to it.
- **`test_calibrate.py`:** the search helpers; on the slices, `fit_dead_time` (PB2/PB4 lag within
  0.05 s, D15), `_observed_rate` and `fit_press` for the one isolated S2 pulse (within 2× of `cda_s2`),
  and `fit_gas_volumes` (a physical fuel load). `cda_pb1` and `cda_pb3` beat 0.5×/2× and 0.8×/1.25×
  on the 12:49 blowdown costs, and `write_calibration` reproduces `calibration.yaml` byte for byte.
- **`test_replay.py`:** calibrated RMS ceilings, about 1.25× the values measured, on 17 channels of
  the three slices. Calibration at least 40 % better than uncalibrated on PT4/PT14 in 12:49 and 12:52,
  12:49 fuel correlation ≥ 0.85, RUD rows excluded, and replay determinism.
- **Docs:** `docs/plant-model.md` §4 had claimed 1 ms/10 ms/100 ms traces "agree to well under a psi".
  It now gives the measured result. README "Tests" mentions the suite.

**Two defects found** (strict xfails, awaiting the user):
1. **`min_ullage_frac` 0 with a full tank** divides by zero. `_update_ullage_volumes` assigns
   `GasNode.volume` directly and bypasses the constructor's 1e-6 m³ floor.
2. **`throat_area` 0** divides by zero in `_substep` once both propellants flow.

Candidate one-line fixes: floor the ullage volume at 1e-6 m³, and guard the throat area, or reject
non-positive values in `PlantConfig`. `tank_volume` 0 and `max_substeps` 0 also divide by zero, but
they are nonsense configs and are not tested.

### 3. Key decisions made
- Calibration will move the constants, so tests assert properties and error ceilings rather than exact
  values.
- Run `calibrate` on the committed slices rather than `testdata/`, so the suite works on a fresh clone.
  Full golden-section fits take about 9 s each, so the tests check each committed area sits in its
  cost valley instead of re-fitting it.
- Conservation must start with PB1/PB3 settled shut. Commanding them shut from a de-energised start leaks
  for the dead time plus the stroke, and a 4000 psi charge lifts the reliefs.

### 4. What worked and what failed
- **Worked:** probing each property before asserting it. The 12:49 slice reproduces the calibration
  notes' PB2/PB4 lags (0.390 and 0.392 s) and the `cda_pb3` RMS (39.6 against 39.7 psi).
- **Failed:** the first conservation probe leaked 0.07 % through the still-closing vents. The first
  "venting never adds gas" assertion failed on 3e-15 kg of summation noise.

### 5. Immediate next steps
1. **Ask the user** about the two xfails: fix the plant, add `PlantConfig` validation, or leave them.
2. `fit_press(..., "S1")` crashes on data with no isolated S1 pulse (`min` of an empty array). It is
   unreachable with the full recordings; note it if `calibrate` gains a partial-data mode.

### 6. Open risks, questions, or blockers
- Replay ceilings carry about 25 % headroom. A deliberate recalibration that trades one channel for
  another may need them re-measured; the docstring says how they were set.
- A tiny pressurant volume at a coarse sub-step starves flow, because the limiter caps each sub-step at
  equalising the pocket. That is not a stability problem, but it is another step-size dependence
  behind `substep_dt`.

---

## Task 7: Integration re-review and republish (queued)

### 1. Current goal
Re-verify every interface contract after phase 2, then republish the integration review at the same URL.

### 2. Current development status
Unblocked: task 3 review and fixes are complete (2026-09-15), including the abort-test finding and
the two engine bugs. Task 6 is done (2026-09-15).

### 3. Key decisions made
Verify by running the system, not by reading reports. The republished review must replace the answered
decisions and the old placeholder hotfire with the phase-2 results.

### 4. What worked and what failed
The 2026-09-13 review process (probe, browser end-to-end check, one visual pass, publish) caught real
defects. The artifact's live watch has since ended because its connection was lost.

### 5. Immediate next steps
1. Restart the backend with the `backend-server` preview in `.claude/launch.json`.
2. Run the browser end-to-end check:
   - IDE load, run, abort, automatic return
   - the hotfire timeline
   - bang-bang behaviour without the board hold
   - pressurising with a vent open
3. Read the existing artifact with action `read` on its URL, because the session scratchpad copy may be
   gone.
4. Update the content and republish with `url` set to the URL above.
5. Update `README.md` and memory.

### 6. Open risks, questions, or blockers
A new session must pass the artifact URL explicitly to update it rather than create a new one. Until then
the published review shows outdated decisions.

---

## Completed in phase 2 (reference)

| Work | Result |
|---|---|
| Loader | Parses board telemetry into `RunData.bbd` (100 ms samples, held per row). Fixed the dropped board columns. S1/S2 open is board OR GC (D13), with raw `gc_commands` kept. `annotations.yaml` marks invalid windows: in 12:49, PT0, LC1–LC3 and THRUST from 108.972 s, and LC4 from 109.064 to 111.194 s |
| Tag database | PB5 is "LOX fill valve". S1 and S2 notes cite D13 |
| Data and tag tests | 43 test functions in `tests/data` and `tests/tags`, including real fixture slices such as the operator-only solenoid opens from 12:52 |
| NI card simulation tests | 35 tests in `tests/hwio` |
| Frontend tests | vitest, 90 tests in 7 files. `tsconfig.test.json` keeps the build green |
| Docs | Decisions D12 and D13. The data-survey addendum (board telemetry fields, RUD timeline). A "Tests" section in the README |

## Open questions for the stand team

1. After an abort, should control return only after the recorded 3.0 s hold, or after an arm step?
2. Please confirm the orchestrator refinements in D12: thresholds on real readings, output forces cleared
   at the latch, stop, reset and program loads refused while latched, and tripped thresholds that can be
   disabled during the latch.
3. What concentration is the IPA? Anhydrous is assumed.
4. How are the four GN2 bottles split across the two buses?
5. When the GC command and the board command disagree, is "either one opens the solenoid" correct (D13)?
6. What do the board's vent output and telemetry fields 9 to 11 mean? The vent columns are all zero.
7. Were any manual vents or bleeds open during the 12:52 safing run? The answer decides whether the
   vent-open mismatch lies in the model.
8. What is the PB valve actuation delay? The recordings imply about 0.23 s once logging latency is
   subtracted.

## File map

- **`docs/decisions.md`:** D1–D17, authoritative.
- **`docs/data-survey.md`:** the recordings, board telemetry fields and RUD timeline.
- **`docs/runtime.md`, `docs/protocol.md`, `docs/plc-language.md` §6.4–6.5:** current for D12 as of
  2026-09-14.
- **`backend/draco_sim/runtime/simulator.py`:** the new abort semantics.
- **`backend/examples/hotfire.sfc.json`:** the real hotfire procedure.
- **`backend/draco_sim/plant/config.py`:** the plant constants, which calibration targets.
- **`backend/draco_sim/plant/calibrate.py`, `calibration.yaml`:** the fits and their output (D15).
- **`backend/draco_sim/data/annotations.yaml`:** invalid sensor windows.
- **`backend/tests/`:** the data, tags, hwio, plc, runtime and protocol suites.
- **`frontend/src/gc/`:** the control panel; `abortUi.ts` holds the abort lockout rules.
- **`.claude/launch.json`:** the `frontend-dev` and `backend-server` previews.
