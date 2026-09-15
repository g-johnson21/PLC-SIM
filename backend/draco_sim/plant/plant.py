from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Mapping, Optional

from .config import LBF_N, LBM_KG, PSI_PA, PlantConfig
from .fluids import bisect, gas_mdot, lag_alpha, liquid_dp, liquid_mdot, ramp, series_cda

logger = logging.getLogger(__name__)

PB_VALVES = ("PB1", "PB2", "PB3", "PB4", "PB5", "PB6")
SOL_VALVES = ("S1", "S2", "S3", "S4", "S5")
VALVES = SOL_VALVES + PB_VALVES
NORMALLY_OPEN = ("PB1", "PB3")

SENSOR_TAGS = (
    "PT0", "PT1", "PT2", "PT3", "PT4", "PT5", "PT11", "PT12", "PT13", "PT14",
    "PT15", "PT21", "PT22", "PT23", "PT24", "PT31", "PT32", "PT33",
    "TC1", "TC2", "TC3", "TC4", "TC5", "TC6", "TC7", "TC8",
    "LC1", "LC2", "LC3", "LC4", "LC_FUEL", "THRUST",
)

_TINY = 1e-12


class GasNode:
    __slots__ = ("name", "volume", "mass", "temp")

    def __init__(self, name: str, volume: float, temp: float) -> None:
        self.name = name
        self.volume = max(volume, 1e-6)
        self.temp = temp
        self.mass = 0.0

    def pressure(self, rgas: float) -> float:
        return self.mass * rgas * self.temp / self.volume

    def set_pressure(self, p_abs: float, rgas: float) -> None:
        self.mass = max(p_abs, 0.0) * self.volume / (rgas * self.temp)


@dataclass
class PlantState:
    t: float = 0.0
    node_p_psig: dict[str, float] = field(default_factory=dict)
    node_t_degF: dict[str, float] = field(default_factory=dict)
    node_mass_kg: dict[str, float] = field(default_factory=dict)
    lox_mass_kg: float = 0.0
    fuel_mass_kg: float = 0.0
    lox_level_frac: float = 0.0
    fuel_level_frac: float = 0.0
    valve_cmd: dict[str, bool] = field(default_factory=dict)
    valve_pos: dict[str, float] = field(default_factory=dict)
    flow_kgps: dict[str, float] = field(default_factory=dict)
    chamber_p_psig: float = 0.0
    thrust_lbf: float = 0.0
    ignited: bool = False
    pb_air_ok: bool = False
    warnings: list[str] = field(default_factory=list)


def _k2f(t_k: float) -> float:
    return (t_k - 273.15) * 9.0 / 5.0 + 32.0


class Plant:
    def __init__(self, cfg: Optional[PlantConfig] = None) -> None:
        self.cfg = cfg if cfg is not None else PlantConfig.calibrated()
        self.k = self.cfg.si()
        self._ic: dict[str, float] = {}
        self._ic_tc: dict[str, float] = {}
        self._ic_valves: dict[str, bool] = {}
        self.state = PlantState()
        self.reset()

    # ------------------------------------------------------------------ setup
    def set_initial(
        self,
        *,
        bottle_psi: Optional[float] = None,
        lox_ullage_psi: Optional[float] = None,
        fuel_ullage_psi: Optional[float] = None,
        lox_mass_lbm: Optional[float] = None,
        fuel_mass_lbm: Optional[float] = None,
        muscle_bus_psi: Optional[float] = None,
        ambient_degF: Optional[float] = None,
        bottle_lox_psi: Optional[float] = None,
        bottle_fuel_psi: Optional[float] = None,
        purge_bus_psi: Optional[float] = None,
        lox_press_up_psi: Optional[float] = None,
        tc_degF: Optional[Mapping[str, float]] = None,
        valves: Optional[Mapping[str, bool]] = None,
    ) -> None:
        """All gauge psi / lbm / degF. Stored, then applied by reset(). `valves` starts
        those valves settled in the given state instead of de-energised."""
        if tc_degF is not None:
            self._ic_tc = {k: float(v) for k, v in tc_degF.items() if k in self.tc}
        if valves is not None:
            self._ic_valves = {k: bool(v) for k, v in valves.items() if k in VALVES}
        given = {
            "bottle_psi": bottle_psi,
            "lox_ullage_psi": lox_ullage_psi,
            "fuel_ullage_psi": fuel_ullage_psi,
            "lox_mass_lbm": lox_mass_lbm,
            "fuel_mass_lbm": fuel_mass_lbm,
            "muscle_bus_psi": muscle_bus_psi,
            "ambient_degF": ambient_degF,
            "bottle_lox_psi": bottle_lox_psi,
            "bottle_fuel_psi": bottle_fuel_psi,
            "purge_bus_psi": purge_bus_psi,
            "lox_press_up_psi": lox_press_up_psi,
        }
        self._ic.update({name: float(v) for name, v in given.items() if v is not None})
        self.reset()

    def reset(self) -> None:
        k = self.k
        ic = self._ic
        self.t = 0.0
        self.p_atm = k["p_atm"]
        self.rgas = k["r_n2"]
        self.gamma = k["gamma_n2"]

        amb_f = ic.get("ambient_degF")
        self.t_amb = (amb_f - 32.0) * 5.0 / 9.0 + 273.15 if amb_f is not None else k["ambient_default"]

        n_bottles = max(1.0, k["bottle_count"])
        n_lox = min(max(k["bottle_split_lox"], 0.0), n_bottles)
        self.common_bottles = k["bottles_common_manifold"] >= 0.5
        if self.common_bottles:
            v_lox = k["bottle_volume"] * n_bottles * 0.5
            v_fuel = v_lox
        else:
            v_lox = k["bottle_volume"] * max(n_lox, 1e-3)
            v_fuel = k["bottle_volume"] * max(n_bottles - n_lox, 1e-3)

        self.tank_volume = k["tank_volume"]
        v_ull_min = self.tank_volume * k["min_ullage_frac"]

        self.nodes: dict[str, GasNode] = {
            "bottles_lox": GasNode("bottles_lox", v_lox, self.t_amb),
            "bottles_fuel": GasNode("bottles_fuel", v_fuel, self.t_amb),
            "lox_press_up": GasNode("lox_press_up", k["vol_lox_press_up"], self.t_amb),
            "lox_press_dn": GasNode("lox_press_dn", k["vol_lox_press_dn"], self.t_amb),
            "fuel_press_up": GasNode("fuel_press_up", k["vol_fuel_press_up"], self.t_amb),
            "fuel_press_dn": GasNode("fuel_press_dn", k["vol_fuel_press_dn"], self.t_amb),
            "purge_bus": GasNode("purge_bus", k["vol_purge_bus"], self.t_amb),
            "muscle_bus": GasNode("muscle_bus", k["vol_muscle_bus"], self.t_amb),
            "lox_ullage": GasNode("lox_ullage", self.tank_volume, k["lox_ullage_temp"]),
            "fuel_ullage": GasNode("fuel_ullage", self.tank_volume, k["fuel_ullage_temp"]),
        }
        self._v_ull_min = v_ull_min

        p_bot = ic.get("bottle_psi", k["init_bottle"] / PSI_PA) * PSI_PA + self.p_atm
        p_bot_lox = ic.get("bottle_lox_psi")
        p_bot_lox = p_bot_lox * PSI_PA + self.p_atm if p_bot_lox is not None else p_bot
        p_bot_fuel = ic.get("bottle_fuel_psi")
        p_bot_fuel = p_bot_fuel * PSI_PA + self.p_atm if p_bot_fuel is not None else p_bot
        self.nodes["bottles_lox"].set_pressure(p_bot_lox, self.rgas)
        self.nodes["bottles_fuel"].set_pressure(p_bot_fuel, self.rgas)
        self._bottle_ref = {
            "bottles_lox": (self.nodes["bottles_lox"].mass, self.t_amb),
            "bottles_fuel": (self.nodes["bottles_fuel"].mass, self.t_amb),
        }

        self.lox_mass = ic.get("lox_mass_lbm", k["init_lox_mass"] / LBM_KG) * LBM_KG
        self.fuel_mass = ic.get("fuel_mass_lbm", k["init_fuel_mass"] / LBM_KG) * LBM_KG
        self._update_ullage_volumes()

        p_lox_ull = ic.get("lox_ullage_psi", k["init_lox_ullage"] / PSI_PA) * PSI_PA + self.p_atm
        p_fuel_ull = ic.get("fuel_ullage_psi", k["init_fuel_ullage"] / PSI_PA) * PSI_PA + self.p_atm
        self.nodes["lox_ullage"].set_pressure(p_lox_ull, self.rgas)
        self.nodes["fuel_ullage"].set_pressure(p_fuel_ull, self.rgas)
        for name in ("lox_press_up", "lox_press_dn"):
            self.nodes[name].set_pressure(p_lox_ull, self.rgas)
        if "lox_press_up_psi" in ic:
            # C1 lets this pocket sit below the tank, as PT2 does in the logs
            self.nodes["lox_press_up"].set_pressure(ic["lox_press_up_psi"] * PSI_PA + self.p_atm, self.rgas)
        for name in ("fuel_press_up", "fuel_press_dn"):
            self.nodes[name].set_pressure(p_fuel_ull, self.rgas)

        p_muscle = ic.get("muscle_bus_psi", k["init_muscle"] / PSI_PA) * PSI_PA + self.p_atm
        self.nodes["muscle_bus"].set_pressure(p_muscle, self.rgas)
        p_purge = ic.get("purge_bus_psi", k["init_purge"] / PSI_PA) * PSI_PA + self.p_atm
        self.nodes["purge_bus"].set_pressure(p_purge, self.rgas)

        # cold start = de-energised: NO valves open, everything else shut
        self.cmd: dict[str, bool] = {v: self._ic_valves.get(v, v in NORMALLY_OPEN) for v in VALVES}
        self.pos: dict[str, float] = {v: (1.0 if self.cmd[v] else 0.0) for v in VALVES}
        # PB actuators act on a command only once it has stood for pb_dead_time
        self._pb_seen: dict[str, bool] = {v: self.cmd[v] for v in PB_VALVES}
        self._pb_pending: dict[str, float] = {v: 0.0 for v in PB_VALVES}
        self.flows: dict[str, float] = {}
        self._r1_mdot = 0.0
        self._compressor_on = False
        self._ignite_override: Optional[bool] = None
        self.ignited = False

        self.p_chamber = self.p_atm
        self.p_man_lox = self.p_atm
        self.p_man_fuel = self.p_atm
        self.thrust = 0.0
        p_l = self.nodes["lox_ullage"].pressure(self.rgas) + k["rho_lox"] * k["gravity"] * k["tank_height"] * self.lox_level
        p_f = self.nodes["fuel_ullage"].pressure(self.rgas) + k["rho_fuel"] * k["gravity"] * k["tank_height"] * self.fuel_level
        self._taps = {"PT4": p_l, "PT21": p_l, "PT22": p_l, "PT14": p_f, "PT23": p_f, "PT24": p_f}

        amb_f_out = _k2f(self.t_amb)
        self.tc: dict[str, float] = {f"TC{i}": amb_f_out for i in range(1, 9)}
        self.tc.update(self._ic_tc)
        self.lc: dict[str, float] = {"LC1": 0.0, "LC2": 0.0, "LC3": 0.0}
        self.pb_air_ok = (self.nodes["muscle_bus"].pressure(self.rgas) - self.p_atm) >= k["pb_min_actuation"]
        self.warnings: list[str] = []
        self._refresh_state()

    # ------------------------------------------------------------------ helpers
    def _update_ullage_volumes(self) -> None:
        rho_l = self.k["rho_lox"]
        rho_f = self.k["rho_fuel"]
        self.lox_mass = max(0.0, self.lox_mass)
        self.fuel_mass = max(0.0, self.fuel_mass)
        v_lox_liq = min(self.lox_mass / rho_l, self.tank_volume * (1.0 - self.k["min_ullage_frac"]))
        v_fuel_liq = min(self.fuel_mass / rho_f, self.tank_volume * (1.0 - self.k["min_ullage_frac"]))
        self.nodes["lox_ullage"].volume = max(self._v_ull_min, self.tank_volume - v_lox_liq)
        self.nodes["fuel_ullage"].volume = max(self._v_ull_min, self.tank_volume - v_fuel_liq)
        self.lox_level = v_lox_liq / self.tank_volume
        self.fuel_level = v_fuel_liq / self.tank_volume

    def _move(self, up: GasNode, dn: Optional[GasNode], cda: float, dt: float,
              p_sink: Optional[float] = None) -> float:
        """Gas transfer with a no-overshoot limiter: the step can never drive the
        downstream pressure above the upstream one, which keeps the explicit
        integrator stable for arbitrarily small node volumes."""
        if cda <= _TINY:
            return 0.0
        p_up = up.pressure(self.rgas)
        p_dn = dn.pressure(self.rgas) if dn is not None else (self.p_atm if p_sink is None else p_sink)
        mdot = gas_mdot(cda, p_up, up.temp, p_dn, self.gamma, self.rgas)
        if mdot <= 0.0:
            return 0.0
        dm = mdot * dt
        k_u = self.rgas * up.temp / up.volume
        if dn is None:
            dm_eq = up.mass - p_dn / k_u
        else:
            k_d = self.rgas * dn.temp / dn.volume
            dm_eq = (up.mass * k_u - dn.mass * k_d) / (k_u + k_d)
        dm = min(dm, max(0.0, dm_eq), up.mass * 0.999)
        up.mass -= dm
        if dn is not None:
            dn.mass += dm
        return dm / dt if dt > 0.0 else 0.0

    def _check_cda(self, cda: float, p_up: float, p_dn: float) -> float:
        return cda if p_up > p_dn + self.k["check_crack"] else 0.0

    def _relief_cda(self, p_abs: float, set_gauge: float) -> float:
        return self.k["cda_relief"] * ramp(p_abs - self.p_atm, set_gauge, set_gauge + self.k["relief_band"])

    def _manual(self, name: str) -> float:
        return self.k["cda_manual_full"] * max(0.0, min(1.0, self.k[f"open_{name}"]))

    # ------------------------------------------------------------------ liquid
    def _solve_liquid(self, rho: float, pvap: float, p_src: float, cda_b: float,
                      cda_pre: float, cda_v: float, cda_mid: float,
                      sinks: list[tuple[float, float]]) -> tuple[float, float, float, float, list[float]]:
        """Quasi-static incompressible chain: source -> cda_b -> tank-outlet tap ->
        cda_pre -> venturi -> cda_mid -> junction -> sinks.

        Returns (mdot_total, p_junction, p_outlet_tap, p_venturi_inlet, per-sink flows).
        Liquid lines carry no pressure state of their own: at these line volumes the
        acoustic/compressibility dynamics are far faster than the 10-100 Hz scan, so
        every liquid pressure is solved algebraically from the current flow."""
        iters = int(self.k["bisect_iters"])
        active = [(c, ps) for c, ps in sinks if c > _TINY]
        cda_up = series_cda(cda_b, cda_pre, cda_mid)
        if cda_up <= _TINY or not active:
            return 0.0, p_src, p_src, p_src, [0.0 for _ in sinks]

        if len(active) == 1:
            c, ps = active[0]
            mdot = liquid_mdot(series_cda(cda_up, c), rho, p_src - ps)
            p_j = p_src - liquid_dp(cda_up, rho, mdot)
        else:
            lo = min(ps for _, ps in active)

            def resid(p: float) -> float:
                return liquid_mdot(cda_up, rho, p_src - p) - sum(liquid_mdot(c, rho, p - ps) for c, ps in active)

            p_j = bisect(resid, lo, p_src, iters)
            mdot = liquid_mdot(cda_up, rho, p_src - p_j)

        p_tap = p_src - liquid_dp(cda_b, rho, mdot)
        p_vin = p_tap - liquid_dp(cda_pre, rho, mdot)
        m_cav = liquid_mdot(cda_v, rho, p_vin - pvap)
        if mdot > m_cav:
            # throat has flashed: the venturi, not the downstream network, sets the flow
            mdot = m_cav
            lo = min(ps for _, ps in active)

            def resid2(p: float) -> float:
                return mdot - sum(liquid_mdot(c, rho, p - ps) for c, ps in active)

            p_j = bisect(resid2, lo, max(p_src, lo + 1.0), iters)
            p_tap = p_src - liquid_dp(cda_b, rho, mdot)
            p_vin = p_tap - liquid_dp(cda_pre, rho, mdot)

        flows = [liquid_mdot(c, rho, p_j - ps) if c > _TINY else 0.0 for c, ps in sinks]
        return mdot, p_j, p_tap, p_vin, flows

    # ------------------------------------------------------------------ step
    def step(self, dt_s: float, valves: Mapping[str, bool], *, ignite: Optional[bool] = None) -> None:
        dt_s = float(dt_s)
        if not math.isfinite(dt_s) or dt_s <= 0.0:
            return
        for name in VALVES:
            if name in valves:
                self.cmd[name] = bool(valves[name])
        self._ignite_override = ignite

        n = max(1, int(math.ceil(dt_s / self.k["substep_dt"])))
        cap = int(self.k["max_substeps"])
        if n > cap:
            self._warn(f"dt {dt_s:.4f} s needs {n} sub-steps, capped at {cap}")
            n = cap
        h = dt_s / n
        snapshot = {name: node.mass for name, node in self.nodes.items()}
        for _ in range(n):
            self._substep(h)
        if not self._finite_check():
            for name, m in snapshot.items():
                self.nodes[name].mass = m
            self._warn("non-finite state detected; rolled back this step")
        self.t += dt_s
        self._refresh_state()

    def _warn(self, msg: str) -> None:
        logger.warning("plant: %s", msg)
        self.warnings.append(msg)
        if len(self.warnings) > 50:
            del self.warnings[:-50]

    def _finite_check(self) -> bool:
        vals = [n.mass for n in self.nodes.values()]
        vals += [self.lox_mass, self.fuel_mass, self.p_chamber, self.thrust]
        return all(math.isfinite(v) for v in vals)

    def _substep(self, dt: float) -> None:
        k = self.k
        rgas = self.rgas
        nodes = self.nodes
        a_pb = lag_alpha(dt, k["pb_stroke_tau"])
        a_sol = lag_alpha(dt, k["solenoid_tau"])
        a_tc = lag_alpha(dt, k["tc_tau"])
        a_lc = lag_alpha(dt, k["lc_tau"])
        a_ch = lag_alpha(dt, k["chamber_tau"])

        # --- actuation -------------------------------------------------
        muscle = nodes["muscle_bus"]
        p_muscle_g = muscle.pressure(rgas) - self.p_atm
        air_ok = p_muscle_g >= k["pb_min_actuation"]
        self.pb_air_ok = air_ok
        swept = 0.0
        for name in PB_VALVES:
            if self.cmd[name] == self._pb_seen[name]:
                self._pb_pending[name] = 0.0
            else:
                self._pb_pending[name] += dt
                if self._pb_pending[name] >= k["pb_dead_time"]:
                    self._pb_seen[name] = self.cmd[name]
                    self._pb_pending[name] = 0.0
            normal = 1.0 if name in NORMALLY_OPEN else 0.0
            target = (1.0 if self._pb_seen[name] else 0.0) if air_ok else normal
            new = self.pos[name] + (target - self.pos[name]) * a_pb
            swept += abs(new - self.pos[name])
            self.pos[name] = new
        for name in SOL_VALVES:
            target = 1.0 if self.cmd[name] else 0.0
            self.pos[name] += (target - self.pos[name]) * a_sol
        if swept > 0.0:
            dm = swept * k["pb_actuator_volume"] * muscle.pressure(rgas) / (rgas * muscle.temp)
            muscle.mass = max(1e-9, muscle.mass - dm)

        # --- muscle bus ------------------------------------------------
        p_mus_g = muscle.pressure(rgas) - self.p_atm
        if p_mus_g <= k["compressor_cut_in"]:
            self._compressor_on = True
        elif p_mus_g >= k["compressor_cut_out"]:
            self._compressor_on = False
        if self._compressor_on:
            muscle.mass += k["compressor_mdot"] * dt
        self.flows["COMPRESSOR"] = k["compressor_mdot"] if self._compressor_on else 0.0
        self.flows["S3"] = self._move(muscle, None, k["cda_s3"] * self.pos["S3"], dt)
        self.flows["B5"] = self._move(muscle, None, self._manual("b5"), dt)

        # --- bottles ---------------------------------------------------
        for name in ("bottles_lox", "bottles_fuel"):
            node = nodes[name]
            m0, t0 = self._bottle_ref[name]
            if m0 > _TINY and node.mass > _TINY:
                node.temp = max(40.0, t0 * (node.mass / m0) ** (k["polytropic_n"] - 1.0))
        if self.common_bottles:
            a, b = nodes["bottles_lox"], nodes["bottles_fuel"]
            if a.pressure(rgas) >= b.pressure(rgas):
                self._move(a, b, k["cda_bottle_crosstie"], dt)
            else:
                self._move(b, a, k["cda_bottle_crosstie"], dt)

        self._update_ullage_volumes()
        lox_ull, fuel_ull = nodes["lox_ullage"], nodes["fuel_ullage"]

        # --- LOX pressurant --------------------------------------------
        up, dn = nodes["lox_press_up"], nodes["lox_press_dn"]
        self.flows["S1"] = self._move(nodes["bottles_lox"], up, k["cda_s1"] * self.pos["S1"], dt)
        self.flows["RV1"] = self._move(up, None, self._relief_cda(up.pressure(rgas), k["rv1_set"]), dt)
        self.flows["C1"] = self._move(
            up, dn, self._check_cda(k["cda_check_gas"], up.pressure(rgas), dn.pressure(rgas)), dt)
        p_dn, p_ull = dn.pressure(rgas), lox_ull.pressure(rgas)
        if p_dn >= p_ull:
            self.flows["LOX_PRESS_LINE"] = self._move(dn, lox_ull, k["cda_lox_press_line"], dt)
        else:
            self.flows["LOX_PRESS_LINE"] = -self._move(lox_ull, dn, k["cda_lox_press_line"], dt)
        self.flows["RV2"] = self._move(lox_ull, None, self._relief_cda(lox_ull.pressure(rgas), k["rv2_set"]), dt)
        self.flows["PB1"] = self._move(lox_ull, None, k["cda_pb1"] * self.pos["PB1"], dt)

        # --- fuel pressurant, R1 purge branch ---------------------------
        up, dn = nodes["fuel_press_up"], nodes["fuel_press_dn"]
        self.flows["S2"] = self._move(nodes["bottles_fuel"], up, k["cda_s2"] * self.pos["S2"], dt)
        self.flows["C3"] = self._move(
            up, dn, self._check_cda(k["cda_check_gas"], up.pressure(rgas), dn.pressure(rgas)), dt)
        self.flows["RV3"] = self._move(dn, None, self._relief_cda(dn.pressure(rgas), k["rv3_set"]), dt)
        self.flows["B3"] = self._move(dn, None, self._manual("b3"), dt)
        purge = nodes["purge_bus"]
        set_eff = k["r1_set"] - k["r1_droop"] * self._r1_mdot
        r1_cda = k["cda_r1"] * ramp(set_eff - (purge.pressure(rgas) - self.p_atm), 0.0, k["r1_band"])
        self._r1_mdot = self._move(dn, purge, r1_cda, dt)
        self.flows["R1"] = self._r1_mdot
        self.flows["RV5"] = self._move(purge, None, self._relief_cda(purge.pressure(rgas), k["rv5_set"]), dt)
        self.flows["B6"] = self._move(purge, None, self._manual("b6"), dt)
        p_dn, p_ull = dn.pressure(rgas), fuel_ull.pressure(rgas)
        if p_dn >= p_ull:
            self.flows["FUEL_PRESS_LINE"] = self._move(dn, fuel_ull, k["cda_fuel_press_line"], dt)
        else:
            self.flows["FUEL_PRESS_LINE"] = -self._move(fuel_ull, dn, k["cda_fuel_press_line"], dt)
        self.flows["PB3"] = self._move(fuel_ull, None, k["cda_pb3"] * self.pos["PB3"], dt)

        # --- liquid run lines -------------------------------------------
        rho_l, rho_f = k["rho_lox"], k["rho_fuel"]
        head_l = rho_l * k["gravity"] * k["tank_height"] * self.lox_level
        head_f = rho_f * k["gravity"] * k["tank_height"] * self.fuel_level
        p_src_l = lox_ull.pressure(rgas) + head_l
        p_src_f = fuel_ull.pressure(rgas) + head_f

        cda_out_l = k["cda_lox_tank_outlet"] if self.lox_mass > _TINY else 0.0
        cda_mid_l = series_cda(k["cda_venturi"] / math.sqrt(max(1e-6, 1.0 - k["venturi_recovery"])),
                               k["cda_lox_line_post"])
        sinks_l = [
            (k["cda_pb6"] * self.pos["PB6"], self.p_atm),
            (series_cda(k["cda_pb2"] * self.pos["PB2"], k["cda_check_liquid"], k["cda_inj_lox"]), self.p_chamber),
        ]
        mdot_l, pj_l, pt4, pt21, flows_l = self._solve_liquid(
            rho_l, k["pvap_lox"], p_src_l, cda_out_l, k["cda_lox_line_pre"], k["cda_venturi"], cda_mid_l, sinks_l)
        pt22 = max(k["pvap_lox"], pt21 - liquid_dp(k["cda_venturi"], rho_l, mdot_l))

        cda_b4 = self._manual("b4") if self.fuel_mass > _TINY else 0.0
        cda_mid_f = series_cda(k["cda_venturi"] / math.sqrt(max(1e-6, 1.0 - k["venturi_recovery"])),
                               k["cda_fuel_line_post"])
        sinks_f = [
            (0.0, self.p_atm),
            (series_cda(k["cda_pb4"] * self.pos["PB4"], k["cda_check_liquid"], k["cda_inj_fuel"]), self.p_chamber),
        ]
        mdot_f, pj_f, pt14, pt23, flows_f = self._solve_liquid(
            rho_f, k["pvap_fuel"], p_src_f, cda_b4, k["cda_fuel_line_pre"], k["cda_venturi"], cda_mid_f, sinks_f)
        pt24 = max(k["pvap_fuel"], pt23 - liquid_dp(k["cda_venturi"], rho_f, mdot_f))

        dm_l = min(mdot_l * dt, self.lox_mass)
        dm_f = min(mdot_f * dt, self.fuel_mass)
        if dt > 0.0:
            scale_l = dm_l / (mdot_l * dt) if mdot_l * dt > _TINY else 1.0
            scale_f = dm_f / (mdot_f * dt) if mdot_f * dt > _TINY else 1.0
            mdot_l *= scale_l
            mdot_f *= scale_f
            flows_l = [f * scale_l for f in flows_l]
            flows_f = [f * scale_f for f in flows_f]
        self.lox_mass -= dm_l
        self.fuel_mass -= dm_f

        # dewar fill: B1 + PB5 + C5 feed the tank-outlet tee and back up into the tank
        cda_fill = series_cda(self._manual("b1"), k["cda_pb5"] * self.pos["PB5"],
                              k["cda_dewar_line"], k["cda_check_liquid"], k["cda_lox_tank_outlet"])
        p_dewar = k["dewar_pressure"] + self.p_atm
        mdot_fill = liquid_mdot(cda_fill, rho_l, p_dewar - max(pt4, self.p_atm) - k["check_crack"])
        if self.lox_level >= 1.0 - k["min_ullage_frac"]:
            mdot_fill = 0.0
        self.lox_mass += mdot_fill * dt
        self.flows["LOX_FILL"] = mdot_fill

        self.flows["LOX_LIQ"] = mdot_l
        self.flows["FUEL_LIQ"] = mdot_f
        self.flows["PB6_VENT"] = flows_l[0]
        self.flows["LOX_RUN"] = flows_l[1]
        self.flows["FUEL_RUN"] = flows_f[1]
        self._update_ullage_volumes()

        # --- engine manifolds ------------------------------------------
        p_man_l = self._manifold(pj_l, flows_l[1], rho_l, k["cda_pb2"] * self.pos["PB2"],
                                 k["cda_s4"] * self.pos["S4"], k["cda_inj_lox"], "S4", dt)
        p_man_f = self._manifold(pj_f, flows_f[1], rho_f, k["cda_pb4"] * self.pos["PB4"],
                                 k["cda_s5"] * self.pos["S5"], k["cda_inj_fuel"], "S5", dt)
        self.p_man_lox += (p_man_l - self.p_man_lox) * a_ch
        self.p_man_fuel += (p_man_f - self.p_man_fuel) * a_ch

        # --- chamber ----------------------------------------------------
        run_l, run_f = flows_l[1], flows_f[1]
        both = run_l > k["ignition_min_mdot"] and run_f > k["ignition_min_mdot"]
        valves_open = self.pos["PB2"] > 0.5 and self.pos["PB4"] > 0.5
        auto = both and valves_open
        self.ignited = auto if self._ignite_override is None else (self._ignite_override and valves_open and both)
        if self.ignited:
            p_target = max(self.p_atm, (run_l + run_f) * k["cstar"] / k["throat_area"])
        else:
            p_target = self.p_atm
        self.p_chamber += (p_target - self.p_chamber) * a_ch
        self.p_chamber = max(self.p_atm * 0.1, self.p_chamber)
        thrust_n = max(0.0, k["cf"] * (self.p_chamber - self.p_atm) * k["throat_area"])
        self.thrust += (thrust_n - self.thrust) * a_lc

        self._taps.update({"PT4": pt4, "PT21": pt21, "PT22": pt22,
                           "PT14": pt14, "PT23": pt23, "PT24": pt24})

        # --- thermal / load cells ---------------------------------------
        amb = _k2f(self.t_amb)
        lox_present = self.lox_mass > 1e-3
        lox_line_cold = lox_present or mdot_l > _TINY
        t_lox_f = _k2f(k["t_lox"])
        t_ull_f = _k2f(k["lox_ullage_temp"])
        targets = {
            "TC1": t_lox_f if lox_present else amb,
            "TC2": t_ull_f if lox_present else amb,
            "TC3": t_lox_f if lox_line_cold else amb,
            "TC4": t_lox_f if lox_line_cold else amb,
            "TC5": _k2f(k["tc_manifold_cold"]) if run_l > k["ignition_min_mdot"] else amb,
            "TC6": amb,
            "TC7": amb,
            "TC8": _k2f(k["tc8_hot"]) if self.ignited else amb,
        }
        for name, tgt in targets.items():
            self.tc[name] += (tgt - self.tc[name]) * a_tc

        split = (k["thrust_split_a"], k["thrust_split_b"], k["thrust_split_c"])
        for i, name in enumerate(("LC1", "LC2", "LC3")):
            self.lc[name] = self.thrust / LBF_N * split[i]

        for node in nodes.values():
            if not math.isfinite(node.mass) or node.mass < 0.0:
                node.mass = max(0.0, node.mass) if math.isfinite(node.mass) else 1e-9

    def _manifold(self, p_junction: float, mdot_liq: float, rho: float, cda_valve: float,
                  cda_purge: float, cda_inj: float, purge_name: str, dt: float) -> float:
        """Engine-manifold pressure. Liquid when the run valve is passing, otherwise
        GN2 from the purge bus through the injector; the purge check valve makes the
        two mutually exclusive, since the purge bus cannot push into a live run line."""
        k = self.k
        p_liq = self.p_atm
        if mdot_liq > _TINY and cda_valve > _TINY:
            p_liq = p_junction - liquid_dp(series_cda(cda_valve, k["cda_check_liquid"]), rho, mdot_liq)
        purge = self.nodes["purge_bus"]
        p_purge = purge.pressure(self.rgas)
        p_gas = self.p_atm
        cda_chain = series_cda(cda_purge, k["cda_check_gas"], cda_inj)
        if cda_chain > _TINY and p_purge > max(p_liq, self.p_chamber) + k["check_crack"]:
            self.flows[purge_name] = self._move(purge, None, cda_chain, dt, p_sink=self.p_chamber)
            mdot_g = self.flows[purge_name]

            def resid(p: float) -> float:
                return (gas_mdot(series_cda(cda_purge, k["cda_check_gas"]), p_purge, purge.temp, p,
                                 self.gamma, self.rgas)
                        - gas_mdot(cda_inj, p, purge.temp, self.p_chamber, self.gamma, self.rgas))

            if mdot_g > 0.0:
                p_gas = bisect(resid, self.p_chamber, p_purge, int(k["bisect_iters"]))
        else:
            self.flows[purge_name] = 0.0
        return max(self.p_atm, p_liq, p_gas)

    # ------------------------------------------------------------------ output
    def _refresh_state(self) -> None:
        s = self.state
        s.t = self.t
        s.node_p_psig = {n: (node.pressure(self.rgas) - self.p_atm) / PSI_PA for n, node in self.nodes.items()}
        s.node_t_degF = {n: _k2f(node.temp) for n, node in self.nodes.items()}
        s.node_mass_kg = {n: node.mass for n, node in self.nodes.items()}
        s.lox_mass_kg = self.lox_mass
        s.fuel_mass_kg = self.fuel_mass
        s.lox_level_frac = self.lox_level
        s.fuel_level_frac = self.fuel_level
        s.valve_cmd = dict(self.cmd)
        s.valve_pos = dict(self.pos)
        s.flow_kgps = dict(self.flows)
        s.chamber_p_psig = (self.p_chamber - self.p_atm) / PSI_PA
        s.thrust_lbf = self.thrust / LBF_N
        s.ignited = self.ignited
        s.pb_air_ok = getattr(self, "pb_air_ok", False)
        s.warnings = list(self.warnings)

    def sensors(self) -> dict[str, float]:
        g = lambda p: (p - self.p_atm) / PSI_PA
        tap = self._taps
        lc1 = self.lc["LC1"]
        lc2 = self.lc["LC2"]
        lc3 = self.lc["LC3"]
        out = {
            "PT0": g(self.p_chamber),
            "PT1": self.state.node_p_psig["bottles_lox"],
            "PT2": self.state.node_p_psig["lox_press_up"],
            "PT3": self.state.node_p_psig["lox_press_dn"],
            "PT4": g(tap["PT4"]),
            "PT5": g(self.p_man_lox),
            "PT11": self.state.node_p_psig["bottles_fuel"],
            "PT12": self.state.node_p_psig["fuel_press_dn"],
            "PT13": self.state.node_p_psig["fuel_press_dn"],
            "PT14": g(tap["PT14"]),
            "PT15": g(self.p_man_fuel),
            "PT21": g(tap["PT21"]),
            "PT22": g(tap["PT22"]),
            "PT23": g(tap["PT23"]),
            "PT24": g(tap["PT24"]),
            "PT31": self.state.node_p_psig["muscle_bus"],
            "PT32": self.state.node_p_psig["purge_bus"],
            "PT33": g(self.p_man_fuel),
            "LC1": lc1,
            "LC2": lc2,
            "LC3": lc3,
            "LC4": self.lox_mass / LBM_KG + self.k["lc4_tare"] / LBF_N,
            "LC_FUEL": self.fuel_mass / LBM_KG + self.k["lc_fuel_tare"] / LBF_N,
            "THRUST": lc1 + lc2 + lc3,
        }
        out.update(self.tc)
        for name, v in out.items():
            if not math.isfinite(v):
                out[name] = 0.0
                self._warn(f"non-finite sensor {name}, reported 0")
        return out
