# Draco tag database (task 1)

Source of truth: `backend/draco_sim/tags/tags.yaml` (+ `modules.yaml`,
`annotations.yaml`). This file is a human-readable rendering; if it ever
disagrees with the YAML, the YAML wins. See `docs/decisions.md` (D1, D2, D3,
D5, D8, D12) and `docs/data-survey.md` (including the 2026-09-13 addendum)
for why each field has the value it has.

**Every module/channel assignment in this build is unverified** (`verified:
false` on all 46 tags) — none of it has been checked against real panel
wiring. It is a self-consistent simulator convention, not an as-built record.

## Pressure transducers (NI-9208, current input, 0-10000/1500/500 psi per tag)

| Tag | P&ID | DAQ column | Module.idx:ch | Range (psi) | Notes |
|---|---|---|---|---|---|
| PT1 | PT1 | PT1 LOX GN2 (psi) | NI-9208.0:1 | 0-10000 | |
| PT2 | PT2 | PT2 LOX Upstream (psi) | NI-9208.0:2 | 0-1500 | |
| PT3 | PT3 | bb-ox board psi | NI-9208.0:3 | 0-1500 | LOX bang-bang feedback -> S1; no dedicated CSV header, sourced from the BB board column |
| PT4 | PT4 | PT4 LOX Tank Downstream (psi) | NI-9208.0:4 | 0-1500 | |
| PT5 | PT5 | PT5 LOX Manifold (psi) | NI-9208.0:5 | 0-1500 | |
| PT11 | PT11 | PT11 Fuel GN2 (psi) | NI-9208.0:6 | 0-10000 | |
| PT12 | PT12 | PT12 Fuel Upstream (psi) | NI-9208.0:7 | 0-1500 | |
| PT13 | PT13 | bb-fuel board psi | NI-9208.0:8 | 0-1500 | Fuel bang-bang feedback -> S2; same as PT3 |
| PT14 | PT14 | PT14 Fuel Tank Downstream (psi) | NI-9208.0:9 | 0-1500 | |
| PT15 | PT15 | PT15 Fuel Engine Manifold (psi) | NI-9208.0:10 | 0-1500 | |
| PT21 | PT21 | PT21 LOX Venturi Inlet (psi) | NI-9208.1:0 | 0-1500 | flow pair with PT22 |
| PT22 | PT22 | PT22 LOX Venturi Throat (psi) | NI-9208.1:1 | 0-1500 | |
| PT23 | PT23 | PT23 Fuel Venturi Inlet (psi) | NI-9208.1:2 | 0-1500 | brief had PT23/PT24 swapped; DAQ header wins (D1) |
| PT24 | PT24 | PT24 Fuel Venturi Throat (psi) | NI-9208.1:3 | 0-1500 | |
| PT31 | PT31 | PT31 Muscle Bus (psi) | NI-9208.1:4 | 0-500 | actuation air, not process fluid |
| PT32 | PT32 | PT32 Purge Bus (psi) | NI-9208.1:5 | 0-500 | regulated ~250 psi |
| PT33 | PT33 | *(none)* | NI-9208.1:6 | 0-1500 | on P&ID, never logged |
| PT0 | *(none)* | PT0 Chamber (psi) | NI-9208.1:7 | **unknown** | not on P&ID; range placeholder null, module/card a guess — see note below |

`PT0` is the one pressure tag with a genuinely open spec: no full-scale
range was available anywhere in the source material, so `range: null`
rather than a fabricated number, and the module assignment is flagged as a
guess in its `notes` field (simplest choice — put it on NI-9208 like the
rest — not a claim about the real hardware).

## Thermocouples (NI-9211, K-type assumed, ±80 mV, 14 S/s, no range given)

| Tag | P&ID | DAQ column | Module.idx:ch | Notes |
|---|---|---|---|---|
| TC1 | TC1 | TC1 LOX Tank Bottom (degF) | NI-9211.0:0 | brief said "upper"; DAQ says bottom |
| TC2 | TC2 | TC2 LOX Tank Top (degF) | NI-9211.0:1 | top/bottom reversed vs. brief |
| TC3 | TC3 | TC3 Dragon (degF) | NI-9211.0:2 | DAQ label "Dragon" vs. P&ID location (venturi inlet side) — mismatch flagged, not resolved |
| TC4 | TC4 | TC4 Venturi (degF) | NI-9211.0:3 | assumed venturi outlet side |
| TC5 | TC5 | TC5 Spare 5 (degF) | NI-9211.1:0 | DAQ label "Spare 5" vs. P&ID engine-manifold location — flagged |
| TC6 | *(none)* | TC6 Fuel BB Solenoid (degF) | NI-9211.1:1 | not on P&ID |
| TC7 | *(none)* | TC7 LOX BB Solenoid (degF) | NI-9211.1:2 | not on P&ID |
| TC8 | *(none)* | TC8 Chamber (degF) | NI-9211.1:3 | not on P&ID |

## Load cells (NI-9237 bridge input, ±25 mV/V, rated 2 mV/V output)

| Tag | P&ID (pid_tag) | DAQ column | Module.idx:ch | Capacity (lbf) |
|---|---|---|---|---|
| LC1 | LC-R | LC1 TLCA (lbf) | NI-9237.0:0 | 3000 (thrust cell A) |
| LC2 | LC-G | LC2 TLCB (lbf) | NI-9237.0:1 | 3000 (thrust cell B) |
| LC3 | LC-B | LC3 TLCC (lbf) | NI-9237.0:2 | 3000 (thrust cell C) |
| LC4 | LC1 | LC4 LOX Tank Weight (lbf) | NI-9237.0:3 | 200 (LOX tank weight; erratic 109.064-111.194 s in the 124919 recording, see Annotations below) |
| LC_FUEL | LC2 | *(none)* | NI-9237.1:0 | 200 (fuel tank weight; not logged in any 2026-09-11 file) |
| THRUST | *(none, derived)* | Thrust Combined (lbf) | — | derived = LC1+LC2+LC3 |

**Alias rule (D1, load-bearing):** P&ID load-cell numbers collide with DAQ
numbers (P&ID `LC1` is the fuel/LOX tank cell; DAQ `LC1` is thrust cell A).
`pid_tag` is a plain informational field, never an alias-lookup key. So
`resolve("LC1")` always returns thrust cell A, unambiguously.

## Digital outputs / valves (NI-9476, sourcing, 6-36 VDC, 250 mA/ch, 500 µs)

The `DCn (state)` column is the **functional** state (1 = open). The
electrical energize bit `b` in `Solenoid Command: n | b` equals the state
for NC valves and is inverted for NO valves — i.e. NC valves are
`open_when_energized`, NO valves are `open_when_deenergized` (D3).

**S1/S2 exception (D12/D13, 2026-09-13):** the bang-bang loops ran on the
previous system's own controller board, not the GC, but both wire to the
same solenoids — either can open one. `DC1`/`DC2` are only the GC's manual
commands and do not by themselves track the true valve state (DC2 is 0 in
most 2026-09-11 recordings even when the fuel loop pressurized — the board
commanded it, off DC's radar). D13: in the 125242 safing run the GC alone
opened S1 (302.82-330.53 s) and S2 (317.08-337.82 s) with the board silent
throughout, so board telemetry alone is not enough either. The loader
combines the two: `RunData.valves["S1"]`/`["S2"]` is the OR of the board's
own BBD telemetry (`RunData.bbd["ox"/"fuel"].press_cmd`) and the raw
DC1/DC2 command, and keeps the raw DC columns separately as
`RunData.gc_commands["S1"/"S2"]` — see Board telemetry below.

| DC | Tag (P&ID) | Log alias | Normal | Polarity | Channel | Function |
|---|---|---|---|---|---|---|
| 1 | S1 | SV-LOXBB | NC | open_when_energized | NI-9476.0:0 | LOX bang-bang press solenoid |
| 2 | S2 | SV-FBB | NC | open_when_energized | NI-9476.0:1 | Fuel bang-bang press solenoid |
| 3 | PB1 | SV-LOXV | NO | open_when_deenergized | NI-9476.0:2 | LOX tank GN2 vent |
| 4 | PB3 | SV-FV | NO | open_when_deenergized | NI-9476.0:3 | Fuel tank GN2 vent |
| 5 | PB2 | MV-LOX | NC | open_when_energized | NI-9476.0:4 | LOX main run valve |
| 6 | PB4 | MV-F | NC | open_when_energized | NI-9476.0:5 | Fuel main run valve |
| 7 | S5 | SV-FPURGE | NC | open_when_energized | NI-9476.0:6 | Fuel line purge injection |
| 8 | S4 | SV-LOXPURGE | NC | open_when_energized | NI-9476.0:7 | LOX line purge injection |
| 9 | PB5 | SV-LOX-FILL | NC | open_when_energized | NI-9476.0:8 | LOX fill valve |
| 10 | S3 | SV-MBV | NC | open_when_energized | NI-9476.0:9 | Muscle-bus (actuation air) vent |
| 11 | PB6 | SV-GOX-PURGE | NC | open_when_energized | NI-9476.0:10 | LOX run-line GOX vent/purge |

`dc_index` and `solenoid_command_index` both carry the DC's `n` (1..11) —
the same integer used in the `Solenoid Command: n | b` log lines and the
`aliases` list (`DC1`..`DC11`).

Reserved spares (`reserved: true`, no `daq_column`, no aliases, no wired
function yet): `SPARE_IGNITER` (ch 11), `SPARE_CAMERA_TRIGGER` (ch 12),
`SPARE_COMPRESSOR` (ch 13).

**PB5 confirmed (D8/D12):** PB5 sits on the dewar fill line (P&ID: B1 ->
PB5 -> C5), not the LOX tank outlet — the recorded hotfire flowed LOX with
PB5 closed throughout. The LOX tank outlet is unvalved in the model; this
supersedes D3's original "LOX fill / tank outlet isolation" wording.

## Bang-bang board columns (`RunData.bb`)

Each recording also logs the old board's own per-row columns directly —
`bb-ox`/`bb-fuel` `setpoint`, `enabled`, `board state`, `board press`,
`board vent` and `board psi` — sampled at the DAQ's own ~40 Hz rate, unlike
the sparser `event`-embedded BBD telemetry lines described below. `load_run`
exposes these as `RunData.bb: dict["ox"|"fuel", BangBangTrace]`:

| `BangBangTrace` field | Source column (`bb-<loop> ...`) |
|---|---|
| `setpoint` | `setpoint` |
| `enabled` | `enabled` |
| `state` | `board state` |
| `press` | `board press` |
| `vent` | `board vent` |
| `psi` | `board psi` |

**Bug fixed 2026-09-13:** four of these six fields (`state`/`press`/`vent`/
`psi`) used to come back as empty, zero-length arrays. The loader built the
column name as `f"{prefix} {field_name}"` (e.g. `"bb-ox state"`), but the
real header carries an extra `"board"` word (`"bb-ox board state"`);
`setpoint` and `enabled` have no such word in their column name and so
happened to load correctly, which is why only four of the six fields were
affected. Fixed in `draco_sim/data/loader.py` (`_BB_COLUMN_SUFFIX`); all six
fields are now full per-row arrays, one entry per CSV row, the same length
as `RunData.t`. See docs/data-survey.md's 2026-09-13 addendum for the
column-name survey that found this.

## Board telemetry (`RunData.bbd`)

About every 0.1 s the `event` column carries one `[info] BBD:L:...` (LOX)
and/or `[info] BBD:F:...` (fuel) line from the previous system's bang-bang
controller board — see docs/data-survey.md's 2026-09-13 addendum for the
full field table and how it was decoded. `draco_sim.data.load_run` parses
these into `RunData.bbd: dict["ox"|"fuel", BoardTelemetry]`, one
`BoardTelemetry` per loop:

| Field | Meaning | Status |
|---|---|---|
| `sample_t` | elapsed_s of each raw BBD line for this loop (not one per CSV row) | — |
| `state` | board state, `OFF`/`SUS` | confirmed |
| `press_cmd` | press solenoid command, 0/1 — this is S1/S2's true commanded state | confirmed |
| `psi` | board pressure reading | confirmed |
| `deadband` | always 15 | confirmed |
| `field5` | pressure rate | tentative |
| `field6` | filtered pressure | tentative |
| `field7` | target pressure (setpoint + 10) | tentative |
| `field9` | unknown, ~160-170; tracks the PANDA predictive-close "horizon" value logged nearby | unknown |
| `field10` | unknown, always 1 | unknown |
| `field11` | unknown 0/1; close to (not exactly) the per-loop `bb-<side> enabled` column | unknown |

Every field except `sample_t` is a **zero-order-held, full-length** array —
one entry per CSV row, holding the last parsed value forward, `NaN` (or, for
`state`, the float `NaN` sentinel in an object array) before that loop's
first BBD line in the file. `sample_t` alone is the shorter, unpadded array
of just the raw sample times.

`RunData.valves["S1"]`/`["S2"]` are the OR (D13) of `bbd["ox"/"fuel"].press_cmd`
— zero-order-held and NaN-filled gaps replaced with 0 (closed) — and the raw
DC1/DC2 command (`RunData.gc_commands["S1"/"S2"]`), so they stay plain `int8`
like every other entry in `valves` — the NaN distinction is still available
from `bbd` directly for anyone who needs it.

## Annotations (`RunData.invalid_from` / `invalid_to`)

`backend/draco_sim/data/annotations.yaml` records known-bad channel windows
per recording (`testdata/*.csv` itself stays read-only). `load_run` exposes
these as `RunData.invalid_from: dict[tag, float]` (start of the bad window)
and `RunData.invalid_to: dict[tag, float]` (only present for tags that
recover within the recording — absent means "invalid through EOF"). Keyed
by the exact CSV filename, so it only fires for the real recordings, not
arbitrary slices/fixtures of them. The format is a plain list per recording
(`note` plus an `invalid` list of `{tag, from_s, to_s, reason}`), so adding
another recording or another window is additive.

Currently annotated: `Draco_20260911_124919_hotfire.csv` (the failed
hotfire/RUD, D12) — `PT0`, `LC1`, `LC2`, `LC3`, `THRUST` invalid from
108.972 s (verified against the data: PT0's first frozen-108.501-psi
sample, held through EOF) with no recovery in this file; `LC4` invalid
109.064-111.194 s (a separate, shorter erratic window found by comparing
against its own pre-event noise baseline), recovering to baseline-level
smoothness afterward.

## NI module specs (`modules.yaml`)

| Module | Count | Channels | Resolution | Range | Rate |
|---|---|---|---|---|---|
| NI-9208 | 2 | 16 | 24-bit | ±21.5 mA | 500 S/s (high-speed) / 52 ms/ch (high-res) |
| NI-9211 | 2 | 4 | 24-bit | ±80 mV | 14 S/s |
| NI-9237 | 2 | 4 | *(not specified)* | ±25 mV/V | 50 kS/s/ch simultaneous |
| NI-9476 | 1 | 32 | n/a (digital) | 6-36 VDC, 250 mA/ch | 500 µs update |
| NI-9205 | 1 | 32 SE / 16 diff | 16-bit | ±0.2-±10 V (4 ranges) | 250 kS/s aggregate | unassigned in this build |

## Non-tag DAQ columns (`daq_meta_columns`)

Bang-bang board internals and run bookkeeping that are logged but are not
PLC tags: `bb-fuel setpoint`, `bb-fuel enabled`, `bb-fuel board state`,
`bb-fuel board press`, `bb-fuel board vent`, `bb-ox setpoint`, `bb-ox
enabled`, `bb-ox board state`, `bb-ox board press`, `bb-ox board vent`,
`armed`, `sequence`, `event`, `timestamp`, `elapsed_s`. The CSV loader
(`draco_sim.data`) treats these as the one source of truth for those
headers rather than re-deriving them.

## Python API

```python
from draco_sim.tags import load_tag_db
from draco_sim.data import load_run, list_runs

db = load_tag_db()
db.resolve("SV-LOXBB")        # -> Tag(tag="S1", ...)
db.resolve("bb-ox board psi") # -> Tag(tag="PT3", ...)
db.resolve("LC1")             # -> Tag(tag="LC1", ...) thrust cell A, never LC4
db.plc_specs()                # [{"name": "PT1", "direction": "in", "dtype": "REAL", "units": "psi"}, ...]

for path in list_runs("testdata"):
    run = load_run(path, tag_db=db)
    print(run.duration_s, run.sample_period_s)
    print(run.signals["PT0"].max(), run.signals["THRUST"].max())
    print(run.valves["PB2"])              # int8 array, functional state (1 = open)
    print(run.bb["ox"].psi[:5])           # PT3, taken straight from "bb-ox board psi"
    print(run.valves["S1"])               # true state, board telemetry OR DC1 (D13)
    print(run.gc_commands["S1"])          # raw DC1 column — GC's manual command only
    print(run.bbd["ox"].psi[:5])          # same board, decoded from the BBD:L telemetry line
    print(run.invalid_from, run.invalid_to)  # {} outside the 124919 recording
    print(len(run.events), run.events[0])
```

`TagDatabase` validates on load (unique tags/daq_columns/aliases, no
module/channel used twice, channel within the module's channel count, DO
polarity consistent with `normal_state`) and raises one `ValueError` listing
every problem found, rather than failing on the first.
