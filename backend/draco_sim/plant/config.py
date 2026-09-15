from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

SOURCES = ("P&ID", "user", "datasheet", "physical-constant", "calibrated", "PLACEHOLDER")

CALIBRATION_PATH = Path(__file__).with_name("calibration.yaml")

PSI_PA = 6894.757293168361
LBM_KG = 0.45359237
LBF_N = 4.4482216152605
GAL_M3 = 0.003785411784
IN2_M2 = 0.00064516
L_M3 = 1e-3

# gauge-referenced units keep their gauge value; add P_ATM_PA at the use site.
_UNIT_FACTORS: dict[str, float] = {
    "-": 1.0,
    "count": 1.0,
    "bool": 1.0,
    "Pa": 1.0,
    "psi": PSI_PA,
    "psig": PSI_PA,
    "psia": PSI_PA,
    "m^3": 1.0,
    "L": L_M3,
    "gal": GAL_M3,
    "m^2": 1.0,
    "in^2": IN2_M2,
    "m": 1.0,
    "s": 1.0,
    "kg": 1.0,
    "lbm": LBM_KG,
    "N": 1.0,
    "lbf": LBF_N,
    "kg/s": 1.0,
    "m/s": 1.0,
    "m/s^2": 1.0,
    "kg/m^3": 1.0,
    "J/(kg*K)": 1.0,
    "K": 1.0,
    "Pa/(kg/s)": 1.0,
    "psi/(kg/s)": PSI_PA,
}


@dataclass(frozen=True)
class Constant:
    value: float
    units: str
    source: str
    notes: str = ""

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError(f"bad source {self.source!r}; must be one of {SOURCES}")
        if self.units != "degF" and self.units not in _UNIT_FACTORS:
            raise ValueError(f"unknown units {self.units!r}")

    @property
    def si(self) -> float:
        if self.units == "degF":
            return (float(self.value) - 32.0) * 5.0 / 9.0 + 273.15
        return float(self.value) * _UNIT_FACTORS[self.units]


def _c(value: float, units: str, source: str, notes: str = "") -> Constant:
    return Constant(value=value, units=units, source=source, notes=notes)


PH = "PLACEHOLDER"
PC = "physical-constant"


@dataclass(frozen=True)
class PlantConfig:
    """Every number the plant model uses. Nothing else in the package may hold a
    physical constant. `source` tells you how much to trust each one; run
    `PlantConfig().placeholders()` for the list that still needs pinning down."""

    # --- fluid properties -------------------------------------------------
    r_n2: Constant = _c(296.8, "J/(kg*K)", PC, "specific gas constant, N2")
    gamma_n2: Constant = _c(1.40, "-", PC, "ratio of specific heats, N2 near ambient")
    p_atm: Constant = _c(14.6959, "psia", PC, "standard sea-level atmosphere")
    gravity: Constant = _c(9.80665, "m/s^2", PC)
    rho_lox: Constant = _c(1141.0, "kg/m^3", PC, "saturated LOX at 1 atm, 90.2 K")
    t_lox: Constant = _c(90.2, "K", PC, "LOX normal boiling point")
    pvap_lox: Constant = _c(14.6959, "psia", PC, "LOX vapour pressure at NBP; sets the venturi cavitation floor")

    rho_fuel: Constant = _c(
        785.0, "kg/m^3", PC,
        "isopropyl alcohol at 21 degC (D12: the fuel is IPA). Assumes anhydrous; a 91% or 70% "
        "rubbing-alcohol grade is denser. Pin down: IPA concentration.",
    )
    t_fuel: Constant = _c(70.0, "degF", PH, "assumed stored at ambient")
    pvap_fuel: Constant = _c(
        0.68, "psia", PC, "anhydrous IPA vapour pressure at 70 degF (4.7 kPa); cavitation floor for V2",
    )

    ambient_default: Constant = _c(
        70.0, "degF", PH,
        "site ambient used when set_initial() is not given one. Logged solenoid-body TCs sit near "
        "105 degF, so the real test-day ambient was probably higher. Pin down: a logged ambient channel.",
    )

    # --- GN2 supply -------------------------------------------------------
    bottle_volume: Constant = _c(42.2, "L", "user", "water volume per bottle, DOT 3AA-6000 class")
    bottle_count: Constant = _c(4, "count", "user", "4 x 6K bottles per the P&ID")
    bottle_split_lox: Constant = _c(
        2, "count", PH,
        "bottles on the LOX bus; the rest feed the fuel bus. The split is not stated. Pin down: which "
        "bottles sit on which bus.",
    )
    bottles_common_manifold: Constant = _c(
        0, "bool", "user",
        "0 = two separate GN2 buses (D12, stand team 2026-09-13), which is also why PT1 and PT11 sit "
        "~1300 psi apart for hours in every logged run.",
    )
    cda_bottle_crosstie: Constant = _c(1.0e-4, "m^2", PH, "only used when bottles_common_manifold = 1")
    polytropic_n: Constant = _c(
        1.20, "-", PH,
        "blowdown exponent for the bottles, between 1.0 (isothermal) and 1.4 (adiabatic). Pin down: "
        "fit PT1 decay against integrated S1 flow, or log a bottle-neck TC.",
    )

    # --- tanks ------------------------------------------------------------
    tank_volume: Constant = _c(9.0, "gal", "user", "LOX and fuel tanks treated as equal, 34.1 L")
    tank_height: Constant = _c(
        0.75, "m", PH,
        "internal liquid column height, used only for static head and level %. Pin down: tank drawing.",
    )
    lox_ullage_temp: Constant = _c(
        200.0, "K", PH,
        "bulk ullage gas temperature over LOX. Pin down: needs an ullage TC or a real energy balance.",
    )
    fuel_ullage_temp: Constant = _c(290.0, "K", PH, "bulk ullage gas temperature over fuel")
    min_ullage_frac: Constant = _c(0.02, "-", PH, "numerical floor on ullage volume as a fraction of tank volume")

    # --- pressurant line volumes -----------------------------------------
    vol_lox_press_up: Constant = _c(
        0.5, "L", PH, "S1 outlet to C1 inlet, the RV1 pocket. Pin down: tubing run length and OD.",
    )
    vol_lox_press_dn: Constant = _c(
        2.0, "L", PH,
        "C1 outlet to the LOX tank ullage: the volume PT3 sees. Sets how fast PT3 rises on an S1 pulse. "
        "Pin down: tubing run, or fit a single S1 pulse in replay.",
    )
    vol_fuel_press_up: Constant = _c(0.5, "L", PH, "S2 outlet to C3 inlet")
    vol_fuel_press_dn: Constant = _c(2.0, "L", PH, "C3 outlet to the fuel tank ullage: the volume PT12/PT13 see")
    vol_purge_bus: Constant = _c(1.0, "L", PH, "purge manifold downstream of R1 (PT32)")
    vol_muscle_bus: Constant = _c(
        20.0, "L", PH,
        "pneumatic surge tank plus actuation tubing (PT31). Pin down: surge tank nameplate.",
    )

    # --- gas restrictions -------------------------------------------------
    cda_s1: Constant = _c(
        1.0e-5, "m^2", PH,
        "LOX bang-bang press solenoid, filter loss lumped in. ~3.6 mm equivalent bore. Pin down: "
        "solenoid datasheet Cv, or fit PT3 rise rate on a single pulse.",
    )
    cda_s2: Constant = _c(1.0e-5, "m^2", PH, "fuel bang-bang press solenoid, filter loss lumped in")
    cda_s3: Constant = _c(2.0e-5, "m^2", PH, "muscle-bus vent solenoid")
    cda_s4: Constant = _c(5.0e-6, "m^2", PH, "LOX run-line purge injection solenoid")
    cda_s5: Constant = _c(5.0e-6, "m^2", PH, "fuel run-line purge injection solenoid")
    cda_lox_press_line: Constant = _c(
        1.0e-4, "m^2", PH,
        "tubing between the PT3 node and the LOX ullage; sets how fast PT3 equalises. Roughly the bore "
        "of 1/2 in tube. It MUST stay well above cda_s1: the solenoid sees bottle pressure while this "
        "line sees tank pressure, so a line sized like the solenoid orifice cannot pass the flow and "
        "PT3 pegs against RV1 instead of tracking the tank. Pin down: tube size.",
    )
    cda_fuel_press_line: Constant = _c(
        1.0e-4, "m^2", PH, "tubing between the PT12/PT13 node and the fuel ullage; same caveat as the LOX side",
    )
    cda_check_gas: Constant = _c(5.0e-5, "m^2", PH, "C1, C3 gas check valves, assumed near full bore")
    check_crack: Constant = _c(3.0, "psi", PH, "cracking pressure, all check valves. Pin down: datasheet")

    cda_pb1: Constant = _c(1.0e-5, "m^2", PH, "LOX tank GN2 vent (NO). Sets tank blowdown rate on a vent")
    cda_pb3: Constant = _c(1.0e-5, "m^2", PH, "fuel tank GN2 vent (NO)")

    # --- liquid restrictions ----------------------------------------------
    cda_pb2: Constant = _c(1.0e-4, "m^2", PH, "LOX main run valve, full open")
    cda_pb4: Constant = _c(1.0e-4, "m^2", PH, "fuel main run valve, full open")
    cda_pb5: Constant = _c(1.0e-4, "m^2", PH, "LOX fill valve (D12), full open")
    cda_pb6: Constant = _c(2.0e-5, "m^2", PH, "LOX run-line GOX vent/purge valve, full open")
    cda_manual_full: Constant = _c(
        2.0e-4, "m^2", PH, "full-open CdA shared by the manual valves B1-B6; scaled by open_bN",
    )
    open_b1: Constant = _c(
        1.0, "-", PH,
        "B1 manual isolation in the LOX dewar fill line, upstream of PB5. On the P&ID B1/PB5/C5 sit "
        "between the dewar and the tank-outlet tee, NOT in the tank outlet itself.",
    )
    open_b2: Constant = _c(0.0, "-", PH, "B2 needle valve at the PT4 tap; assumed a closed drain/bleed")
    open_b3: Constant = _c(0.0, "-", PH, "B3 manual vent by PB3 on the fuel pressurant line")
    open_b4: Constant = _c(1.0, "-", PH, "B4 fuel tank outlet ball valve; assumed open for a test")
    open_b5: Constant = _c(0.0, "-", PH, "B5 manual bleed beside S3 on the muscle bus")
    open_b6: Constant = _c(0.0, "-", PH, "B6 manual bleed beside RV5 on the purge bus")
    cda_lox_tank_outlet: Constant = _c(
        2.0e-4, "m^2", PH,
        "LOX tank outlet down to the tee where the dewar fill line joins (the PT4 tap). The P&ID "
        "shows no valve here, which is why the logged hotfire flows LOX with PB5 shut.",
    )
    cda_lox_line_pre: Constant = _c(
        2.0e-4, "m^2", PH, "lumped LOX tubing, tank outlet tee to the V1 inlet tap (PT21)",
    )
    cda_lox_line_post: Constant = _c(2.0e-4, "m^2", PH, "lumped LOX tubing, V1 outlet to the PB6 tee")
    cda_fuel_line_pre: Constant = _c(2.0e-4, "m^2", PH, "lumped fuel tubing, tank outlet to the V2 inlet tap (PT23)")
    cda_fuel_line_post: Constant = _c(2.0e-4, "m^2", PH, "lumped fuel tubing, V2 outlet to PB4")
    cda_check_liquid: Constant = _c(2.0e-4, "m^2", PH, "C2, C4, C5 liquid check valves, assumed near full bore")

    cda_venturi: Constant = _c(
        3.22e-5, "m^2", "user", "V1 and V2 measured throat CdA; the one flow constant that is not a guess",
    )
    venturi_recovery: Constant = _c(
        0.85, "-", PH,
        "fraction of the throat pressure drop recovered downstream. Textbook venturi value, not "
        "measured. Pin down: a steady flow with PT21, PT22 and a downstream tap all logged.",
    )

    cda_inj_lox: Constant = _c(
        2.0e-6, "m^2", PH,
        "LOX injector effective area. ORDER OF MAGNITUDE ONLY, chosen so the model lands near the "
        "brief's quoted 108 psi / 128 lbf operating point instead of producing absurd flow. NOT "
        "calibrated. Pin down: injector drawing or a water flow test.",
    )
    cda_inj_fuel: Constant = _c(
        1.5e-6, "m^2", PH, "fuel injector effective area, same order-of-magnitude caveat as cda_inj_lox",
    )

    dewar_pressure: Constant = _c(
        30.0, "psig", PH, "LOX dewar self-pressurisation during a fill. Pin down: dewar gauge reading",
    )
    cda_dewar_line: Constant = _c(1.0e-4, "m^2", PH, "lumped dewar fill line and C5")

    # --- relief valves and regulator --------------------------------------
    rv1_set: Constant = _c(1350.0, "psig", "P&ID", "LOX pressurant branch relief")
    rv2_set: Constant = _c(1300.0, "psig", "P&ID", "LOX tank ullage relief")
    rv3_set: Constant = _c(1400.0, "psig", "P&ID", "fuel pressurant branch relief")
    rv4_set: Constant = _c(350.0, "psig", "P&ID", "LOX dewar relief; boundary only, not integrated")
    rv5_set: Constant = _c(250.0, "psig", "P&ID", "purge bus relief")
    cda_relief: Constant = _c(2.0e-5, "m^2", PH, "full-lift CdA shared by RV1-RV5. Pin down: relief datasheet")
    relief_band: Constant = _c(
        25.0, "psi", PH, "pressure above setpoint at which a relief reaches full lift; also its reseat band",
    )

    r1_set: Constant = _c(250.0, "psi", "P&ID", "R1 purge regulator outlet setpoint")
    r1_droop: Constant = _c(
        400.0, "psi/(kg/s)", PH, "outlet droop per unit flow. Pin down: regulator flow curve",
    )
    r1_band: Constant = _c(10.0, "psi", PH, "proportional band over which R1 goes from shut to full open")
    cda_r1: Constant = _c(2.0e-5, "m^2", PH, "R1 full-open CdA")

    # --- engine -----------------------------------------------------------
    throat_area: Constant = _c(
        0.50, "in^2", PH,
        "nozzle throat area. Round guess, no drawing available. Pin down: measure the throat.",
    )
    cstar: Constant = _c(
        1500.0, "m/s", PH,
        "characteristic velocity. Round low-side guess for a small LOX/hydrocarbon engine, and it "
        "cannot be better than a guess while the fuel is unidentified.",
    )
    cf: Constant = _c(1.40, "-", PH, "thrust coefficient. Round sea-level guess. Pin down: nozzle geometry")
    chamber_tau: Constant = _c(0.05, "s", PH, "chamber fill/empty first-order time constant")
    ignition_min_mdot: Constant = _c(
        0.005, "kg/s", PH, "per-propellant flow above which auto-ignition is declared",
    )

    # --- muscle bus and actuation -----------------------------------------
    compressor_mdot: Constant = _c(
        2.0e-4, "kg/s", PH, "air compressor delivery into the surge tank. Pin down: compressor nameplate SCFM",
    )
    compressor_cut_in: Constant = _c(90.0, "psig", PH, "pressure switch cut-in")
    compressor_cut_out: Constant = _c(105.0, "psig", PH, "pressure switch cut-out")
    pb_min_actuation: Constant = _c(
        60.0, "psig", PH,
        "muscle-bus pressure below which a PB actuator cannot hold against its spring and returns to "
        "its normal state. Pin down: actuator datasheet.",
    )
    pb_stroke_tau: Constant = _c(0.15, "s", PH, "PB valve stroke first-order time constant")
    pb_dead_time: Constant = _c(
        0.0, "s", PH,
        "delay between a PB command changing and the actuator starting to stroke. A command that "
        "reverts inside the delay is never seen by the valve. Air loss is not delayed.",
    )
    pb_actuator_volume: Constant = _c(
        0.15, "L", PH, "air swept per full PB stroke; reproduces the PT31 dip seen when valves cycle",
    )
    solenoid_tau: Constant = _c(0.01, "s", PH, "S1-S5 solenoid stroke time constant, effectively instant")

    # --- thermal ----------------------------------------------------------
    tc_tau: Constant = _c(2.0, "s", PH, "first-order lag on every thermocouple reading")
    tc8_hot: Constant = _c(
        400.0, "degF", PH,
        "TC8 chamber-wall reading during a burn. A bare placeholder: no combustion or wall model here.",
    )
    tc_manifold_cold: Constant = _c(-100.0, "degF", PH, "TC5 engine-manifold reading once LOX is flowing")

    # --- load cells -------------------------------------------------------
    lc4_tare: Constant = _c(0.0, "lbf", PH, "LC4 tare offset. Pin down: a dry-tank reading")
    lc_fuel_tare: Constant = _c(0.0, "lbf", PH, "LC_FUEL tare offset; the channel is not in any 2026-09-11 log")
    thrust_split_a: Constant = _c(0.3333333333, "-", PH, "fraction of thrust on LC1. Pin down: mount geometry")
    thrust_split_b: Constant = _c(0.3333333333, "-", PH, "fraction of thrust on LC2")
    thrust_split_c: Constant = _c(0.3333333333, "-", PH, "fraction of thrust on LC3")
    lc_tau: Constant = _c(0.02, "s", PH, "load-cell first-order lag")

    # --- numerics ---------------------------------------------------------
    substep_dt: Constant = _c(
        2.0e-3, "s", PH,
        "internal integration sub-step. Numerical, not physical: 2 ms resolves the ~10 ms charging "
        "time constant of the smallest modelled volume (0.5 L through a 1e-5 m^2 orifice).",
    )
    max_substeps: Constant = _c(200, "count", PH, "hard cap on sub-steps per step() call")
    bisect_iters: Constant = _c(24, "count", PH, "bisection iterations for the branched liquid junction solve")

    # --- default initial conditions ---------------------------------------
    init_bottle: Constant = _c(4000.0, "psig", PH, "default bottle charge; logs show 4000-4960 psig, rated 6000")
    init_lox_ullage: Constant = _c(0.0, "psig", PH)
    init_fuel_ullage: Constant = _c(0.0, "psig", PH)
    init_lox_mass: Constant = _c(0.0, "lbm", PH, "a full 9 gal LOX tank is about 86 lbm")
    init_fuel_mass: Constant = _c(0.0, "lbm", PH)
    init_muscle: Constant = _c(100.0, "psig", PH, "logs sit near 100 psig")
    init_purge: Constant = _c(0.0, "psig", PH)

    # ----------------------------------------------------------------------
    def si(self) -> dict[str, float]:
        return {f.name: getattr(self, f.name).si for f in fields(self)}

    def placeholders(self) -> list[tuple[str, Constant]]:
        return [(f.name, getattr(self, f.name)) for f in fields(self)
                if getattr(self, f.name).source == PH]

    def as_dict(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for f in fields(self):
            c: Constant = getattr(self, f.name)
            out[f.name] = {"value": c.value, "units": c.units, "source": c.source, "notes": c.notes}
        return out

    def to_yaml(self, path: str | Path | None = None) -> str:
        text = yaml.safe_dump(self.as_dict(), sort_keys=False, default_flow_style=False, width=100)
        if path is not None:
            Path(path).write_text(text, encoding="utf-8")
        return text

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PlantConfig":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        known = {f.name for f in fields(cls)}
        unknown = set(raw) - known
        if unknown:
            raise ValueError(f"{path}: unknown config keys {sorted(unknown)}")
        defaults = cls()
        kwargs: dict[str, Constant] = {}
        for name, spec in raw.items():
            if not isinstance(spec, dict) or "value" not in spec:
                raise ValueError(f"{path}: {name} must be a mapping with at least a 'value'")
            default: Constant = getattr(defaults, name)
            kwargs[name] = Constant(
                value=float(spec["value"]),
                units=str(spec.get("units", default.units)),
                source=str(spec.get("source", default.source)),
                notes=str(spec.get("notes", default.notes)),
            )
        return cls(**kwargs)

    @classmethod
    def calibrated(cls, path: str | Path | None = None) -> "PlantConfig":
        """Defaults overlaid with the fitted constants from `calibrate`. Falls back to
        the plain defaults when no calibration file exists."""
        path = Path(path) if path is not None else CALIBRATION_PATH
        return cls.from_yaml(path) if path.exists() else cls()
