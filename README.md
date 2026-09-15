# Draco test stand PLC simulator

Training and procedure-validation simulator for the Draco liquid rocket engine test stand
(P&ID `Draco_V4_02`, rev 4.02) as controlled by an NI cRIO-9047. An operator writes control
programs in a lightweight IEC 61131-3-style language (ladder, structured text, sequential function
chart), runs them against a real-time plant model, and operates the stand from a built-in
ground-control panel. It is **not** a replica of the cRIO's native LabVIEW FPGA/RT environment and
does not implement the EtherNet/IP wire protocol; see `docs/decisions.md`.

## Layout
```
backend/     Python 3.13 package draco_sim
  draco_sim/tags      tag database (tags.yaml), NI module table, loaders      docs/tag-database.md
  draco_sim/data      loader for the real DAQ CSVs in testdata/
  draco_sim/hwio      NI card simulation (quantisation, timing, polarity)       docs/hwio.md
  draco_sim/plant     lumped-volume plant model + replay/calibration harness   docs/plant-model.md
  draco_sim/plc       LD / ST / SFC compilers and deterministic runtime        docs/plc-language.md
  draco_sim/runtime   scan loop: abort → sequencer → regulation → I/O          docs/runtime.md
  draco_sim/protocol  WebSocket JSON server (external GC contract)             docs/protocol.md
  examples/           five example programs (bang-bang loops, recorded hotfire SFC, purge, abort monitor)
frontend/    React 19 + Vite + TypeScript: programming IDE and GC control panel
testdata/    eight DAQ recordings from 2026-09-11 (read-only)                  docs/data-survey.md
docs/        decisions.md is the authority where it and the original brief disagree
```

## Run
Backend (from `backend/`; needs `numpy`, `pyyaml`, `websockets`):
```bash
pip install -e .
python -m draco_sim.protocol.server --load-examples
```
Frontend (from `frontend/`):
```bash
npm install
npm run dev
```
Open http://localhost:5173. The Program tab is the IDE, the Control tab is the GC panel. Both talk to
`ws://localhost:8765/ws` and nothing else. Set `VITE_SIM_MOCK=1` to run the UI against an in-browser
mock that cannot compile or run programs.

Headless demonstration of the scan loop, abort preemption and output arbitration:
```bash
python -m draco_sim.runtime.demo
```
Replay a recorded run through the plant model and print per-tag error statistics (calibrated
constants; add `--uncalibrated` for the plain defaults):
```bash
python -m draco_sim.plant.replay ../testdata/Draco_20260911_124919_hotfire.csv
```
Refit the calibrated constants from the recordings (about 70 s):
```bash
python -m draco_sim.plant.calibrate
```

## Tests
Backend, from `backend/` (needs `pytest`, installable with `pip install -e .[test]`):
```bash
python -m pytest -q
```
Frontend, from `frontend/`:
```bash
npm test
```
Measurement fixtures under `backend/tests/fixtures/` are slices of the real 2026-09-11 recordings; the
README there names each source file and row range. `tests/runtime` and `tests/protocol` pin the scan
loop and the wire contract (`docs/runtime.md`, `docs/protocol.md`); the protocol tests serve on an
ephemeral port, never 8765. `tests/plant` checks conservation, the flow limiter, step-size
invariance, extreme configs, the config YAML, `calibrate` piece by piece, and calibrated replay error
ceilings on the fixture slices, without needing `testdata/`. Strict xfails mark known defects with the
reason.

## Calibration status
The plant model has 105 named constants, listed with their provenance in `docs/plant-model.md`.
`python -m draco_sim.plant.calibrate` fits five of them to the 2026-09-11 recordings: the PB valve
dead time, both tank vents and both pressurant solenoids. It writes
`backend/draco_sim/plant/calibration.yaml`, which the plant and the runtime load by default, leaving 80
placeholders. Section 6 of `docs/plant-model.md` gives the residuals, the vent-open check (improved,
still 2-4x too high) and what the data cannot pin down. Engine performance stays uncalibrated until a
successful hotfire is recorded. Decisions are in `docs/decisions.md` D12-D15.
