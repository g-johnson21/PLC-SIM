# Hardware I/O simulation layer (task 2)

`backend/draco_sim/hwio/` sits between the plant (physical truth, engineering
units) and the PLC (what a real cRIO scan would read/write). It consumes
`draco_sim.tags.TagDatabase` (task 1) and knows nothing about the plant
physics or the PLC engine.

## Pipeline (per analog input tag)

1. **physical truth -> transducer electrical output** (`hwio/scaling.py`,
   `hwio/thermocouple.py`):
   - pressure: 4-20 mA loop current over the tag's engineering `range`.
   - temperature: type-K EMF via the NIST ITS-90 polynomials (`degF`
     converted to `degC` first), referenced against a cold-junction
     temperature held in the config, i.e. `E_measured = E(T_hot) - E(T_cj)`.
   - load cell: `mV/V = rated_output_mv_per_v * (force / capacity_lbf)`
     (ratiometric — no excitation voltage needed).
   - optional per-tag additive Gaussian noise and a constant offset are
     applied here, in electrical units, drawn from one `numpy.random.Generator`
     seeded from `HwIoConfig.seed`.
2. **electrical -> card reading** (`hwio/core.py: _refresh_input`,
   `scaling.quantize`): clamp to the card's electrical full-scale (±21.5 mA /
   ±80 mV / ±25 mV/V) and quantise to 24 bits over that span. The channel only
   refreshes at the card's own rate; between refreshes `read_inputs()` returns
   the last converted value (a real hold register, not a fresh recompute).
3. **card reading -> engineering value**: the reverse of step 1, applied to
   the *quantised* electrical value — the inverse ITS-90 polynomial (with the
   same assumed cold-junction reference) for temperature, or straight linear
   rescaling for pressure/load-cell.

`THRUST` has no physical channel; it isn't part of the refresh/hold model —
`read_inputs()` computes it fresh each call as `LC1 + LC2 + LC3` from that
call's (possibly held) load-cell readings.

`PT0` has no engineering range (`docs/tag-database.md`: genuinely unknown
full-scale). Per instructions, HwIo does not guess one — the physical value
passes through unscaled, with a one-time warning per tag, and no
transducer/card model (no electrical value, no quantisation) is applied to it.

## Card timing model

| Module | Mode | Per-channel refresh period |
|---|---|---|
| NI-9208 (PT) | high-speed (default) | 2 ms, flat |
| NI-9208 (PT) | high-res | `52 ms * channels-in-scan`, where channels-in-scan is the number of tags actually wired to that module *instance* (index 0 or 1) — an assumption: unused physical channels are not in the scan list |
| NI-9211 (TC) | — | 1/14 s, flat |
| NI-9237 (LC) | — | 1/50000 s (effectively every simulation step; "far above scan rate" per the brief) |

Mode is global per `HwIoConfig.ni9208_mode` (`"high_speed"` or `"high_res"`),
not selectable per instance. Each channel tracks its own `last_refresh_s`;
`step(dt_s)` advances the internal clock and refreshes any channel where
`now - last_refresh_s >= period`, then snaps `last_refresh_s` to `now` (a
small, deterministic period-drift simplification, not sub-stepped).

`NI-9205` carries no tags; `channels()` still enumerates its 32 channels with
`tag=None` so the HMI can show it present-but-idle.

## Digital outputs: polarity and latency

The PLC writes a **functional** "commanded open" bool. `energize_polarity`
(from the tag DB, already validated against `normal_state`) maps it to the
NI-9476 energize bit:

- `open_when_energized` (NC valves): `bit = 1` iff commanded open.
- `open_when_deenergized` (NO valves): `bit = 0` iff commanded open.

All channels default to `bit = 0` (all coils de-energized) before any write —
which, by construction, is also each valve's correct real-world normal state
(NC closed / NO open) with no power applied.

`write_outputs()` timestamps the write at the current sim time and schedules
`effective_time = write_time + 500us`; `step()` applies any pending write
whose effective time has passed. `valve_states()` returns the post-latency
functional open state for the 11 real valves only (reserved spares are
writable and show up in `channels()`, but drive nothing physical, so the
plant doesn't need them).

## Config placeholders (`hwio/config.py`)

Every number not in the accepted module table is a named field on
`HwIoConfig`, flagged in `PLACEHOLDER_NOTES`:

| Field | Default | Class | Why |
|---|---|---|---|
| `pt_loop_ma` | `(4.0, 20.0)` | ASSUMPTION | standard ISA 4-20 mA loop convention, not a Draco datasheet value |
| `cold_junction_degc` | `25.0` | ASSUMPTION | nominal ambient CJC reference; no CJC sensor spec supplied |
| `bridge_excitation_vdc` | `10.0` | ASSUMPTION | named per house rule only — the mV/V bridge math is ratiometric and never uses it |
| `pressure_transducer_accuracy_ma` | `0.0` | PLACEHOLDER-ZERO | PT accuracy not specified |
| `pressure_noise_density_ma` | `0.0` | PLACEHOLDER-ZERO | PT noise density not specified |
| `tc_accuracy_mv` | `0.0` | PLACEHOLDER-ZERO | TC accuracy not specified |
| `tc_noise_density_mv` | `0.0` | PLACEHOLDER-ZERO | TC noise density not specified |
| `cold_junction_accuracy_degc` | `0.0` | PLACEHOLDER-ZERO | CJC accuracy not specified |
| `bridge_accuracy_mvv` | `0.0` | PLACEHOLDER-ZERO | bridge/load-cell accuracy not specified |
| `bridge_noise_density_mvv` | `0.0` | PLACEHOLDER-ZERO | bridge noise density not specified |

The two "accuracy" and "noise density" placeholders per signal type combine
(root-sum-square) into the effective Gaussian noise stddev actually injected,
unless overridden per tag via `per_tag_noise_stddev` / `per_tag_offset`
(both `dict[str, float]`, empty by default, electrical units). All defaults
are zero, so with a fresh `HwIoConfig()` no noise is injected anywhere.

NI-9237 resolution is `null` in `modules.yaml` (not part of the supplied
module spec), but this task's brief explicitly says to quantise it at 24 bits
like the other two analog-input cards — followed here as an explicit
instruction, flagged as a discrepancy against the accepted module table.

## API

`set_physical` takes exactly the shape `Plant.sensors()` produces: all 32 PLC
input tags, THRUST included. Derived tags (THRUST) are accepted and silently
ignored — there's no physical channel to drive, and `read_inputs()` always
recomputes THRUST from that call's LC1+LC2+LC3 — so the scan loop can pass
`plant.sensors()` straight through with no filtering. It still raises
`ValueError` for a genuinely unknown name or for an output tag.

```python
from draco_sim.tags import load_tag_db
from draco_sim.hwio import HwIo, HwIoConfig

db = load_tag_db()
hw = HwIo(db, config=HwIoConfig(seed=1))

hw.set_physical({"PT1": 4000.0, "TC1": -297.0, "LC4": 68.8, "THRUST": 0.0})  # THRUST ignored
hw.step(0.01)                      # advance 10 ms, refresh any due channels, apply due DO writes
hw.read_inputs()["PT1"]            # -> ~4000.0008 (24-bit quantised round-trip)

hw.write_outputs({"S1": True})     # commands S1 (NC) open; takes effect 500us later
hw.step(0.0006)
hw.valve_states()["S1"]            # -> True, after the latency has elapsed

for ch in hw.channels():           # one row per physical channel, all 8 card instances
    if ch.tag == "PT1":
        print(ch.electrical_value, ch.electrical_unit, ch.raw_code, ch.eng_value)
```

## Known limitation worth flagging

Round-trip error for pressure and load-cell tags is bounded by 24-bit
quantisation alone (sub-mil-psi / sub-mil-lbf). For thermocouples, the
dominant round-trip error is **not** quantisation — it's the fact that NIST
publishes the ITS-90 direct (T->E) and inverse (E->T) Type-K polynomials as
two *separately fitted* functions, so `T(E(T))` carries their own
published fit-pair residual (~0.01-0.02 degC class near cryogenic
temperatures) even at zero quantisation. See the acceptance-check output for
a measured example (~0.02 degF at -297 degF, ~40x the pure quantisation
bound). This is intrinsic to using the standard reference polynomials as
specified, not a simulator defect.
