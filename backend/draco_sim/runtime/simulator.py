from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from draco_sim.hwio import HwIo
from draco_sim.plant import Plant
from draco_sim.plc import (CompileError, CompiledProgram, PlcRuntime, PlcStateError,
                           compile_program, ladder_to_text)
from draco_sim.tags import load_tag_db

from .config import AbortThreshold, BbLoopConfig, ProgramSource, SimConfig
from .errors import SimRejected, SimStateError
from .events import Event, EventLog

GROUPS = ("inputs", "outputs", "plc", "hmi", "abort", "plant", "raw")

# Programs run in this order inside one PLC scan (decisions.md D7, plc-language §7.1):
# the auto-abort monitor computes its request before anything actuates, the sequencer
# owns the procedure, and regulation has the last word on its own coils.
_ROLE_RANK = {"monitor": 0, "sequence": 1, "regulation": 2, "other": 3}

def infer_role(compiled: CompiledProgram) -> str:
    """The role a program gets when the operator did not state one.

    An SFC is a sequence: it owns the stand while it runs. Anything else that drives
    a valve is regulation, so an abort switches it off; anything else that drives no
    valve at all is a monitor and keeps scanning through an abort. Whether a program
    writes a coil is a compile-time fact (CompiledProgram.output_writes), not a guess
    from its name.
    """
    if compiled.is_sfc:
        return "sequence"
    return "regulation" if compiled.output_writes else "monitor"


def role_conflict(role: str, compiled: CompiledProgram) -> str | None:
    """Why an explicit role contradicts what the code does, or None.

    A label must never be able to weaken a safety rule: an SFC owns the stand while it
    runs, only an SFC can, and a program that drives valves cannot pass itself off as
    a monitor. `other` stays allowed, but it does not exempt anything from the abort
    (see Simulator._latch_abort).
    """
    if compiled.is_sfc and role != "sequence":
        return (f"role {role!r} is not allowed for an SFC: a sequential chart owns the "
                f"stand while it runs, so its role must be 'sequence'")
    if not compiled.is_sfc and role == "sequence":
        return (f"role 'sequence' is only allowed for an SFC; this program is "
                f"{compiled.language}")
    if role == "monitor" and compiled.output_writes:
        return (f"role 'monitor' is not allowed for a program that writes output tags "
                f"({', '.join(sorted(compiled.output_writes))}): a monitor must not "
                f"drive valves; use 'regulation'")
    return None


_EXAMPLE_ROLES = (
    ("bangbang_lox.st", "ST", "regulation"),
    ("bangbang_fuel.ld.json", "LD", "regulation"),
    ("hotfire.sfc.json", "SFC", "sequence"),
    ("gn2_purge.sfc.json", "SFC", "sequence"),
    ("abort_monitor.st", "ST", "monitor"),
)


@dataclass
class CompileResult:
    name: str
    language: str
    ok: bool
    errors: list[dict] = field(default_factory=list)
    variables: list[dict] = field(default_factory=list)
    ladder_text: str | None = None

    def as_dict(self) -> dict:
        d = {"name": self.name, "language": self.language, "ok": self.ok,
             "errors": self.errors, "variables": self.variables}
        if self.ladder_text is not None:
            d["ladder_text"] = self.ladder_text
        return d


class Simulator:
    """One stand: hardware I/O simulation, plant and PLC runtime driven by one scan.

    Everything here is synchronous and deterministic — no wall clock, no threads.
    `step()` is one scan in the order docs/runtime.md fixes; `draco_sim.runtime.pacer`
    decides how often a caller should invoke it.
    """

    def __init__(self, config: SimConfig | None = None) -> None:
        self.cfg = config if config is not None else SimConfig()
        self.tag_db = load_tag_db()
        self._specs = self.tag_db.plc_specs()
        self._inputs = tuple(t.tag for t in self.tag_db.inputs)
        self._outputs = tuple(t.tag for t in self.tag_db.outputs)
        self._input_set = {n.upper(): n for n in self._inputs}
        self._output_set = {n.upper(): n for n in self._outputs}
        self._alias = {t.tag: (t.aliases[0] if t.aliases else t.tag) for t in self.tag_db.tags}

        self.hw = HwIo(self.tag_db, self.cfg.hwio)
        self.plant = Plant(self.cfg.plant)
        self._rt = PlcRuntime(self._specs, [])
        self._sources: list[ProgramSource] = []
        self._compiled: list[CompiledProgram] = []
        self._inferred_roles: dict[str, str] = {}
        self._abort_disabled: list[str] = []
        self._chain_tags: frozenset[str] = frozenset()

        self._log = EventLog(self.cfg.event_capacity)
        self._t_base = 0.0
        self._t_scans = 0
        self._scan = 0
        self._running = False
        self._paused = False

        self._manual: dict[str, bool] = {}
        self._hmi_abort = False
        self._bb = {loop: dict(vals) for loop, vals in self.cfg.bb_defaults.items()}
        self._thresholds = [AbortThreshold.from_any(t) for t in self.cfg.abort_thresholds]
        self._abort_latched = False
        self._tripped: dict | None = None
        self._hold_reported: tuple[str, ...] = ()

        self._plc_driven: set[str] = set()
        self._output_image = self._safe_outputs()
        self._seq_t0: dict[str, float] = {}
        self._prev_valves: dict[str, bool] = {}
        self._prime_hardware()

    # ------------------------------------------------------------------ properties
    @property
    def t(self) -> float:
        return self._t_base + self._t_scans * self.dt

    @property
    def dt(self) -> float:
        return self.cfg.dt

    @property
    def scan(self) -> int:
        return self._scan

    @property
    def scan_hz(self) -> float:
        return self.cfg.scan_hz

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def events(self) -> EventLog:
        return self._log

    @property
    def plc(self) -> PlcRuntime:
        return self._rt

    def on_event(self, callback: Callable[[Event], None]) -> None:
        self._log.subscribe(callback)

    def _emit(self, level: str, text: str, source: str = "sim") -> Event:
        return self._log.emit(Event(self.t, self._scan, level, text, source))

    # ------------------------------------------------------------------ programs
    def compile_only(self, program: ProgramSource) -> CompileResult:
        return self._compile(program)[0]

    def _compile(self, program: ProgramSource) -> tuple[CompileResult, CompiledProgram | None]:
        lang = str(program.language).upper()
        try:
            compiled = compile_program(program.source, lang, self._specs, name=program.name)
        except CompileError as exc:
            return CompileResult(program.name, lang, False,
                                 [e.as_dict() for e in exc.errors]), None
        text = ladder_to_text(compiled.source) if lang == "LD" else None
        return CompileResult(program.name, lang, True, [], _variables(compiled), text), compiled

    def load_programs(self, programs: Sequence[ProgramSource]) -> list[CompileResult]:
        """Replace the whole program set. Programs are installed in role order
        (monitor, sequence, regulation, other) so one PLC scan runs the auto-abort
        monitor before the sequencer and the sequencer before regulation (D7).

        A missing role is inferred from the compiled code; an explicit role that
        contradicts the code (role_conflict) fails that program's result like a
        compile error, and nothing is loaded."""
        if self._abort_latched:
            raise SimRejected("cannot load programs while an abort is latched",
                              code="abort_active")
        if self._running:
            raise SimStateError("cannot load programs while the PLC is running; "
                                "stop it first", details={"running": True})
        given = [p if isinstance(p, ProgramSource) else ProgramSource(**p) for p in programs]
        sources: list[ProgramSource] = []
        results: list[CompileResult] = []
        compiled: list[CompiledProgram] = []
        inferred: dict[str, str] = {}
        from_inference: set[str] = set()
        for src in given:
            res, prog = self._compile(src)
            results.append(res)
            if prog is None:
                sources.append(src if src.role else replace(src, role="other"))
                continue
            compiled.append(prog)
            inferred[prog.name] = infer_role(prog)
            conflict = role_conflict(src.role, prog) if src.role else None
            if conflict:
                res.ok = False
                res.errors.append({"message": conflict, "line": None, "col": None,
                                   "path": "/role", "program": src.name})
            if src.role:
                sources.append(src)
            else:
                from_inference.add(src.name)
                sources.append(replace(src, role=inferred[prog.name]))
        bad = [r for r in results if not r.ok]
        if bad:
            raise SimRejected(
                f"{len(bad)} program(s) failed to compile: "
                f"{', '.join(r.name for r in bad)}",
                code="compile_error",
                details={"results": [r.as_dict() for r in results]})

        order = sorted(range(len(sources)),
                       key=lambda i: (_ROLE_RANK[sources[i].role], i))
        self._sources = [sources[i] for i in order]
        self._compiled = [compiled[i] for i in order]
        self._inferred_roles = inferred
        self._abort_disabled = []
        # every output tag some loaded abort chain can write (abort_step + reachable steps)
        self._chain_tags = frozenset().union(*(p.abort_writes for p in self._compiled))

        forced = self._rt.forced()
        self._rt = PlcRuntime(self._specs, self._compiled)
        dropped = []
        for name, value in forced.items():
            try:
                self._rt.force(name, value)
            except ValueError:
                dropped.append(name)
        if dropped:
            self._emit("warn", f"forces dropped (name no longer exists): "
                               f"{', '.join(sorted(dropped))}")
        self._seq_t0.clear()
        self._mirror_bb()
        self._clear_manual(forget_plc=True)
        self._emit("info", "programs loaded: " +
                   ", ".join(f"{s.name} [{s.role}"
                             f"{', inferred' if s.name in from_inference else ''}]"
                             for s in self._sources))
        return results

    def load_examples(self, directory: str | Path | None = None) -> list[CompileResult]:
        """Load the five shipped examples with their declared roles, and check the
        declarations against what the loader would have inferred."""
        sources = self.example_sources(directory)
        results = self.load_programs(sources)
        declared = {s.name: s.role for s in sources}
        for name, guess in self._inferred_roles.items():
            if declared.get(name) not in (None, guess):
                self._emit("warn", f"example {name} declares role "
                                   f"{declared[name]!r} but its code infers "
                                   f"{guess!r}", "sim")
        return results

    def example_sources(self, directory: str | Path | None = None) -> list[ProgramSource]:
        base = Path(directory or self.cfg.examples_dir or _examples_dir())
        out = []
        for filename, language, role in _EXAMPLE_ROLES:
            path = base / filename
            text = path.read_text(encoding="utf-8")
            out.append(ProgramSource(filename.split(".")[0], language, text, role))
        return out

    def inferred_roles(self) -> dict[str, str]:
        """What the loader would classify each loaded program as, whether or not an
        explicit role overrode it."""
        return dict(self._inferred_roles)

    def programs(self) -> list[dict]:
        sfc = self._rt.sfc_state()
        enabled = self._rt.program_enabled()
        halted = {n.upper() for n in self._rt.halted_programs()}
        out = []
        for src in self._sources:
            chart = sfc.get(src.name)
            if chart is not None:
                running = bool(chart["running"])
            else:
                running = (self._running and enabled.get(src.name, False)
                           and src.name.upper() not in halted)
            out.append({"name": src.name, "language": str(src.language).upper(),
                        "source": src.source, "role": src.role,
                        "compiled_ok": True, "running": running})
        return out

    # ------------------------------------------------------------------ PLC control
    def plc_run(self) -> None:
        if self._running:
            return
        self._running = True
        self._emit("info", "PLC RUN", "hmi")

    def plc_stop(self) -> None:
        """A stopped PLC is a safe stand, and it stays safe when the PLC runs again (D14,
        D17): every coil de-energizes, and nothing that could command a valve on the next
        plc.run is left behind -- no manual command, output force, running chart, enabled
        bang-bang loop or held coil. The runtime gets a cold restart (variables back to
        their declared values). The program set, input forces, the HMI setpoints and the
        programs an abort switched off are kept."""
        self._refuse_while_latched("plc.stop")
        if not self._running:
            return
        self._running = False
        self._emit("info", "PLC STOP -- outputs held at their normal (fail-safe) state", "hmi")
        if self._hmi_abort:
            self._hmi_abort = False
            self._emit("abort", "pending abort request dropped: the PLC is stopped and every "
                                "output is at its fail-safe state", "hmi")
        charts = self._rt.sfc_state()
        forces = sorted(n for n in self._rt.forced() if n.upper() in self._output_set)
        cleared = [f"{what}: {', '.join(names)}" for what, names in (
            ("manual commands", sorted(self._manual)),
            ("output forces", forces),
            ("sequences", [p.name for p in self._compiled
                           if p.is_sfc and charts.get(p.name, {}).get("running")]),
            ("bang-bang loops", [loop for loop, vals in self._bb.items() if vals["enable"]]),
        ) if names]
        for name in forces:
            self._rt.unforce(name)
        self._rt.reset()
        for name in self._abort_disabled:
            self._rt.set_program_enabled(name, False)
        self._seq_t0.clear()
        for loop in self._bb:
            self._bb[loop]["enable"] = False
        self._mirror_bb()
        self._clear_manual(forget_plc=True)
        if cleared:
            self._emit("warn", "cleared so nothing moves on plc.run: " + "; ".join(cleared), "hmi")

    def plc_reset(self) -> None:
        self._refuse_while_latched("plc.reset")
        self._reset_plc()
        self._emit("info", "PLC RESET -- variables, charts and the output image are at "
                           "their construction state; regulation loops are OFF", "hmi")

    def _reset_plc(self) -> None:
        self._rt.reset()
        for src in self._sources:
            self._rt.set_program_enabled(src.name, True)
        self._abort_disabled = []
        self._abort_latched = False
        self._hold_reported = ()
        self._hmi_abort = False
        self._tripped = None
        self._seq_t0.clear()
        for loop in self._bb:
            self._bb[loop]["enable"] = False
        self._mirror_bb()
        self._clear_manual(forget_plc=True)

    def _refuse_while_latched(self, what: str) -> None:
        if self._abort_latched:
            raise SimRejected(f"{what} is refused while an abort is latched; control returns "
                              f"to the operator when the abort sequence completes",
                              code="abort_active", details={"waiting_on": self.waiting_on()})

    def plc_clear_faults(self) -> None:
        self._rt.clear_faults()
        self._emit("info", "PLC faults cleared; halted programs restarted", "hmi")

    def pause(self) -> None:
        self._paused = True
        self._emit("info", "simulation paused", "hmi")

    def resume(self) -> None:
        self._paused = False
        self._emit("info", "simulation resumed", "hmi")

    def set_scan_hz(self, scan_hz: float) -> None:
        hz = float(scan_hz)
        if hz <= 0.0:
            raise SimRejected("scan_hz must be > 0", code="bad_request")
        self._t_base = self.t
        self._t_scans = 0
        self.cfg.scan_hz = hz
        self._emit("info", f"scan rate set to {hz:g} Hz")

    # ------------------------------------------------------------------ the scan
    def step(self) -> None:
        """One scan, in the order docs/runtime.md fixes. Everything emitted during
        this scan is stamped with the scan index and the simulated time at its end."""
        dt = self.dt
        self._scan += 1
        self._t_scans += 1

        # 1 input image. Also refreshed while the PLC is stopped: a real scan engine in
        # STOP freezes its image, but freezing the operator's tank-pressure display is a
        # worse lie than a fresh one, and a runtime that is not scanning does nothing
        # with the values. Everything else in 2-6 is genuinely skipped.
        cards = self.hw.read_inputs()
        self._rt.write_inputs(cards)
        result = None
        if self._running:
            # the threshold table reads the cards, not the forced image the programs see,
            # so a forced input can never mask a trip
            trips = self._tripped_thresholds(cards)               # 2a threshold table
            cause = trips[0] if trips else None
            if cause is None:
                cause = self._eval_request_global()               # 2b program request
            if cause is None and self._hmi_abort:                 # 3 manual abort bit
                cause = {"tag": "hmi.abort", "value": True, "threshold": None,
                         "source": "manual", "label": "operator abort"}
            if cause is not None and not self._abort_latched:     # 4 latch
                self._latch_abort(cause)

            before_steps = self._rt.sfc_state()
            result = self._rt.scan(dt)                            # 5 (abort chains too)
            for fault in result.faults:
                self._emit("fault", str(fault), "plc")
            self._announce_steps(before_steps)
            final = self._arbitrate(result)                       # 6 output arbitration
            if self._abort_latched:
                self._check_return(cards, final)                  # 6b return of control
        else:
            final = self._safe_outputs()

        self._output_image = final
        self.hw.write_outputs(final)                              # 7 hardware and plant
        self.hw.step(dt)
        self.plant.step(dt, self.hw.valve_states())
        self.hw.set_physical(self.plant.sensors())
        self._announce_valves()

    def run_scans(self, n: int) -> None:
        for _ in range(int(n)):
            self.step()

    def run_for(self, seconds: float) -> None:
        self.run_scans(round(float(seconds) * self.cfg.scan_hz))

    # ------------------------------------------------------------------ abort
    def _tripped_thresholds(self, cards: Mapping[str, float]) -> list[dict]:
        """Every enabled row the real card readings trip, in table order."""
        out = []
        for th in self._thresholds:
            if not th.enabled:
                continue
            name = self._input_set.get(th.tag.upper())
            reading = cards.get(name) if name is not None else None
            if reading is not None and th.test(float(reading)):
                out.append({"tag": name, "value": float(reading), "threshold": th.value,
                            "op": th.op, "source": "threshold", "label": th.label})
        return out

    def _eval_request_global(self) -> dict | None:
        wanted = self.cfg.auto_abort_global.upper()
        for name, value in self._rt.globals().items():
            if name.upper() == wanted and bool(value):
                return {"tag": f"plc.globals.{name}", "value": True, "threshold": None,
                        "source": "program", "label": "program abort request"}
        return None

    def _latch_abort(self, cause: dict) -> None:
        self._abort_latched = True
        self._hmi_abort = False
        self._hold_reported = ()
        self._tripped = {"tag": cause["tag"], "value": cause["value"],
                         "threshold": cause["threshold"], "t": self.t,
                         "source": cause["source"]}
        self._rt.trigger_abort()
        # Keyed off the code, not the label: every non-SFC program that can drive a
        # valve is switched off, whatever it is called, plus anything explicitly
        # labelled regulation. A program disabled despite its label is named with it.
        stopped = []
        for src, prog in zip(self._sources, self._compiled):
            if prog.is_sfc or not (prog.output_writes or src.role == "regulation"):
                continue
            self._rt.set_program_enabled(prog.name, False)
            if prog.name not in self._abort_disabled:
                self._abort_disabled.append(prog.name)
            stopped.append(prog.name if src.role == "regulation"
                           else f"{prog.name} [{src.role}]")
        self._manual.clear()
        # abort is absolute (D12): no output force survives the latch, and a forced value
        # left in the image does not count as the PLC having driven that coil
        forces = sorted(n for n in self._rt.forced() if n.upper() in self._output_set)
        for name in forces:
            self._rt.unforce(name)
            self._plc_driven.discard(name)
        for prog in self._compiled:
            if prog.is_sfc and prog.sfc.abort_step is not None:
                self._seq_t0.setdefault(prog.name, self.t)
        detail = cause["tag"]
        if cause["source"] == "threshold":
            detail = (f"{cause['tag']}={cause['value']:.1f} {cause['op']} "
                      f"{cause['threshold']:.1f}")
        self._emit("abort", f"ABORT LATCHED -- {detail} ({cause['label']}); "
                            f"regulation off: {', '.join(stopped) or 'none'}; "
                            f"manual commands cleared", "plc")
        if forces:
            self._emit("abort", "output forces cleared: " +
                       ", ".join(f"{self._alias.get(n, n)} ({n})" for n in forces), "plc")
        safe = self._safe_outputs()
        failsafe = [tag for tag in safe
                    if tag not in self._chain_tags and self._output_image.get(tag) != safe[tag]]
        if failsafe:
            self._emit("abort", "fail-safe (no abort chain writes them): " +
                       ", ".join(f"{self._alias.get(tag, tag)} ({tag}) "
                                 f"{'OPEN' if safe[tag] else 'CLOSED'}" for tag in failsafe),
                       "plc")

    def _check_abort_request(self) -> None:
        # a stopped PLC already holds every coil de-energized, so there is nothing to
        # abort, and a request left pending would latch much later on plc.run (D14)
        if not self._running:
            raise SimRejected("the PLC is stopped: every output is already at its "
                              "fail-safe state, so there is nothing to abort",
                              code="rejected")

    def abort(self) -> None:
        self._check_abort_request()
        # a request made while latched is already being served by the running abort
        if not self._hmi_abort and not self._abort_latched:
            self._hmi_abort = True
            self._emit("abort", "manual abort requested (hmi.abort)", "hmi")

    def abort_clear(self) -> None:
        """Kept for protocol compatibility: an abort ends by itself (D12). A no-op when
        nothing is latched, otherwise a refusal naming what the abort is waiting on."""
        if not self._abort_latched:
            return
        waiting = self.waiting_on()
        raise SimRejected(
            "an abort ends by itself when the abort sequence is complete; waiting on: " +
            ("; ".join(waiting) if waiting else "nothing, control returns on the next scan"),
            code="rejected", details={"waiting_on": waiting})

    def waiting_on(self) -> list[str]:
        """Why a latched abort has not returned control yet; [] when nothing is latched."""
        if not self._abort_latched:
            return []
        return self._incomplete_chains() + self._holds(self.hw.read_inputs())

    def _holds(self, cards: Mapping[str, float]) -> list[str]:
        out = [f"{c['tag']} {c['op']} {c['threshold']:g} still tripped"
               for c in self._tripped_thresholds(cards)]
        request = self._eval_request_global()
        if request is not None:
            out.append(f"{request['tag']} still set")
        return out

    def _check_return(self, cards: Mapping[str, float], final: Mapping[str, bool]) -> None:
        """Control returns on the first scan where every abort chain is complete and
        nothing still trips. A trip that outlives the chains holds the latch; disabling
        its row with abort.config lets a failed sensor go."""
        if self._incomplete_chains():
            return
        holds = self._holds(cards)
        if holds:
            if tuple(holds) != self._hold_reported:
                self._hold_reported = tuple(holds)
                self._emit("abort", "abort sequence complete but the latch is held: " +
                           "; ".join(holds) + " (a failed sensor's threshold can be "
                           "disabled with abort.config)", "plc")
            return
        self._rt.clear_abort()
        for prog in self._compiled:
            if prog.is_sfc:
                self._rt.stop_sfc(prog.name)
        # nothing re-arms itself after an abort (D14): the programs it switched off stay
        # off until plc.reset, sim.reset or program.load
        for loop in self._bb:
            self._bb[loop]["enable"] = False
        self._mirror_bb()
        self._abort_latched = False
        self._hold_reported = ()
        self._seq_t0.clear()
        # outputs stay where the abort left them; the PLC image behind them is history
        safe = self._safe_outputs()
        self._plc_driven.clear()
        self._manual = {tag: value for tag, value in final.items() if value != safe[tag]}
        self._emit("abort", "abort sequence complete -- stand safe, operator in control", "plc")
        if self._abort_disabled:
            self._emit("abort", "programs left off until plc.reset re-arms them: " +
                       ", ".join(self._abort_disabled), "plc")
        if self._manual:
            self._emit("abort", "held as manual commands: " + ", ".join(
                f"{self._alias.get(tag, tag)} ({tag}) {'OPEN' if value else 'CLOSED'}"
                for tag, value in sorted(self._manual.items())), "plc")

    def abort_config(self, thresholds: Iterable[AbortThreshold | dict]) -> None:
        table = [AbortThreshold.from_any(t) for t in thresholds]
        unknown = [t.tag for t in table if t.tag.upper() not in self._input_set]
        if unknown:
            raise SimRejected(f"unknown tag(s) in the abort table: {sorted(unknown)}",
                              code="unknown_name", details={"names": sorted(unknown)})
        self._thresholds = table
        armed = [f"{t.tag} {t.op} {t.value:g}" for t in table if t.enabled]
        self._emit("info", "abort thresholds set; armed: " +
                           (", ".join(armed) if armed else "none"), "hmi")

    def _chain_status(self) -> dict[str, dict]:
        """Per SFC with an abort chain: whether its safing chain has finished."""
        state = self._rt.sfc_state()
        out: dict[str, dict] = {}
        for prog in self._compiled:
            if not prog.is_sfc or prog.sfc.abort_step is None:
                continue
            body = prog.sfc
            chart = state.get(prog.name, {})
            active = set(chart.get("active_steps", ()))
            terminal = {body.steps[i].name for i in _terminal_steps(body)
                        if i in body.abort_set}
            done = (not chart.get("running", False)) or (bool(active) and active <= terminal)
            out[prog.name] = {"done": done, "active": sorted(active),
                              "terminal": sorted(terminal)}
        return out

    def _incomplete_chains(self) -> list[str]:
        out = []
        for name, info in self._chain_status().items():
            if info["done"]:
                continue
            where = ", ".join(info["active"]) or "(no active step)"
            if not info["terminal"]:
                where += " (its abort chain has no final step, so it never completes)"
            out.append(f"{name} at {where}")
        return out

    # ------------------------------------------------------------------ sequences
    def sequence_start(self, name: str) -> None:
        prog = self._sfc_program(name)
        if self._abort_latched:
            raise SimRejected(f"cannot start {prog.name}: an abort is latched",
                              code="abort_active")
        if not self._running:
            raise SimRejected(f"cannot start {prog.name}: the PLC is stopped",
                              code="rejected")
        active = self.active_sequence()
        if active is not None and active.upper() != prog.name.upper():
            raise SimRejected(f"cannot start {prog.name}: sequence {active} is running",
                              code="rejected", details={"active_sequence": active})
        try:
            self._rt.start_sfc(prog.name)
        except PlcStateError as exc:
            raise SimRejected(str(exc), code="abort_active") from None
        self._seq_t0[prog.name] = self.t
        held = (" (manual commands stay in force: " + ", ".join(sorted(self._manual)) + ")"
                if self._manual else "")
        self._emit("sequence", f"T+0.000 {prog.name} STARTED{held}", "hmi")

    def sequence_stop(self, name: str) -> None:
        prog = self._sfc_program(name)
        if self._abort_latched:
            raise SimRejected(f"cannot stop {prog.name} while an abort is latched: "
                              f"the safing chain must run", code="abort_active")
        self._rt.stop_sfc(prog.name)
        self._emit("sequence", f"{prog.name} STOPPED by the operator "
                               f"(outputs hold their last commanded state)", "hmi")

    def _sfc_program(self, name: str) -> CompiledProgram:
        for prog in self._compiled:
            if prog.name.upper() == str(name).upper():
                if not prog.is_sfc:
                    raise SimRejected(f"program {prog.name!r} is not a sequence",
                                      code="rejected")
                return prog
        raise SimRejected(f"unknown sequence {name!r}", code="unknown_name",
                          details={"name": name})

    def active_sequence(self) -> str | None:
        """The chart that currently owns the stand: running and not parked on a final
        step. A chart sitting on COMPLETE / ABORT_DONE has finished."""
        state = self._rt.sfc_state()
        for prog in self._compiled:
            if not prog.is_sfc:
                continue
            chart = state.get(prog.name)
            if not chart or not chart["running"]:
                continue
            active = set(chart["active_steps"])
            terminal = {prog.sfc.steps[i].name for i in _terminal_steps(prog.sfc)}
            if active and active <= terminal:
                continue
            return prog.name
        return None

    def _announce_steps(self, before: Mapping[str, dict]) -> None:
        after = self._rt.sfc_state()
        for prog in self._compiled:
            if not prog.is_sfc:
                continue
            name = prog.name
            was = set(before.get(name, {}).get("active_steps", ()))
            now = after.get(name, {}).get("active_steps", ())
            for step in now:
                if step in was:
                    continue
                t0 = self._seq_t0.setdefault(name, self.t)
                self._emit("sequence", f"T+{self.t - t0:.3f} {name} {step}", "plc")

    # ------------------------------------------------------------------ arbitration
    def manual_allowed(self) -> bool:
        return (self._running and not self._abort_latched
                and self.active_sequence() is None)

    def _arbitrate(self, result) -> dict[str, bool]:
        """Per output tag, in order:

        1. an enabled program wrote it this scan (or it is forced) -> the PLC image;
        2. an operator manual command is set               -> the manual command;
        3. the PLC has driven it since the last reset      -> the PLC image (held);
        4. nothing has ever driven it                      -> its fail-safe state.

        While an abort is latched a two-row table applies instead: written by a loaded
        abort chain and driven by the PLC -> the PLC image; anything else -> fail-safe,
        whichever program last drove it. Output forces were cleared at the latch.

        Rule 4 matters: a cleared PLC output image is all-false, and false means
        'commanded closed', which would seal the two normally-open tank vents the
        moment an abort cleared the manual commands. A coil nothing has driven sits
        de-energized, the way the hardware does.
        """
        # a running sequence leaves manual commands in force; only an abort releases them
        # here (plc_stop drops them itself)
        if self._manual and self._abort_latched:
            dropped = ", ".join(sorted(self._manual))
            self._manual.clear()
            self._emit("warn", f"manual commands dropped ({dropped}): the stand is "
                               f"under abort control", "sim")
        if self._manual:
            # a chart that writes a coil takes it back: hotfire closes PB2 once, and a
            # left-over manual PB2 open must not re-open it on the next scan
            charts = self._rt.sfc_state()
            seq_tags = {t for p in self._compiled
                        if p.is_sfc and charts.get(p.name, {}).get("running")
                        for t in p.output_writes}
            taken = sorted(t for t in self._manual if t in result.outputs_written and t in seq_tags)
            for tag in taken:
                del self._manual[tag]
            if taken:
                self._emit("warn", "manual command released to the running sequence: " +
                           ", ".join(f"{self._alias.get(t, t)} ({t})" for t in taken), "sim")
        forced = {n for n in self._rt.forced() if n.upper() in self._output_set}
        owned = set(result.outputs_written) | forced
        self._plc_driven |= owned
        plc_image = self._rt.read_outputs()
        final = self._safe_outputs()
        if self._abort_latched:
            for tag in final:
                if tag in self._chain_tags and tag in self._plc_driven:
                    final[tag] = bool(plc_image[tag])
            return final
        for tag in final:
            if tag in owned or (tag not in self._manual and tag in self._plc_driven):
                final[tag] = bool(plc_image[tag])
            elif tag in self._manual:
                final[tag] = self._manual[tag]
        return final

    def _safe_outputs(self) -> dict[str, bool]:
        """Every coil de-energized: NC valves closed, NO valves open. This is what the
        stand does with the PLC stopped or the power off."""
        return {t.tag: t.normal_state == "NO" for t in self.tag_db.outputs}

    def _clear_manual(self, forget_plc: bool = False) -> None:
        """Drop every manual command. `forget_plc` also forgets which coils the PLC
        has driven, which belongs with anything that clears the PLC output image."""
        self._manual.clear()
        if forget_plc:
            self._plc_driven.clear()

    def _announce_valves(self) -> None:
        states = self.hw.valve_states()
        for tag, open_ in states.items():
            if self._prev_valves.get(tag) != open_:
                if tag in self._prev_valves:
                    self._emit("command", f"{self._alias.get(tag, tag)} ({tag}) -> "
                                          f"{'OPEN' if open_ else 'CLOSED'}", "plc")
        self._prev_valves = states

    def _prime_hardware(self) -> None:
        self.hw.set_physical(self.plant.sensors())
        self.hw.step(0.0)
        self._prev_valves = self.hw.valve_states()

    # ------------------------------------------------------------------ read / write
    def read(self, names: Sequence[str]) -> dict[str, Any]:
        values: dict[str, Any] = {}
        unknown: list[str] = []
        for name in names:
            found, value = self._read_one(str(name))
            if found:
                values[str(name)] = value
            else:
                unknown.append(str(name))
        if unknown:
            raise SimRejected(f"unknown name(s): {unknown}", code="unknown_name",
                              details={"names": unknown})
        return values

    def _read_one(self, name: str) -> tuple[bool, Any]:
        key = name.upper()
        if key in self._input_set:
            return True, self._rt.read_inputs()[self._input_set[key]]
        if key in self._output_set:
            return True, self._output_image[self._output_set[key]]
        low = name.lower()
        if low.startswith("plc.globals."):
            wanted = name[len("plc.globals."):].upper()
            for gname, value in self._rt.globals().items():
                if gname.upper() == wanted:
                    return True, value
            return False, None
        if low == "hmi.abort":
            return True, self._hmi_abort
        if low.startswith("hmi.bb."):
            parts = name.split(".")
            if len(parts) == 4 and parts[2] in self._bb:
                return self._read_bb(parts[2], parts[3])
            return False, None
        if low == "hmi.manual_allowed":
            return True, self.manual_allowed()
        if low == "hmi.active_sequence":
            return True, self.active_sequence()
        if low == "abort.thresholds":
            return True, [t.as_dict() for t in self._thresholds]
        if low == "abort.tripped":
            return True, self._tripped
        if low == "abort.latched":
            return True, self._abort_latched
        if low == "abort.waiting_on":
            return True, self.waiting_on()
        if low.startswith("plant."):
            return _walk(self._plant_dict(), name.split(".")[1:])
        if low.startswith("raw."):
            raw = self._raw_dict()
            key = name[4:]
            return (True, raw[key]) if key in raw else (False, None)
        return False, None

    def _read_bb(self, loop: str, field_: str) -> tuple[bool, Any]:
        if field_ == "state":
            return True, self._bb_state(loop)
        if field_ in ("setpoint", "deadband", "enable"):
            return True, self._bb[loop][field_]
        return False, None

    def _abort_switched_off(self, loop: str) -> list[str]:
        """Programs driving this loop's solenoid that an abort switched off and no reset
        has re-armed."""
        sol = self.cfg.bb_globals[loop].solenoid
        return [prog.name for prog in self._compiled
                if prog.name in self._abort_disabled and sol in prog.output_writes]

    def _bb_state(self, loop: str) -> str:
        if not self._bb[loop]["enable"] or self._abort_switched_off(loop):
            return "OFF"
        return "PRESS" if self._output_image.get(self.cfg.bb_globals[loop].solenoid) else "HOLD"

    def write(self, values: Mapping[str, Any]) -> None:
        """Atomic: every name is checked before anything is applied."""
        plan: list[tuple[str, str, Any]] = []
        unknown: list[str] = []
        # one write may disable a loop and hand its solenoid to the operator
        enabling = {loop: bool(v) for k, v in values.items() for loop in self._bb
                    if str(k).lower() == f"hmi.bb.{loop}.enable"}
        for name, value in values.items():
            key = str(name)
            low = key.lower()
            up = key.upper()
            if up in self._input_set:
                raise SimRejected(f"{key} is an input tag and is read-only",
                                  code="read_only", details={"name": key})
            if up in self._output_set:
                self._check_manual_write(self._output_set[up], enabling)
                plan.append(("output", self._output_set[up], bool(value)))
            elif low.startswith("plc.globals."):
                resolved = self._resolve_global(key[len("plc.globals."):])
                if resolved is None:
                    unknown.append(key)
                else:
                    plan.append(("global", resolved, value))
            elif low == "hmi.abort":
                if not bool(value):
                    raise SimRejected("hmi.abort cannot be written false; an abort ends by "
                                      "itself when the abort sequence completes",
                                      code="rejected", details={"name": key})
                self._check_abort_request()
                plan.append(("abort", "", True))
            elif low.startswith("hmi.bb."):
                parts = key.split(".")
                if (len(parts) != 4 or parts[2] not in self._bb
                        or parts[3] not in ("setpoint", "deadband", "enable")):
                    if len(parts) == 4 and parts[3] == "state":
                        raise SimRejected("hmi.bb.<loop>.state is derived and read-only",
                                          code="read_only", details={"name": key})
                    unknown.append(key)
                elif parts[3] == "enable" and bool(value) and self._abort_latched:
                    raise SimRejected(f"{key}: bang-bang loops stay off while an abort is "
                                      f"latched", code="abort_active", details={"name": key})
                elif parts[3] == "enable" and bool(value) and self._abort_switched_off(parts[2]):
                    off = self._abort_switched_off(parts[2])
                    raise SimRejected(f"{key}: {', '.join(off)} has been off since the abort; "
                                      f"plc.reset re-arms it", code="rejected",
                                      details={"name": key, "programs": off})
                else:
                    plan.append(("bb", f"{parts[2]}.{parts[3]}", value))
            elif low == "abort.thresholds":
                raise SimRejected("write the abort table with abort.config",
                                  code="rejected", details={"name": key})
            elif low.startswith("plant.") or low.startswith("raw.") or low.startswith("hmi."):
                raise SimRejected(f"{key} is read-only", code="read_only",
                                  details={"name": key})
            else:
                unknown.append(key)
        if unknown:
            raise SimRejected(f"unknown name(s): {unknown}", code="unknown_name",
                              details={"names": unknown})

        for kind, target, value in plan:
            if kind == "output":
                self._manual[target] = value
                self._emit("command", f"manual {self._alias.get(target, target)} "
                                      f"({target}) -> {'OPEN' if value else 'CLOSED'}", "hmi")
            elif kind == "global":
                self._rt.write_globals({target: value})
            elif kind == "abort":
                self.abort()
            else:
                loop, field_ = target.split(".")
                self._bb[loop][field_] = bool(value) if field_ == "enable" else float(value)
                self._mirror_bb(loop)
                sol = self.cfg.bb_globals[loop].solenoid
                if field_ == "enable" and self._bb[loop]["enable"] and sol in self._manual:
                    # an enabled loop owns its solenoid (D17); inside its band it writes
                    # nothing, so a left-over manual open would keep pressing
                    del self._manual[sol]
                    self._emit("warn", f"manual command released to the {loop} bang-bang loop: "
                                       f"{self._alias.get(sol, sol)} ({sol})", "hmi")
                self._emit("info", f"bang-bang {loop}: {field_} = "
                                   f"{self._bb[loop][field_]}", "hmi")

    def _loop_for(self, tag: str) -> str | None:
        """The bang-bang loop whose solenoid this output is, if any."""
        for loop in self._bb:
            if self.cfg.bb_globals[loop].solenoid == tag:
                return loop
        return None

    def _check_manual_write(self, tag: str, enabling: Mapping[str, bool]) -> None:
        if self._abort_latched:
            raise SimRejected(f"{tag}: an abort is latched and owns every output until the "
                              f"abort sequence completes", code="abort_active",
                              details={"name": tag})
        active = self.active_sequence()
        if active is not None:
            raise SimRejected(f"{tag}: sequence active ({active}); stop it first",
                              code="rejected", details={"name": tag,
                                                        "active_sequence": active})
        if not self._running:
            raise SimRejected(f"{tag}: the PLC is stopped and outputs are held at their "
                              f"safe state", code="rejected", details={"name": tag})
        loop = self._loop_for(tag)
        if loop is not None and enabling.get(loop, self._bb[loop]["enable"]):
            raise SimRejected(f"{tag}: the {loop} bang-bang loop is enabled and owns it; "
                              f"disable the loop to actuate {tag} by hand",
                              code="rejected", details={"name": tag, "loop": loop})

    def _resolve_global(self, name: str) -> str | None:
        for gname in self._rt.globals():
            if gname.upper() == str(name).upper():
                return gname
        return None

    def _mirror_bb(self, loop: str | None = None) -> None:
        loops = [loop] if loop is not None else list(self._bb)
        mapping = {}
        for name in loops:
            cfgl: BbLoopConfig = self.cfg.bb_globals[name]
            vals = self._bb[name]
            for field_, gname in (("setpoint", cfgl.setpoint), ("deadband", cfgl.deadband),
                                  ("enable", cfgl.enable)):
                if self._resolve_global(gname):
                    mapping[gname] = vals[field_]
        if mapping:
            self._rt.write_globals(mapping)

    # ------------------------------------------------------------------ forcing
    def force(self, name: str, value: Any) -> None:
        if self._abort_latched and str(name).upper() in self._output_set:
            raise SimRejected(f"{name}: output forces are refused while an abort is latched",
                              code="abort_active", details={"name": name})
        try:
            self._rt.force(name, value)
        except ValueError as exc:
            raise SimRejected(str(exc), code="unknown_name", details={"name": name}) from None
        self._emit("warn", f"FORCED {name} := {value}", "hmi")

    def unforce(self, name: str) -> None:
        try:
            self._rt.unforce(name)
        except ValueError as exc:
            raise SimRejected(str(exc), code="unknown_name", details={"name": name}) from None
        self._emit("info", f"force removed on {name}", "hmi")

    # ------------------------------------------------------------------ sim reset
    def reset_plant(self, initial: Mapping[str, Any] | None = None) -> None:
        """sim.reset, the instructor's reset and the one reset allowed while an abort is
        latched: new plant initial conditions, hardware image rebuilt, clock and scan
        counter to zero, and the PLC cleared the way plc.reset clears it (variables,
        charts, output image, manual commands, abort latch and record). The program set
        and forces are kept."""
        kwargs = dict(initial or {})
        allowed = {"bottle_psi", "lox_ullage_psi", "fuel_ullage_psi", "lox_mass_lbm",
                   "fuel_mass_lbm", "muscle_bus_psi", "ambient_degF", "bottle_lox_psi",
                   "bottle_fuel_psi", "purge_bus_psi", "tc_degF"}
        unknown = sorted(set(kwargs) - allowed)
        if unknown:
            raise SimRejected(f"unknown initial condition(s): {unknown}",
                              code="unknown_name", details={"names": unknown})
        self.plant.set_initial(**kwargs)
        was_latched = self._abort_latched
        self._reset_plc()
        self.hw.reset()
        self._output_image = self._safe_outputs()
        self._t_base = 0.0
        self._t_scans = 0
        self._scan = 0
        self._prime_hardware()
        if was_latched:
            self._emit("abort", "abort cleared by sim.reset (instructor action)", "hmi")
        self._emit("info", "sim reset: " + (", ".join(f"{k}={v}" for k, v in kwargs.items())
                                            or "plant config defaults"), "hmi")

    # ------------------------------------------------------------------ snapshot
    def snapshot(self, groups: Sequence[str] | None = None) -> dict:
        want = set(GROUPS) if groups is None else {str(g).lower() for g in groups}
        out: dict[str, Any] = {"t": self.t, "scan": self._scan,
                               "scan_hz": self.cfg.scan_hz, "paused": self._paused}
        if "inputs" in want:
            out["inputs"] = self._rt.read_inputs()
        if "outputs" in want:
            out["outputs"] = dict(self._output_image)
        if "plc" in want:
            out["plc"] = {
                "running": self._running,
                "abort_active": self._rt.abort_active(),
                "faults": [dataclasses.asdict(f) for f in self._rt.faults()],
                "halted": self._rt.halted_programs(),
                "enabled": self._rt.program_enabled(),
                "sfc": self._rt.sfc_state(),
                "globals": self._rt.globals(),
                "forced": self._rt.forced(),
            }
        if "hmi" in want:
            out["hmi"] = {
                "abort": self._hmi_abort,
                "bb": {loop: {**vals, "state": self._bb_state(loop),
                              "abort_off": self._abort_switched_off(loop)}
                       for loop, vals in self._bb.items()},
                "manual_allowed": self.manual_allowed(),
                "active_sequence": self.active_sequence(),
                "manual": dict(self._manual),
            }
        # the abort group is always present: it is the one thing a client must never
        # be able to filter away
        out["abort"] = {"thresholds": [t.as_dict() for t in self._thresholds],
                        "tripped": self._tripped, "latched": self._abort_latched,
                        "waiting_on": self.waiting_on()}
        if "plant" in want:
            out["plant"] = self._plant_dict()
        if "raw" in want:
            out["raw"] = self._raw_dict()
        return out

    def _plant_dict(self) -> dict:
        return dataclasses.asdict(self.plant.state)

    def _raw_dict(self) -> dict:
        out = {}
        for ch in self.hw.channels():
            out[f"{ch.module}.{ch.module_index}.{ch.channel}"] = {
                "tag": ch.tag, "kind": ch.kind, "electrical_value": ch.electrical_value,
                "electrical_unit": ch.electrical_unit, "raw_code": ch.raw_code,
                "eng_value": ch.eng_value, "eng_unit": ch.eng_unit,
                "last_refresh_s": ch.last_refresh_s}
        return out

    # ------------------------------------------------------------------ welcome
    def welcome_payload(self) -> dict:
        return {
            "protocol": 1,
            "sim_version": self.cfg.sim_version,
            "tags": [self._tag_entry(t) for t in self.tag_db.tags],
            "programs": self.programs(),
            "examples": [{"name": s.name, "language": str(s.language).upper(),
                          "source": s.source} for s in self.example_sources()],
            "notice": self.cfg.notice,
        }

    @staticmethod
    def _tag_entry(tag) -> dict:
        return {"tag": tag.tag, "kind": tag.kind, "signal": tag.signal,
                "units": tag.units, "range": list(tag.range) if tag.range else None,
                "normal_state": tag.normal_state, "description": tag.description,
                "aliases": list(tag.aliases), "pid_tag": tag.pid_tag}


def _terminal_steps(body) -> set[int]:
    froms = set()
    for tr in body.transitions:
        froms.update(tr.froms)
    return {i for i in range(len(body.steps)) if i not in froms}


def _variables(prog: CompiledProgram) -> list[dict]:
    out = []
    for decl in prog.locals:
        if decl.name.startswith("#"):
            continue
        out.append({"name": decl.name, "type": decl.fb_type or decl.dtype,
                    "scope": "VAR_CONSTANT" if decl.constant else "VAR"})
    for decl in prog.globals:
        out.append({"name": decl.name, "type": decl.fb_type or decl.dtype,
                    "scope": "VAR_GLOBAL"})
    return out


def _walk(root: Mapping[str, Any], path: Sequence[str]) -> tuple[bool, Any]:
    node: Any = root
    for part in path:
        if isinstance(node, Mapping) and part in node:
            node = node[part]
        else:
            return False, None
    return True, node


def _examples_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "examples"
