# Draco simulator integration review, phase 2 (2026-09-15)

Supersedes the 2026-09-13 phase 1 review. Every result below was produced by running the
system, not by reading task reports. The evidence files in this folder are the raw output.

| File | What it is |
|---|---|
| `probes.json` | `backend/scripts/integration_review.py` run without `--observe`: deterministic in-process probes of the `Simulator`, asserting each contract before recording it |
| `browser-wire.json` | 120 s read-only WebSocket capture (`--observe`) while an operator ran, pressed, started the hotfire and hit ABORT in the control panel |
| `browser-press-hotfire.json` | 75 s capture of a fresh plant: vents closed by hand, both loops enabled, press-up to the band |
| `browser-hotfire.json` | 60 s capture of the hotfire started from the panel with both loops regulating |
| `wire-vent-open.json` | GC-client script: state after the completed hotfire, `sim.reset`, LOX loop enabled with PB1 left open |
| `panel-after-abort-return.png`, `task7-hotfire-burn.png`, `task7-hotfire-complete.png` | panel screenshots |

## 1. Baseline

| Check | Result |
|---|---|
| Backend `python -m pytest -q` from `backend/` | 568 passed, 2 xfailed (the two task 6 plant guards, awaiting the user) |
| Frontend `npx vitest run` | 105 passed in 9 files |
| Server | `python -m draco_sim.protocol.server --load-examples` on 8765; `welcome.programs` = hotfire (sequence), bangbang_lox and bangbang_fuel (regulation) |
| Panel | Vite dev server on 5173, `connected` to the real backend for the whole session |

Re-run when the review was finished (2026-09-15): backend 568 passed, 2 xfailed in 17.6 s;
vitest 105 passed; `probes.json` regenerated identical.

## 2. Contracts re-verified

### 2.1 Hotfire timeline (D12, `docs/plc-language.md` §6.5)

The real procedure keys every transition to `SYS_TIME - t_start`, so the cards must see the
commands at T+0, 0.5, 8.0, 8.5, 8.7 and 11.7 s plus one scan at any scan rate.

| Rate | PB2 open | PB4 open | PB2 close | PB4 close | S4, S5 open | S4, S5 close |
|---|---|---|---|---|---|---|
| 50 Hz (probe) | 0.020 | 0.520 | 8.020 | 8.520 | 8.720 | 11.720 |
| 30 Hz (probe) | 0.033 | 0.533 | 8.033 | 8.533 | 8.733 | 11.733 |
| 50 Hz, live from the panel | 0.020 | 0.520 | 8.020 | 8.520 | 8.720 | (capture ended at T+9.0; probe covers it) |

Both probe runs park on `COMPLETE`. The chart itself fires at T+ exactly; the one-scan offset
is the documented output-image latency. Live, the burn ran with both bang-bang loops enabled:
S1 and S2 topped the tanks up three times during the 8 s burn (100 ms pulses), and the loops
kept their enables after `COMPLETE`. `T+0.000 hotfire STARTED (manual commands stay in force:
PB1, PB3)` confirms D16: the vent closes made before Start survived the sequence.

### 2.2 Abort and automatic return of control (D12, D14)

Live, from the panel (`browser-wire.json`): ABORT pressed at T+3.0 into the burn.

| Scan | What happened |
|---|---|
| 2825 | `manual abort requested (hmi.abort)` |
| 2826 | `ABORT LATCHED -- hmi.abort (operator abort); regulation off: bangbang_lox, bangbang_fuel; manual commands cleared`. Same scan: `hotfire ABORT`, PB1 and PB3 open, PB2 closed, `waiting_on: ["hotfire at ABORT"]`, `hmi.manual` emptied, both loops show `state: OFF` with `abort_off` naming their program while `enable` still reads true |
| 2831, 2836, 2841 | ABORT_2 (PB4 closed), ABORT_3 (S1 closed), ABORT_4 (S4, S5 open), `waiting_on` following the step |
| 3091, 3092 | ABORT_5 (purges closed), ABORT_DONE, `abort sequence complete -- stand safe, operator in control`, `programs left off until plc.reset re-arms them: bangbang_lox, bangbang_fuel`. `latched` false, `manual_allowed` true, both `enable` false, `tripped` kept |

5.32 s from latch to return, as documented (5.3 s chain plus one scan). Outputs held where the
abort left them: PB1 and PB3 open, everything else closed. The panel showed OPERATOR IN CONTROL
with the "stand safe" notice and "Left off since the abort: bangbang_lox, bangbang_fuel. PLC
Reset re-arms them" (`panel-after-abort-return.png`); both loop buttons read Disabled with the
D14 explanation; PLC Reset re-armed them.

Probe (`probes.json` → `abort`): a threshold on PT1 at 90 % of the live reading trips while PT1 is
forced to 0, so thresholds read the cards, not the forced value. The output force on S1 is
cleared at the latch. With the threshold still tripped at chain end the latch holds with
`"PT1 > 3391.17 still tripped"`; clearing the threshold via `abort.config` returns control. After
return only PB1 and PB3 are energised, `bangbang_lox` and `bangbang_fuel` stay disabled, a manual
PB2 write is accepted, and `plc.stop` then `plc.run` leaves only PB1 and PB3 open (D17).

### 2.3 Bang-bang without the board hold (D12, D15, D17)

Phase 1 simulated the old board's 1 s telemetry hold on PT3 and PT13. Phase 2 removed it.

| Check | Result |
|---|---|
| Probe: PT3 and PT13 change by more than 0.1 psi | on 48 of the first 50 scans (every scan from t = 0.06 s), so no hold |
| Probe: settled after 15 s | PT3 926.9, PT13 897.6 psi against setpoints 904 and 870 with a 15 psi deadband; no limit cycle, both `HOLD`, S1 and S2 closed |
| Live press-up from 0 psi (`browser-press-hotfire.json`) | S1 open 12.84 → 15.38 s (PT3 0 → 919), S2 open 14.18 → 16.18 s (PT13 0 → 890); one pulse each, then `HOLD` at 921 / 890 |
| Panel | trend strips show a smooth ramp and a flat hold (`task7-hotfire-burn.png`); the LOX card says "Enabled: the loop owns S1. Disable it to actuate S1 by hand" (D17) |

Readings settle 8–13 psi above the top of the band because the solenoid closes on the reading and
the line then equalises into the tank, as `docs/plant-model.md` §6 predicts.

### 2.4 Pressurising with a vent open (D15, `docs/plant-model.md` §6)

Probe (`probes.json` → `vent_open`) reproduces the §6 table exactly, tank psig with S1/S2 held open:

| Config | Vents | PT3 at 5 / 15 / 60 s | PT13 at 5 / 15 / 60 s |
|---|---|---|---|
| uncalibrated | open | 1311 / 1311 / 773 | 1411 / 1406 / 873 |
| calibrated | open | 789 / 756 / 302 | 621 / 523 / 211 |
| calibrated | closed | 1319 / 1319 / 1302 | 1419 / 1416 / 1401 |

Live (`wire-vent-open.json`): after `sim.reset` PB1 and PB3 read open by default. Enabling the
LOX loop with PB1 open held S1 open for the whole 20 s; PT4 reached 132 psi at 2 s, 506 at 8 s
and 752 at 18 s while the bottle fell from 4000 to 3600 psi. With the vent closed the same
loop reaches its band in 2.5 s and pulses S1 once. So the loop runs the bottles down through an
open vent rather than filling the tank, which is the qualitative behaviour the stand team asked
for. Quantitatively the model is still 2× (fuel) to 4× (LOX) too high against the 12:52 GC opens;
the user decided against temperature physics (D16), so this stays a documented limitation.

### 2.5 Protocol (`docs/protocol.md`)

Observed on the wire during the session, all matching the document: `welcome` with roles;
`state` at 50 Hz with `abort.latched`, `abort.waiting_on`, `hmi.bb.<loop>.abort_off`,
`hmi.manual`, `hmi.manual_allowed`, `hmi.active_sequence`; `event` texts in the stand's log
style (`MV-LOX (PB2) -> OPEN`, `T+8.020 hotfire CLOSE_LOX_MAIN`); `read`, `write`, `sim.reset`
acks. `tripped.value` is boolean `true` with `threshold: null` for the manual source, exactly as
the type table says. The reference client (the panel) displays `waiting_on` strings and does
not parse them.

### 2.6 PLC engine and plant

Covered by the regression suites rather than re-probed here: `tests/plc` 219 cases (task 3
fixed the diagnostic rendering, the 10,000-iteration cap and abort chains in disabled or halted
charts), `tests/plant` 116 cases (conservation, limiter, step-size invariance, config
round trip, `calibrate` piece by piece, calibrated replay ceilings). Both ran in the 568-pass
baseline above.

## 3. Findings

No new defects. Every behaviour probed or observed matched `docs/runtime.md`, `docs/protocol.md`,
`docs/plc-language.md` §6.5 and `docs/plant-model.md` §6.

Observations worth keeping in view:

1. **A completed hotfire leaves the bang-bang loops enabled and regulating.** Only an abort
   switches them off. That is per the docs and is what the recordings show, but an operator who
   expects "sequence complete" to mean "stand quiet" should be told otherwise in training.
2. **Vent-open realism** is unchanged since D16 and remains the largest plant-model error.
   Stand-team questions 7 and 8 in `handoff.md` would decide whether it is physics or procedure.
3. **Two plant xfails** (`min_ullage_frac` 0 with a full tank; `throat_area` 0) still await a
   user decision between a floor, a config validator, or leaving them.
4. **An abort opens hand-closed vents 0.3 s before the recorded chain does.** The pre-press
   PB1/PB3 close is a manual command, the latch drops manual commands, and the chain writes
   PB1/PB3 only in `ABORT_4`, so rule A2 (`docs/runtime.md` §2) leaves them at their normally
   open state from the latch scan. In `browser-wire.json` both vents open on scan 2826 while
   S1, open since scan 2821, closes only at `ABORT_3` (scan 2836). The 12:49 recording opens
   the vents at +0.3 s, after the press solenoids close at +0.2 s (`docs/data-survey.md`).
   Documented, but a question for the stand team (added to question 1 in `handoff.md`).

## 4. Decisions answered since the phase 1 review

| Phase 1 open item | Now |
|---|---|
| Abort semantics: manual clear, forces surviving | D12/D14: absolute abort, automatic return, nothing re-arms until `plc.reset`. Verified in 2.2 |
| Placeholder hotfire | The recorded procedure in `backend/examples/hotfire.sfc.json`, exact at 30 and 50 Hz. Verified in 2.1 |
| Fuel identity, GN2 buses, PB5 | IPA, two buses, LOX fill valve (D12) |
| Board hold on PT3/PT13 | Removed (D12). Verified in 2.3 |
| Uncalibrated vents and press | Five constants calibrated (D15). Verified in 2.4 |
| Stopped PLC and loop ownership | D17. Verified by `probes.json` `abort.stop_run_safe` and the panel lockout text |

## 5. Publication

The phase 1 review lives at https://claude.ai/code/artifact/ec3bb330-2764-4300-aa59-98860f7d38c2.
Revision B of that page is `review-page.html` in this folder: this review rebuilt in the phase 1
page's design (read from the live artifact), loading the two panel screenshots beside it. The
user chose not to publish it (2026-09-15), so the URL still shows phase 1. To republish, pass
that URL with `review-page.html` as the page and `panel-after-abort-return.png` and
`task7-hotfire-burn.png` as supporting files, so it replaces rather than duplicates. This file
stays the review of record.

## 6. Reproducing

```bash
cd backend
export PYTHONPATH=.                   # the script imports draco_sim from the source tree
python scripts/integration_review.py --output ../docs/reviews/2026-09-15/probes.json
python -m draco_sim.protocol.server --load-examples          # separate shell
python scripts/integration_review.py --observe 120 --output ../docs/reviews/2026-09-15/browser-wire.json
```

Then exercise the panel at http://localhost:5173 while `--observe` records.
