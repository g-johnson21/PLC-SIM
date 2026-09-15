# Fixtures

Each file here is a byte-verbatim slice of one real recording in `testdata/`
(header line + a contiguous run of data rows, copied as-is — `testdata/`
itself stays read-only). Row ranges below are 1-indexed source-file line
numbers, header included (i.e. `2` is the first data row).

| Fixture | Source (`testdata/`) | Source lines | Rows | Why this slice |
|---|---|---|---|---|
| `fuel_press_123642.csv` | `Draco_20260911_123642_hotfire.csv` | 11602-12051 | 450 | Covers the stepwise fuel bang-bang pressurization (fuel 200->800 psi) — the one recording where the board's own `BBD:F` telemetry commands fuel press (S2) while `bb-fuel board press` and DC2 both stay 0/unhelpful, per docs/data-survey.md's addendum. |
| `hotfire_rud_124919.csv` | `Draco_20260911_124919_hotfire.csv` | 3740-4339 | 600 | Straddles the hotfire attempt and its RUD: elapsed_s ≈100.0-116.0 s brackets the T+107.9-109.5 s sequence (PB2/PB4 open, RUD, manual abort) documented in docs/data-survey.md and annotated in `draco_sim/data/annotations.yaml`. |
| `lox_vent_125242.csv` | `Draco_20260911_125242_hotfire.csv` | 30117-30343 | 227 | A slice of the post-test LOX safing/venting run, for exercising bang-bang board telemetry and S1 hold behavior outside the hotfire/RUD window. |
| `operator_open_125242.csv` | `Draco_20260911_125242_hotfire.csv` | 11344-12868 | 1525 | Covers elapsed_s 300.03-340.51 s, where the operator alone opened S1 (302.82-330.53 s) and S2 (317.08-337.82 s) through the GC's DC1/DC2 with the board telemetry silent throughout (D13, docs/decisions.md) — for exercising the valves = board OR gc_commands rule on GC-only opens. |

Row ranges were confirmed by matching each fixture's first and last data row
verbatim against its source file (`grep -n -F` on the row text) and checking
the header lines are byte-identical (mod CRLF).

Note: `annotations.yaml` keys its invalid-window entries by the exact real
recording filename, so it does not fire for `hotfire_rud_124919.csv` (a
differently-named slice) unless a test deliberately copies it to a temp file
named `Draco_20260911_124919_hotfire.csv` — see `tests/data/test_annotations.py`.
