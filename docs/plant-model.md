# Draco plant model (task 3)

Lumped-volume physics for the Draco stand. Consumes the 11 functional valve states,
produces the 32 PLC sensor inputs. Deterministic: no wall clock, no randomness, same
inputs give the same outputs every run.

```python
from draco_sim.plant import Plant, PlantConfig

plant = Plant()                  # calibrated; Plant(PlantConfig()) for the plain defaults
plant.set_initial(bottle_psi=4000, lox_ullage_psi=0, lox_mass_lbm=60, ambient_degF=70)
plant.step(0.02, {"S1": True, "PB2": False, ...}, ignite=None)
plant.sensors()      # -> the 32 tags, engineering units
plant.state          # -> PlantState, for the HMI
plant.reset()
```

`step()` is safe for any `dt <= 0.1 s` and sub-cycles internally. `sensors()` never
returns a NaN or an infinity: the model clamps, logs a warning onto `state.warnings`,
and carries on.

**Every constant lives in `draco_sim/plant/config.py`.** Nothing else in the package
holds a physical number. Each one carries `value`, `units`, `source` and `notes`;
`PlantConfig().placeholders()` lists the 85 defaults that are still guesses.
`PlantConfig.calibrated()`, which `Plant()` and the runtime use, overlays the five
constants fitted into `calibration.yaml` (section 6), leaving 80.

---

## 1. The fuel is isopropyl alcohol

The stand team confirmed IPA (D12). `rho_fuel` is 785 kg/m3 and `pvap_fuel` 0.68 psia,
published values for anhydrous IPA at the assumed 70 degF storage temperature. A 91% or
70% grade is denser; the concentration is an open question for the stand team.

c\*, Cf and the throat area stay placeholders. The 12:49 recording is a failed start with
a RUD (D12), so there is no steady burn to fit them to. No fuel load cell is logged, so
the fuel load is always an input; calibration estimates 39.5 lbm for the 12:36 run
(section 6).

## 2. Node / edge diagram

Boxes are pressure states. `==` is a gas edge (compressible orifice), `--` a liquid
edge (incompressible orifice), `>|` a check valve, `[RVn]` a relief to atmosphere.

```
                      GN2 BOTTLES                                 AIR COMPRESSOR
              (bottles_lox)   (bottles_fuel)                            |
                    |               |                                   v
              PT1 --+               +-- PT11                     (muscle_bus) PT31
                    |               |                             |   |
                 S1 ==           == S2                            |   == S3 -> atm
                    |               |                             |   == B5 -> atm
             (lox_press_up)   (fuel_press_up)                     |
              PT2 -+ [RV1 1350]     |                             +--> actuation air for
                    |               |                                  PB1..PB6 (gated on
                 C1 >|           >| C3                                 pb_min_actuation)
                    |               |
             (lox_press_dn)   (fuel_press_dn)
              PT3 -+ [RV2 1300]     +- PT12, PT13  [RV3 1400]  [B3 -> atm]
                    |               |         |
                    ==              ==        == R1 (droop) ==> (purge_bus) PT32
                    |               |                             | [RV5 250] [B6 -> atm]
              (lox_ullage) ==PB1    (fuel_ullage) ==PB3           |
                    |      -> atm         |       -> atm          +====== S4 ==> LOX manifold
             ==========                 =========                 +====== S5 ==> fuel manifold
             | LOX TANK|                |FUEL TANK|                          (both via C6/C7)
             | LC4     |                | LC_FUEL |
             ==========                 =========
                    |                        |
       (no valve in the outlet)          PT14 + B4
                    |                        |
     LOX DEWAR --B1--PB5-->|C5-- PT4 tee     |
                    |                        |
              PT21 -+- V1 -+- PT22      PT23 + V2 + PT24
                    |                        |
                PB6 -> atm                   |
                    |                        |
                   PB2                      PB4
                    |                        |
                 C2/C6                    C4/C7
                    |                        |
       LOX MANIFOLD PT5, TC5        FUEL MANIFOLD PT15, PT33
                    \                       /
                     ====== CHAMBER =======
                      PT0, TC8, thrust -> LC1+LC2+LC3
```

### Interpretation choices baked into that diagram

**PB1 and PB3 are vents, not inline valves.** Per the user's instruction and D3, the
two normally-open pneumatic valves are the tank GN2 vents. They are modelled as a path
from the tank ullage to atmosphere, in parallel with the pressurant inlet path, not as
an isolation valve in the pressurant line. A consequence is that the `lox_press_dn`
node (PT3) stays permanently connected to the LOX ullage through `cda_lox_press_line`,
which is exactly why PT3 tracks PT4 in the logs. The literal P&ID line reading would put
PB1 in series between C1 and the tank; that reading is not used. **Failure direction:**
NO plus spring return means loss of muscle-bus air vents both tanks.

**B1 / PB5 / C5 are on the dewar fill line, not the LOX tank outlet.** The brief put
PB5 in series with the tank outlet. The P&ID puts B1, PB5 and C5 between the LOX dewar
and the tee where the tank drops in, and the logged hotfire flows LOX with PB5 shut the
whole time, which is impossible if PB5 is in the run path. The model therefore gives the
LOX tank an unvalved outlet (`cda_lox_tank_outlet`) and treats the dewar as a one-way
fill source through B1 -> PB5 -> C5 into the same tee.

**PT33 shares the fuel manifold node with PT15.** PT33 is on the P&ID at the engine and
appears in no log, so there is nothing to distinguish it from PT15.

**The GN2 bottles form two separate buses** (D12, stand team), which is also why PT1 and
PT11 sit 900-1350 psi apart for hours in every logged run. `bottles_common_manifold` is 0
with source `user`, and `bottle_split_lox` bottles feed the LOX bus. The split is not
stated; section 6 shows the data cannot settle it either.

## 3. Equations

**Gas edges** — isentropic compressible flow, N2, absolute pressures:

```
r_crit = (2/(g+1))^(g/(g-1))                        = 0.5283 for g = 1.4
choked      (p_dn/p_up <= r_crit):
    mdot = CdA * p_up / sqrt(R*T_up) * sqrt(g) * (2/(g+1))^((g+1)/(2(g-1)))
unchoked:
    mdot = CdA * p_up / sqrt(R*T_up) * sqrt( 2g/(g-1) * (r^(2/g) - r^((g+1)/g)) )
reverse flow (p_dn >= p_up): zero; edges that can flow both ways are evaluated
in both directions and the higher-pressure side wins.
```

**Gas nodes** — ideal gas, `p = m R T / V`. Every node except the bottles is isothermal
at a fixed node temperature (ambient, or `lox_ullage_temp` / `fuel_ullage_temp`). The
bottles blow down polytropically: `p/p0 = (m/m0)^n`, hence `T/T0 = (m/m0)^(n-1)`.

**Ullage volume** tracks the liquid: `V_ull = V_tank - m_liq/rho`, floored at
`min_ullage_frac`. Draining liquid therefore drops tank pressure with no extra
machinery, which is where the run-phase tank droop comes from.

**Liquid path** — quasi-static and incompressible. Liquid lines carry no pressure state
of their own: at these volumes the compressibility dynamics are orders of magnitude
faster than a 10-100 Hz scan, so every liquid pressure is solved algebraically from the
current flow each sub-step. Orifices in series combine as `1/A^2 = sum 1/Ai^2` and
`mdot = CdA * sqrt(2 rho dP)`.

The chain per propellant is

```
ullage + rho*g*h  --cda_tank_outlet-->  PT4/PT14 tee  --cda_line_pre-->  PT21/PT23
   --venturi-->  --cda_line_post-->  junction J  -->  { PB6 to atmosphere, PB2/PB4 to chamber }
```

When only one sink is open the whole chain is closed form. When both are (PB6 and PB2
together, off-nominal) the junction pressure comes from a bisection on the mass balance
at J; the residual is strictly monotone, so it always brackets.

**Venturi.** Two different areas do two different jobs, which is the point of a venturi:

- the *throat* reading PT22/PT24 uses the full dynamic drop, `dP = mdot^2/(2 rho CdA_v^2)`;
- the *network* sees only the permanent loss, `(1 - venturi_recovery)` of that drop,
  implemented as an effective `CdA_v / sqrt(1 - recovery)` in the series chain.

So a venturi can show a large throat dip while costing the system little, which is what
a flow-measuring venturi is for.

**Cavitation.** If the throat pressure would fall below the propellant vapour pressure,
the venturi chokes and *it*, not the downstream network, sets the flow:
`mdot = CdA_v * sqrt(2 rho (p_inlet - p_vap))`. The junction pressure is then re-solved
against that fixed inflow. This is the regime a cavitating venturi is normally run in and
the model supports both regimes without changing structure - only the CdA values decide
which one you are in.

**Engine manifold.** Liquid when the run valve passes flow (`p_J` minus the drop across
the run valve and its check). Otherwise GN2 from the purge bus through S4/S5 and out the
injector, with the intermediate manifold pressure from a bisection on gas mass balance.
The two are mutually exclusive for free, because the purge check valve cannot push a
250 psi bus into a 900 psi run line. The result is passed through a first-order lag
(`chamber_tau`) to stand in for manifold fill.

**Chamber.** `p_c = mdot_total * cstar / A_t`, first-order lagged, and
`F = Cf * (p_c - p_atm) * A_t`. The gauge form of the thrust equation is a
simplification: the textbook `F = Cf * p_c_abs * A_t` is vacuum-referenced and would
give non-zero thrust on a cold stand, and the exit area needed to do it properly is not
known. The flow solve uses the previous sub-step's chamber pressure, so the
chamber/feed coupling is explicit; the chamber lag damps it.

**Ignition.** `ignite=None` (the default) auto-ignites when PB2 and PB4 are both open
and both propellants exceed `ignition_min_mdot`. `ignite=True/False` is the hook for a
future igniter DO and still requires flow through both run valves. There is no igniter
model, no ignition delay and no hard-start behaviour; auto-ignition is a placeholder.

**Valves.** Solenoids S1-S5 are a first-order lag with `solenoid_tau` (10 ms, near
instant). PB1-PB6 start to move `pb_dead_time` after their command changes (a command that
reverts sooner is never seen), then follow a first-order lag with `pb_stroke_tau`; their *target* is the
commanded state only while muscle-bus gauge pressure is at or above
`pb_min_actuation`; below that they drive to their normal state, because a spring-return
pneumatic actuator does not freeze when it loses air, it returns. Effective CdA is
linear in stroke. Each stroke pulls `pb_actuator_volume` of air off the muscle bus,
which reproduces the PT31 dip the logs show when valves cycle.

**Passive elements.** Checks C1-C7 pass forward only above `check_crack`. Reliefs RV1,
RV2, RV3, RV5 ramp from shut to `cda_relief` over `relief_band` above setpoint. RV4 is
on the dewar, which is a boundary condition here, so it is config only. The regulator R1
is an orifice modulated proportionally toward `r1_set - r1_droop * mdot`. Manual valves
B1-B6 are config-set open fractions of `cda_manual_full`.

**Sensors.** Thermocouples are first-order lags with `tc_tau` toward a target: TC1 the
LOX liquid temperature when liquid is present, TC2 the ullage gas temperature, TC3/TC4
the run-line temperature, TC5 the manifold, TC6/TC7 ambient, TC8 ambient or `tc8_hot`
while burning. TC6/TC7/TC8 are flat placeholders with no physics behind them. Load cells:
LC4 and LC_FUEL are liquid mass in lbm plus a tare; LC1-LC3 split thrust three ways;
THRUST is their sum. PT3 and PT13 read the pressurant line nodes directly. The logged
board columns step about once a second, but that was the old board's telemetry, not the
transducers the cRIO reads (D12), so the hold lives only in the replay comparison.

## 4. Sub-stepping

`step(dt, ...)` splits `dt` into `ceil(dt / substep_dt)` equal sub-steps, capped at
`max_substeps`. `substep_dt` defaults to 2 ms: the smallest modelled volume (0.5 L)
through the smallest gas orifice feeding it (1e-5 m2) has a charging time constant
around 10 ms, so 2 ms resolves it with margin.

Stability does not actually rest on the sub-step size. Two guards do:

- **No-overshoot limiter.** Every gas transfer is clamped so the step cannot drive the
  downstream pressure above the upstream one. `dm_eq` is the exact mass transfer that
  equalises the pair, so the approach is monotone and cannot ring or diverge no matter
  how small the node.
- **First-order lags use `1 - exp(-dt/tau)`,** which is exact for any `dt`, rather than
  the `dt/tau` approximation that blows up when `dt > tau`.

Acceptance check 5 runs the same hotfire at `dt = 0.001`, `0.01` and `0.1 s`; the traces
agree to well under a psi.

## 5. Known weaknesses

1. **No fuel load cell.** The fuel load is an input, and every fuel-side vent and press
   fit scales with the fuel ullage volume it implies (section 6).
2. **No boiloff or self-pressurisation.** The logs show the LOX tank climbing 226 -> 503
   psi over 500 s with no valve commanded and LC4 falling 79 -> 51 lbm over the same
   run. That is boiloff, and the model has none of it. It is the main reason the replay
   LOX-mass and slow-pressure traces drift.
3. **Energy is not conserved in gas nodes.** Everything except the bottles is isothermal.
   Real fill heating and blowdown cooling are absent, so fast transients under-predict
   temperature swings and mis-predict pressure. It is the leading suspect for the
   vent-open error in section 6, where the model holds the tank 2-4x too high.
4. **No two-phase flow anywhere.** LOX is a constant-density liquid; once the tank hits
   zero mass, flow stops rather than transitioning to GOX blow-through.
5. **Chamber is an algebraic c\* model.** No combustion, no mixture-ratio dependence, no
   ignition transient, no hard start, no throat erosion. Mixture ratio is not computed.
6. **The engine manifold is a target pressure plus a lag**, not a real mixed-phase
   volume. Between a liquid run and a gas purge it is an interpolation, not physics.
7. **Bang-bang board vent output is not modelled.** The real board has a `vent` output
   (D2); it reads zero in every logged run, so there is nothing here to model it from.
8. **Static head uses a cylinder assumption** and `tank_height` is a guess.
9. **Line-pressure dynamics on the liquid side are absent** by construction (section 3).
   Water hammer and valve-opening transients faster than a few ms do not exist here.
10. **`cda_lox_press_line` must stay well above `cda_s1`.** The solenoid sees bottle
    pressure and the line sees tank pressure, so a line sized like the solenoid orifice
    cannot pass the flow and PT3 pegs at the RV1 setpoint instead of tracking the tank.
    This bit once during development; it is a real trap for whoever calibrates.
11. **One dead time for every PB valve, both directions.** `pb_dead_time` comes from
    air-to-open valves. The normally-open vent PB1 opened faster in 12:36 (0.28 s against
    0.35-0.45 s), consistent with a spring return, but one event cannot pin a second value.
12. **No boil-off or flashing on venting.** Below ~250 psi a venting LOX tank holds up
    (12:36: PT4 plateaus at 127 psi with PB1 open while LC4 falls 10 lbm); the model keeps
    blowing down.

## 6. Replay and calibration

```
python -m draco_sim.plant.replay ../testdata/Draco_20260911_124919_hotfire.csv \
       [--out report.csv] [--every 40] [--uncalibrated | --config plant.yaml] \
       [--substep 0.01] [--lox-mass 60] [--fuel-mass 40] [--limit 30]
python -m draco_sim.plant.calibrate [--data ../testdata] [--out calibration.yaml] [--report]
```

Replay seeds initial conditions from the first logged row: PT1/PT11 -> the two buses,
PT4/PT14 -> ullage pressures, PT2 -> the LOX pocket behind C1, PT31 -> muscle bus, PT32 ->
purge bus, LC4 -> LOX mass unless the channel is parked on the 2748.524 stuck sentinel,
TC1-TC8 -> thermocouple states so the 2 s lag does not inject a fake startup transient,
and every valve settled in its logged state. It then drives the plant with the recorded
valve states at the recorded timestamps and prints:

- a per-tag table: observed range, predicted range, RMS error, max error, bias, correlation;
- a **sign check** listing any channel where the log and the model both moved and moved
  in opposite directions - that is a topology symptom, not a constant that needs tuning -
  and separately any channel where the model stayed flat while the log moved;
- a **drive coverage** block: how many rows each valve was open and how many transitions
  it made.

`--out` writes a coarse predicted-vs-logged CSV (every Nth row, both series side by side
plus the valve states) for offline plotting. No plotting dependency.

Rows inside a window annotated invalid in `data/annotations.yaml` are excluded from the
statistics. A logged column that updates less often than every 0.5 s is held telemetry
(the board's PT3/PT13 columns step about once a second), so it is compared against the
prediction sampled where the column updates, marked `held`.

### Calibration

`calibrate.py` runs in about 70 s and is deterministic: fixed windows, fixed search
brackets and iteration counts, no timestamps in the output. It fits five constants and
writes them to `calibration.yaml` with source `calibrated`; each note carries its window,
method and residual. Transducers refresh about every 0.1 s while rows arrive every 26 ms,
so every fit compares only rows where the logged value changed.

| constant | value | data | method | spread |
|---|---|---|---|---|
| `pb_dead_time` | 0.23 s | 7 isolated PB opens, 12:36 and 12:49 | median command-to-response lag (0.366 s) minus the median S1/S2 lag (0.138 s over 17 opens), taken as command-logging latency | PB lags 0.28-0.45 s |
| `cda_pb1` | 2.7e-5 m^2 | vent blowdowns 12:36 486.00-487.6 s and 12:49 109.82-115.0 s | least squares on log absolute PT4, LOX mass from LC4 | each window alone: 3.5e-5 and 2.4e-5; RMS 72 and 30 psi |
| `cda_pb3` | 4.57e-5 m^2 | 12:49 109.82-113.5 s, PT14 651->73 psi | least squares on log absolute PT14 | RMS 40 psi |
| `cda_s1` | 8.04e-6 m^2 | 13 isolated S1 pulses | area whose modelled PT4 rise rate matches the logged one (D13) | 7.0e-6-1.2e-5; 12:49 median 7.6e-6, 12:36 median 9.0e-6 |
| `cda_s2` | 7.83e-6 m^2 | 7 isolated S2 pulses, 12:36 | same, on PT14 | 5.6e-6-1.4e-5 |

What the fits found:

- **No fuel run-line fill time.** PB2 reaches the LOX venturi in 0.390 s and PB4 the fuel
  venturi in 0.392 s. The gap after PB4 in the 12:49 hotfire is the PB actuation delay
  that both run valves share, not fuel filling the line, so `pb_dead_time` models it.
- **Rate, not pulse width.** At the fitted `cda_s1` the modelled PT4 slope matches the
  12:49 pulse at 57.8 s (about 68 psi per 0.2 s), but the logged tank keeps rising for
  about 0.2 s after the telemetry says S1 closed. Replaying telemetry pulse widths
  therefore under-fills: the 12:36 fuel channels get worse (RMS 211 -> 288 psi). The
  simulator's bang-bang loops use the PLC's own pulse widths, so the rate is what matters.
- **Fuel load.** The seven 12:36 S2 pulses drop PT11 by 174 psi in total and raise PT14 by
  862 psi and PT32 by 221 psi. In the model's gas laws (two bottles on the fuel bus,
  `polytropic_n` 1.2) that is 11.3 L of gas downstream of S2, so 39.5 lbm of IPA. The fuel
  fits and the report use it; `init_fuel_mass` stays a placeholder.
- **Bottle split not identifiable.** The two clean 12:49 S1 pulses imply 2.9 and 2.6
  bottles on the LOX bus at `lox_ullage_temp` 200 K, or two bottles with ullage gas near
  270 K. `bottle_split_lox` stays a placeholder at 2.
- **Vent windows stop above ~250 psi,** where LOX flashing takes over (weakness 12).

### Pressurising with a vent open

The stand team asked whether this behaves realistically once vents and press-up are
calibrated (D12). Two checks, both printed by `calibrate`:

Full 4000 psi buses, S1 and S2 held open, LOX 60 lbm, fuel 39.5 lbm, tank psig:

| model | vents | PT3 at 5 s | 15 s | 60 s | PT13 at 5 s | 15 s | 60 s |
|---|---|---|---|---|---|---|---|
| uncalibrated | open | 1311 | 1311 | 773 | 1411 | 1406 | 873 |
| calibrated | open | 789 | 756 | 302 | 621 | 523 | 211 |
| calibrated | closed | 1319 | 1319 | 1302 | 1419 | 1416 | 1401 |

Against the data: in the 12:52 safing run the operator opened S1 at 302.82 s and S2 at
317.08 s with PB1/PB3 open and the bottles isolated, so PT1 and PT11 read trapped lines
(fitted at 0.96 and 0.84 L). At the tank peak, where press inflow equals vent outflow:

| side | tank peak, logged | model | tank / line absolute pressure, logged | model |
|---|---|---|---|---|
| LOX | 18 psi | 64 psi | 0.083 | 0.326 |
| fuel | 60 psi | 150 psi | 0.108 | 0.214 |

**Better, but not yet realistic.** Before calibration the vents were so small that the
tanks pressurised to their relief valves with the vents open. Calibrated, a vent-open
press levels off far lower, but it still holds the tank 2x (fuel) to 4x (LOX) too high
relative to supply. Scaled to a 4000 psi supply, the 12:52 ratios imply roughly 320 psig
LOX and 420 psig fuel, where the model reaches about 790 and 620 psig. This data cannot
separate two candidate causes. One is the isothermal ullage and line nodes: expansion-
cooled pressurant, and on the LOX side chilling over the liquid, carry less pressure per
unit mass. The other is manual vents or bleeds that may have been open during safing.
Tuning the areas to 12:52 would break the closed-vent rise rates the bang-bang loops rely
on, so it was not done.

### Replay RMS before and after

psi, invalid windows excluded, fuel 39.5 lbm, sub-step 10 ms. *Before* is the phase-1 code,
*uncalibrated* the current code with `PlantConfig()` (no board hold, IPA, seeding from
PT4/PT14/PT2 and settled valves), *calibrated* adds `calibration.yaml`.

| run | tag | before | uncalibrated | calibrated |
|---|---|---|---|---|
| 12:36 | PT1 | 43 | 43 | 25 |
| 12:36 | PT2 | 335 | 287 | 287 |
| 12:36 | PT4 | 315 | 312 | 312 |
| 12:36 | PT14 | 223 | 211 | 288 |
| 12:49 | PT1 | 496 | 496 | 348 |
| 12:49 | PT2 | 346 | 346 | 280 |
| 12:49 | PT4 | 343 | 343 | 277 |
| 12:49 | PT11 | 21 | 21 | 12 |
| 12:49 | PT14 | 107 | 107 | 35 |
| 12:49 | PT22 | 340 | 339 | 274 |
| 12:49 | PT24 | 123 | 124 | 70 |
| 12:52 | PT4 | 160 | 160 | 72 |
| 12:52 | PT14 | 155 | 155 | 67 |
| 12:52 | PT1 | 1512 | 1512 | 1718 |

In 12:49, correlation rises from 0.90 to 0.95 on PT4 and from 0.96 to 1.00 on PT14. The
12:36 LOX channels are dominated by self-pressurisation (226 -> 503 psi over 500 s),
which the model lacks. In 12:52, PT1 and PT11 are trapped lines that the model's bottle
nodes cannot represent.

### What the 2026-09-11 logs cannot calibrate

- **Engine performance.** 12:49 is a failed start with a RUD (D12); PT0, LC1-LC3 and
  THRUST are annotated invalid from 108.972 s. Do not fit `cstar`, `cf` or `throat_area`
  to it. The 128 lbf peak was a start transient, which resolves the earlier
  venturi-versus-thrust inconsistency.
- **There is no fuel tank load cell**, so initial fuel mass is a pure guess. Without
  `--fuel-mass` the model has no fuel, does not ignite, and PT0/THRUST stay flat. With
  `--fuel-mass 40` the hotfire replay peaks at PT0 222 psi and 156 lbf, against a logged
  108.5 psi and 128 lbf before both channels failed - the right order of magnitude off
  untuned placeholders, and nothing more than that.
- **Where the pressure drop lives is the top calibration question.** The logs put most of
  the run-line drop across the venturi (PT21 658 -> PT22 125 psi, with PT5 at 349). The
  current placeholders put it across the injector instead, so the model predicts a ~3 psi
  venturi dP where the log shows ~500. The model structure supports either; raising
  `cda_inj_lox`/`cda_inj_fuel` until the venturi cavitates moves it. Note that taking
  `cda_venturi = 3.22e-5` and the logged dP at face value implies about 3 kg/s of LOX,
  which cannot produce 128 lbf of thrust - so the venturi CdA, the density (two-phase?),
  or the thrust/Pc channels disagree with each other. **Resolve this with a human before
  fitting anything.**

## 7. Constants

Generated from `PlantConfig.calibrated()`. 105 constants: 5 calibrated, 20 from the P&ID, the user or physical constants, and 80 placeholders.

### Calibrated

| name | value | units | placeholder default | how it was fitted |
|---|---|---|---|---|
| `cda_s1` | 8.04e-06 | m^2 | 1e-05 | median over 13 isolated S1 pulses (12:49 median 7.56e-06, 12:36 median 8.95e-06; range 7.04e-06-1.20e-05) of the area whose modelled PT4 rise rate, 0.1-0.35 s after opening, matches the logged rise rate (median interior step between transducer updates). Fitted on rate, not on the telemetry pulse width, per D13. |
| `cda_s2` | 7.83e-06 | m^2 | 1e-05 | median over 7 isolated S2 pulses (12:36 median 7.83e-06; range 5.57e-06-1.41e-05) of the area whose modelled PT14 rise rate, 0.1-0.35 s after opening, matches the logged rise rate (median interior step between transducer updates). Fitted on rate, not on the telemetry pulse width, per D13. Fuel load 39 lbm from the 12:36 S2 mass balance. |
| `cda_pb1` | 2.7e-05 | m^2 | 1e-05 | golden-section least squares on log absolute PT4 over the vent blowdowns 12:36 486.00-487.6 s (516->228 psi, LC4 71 lbm, RMS 72.5 psi, alone 3.53e-05); 12:49 109.82-115.0 s (683->276 psi, LC4 41 lbm, RMS 30.4 psi, alone 2.40e-05). Stops above ~250 psi; below that the LOX flashes and holds the tank up. Valid at lox_ullage_temp: the fit identifies cda * sqrt(T). |
| `cda_pb3` | 4.57e-05 | m^2 | 1e-05 | golden-section least squares on log absolute PT14, 12:49 109.82-113.5 s (651->73 psi), RMS 39.7 psi. Fuel load 39 lbm from the 12:36 S2 mass balance; the fit scales with the fuel ullage volume, which no load cell measures. |
| `pb_dead_time` | 0.23 | s | 0 | median PB open lag 0.366 s over 7 isolated opens of PB1, PB2, PB5, PB6 (12:36, 12:49) minus median solenoid lag 0.138 s over 17 S1/S2 opens, taken as command-logging latency. Lag = midpoint between the last transducer update within 8 psi of the pre-command level and the first outside it (updates are ~0.1 s apart). PB2 and PB4 lag 0.390 and 0.392 s to their venturi, so the fuel run line adds no resolvable fill time. |

### Constants that are not placeholders

| name | value | units | source | note |
|---|---|---|---|---|
| `r_n2` | 296.8 | J/(kg*K) | physical-constant | specific gas constant, N2 |
| `gamma_n2` | 1.4 | - | physical-constant | ratio of specific heats, N2 near ambient |
| `p_atm` | 14.6959 | psia | physical-constant | standard sea-level atmosphere |
| `gravity` | 9.80665 | m/s^2 | physical-constant |  |
| `rho_lox` | 1141 | kg/m^3 | physical-constant | saturated LOX at 1 atm, 90.2 K |
| `t_lox` | 90.2 | K | physical-constant | LOX normal boiling point |
| `pvap_lox` | 14.6959 | psia | physical-constant | LOX vapour pressure at NBP; sets the venturi cavitation floor |
| `rho_fuel` | 785 | kg/m^3 | physical-constant | isopropyl alcohol at 21 degC (D12: the fuel is IPA). Assumes anhydrous; a 91% or 70% rubbing-alcohol grade is denser. Pin down: IPA concentration. |
| `pvap_fuel` | 0.68 | psia | physical-constant | anhydrous IPA vapour pressure at 70 degF (4.7 kPa); cavitation floor for V2 |
| `bottle_volume` | 42.2 | L | user | water volume per bottle, DOT 3AA-6000 class |
| `bottle_count` | 4 | count | user | 4 x 6K bottles per the P&ID |
| `bottles_common_manifold` | 0 | bool | user | 0 = two separate GN2 buses (D12, stand team 2026-09-13), which is also why PT1 and PT11 sit ~1300 psi apart for hours in every logged run. |
| `tank_volume` | 9 | gal | user | LOX and fuel tanks treated as equal, 34.1 L |
| `cda_venturi` | 3.22e-05 | m^2 | user | V1 and V2 measured throat CdA; the one flow constant that is not a guess |
| `rv1_set` | 1350 | psig | P&ID | LOX pressurant branch relief |
| `rv2_set` | 1300 | psig | P&ID | LOX tank ullage relief |
| `rv3_set` | 1400 | psig | P&ID | fuel pressurant branch relief |
| `rv4_set` | 350 | psig | P&ID | LOX dewar relief; boundary only, not integrated |
| `rv5_set` | 250 | psig | P&ID | purge bus relief |
| `r1_set` | 250 | psi | P&ID | R1 purge regulator outlet setpoint |

### PLACEHOLDERS

| name | provisional value | units | what would pin it down |
|---|---|---|---|
| `t_fuel` | 70 | degF | assumed stored at ambient |
| `ambient_default` | 70 | degF | site ambient used when set_initial() is not given one. Logged solenoid-body TCs sit near 105 degF, so the real test-day ambient was probably higher. Pin down: a logged ambient channel. |
| `bottle_split_lox` | 2 | count | bottles on the LOX bus; the rest feed the fuel bus. The split is not stated. Pin down: which bottles sit on which bus. |
| `cda_bottle_crosstie` | 0.0001 | m^2 | only used when bottles_common_manifold = 1 |
| `polytropic_n` | 1.2 | - | blowdown exponent for the bottles, between 1.0 (isothermal) and 1.4 (adiabatic). Pin down: fit PT1 decay against integrated S1 flow, or log a bottle-neck TC. |
| `tank_height` | 0.75 | m | internal liquid column height, used only for static head and level %. Pin down: tank drawing. |
| `lox_ullage_temp` | 200 | K | bulk ullage gas temperature over LOX. Pin down: needs an ullage TC or a real energy balance. |
| `fuel_ullage_temp` | 290 | K | bulk ullage gas temperature over fuel |
| `min_ullage_frac` | 0.02 | - | numerical floor on ullage volume as a fraction of tank volume |
| `vol_lox_press_up` | 0.5 | L | S1 outlet to C1 inlet, the RV1 pocket. Pin down: tubing run length and OD. |
| `vol_lox_press_dn` | 2 | L | C1 outlet to the LOX tank ullage: the volume PT3 sees. Sets how fast PT3 rises on an S1 pulse. Pin down: tubing run, or fit a single S1 pulse in replay. |
| `vol_fuel_press_up` | 0.5 | L | S2 outlet to C3 inlet |
| `vol_fuel_press_dn` | 2 | L | C3 outlet to the fuel tank ullage: the volume PT12/PT13 see |
| `vol_purge_bus` | 1 | L | purge manifold downstream of R1 (PT32) |
| `vol_muscle_bus` | 20 | L | pneumatic surge tank plus actuation tubing (PT31). Pin down: surge tank nameplate. |
| `cda_s3` | 2e-05 | m^2 | muscle-bus vent solenoid |
| `cda_s4` | 5e-06 | m^2 | LOX run-line purge injection solenoid |
| `cda_s5` | 5e-06 | m^2 | fuel run-line purge injection solenoid |
| `cda_lox_press_line` | 0.0001 | m^2 | tubing between the PT3 node and the LOX ullage; sets how fast PT3 equalises. Roughly the bore of 1/2 in tube. It MUST stay well above cda_s1: the solenoid sees bottle pressure while this line sees tank pressure, so a line sized like the solenoid orifice cannot pass the flow and PT3 pegs against RV1 instead of tracking the tank. Pin down: tube size. |
| `cda_fuel_press_line` | 0.0001 | m^2 | tubing between the PT12/PT13 node and the fuel ullage; same caveat as the LOX side |
| `cda_check_gas` | 5e-05 | m^2 | C1, C3 gas check valves, assumed near full bore |
| `check_crack` | 3 | psi | cracking pressure, all check valves. Pin down: datasheet |
| `cda_pb2` | 0.0001 | m^2 | LOX main run valve, full open |
| `cda_pb4` | 0.0001 | m^2 | fuel main run valve, full open |
| `cda_pb5` | 0.0001 | m^2 | LOX fill valve (D12), full open |
| `cda_pb6` | 2e-05 | m^2 | LOX run-line GOX vent/purge valve, full open |
| `cda_manual_full` | 0.0002 | m^2 | full-open CdA shared by the manual valves B1-B6; scaled by open_bN |
| `open_b1` | 1 | - | B1 manual isolation in the LOX dewar fill line, upstream of PB5. On the P&ID B1/PB5/C5 sit between the dewar and the tank-outlet tee, NOT in the tank outlet itself. |
| `open_b2` | 0 | - | B2 needle valve at the PT4 tap; assumed a closed drain/bleed |
| `open_b3` | 0 | - | B3 manual vent by PB3 on the fuel pressurant line |
| `open_b4` | 1 | - | B4 fuel tank outlet ball valve; assumed open for a test |
| `open_b5` | 0 | - | B5 manual bleed beside S3 on the muscle bus |
| `open_b6` | 0 | - | B6 manual bleed beside RV5 on the purge bus |
| `cda_lox_tank_outlet` | 0.0002 | m^2 | LOX tank outlet down to the tee where the dewar fill line joins (the PT4 tap). The P&ID shows no valve here, which is why the logged hotfire flows LOX with PB5 shut. |
| `cda_lox_line_pre` | 0.0002 | m^2 | lumped LOX tubing, tank outlet tee to the V1 inlet tap (PT21) |
| `cda_lox_line_post` | 0.0002 | m^2 | lumped LOX tubing, V1 outlet to the PB6 tee |
| `cda_fuel_line_pre` | 0.0002 | m^2 | lumped fuel tubing, tank outlet to the V2 inlet tap (PT23) |
| `cda_fuel_line_post` | 0.0002 | m^2 | lumped fuel tubing, V2 outlet to PB4 |
| `cda_check_liquid` | 0.0002 | m^2 | C2, C4, C5 liquid check valves, assumed near full bore |
| `venturi_recovery` | 0.85 | - | fraction of the throat pressure drop recovered downstream. Textbook venturi value, not measured. Pin down: a steady flow with PT21, PT22 and a downstream tap all logged. |
| `cda_inj_lox` | 2e-06 | m^2 | LOX injector effective area. ORDER OF MAGNITUDE ONLY, chosen so the model lands near the brief's quoted 108 psi / 128 lbf operating point instead of producing absurd flow. NOT calibrated. Pin down: injector drawing or a water flow test. |
| `cda_inj_fuel` | 1.5e-06 | m^2 | fuel injector effective area, same order-of-magnitude caveat as cda_inj_lox |
| `dewar_pressure` | 30 | psig | LOX dewar self-pressurisation during a fill. Pin down: dewar gauge reading |
| `cda_dewar_line` | 0.0001 | m^2 | lumped dewar fill line and C5 |
| `cda_relief` | 2e-05 | m^2 | full-lift CdA shared by RV1-RV5. Pin down: relief datasheet |
| `relief_band` | 25 | psi | pressure above setpoint at which a relief reaches full lift; also its reseat band |
| `r1_droop` | 400 | psi/(kg/s) | outlet droop per unit flow. Pin down: regulator flow curve |
| `r1_band` | 10 | psi | proportional band over which R1 goes from shut to full open |
| `cda_r1` | 2e-05 | m^2 | R1 full-open CdA |
| `throat_area` | 0.5 | in^2 | nozzle throat area. Round guess, no drawing available. Pin down: measure the throat. |
| `cstar` | 1500 | m/s | characteristic velocity. Round low-side guess for a small LOX/hydrocarbon engine, and it cannot be better than a guess while the fuel is unidentified. |
| `cf` | 1.4 | - | thrust coefficient. Round sea-level guess. Pin down: nozzle geometry |
| `chamber_tau` | 0.05 | s | chamber fill/empty first-order time constant |
| `ignition_min_mdot` | 0.005 | kg/s | per-propellant flow above which auto-ignition is declared |
| `compressor_mdot` | 0.0002 | kg/s | air compressor delivery into the surge tank. Pin down: compressor nameplate SCFM |
| `compressor_cut_in` | 90 | psig | pressure switch cut-in |
| `compressor_cut_out` | 105 | psig | pressure switch cut-out |
| `pb_min_actuation` | 60 | psig | muscle-bus pressure below which a PB actuator cannot hold against its spring and returns to its normal state. Pin down: actuator datasheet. |
| `pb_stroke_tau` | 0.15 | s | PB valve stroke first-order time constant |
| `pb_actuator_volume` | 0.15 | L | air swept per full PB stroke; reproduces the PT31 dip seen when valves cycle |
| `solenoid_tau` | 0.01 | s | S1-S5 solenoid stroke time constant, effectively instant |
| `tc_tau` | 2 | s | first-order lag on every thermocouple reading |
| `tc8_hot` | 400 | degF | TC8 chamber-wall reading during a burn. A bare placeholder: no combustion or wall model here. |
| `tc_manifold_cold` | -100 | degF | TC5 engine-manifold reading once LOX is flowing |
| `lc4_tare` | 0 | lbf | LC4 tare offset. Pin down: a dry-tank reading |
| `lc_fuel_tare` | 0 | lbf | LC_FUEL tare offset; the channel is not in any 2026-09-11 log |
| `thrust_split_a` | 0.333333 | - | fraction of thrust on LC1. Pin down: mount geometry |
| `thrust_split_b` | 0.333333 | - | fraction of thrust on LC2 |
| `thrust_split_c` | 0.333333 | - | fraction of thrust on LC3 |
| `lc_tau` | 0.02 | s | load-cell first-order lag |
| `substep_dt` | 0.002 | s | internal integration sub-step. Numerical, not physical: 2 ms resolves the ~10 ms charging time constant of the smallest modelled volume (0.5 L through a 1e-5 m^2 orifice). |
| `max_substeps` | 200 | count | hard cap on sub-steps per step() call |
| `bisect_iters` | 24 | count | bisection iterations for the branched liquid junction solve |
| `init_bottle` | 4000 | psig | default bottle charge; logs show 4000-4960 psig, rated 6000 |
| `init_lox_ullage` | 0 | psig |  |
| `init_fuel_ullage` | 0 | psig |  |
| `init_lox_mass` | 0 | lbm | a full 9 gal LOX tank is about 86 lbm |
| `init_fuel_mass` | 0 | lbm |  |
| `init_muscle` | 100 | psig | logs sit near 100 psig |
| `init_purge` | 0 | psig |  |
