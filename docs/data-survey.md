# Test data survey — `testdata/*.csv` (surveyed 2026-09-12)

Eight DAQ recordings from 2026-09-11, all sharing one 56-column schema. Sample period ~25 ms (~40 Hz).
This file records what is *in the data*; it makes no decisions about how the simulator maps it.

## Files

| File | Duration (s) | What it appears to contain |
|---|---|---|
| Draco_20260911_100047 | 1047 | Fuel-side GN2 bottle open (PT11 0 -> 4857), fuel BB board at 125 psi |
| Draco_20260911_101815 | 4520 | Long hold; LOX BB board at 125 psi; ends with both GN2 branches vented |
| Draco_20260911_113337 | 1423 | LOX BB at 125; GOX purge pulses |
| Draco_20260911_115721 | 1364 | Hold, both bottles ~4000/4900 psi, no BB activity |
| Draco_20260911_122004 | 998 | LOX fill (DC9) and GOX purge pulses; TCs go cryogenic |
| Draco_20260911_123642 | 757 | Stepwise BB pressurization: LOX 300->834 psi, fuel 200->800 psi |
| Draco_20260911_124919 | 202 | **Hotfire attempt**: 5 s sequence, ~1 s burn, abort at ~T+1.6 s, then 4× GN2 purge sequences |
| Draco_20260911_125242 | 1761 | Post-test safing/venting; PT1 3523 -> 13, PT11 4827 -> 7 |

## Columns (as logged)

Analog: PT1 LOX GN2, PT2 LOX Upstream, PT4 LOX Tank Downstream, PT21 LOX Venturi Inlet,
PT22 LOX Venturi Throat, PT5 LOX Manifold, PT11 Fuel GN2, PT12 Fuel Upstream, PT14 Fuel Tank
Downstream, PT23 Fuel Venturi Inlet, PT24 Fuel Venturi Throat, PT15 Fuel Engine Manifold,
PT31 Muscle Bus, PT32 Purge Bus, PT0 Chamber (all psi);
LC1 TLCA, LC2 TLCB, LC3 TLCC, LC4 LOX Tank Weight, Thrust Combined (lbf);
TC1 LOX Tank Bottom, TC2 LOX Tank Top, TC3 Dragon, TC4 Venturi, TC5 Spare 5,
TC6 Fuel BB Solenoid, TC7 LOX BB Solenoid, TC8 Chamber (degF).

Discrete commands (0/1): DC1 LOx Tank BB, DC2 Fuel Tank BB, DC3 LOx GN2 Vent, DC4 Fuel GN2 Vent,
DC5 Ox Runline, DC6 Fuel Runline, DC7 Fuel Purge, DC8 LOX Purge, DC9 LOX Fill,
DC10 Muscle Bus Vent, DC11 GOX Purge.

Bang-bang board, per loop (`bb-fuel`, `bb-ox`): setpoint, enabled, board state (OFF/SUS),
board press, board vent, board psi. Plus `armed`, `sequence` (id string), `event` (log text).

Command names used in the event log: SV-LOXBB, SV-FBB, SV-LOXV, SV-FV, MV-LOX, MV-F,
SV-FPURGE, SV-LOXPURGE, SV-LOX-FILL, SV-MBV, SV-GOX-PURGE (matching DC1..DC11 in order).
`Solenoid Command: <n> | <0|1>` lines use the same 1..11 index.

## Differences from the orchestrator brief's tag database

- **No PT3, PT13, PT33** columns exist. PT4/PT14 are labelled "Tank Downstream", not "run line".
- **Bang-bang feedback**: the BB board reports its own `board psi`. While enabled it tracks PT4 most
  closely on the LOX side (mean |diff| 8 psi vs 13 for PT2) and PT12 on the fuel side (5 psi vs 6 for
  PT14). The BBD log line carries setpoint+10 and a fixed 15 field, e.g. `BBD:L:SUS:0:<psi>:<rate>:<filt>:914.00:15:...`
  when the column setpoint is 904. Board has both `press` and `vent` outputs.
- **Load cells**: LC1/LC2/LC3 are the three thrust cells (TLCA/B/C, = LC-R/G/B on the P&ID),
  LC4 is LOX tank weight. **No fuel tank load cell is logged.** LC4 reads a constant 2748.524 in six
  of eight files (likely disconnected/stuck); thrust cells read ~-24,700 in the last file (tare artefact).
- **Thermocouples**: 8 logged, which exactly fills 2× NI-9211. TC1/TC2 top/bottom are the reverse of the
  brief. TC6/TC7 are BB solenoid body temps, TC8 chamber. TC3 is labelled "Dragon".
- **Chamber pressure PT0** exists (not on P&ID). It freezes at 108.501 psi from ~T+1.6 s in the hotfire
  and stays frozen through the following file — treat as sensor/DAQ fault after that point.
- **Valve set**: 11 commanded devices, but the names are functional (GN2 vents, LOX fill, muscle-bus
  vent, GOX purge) and do not map one-to-one onto the P&ID's S1–S5 / PB1–PB6 without confirmation.
- **Muscle bus** (PT31, ~100 psi) is the actuation-air supply; PT32 purge bus ~220 psi when charged.
- **Bottle pressures** observed: PT1 ~4000–4060 psi, PT11 ~4860–4960 psi. Never near 6000.

## Real hotfire sequence trace (file 124919, `seq-hotfire-copy`)

T+0.00 HOT FIRE ARMED, "T-0.5 OX LEAD": MV-LOX OPEN
T+0.50 "T-0 FUEL RUNLINE OPEN": MV-F OPEN
~T+1.6 abort (`seq-abort`): MV-LOX CLOSED; +0.1 MV-F CLOSED; +0.2 SV-LOXBB & SV-FBB CLOSED;
+0.3 SV-LOXV, SV-FV, SV-FPURGE, SV-LOXPURGE OPEN; +5.3 purges CLOSED, "Abort state reached — stand is venting".
Peak PT0 108.5 psi, peak Thrust Combined 128 lbf. Pre-fire BB setpoints: LOX 904, fuel 870 psi.

GN2 Purge sequence (`seq-custom-13`): SV-FPURGE + SV-LOXPURGE OPEN, 2.0 s, CLOSED.

## Addendum 2026-09-13, after the stand team's answers (decisions D12)

**Old controller board telemetry.** About every 0.1 s the `event` cell carries `[info] BBD:L:...` and
`[info] BBD:F:...` lines from the previous system's bang-bang board. Colon-separated fields:

| # | Meaning | Status |
|---|---|---|
| 1 | Side: `L` LOX, `F` fuel | confirmed |
| 2 | Board state `OFF` / `SUS` | confirmed |
| 3 | Press solenoid command, 0/1 (S1 for L, S2 for F) | confirmed for LOX against `bb-ox board press` |
| 4 | Board pressure, psi | confirmed |
| 5 | Pressure rate | tentative |
| 6 | Filtered pressure | tentative |
| 7 | Target pressure (above the column setpoint) | tentative |
| 8 | Deadband, always 15 | confirmed |
| 9 | Unknown, e.g. 163.0 | unknown; tracks (not exactly) the "horizon" value in nearby `PANDA PRED_CLOSE` log lines, e.g. horizon=164.0 vs. field9=163.6 at t=58.196s in the 124919 hotfire |
| 10 | Unknown, always 1 | unknown |
| 11 | Unknown 0/1, possibly armed | tentatively closer to the per-loop `bb-<side> enabled` bit than to the global `armed` column (95.9% agreement with `enabled` vs. 59.2% with `armed`, in the 124919 hotfire), still not exact |

- `bb-ox board press` is populated (1,589 rows at 1 across the recordings) and matches field 3 in duration.
- `bb-fuel board press` is 0 in every row of every recording. Fuel press commands exist only in field 3
  (17 telemetry lines at 1, during the 12:36 stepwise pressurisation).
- `bb-* board vent` columns are 0 everywhere.
- DC1/DC2 carry the GC's manual solenoid commands, not the board's.
- **Loader bug fixed 2026-09-13**: `BangBangTrace.state/press/vent/psi` were built from `f"{prefix}
  {field_name}"` (e.g. `"bb-ox state"`), which does not exist — the real columns say `"bb-ox board
  state"` etc. `setpoint`/`enabled` happened to have no `board` word and so loaded fine, which is why
  only four of the six fields were affected. Fixed in `draco_sim/data/loader.py` (`_BB_COLUMN_SUFFIX`).
- **S1/S2 truth is the board's, not DC1/DC2** (D12). Cross-checking the board's telemetry field 3
  against `bb-ox board press` for LOX gives agreement of 96-100% in six of eight recordings; the two
  outliers are `Draco_20260911_101815` (99.0%) and `Draco_20260911_124919` (96.0%) — in both cases the
  mismatches are short (1-18 row) runs right at transition edges, not steady-state disagreement, so
  field 3 stands as confirmed. `draco_sim.data.load_run` now sources `valves["S1"]`/`["S2"]` from board
  telemetry (`bbd["ox"/"fuel"].press_cmd`) and keeps DC1/DC2 as `gc_commands["S1"/"S2"]`. GC-vs-board
  disagreement is real and sometimes large — e.g. in `Draco_20260911_101815`, DC1=1 while the board's
  press command was 0 for 5,206 rows (of 176,732), and the reverse for 909 rows; in the 124919 hotfire,
  112 and 191 rows respectively. DC2 is 0 in every 2026-09-11 recording (confirmed above) while the
  board commanded fuel press 18-26 times in five of the eight files — so for S2 essentially all of the
  "board on" time is invisible to the GC command. No combining rule is imposed; both are exposed as
  separate `RunData` fields for the stand team to arbitrate.

**12:49 failed hotfire.** Per the stand team, the engine suffered a RUD, the abort was manual, and the
thrust load cells and chamber PT failed at that moment. From the data:

| t (s) | Event |
|---|---|
| 107.925 | PB2 (MV-LOX) opens; LOX venturi ΔP rises to ≈300–385 psi |
| 108.423 | PB4 (MV-F) opens |
| ≈108.9 | Fuel venturi ΔP rises from ≈0: fuel arrival ≈0.5 s after PB4 |
| 108.919 | THRUST reads its peak, 128 lbf |
| 108.972 | PT0 freezes at 108.501 psi for the rest of the recording |
| 109.017 | THRUST and LC1–LC3 read garbage |
| ≈109.1 | LC4 becomes erratic |
| 109.52 | Manual abort sequence starts |

Pressure transducers stay valid through the event. The 128 lbf figure is a start transient, not a
steady-state thrust, which resolves the earlier venturi-versus-thrust inconsistency.

**Verified against the raw data (2026-09-13), for `backend/draco_sim/data/annotations.yaml`:** PT0's
freeze is exact at t=108.972s (value 108.501 psi from that sample through the last row of the file, idx
4074 of 7604 — confirmed constant, not just approximately so). `PT0`, `LC1`, `LC2`, `LC3` and `THRUST`
are annotated invalid from that same instant (per the stand team, all five failed together in the RUD)
through end of file (no recovery in this recording). `LC4` is a separate, shorter fault: its first
clearly anomalous sample (>6 sigma vs. a t<100s baseline of mean 61.3 / std 6.0 lbf) is at t=109.064s
(49.3 -> 101.5 lbf in one 26ms step), and its 1-second rolling standard deviation — a baseline-quiet
~0.3 lbf normally — stays elevated (jumping between roughly -5 and +100 lbf) until t=111.166s and is
back under the elevated threshold by t=111.194s, after which it tracks a smooth, low-noise (slowly
decreasing, consistent with continued tank venting) signal through the rest of the file. So LC4 is
annotated invalid 109.064-111.194s, distinct from the RUD-onset window on the other four channels.
