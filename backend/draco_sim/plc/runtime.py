from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping

from .compiler import SYS_VARS, VarDecl
from .errors import PlcFault, PlcFaultSignal, PlcStateError
from .fb import FunctionBlock
from .nodes import ExecContext
from .program import CompiledProgram
from .sfc import SfcBody, SfcState
from .types import TagSpec, accumulate, coerce_value, default_value, normalise_tags

# An engine bug must surface as a fault, not as an exception out of scan().
_TRAPPED = (PlcFaultSignal, ZeroDivisionError, ValueError, OverflowError, TypeError,
            KeyError, AttributeError, IndexError, RecursionError)


@dataclass
class ScanResult:
    scan_index: int
    dt_s: float
    sim_time_s: float
    faults: list[PlcFault] = field(default_factory=list)
    outputs_changed: dict[str, Any] = field(default_factory=dict)
    duration_s: float = 0.0
    outputs_written: frozenset[str] = frozenset()


class _OutputImage(dict):
    """The output image, which also records which tags the running programs wrote.

    A write counts even when it stores the value the tag already had: output
    arbitration needs to know that a program is driving the coil, not that the
    coil changed. Recording is only on while a program body executes, so forces
    and external edits are not mistaken for program writes.
    """

    __slots__ = ("written", "recording")

    def __init__(self) -> None:
        super().__init__()
        self.written: set[str] = set()
        self.recording = False

    def __setitem__(self, key, value) -> None:
        if self.recording:
            self.written.add(key)
        super().__setitem__(key, value)


class _ProgramState:
    __slots__ = ("prog", "ctx", "locals", "fbs", "sfc", "halted", "enabled")

    def __init__(self, prog: CompiledProgram, ctx: ExecContext, locals_: dict,
                 fbs: list[FunctionBlock], sfc: SfcState | None):
        self.prog = prog
        self.ctx = ctx
        self.locals = locals_
        self.fbs = fbs
        self.sfc = sfc
        self.halted = False
        self.enabled = True


class PlcRuntime:
    """Holds the I/O image, program memory and scan state for one set of programs.

    Programs run in the order given. Nothing in here reads the wall clock: all time
    comes from the dt passed to scan(), so two runtimes fed the same inputs and dts
    produce identical outputs. (ScanResult.duration_s is a diagnostic measured with
    perf_counter and never influences program behaviour.)
    """

    def __init__(self, tags, programs: list[CompiledProgram]):
        self.tags: list[TagSpec] = normalise_tags(tags)
        self._tagmap = {t.name.upper(): t for t in self.tags}
        self.programs = list(programs)

        seen: set[str] = set()
        for p in self.programs:
            key = p.name.upper()
            if key in seen:
                raise ValueError(f"duplicate program name {p.name!r}")
            seen.add(key)
            missing = p.tag_names - set(self._tagmap)
            if missing:
                raise ValueError(f"program {p.name!r} was compiled against tags that this "
                                 f"runtime does not have: {sorted(missing)}")

        self._inputs: dict[str, Any] = {}
        self._written: dict[str, Any] = {}
        self._outputs = _OutputImage()
        self._globals: dict[str, Any] = {}
        self._global_decls: dict[str, VarDecl] = {}
        self._sys: dict[str, Any] = {}
        self._states: list[_ProgramState] = []
        self._forced: dict[str, tuple[str, str | None, str, Any]] = {}
        self._faults: list[PlcFault] = []

        self._merge_globals()
        self._build()

    # ------------------------------------------------------------------ construction
    def _merge_globals(self) -> None:
        for p in self.programs:
            for d in p.globals:
                key = d.name.upper()
                prev = self._global_decls.get(key)
                if prev is None:
                    self._global_decls[key] = d
                    continue
                if prev.dtype != d.dtype or prev.fb_type != d.fb_type:
                    raise ValueError(
                        f"VAR_GLOBAL {d.name!r} is declared as "
                        f"{prev.fb_type or prev.dtype} and as {d.fb_type or d.dtype}")
                if d.init is not None and prev.init is not None and d.init != prev.init:
                    raise ValueError(f"VAR_GLOBAL {d.name!r} has conflicting initial values "
                                     f"{prev.init!r} and {d.init!r}")
                if prev.init is None and d.init is not None:
                    self._global_decls[key] = d

    def _build(self) -> None:
        self._inputs.clear()
        self._written.clear()
        self._outputs.clear()
        for t in self.tags:
            if t.direction == "in":
                self._inputs[t.name] = default_value(t.dtype)
                self._written[t.name] = default_value(t.dtype)
            else:
                self._outputs[t.name] = default_value(t.dtype)
        self._globals.clear()
        for d in self._global_decls.values():
            self._globals[d.name] = d.make()
        self._sys.clear()
        self._sys.update({"SYS_ABORT": False, "SYS_SCAN_TIME": 0.0,
                          "SYS_FIRST_SCAN": True, "SYS_TIME": 0.0})

        self._states = []
        for p in self.programs:
            locals_: dict[str, Any] = {d.name: d.make() for d in p.locals}
            ctx = ExecContext(locals_, self._globals, self._inputs, self._outputs,
                              self._sys, p.name)
            fbs = [v for v in locals_.values() if isinstance(v, FunctionBlock)]
            fbs += [self._globals[d.name] for d in p.globals
                    if isinstance(self._globals.get(d.name), FunctionBlock)]
            sfc = None
            if p.sfc is not None:
                sfc = SfcState(len(p.sfc.steps))
                ctx.sfc = sfc
                ctx.steps = sfc.steps
                if p.sfc.autostart:
                    p.sfc.start(sfc)
            self._states.append(_ProgramState(p, ctx, locals_, fbs, sfc))

        self._scan_index = 0
        self._sim_raw = 0.0
        self._sim_comp = 0.0
        self._sim_time = 0.0
        self._abort = False
        self._abort_pending = False
        self._faults = []
        self._apply_forces()

    def reset(self) -> None:
        """Cold restart: variables to their initial values, SFCs back to construction
        state, faults and abort cleared. Forces are kept and re-applied."""
        self._build()

    # ------------------------------------------------------------------ I/O
    def write_inputs(self, values: Mapping[str, Any]) -> None:
        for name, value in values.items():
            spec = self._tagmap.get(str(name).upper())
            if spec is None:
                raise ValueError(f"unknown tag {name!r}")
            if spec.direction != "in":
                raise ValueError(f"tag {spec.name!r} is an output and cannot be written "
                                 f"with write_inputs()")
            v = coerce_value(value, spec.dtype)
            self._written[spec.name] = v
            if spec.name not in self._forced:
                self._inputs[spec.name] = v

    def read_outputs(self) -> dict[str, Any]:
        return dict(self._outputs)

    def read_inputs(self) -> dict[str, Any]:
        return dict(self._inputs)

    # ------------------------------------------------------------------ scan
    def scan(self, dt_s: float) -> ScanResult:
        t0 = time.perf_counter()
        dt = float(dt_s)
        if dt < 0.0:
            raise ValueError("dt_s must be >= 0")
        self._scan_index += 1
        self._sys["SYS_SCAN_TIME"] = dt
        self._sys["SYS_FIRST_SCAN"] = self._scan_index == 1
        self._sys["SYS_TIME"] = self._sim_time

        if self._abort_pending:
            self._abort_pending = False
            for ps in self._states:
                if ps.sfc is not None:
                    ps.prog.sfc.apply_abort(ps.sfc, self._scan_index)
                    if ps.prog.sfc.abort_step is not None:
                        # A fresh abort enters the safing chain even after a program fault.
                        ps.halted = False
        self._sys["SYS_ABORT"] = self._abort
        self._apply_forces()

        before = dict(self._outputs)
        self._outputs.written.clear()
        faults: list[PlcFault] = []
        for ps in self._states:
            aborting = (self._abort and ps.sfc is not None
                        and ps.sfc.aborted and ps.sfc.running)
            if ps.halted or (not ps.enabled and not aborting):
                continue
            ctx = ps.ctx
            ctx.dt = dt
            ctx.scan = self._scan_index
            snap = self._snapshot(ps)
            written_before = set(self._outputs.written)
            self._outputs.recording = True
            try:
                ps.prog.executable.execute(ctx)
            except _TRAPPED as exc:
                self._restore(ps, snap)
                # the faulting program's writes were rolled back, so it wrote nothing
                self._outputs.written.clear()
                self._outputs.written.update(written_before)
                ps.halted = True
                if isinstance(exc, PlcFaultSignal):
                    fault = PlcFault(ps.prog.name, exc.kind, exc.message, exc.line, exc.col,
                                     exc.path, self._scan_index, self._sim_time)
                else:
                    fault = PlcFault(ps.prog.name, "internal",
                                     f"{type(exc).__name__}: {exc}", None, None, None,
                                     self._scan_index, self._sim_time)
                faults.append(fault)
                self._faults.append(fault)
            finally:
                self._outputs.recording = False

        self._apply_forces()
        changed = {k: v for k, v in self._outputs.items() if before[k] != v}
        self._sim_raw, self._sim_comp = accumulate(self._sim_raw, self._sim_comp, dt)
        self._sim_time = self._sim_raw + self._sim_comp
        return ScanResult(self._scan_index, dt, self._sim_time, faults, changed,
                          time.perf_counter() - t0,
                          frozenset(self._outputs.written))

    @staticmethod
    def _snapshot(ps: _ProgramState):
        return (dict(ps.locals), [fb.state() for fb in ps.fbs],
                dict(ps.ctx.globals), dict(ps.ctx.outputs),
                ps.sfc.snapshot() if ps.sfc is not None else None)

    @staticmethod
    def _restore(ps: _ProgramState, snap) -> None:
        locals_, fbstates, globals_, outputs, sfcsnap = snap
        ps.locals.clear()
        ps.locals.update(locals_)
        for fb, st in zip(ps.fbs, fbstates):
            fb.restore(st)
        ps.ctx.globals.clear()
        ps.ctx.globals.update(globals_)
        ps.ctx.outputs.clear()
        ps.ctx.outputs.update(outputs)
        if sfcsnap is not None:
            ps.sfc.restore(sfcsnap)

    @property
    def scan_index(self) -> int:
        return self._scan_index

    @property
    def sim_time_s(self) -> float:
        return self._sim_time

    # ------------------------------------------------------------------ abort
    def trigger_abort(self) -> None:
        """Latch the abort. On the next scan every SFC drops out of its current steps
        and enters its abort chain; normal transitions stay blocked until clear_abort()."""
        self._abort = True
        self._abort_pending = True
        self._sys["SYS_ABORT"] = True

    def clear_abort(self) -> None:
        """Drop the latch and the transition block. This starts, stops and restarts
        nothing: every chart stays exactly where the abort left it, and arming a
        sequence again is an explicit start_sfc() (normally after reset())."""
        self._abort = False
        self._abort_pending = False
        self._sys["SYS_ABORT"] = False
        for ps in self._states:
            if ps.sfc is not None:
                ps.sfc.aborted = False

    def abort_active(self) -> bool:
        return self._abort

    # ------------------------------------------------------------------ sequences
    def _sfc_state(self, name: str) -> _ProgramState:
        for ps in self._states:
            if ps.prog.name.upper() == str(name).upper():
                if ps.sfc is None:
                    raise ValueError(f"program {ps.prog.name!r} is not an SFC")
                return ps
        raise ValueError(f"unknown program {name!r}")

    def start_sfc(self, name: str) -> None:
        """Run a sequence from its initial step. Entry actions of the initial step
        execute on the next scan.

        Refused while an abort is latched: an abort gates every sequence in the
        runtime, including ones that were not running when it latched."""
        ps = self._sfc_state(name)
        if self._abort:
            raise PlcStateError(
                f"cannot start sequence {ps.prog.name!r}: an abort is latched. "
                f"Call clear_abort() (and normally reset()) before arming a sequence.")
        ps.prog.sfc.start(ps.sfc)

    def stop_sfc(self, name: str) -> None:
        """Deactivate every step. No exit actions run and outputs hold their state."""
        ps = self._sfc_state(name)
        ps.prog.sfc.stop(ps.sfc)

    def sfc_state(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for ps in self._states:
            if ps.sfc is None:
                continue
            body: SfcBody = ps.prog.sfc
            out[ps.prog.name] = {
                "active_steps": [body.steps[i].name for i, s in enumerate(ps.sfc.steps)
                                 if s.active],
                "step_times": {body.steps[i].name: s.t for i, s in enumerate(ps.sfc.steps)
                               if s.active},
                "aborted": ps.sfc.aborted,
                "running": ps.sfc.running,
                "stored_actions": list(ps.sfc.stored),
            }
        return out

    # ------------------------------------------------------------------ faults
    def faults(self) -> list[PlcFault]:
        return list(self._faults)

    def clear_faults(self) -> None:
        """Restart every halted program. Variables keep the values they had when the
        program faulted (the faulting scan itself was rolled back)."""
        self._faults.clear()
        for ps in self._states:
            ps.halted = False

    def halted_programs(self) -> list[str]:
        return [ps.prog.name for ps in self._states if ps.halted]

    def set_program_enabled(self, name: str, enabled: bool) -> None:
        """Skip a program in the scan. Its outputs hold; the scan loop uses this to
        stop regulation while an abort is active. Latched SFC abort chains still run."""
        for ps in self._states:
            if ps.prog.name.upper() == str(name).upper():
                ps.enabled = bool(enabled)
                return
        raise ValueError(f"unknown program {name!r}")

    def program_enabled(self) -> dict[str, bool]:
        return {ps.prog.name: ps.enabled for ps in self._states}

    # ------------------------------------------------------------------ variables
    def variables(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for ps in self._states:
            vals: dict[str, Any] = {}
            for d in ps.prog.locals:
                if d.name.startswith("#"):
                    continue
                _expand(vals, d.name, ps.locals.get(d.name))
            for d in ps.prog.globals:
                _expand(vals, d.name, self._globals.get(d.name))
            if ps.sfc is not None:
                for sd, st in zip(ps.prog.sfc.steps, ps.sfc.steps):
                    vals[f"{sd.name}.X"] = st.active
                    vals[f"{sd.name}.T"] = st.t
            out[ps.prog.name] = vals
        return out

    def globals(self) -> dict[str, Any]:
        return dict(self._globals)

    def write_globals(self, values: Mapping[str, Any]) -> None:
        """Set VAR_GLOBAL values from outside (operator setpoints, enables)."""
        for name, value in values.items():
            decl = self._global_decls.get(str(name).upper())
            if decl is None:
                raise ValueError(f"unknown global variable {name!r}")
            if decl.fb_type is not None:
                raise ValueError(f"{decl.name!r} is a function block instance")
            v = coerce_value(value, decl.dtype)
            self._globals[decl.name] = v
            if decl.name in self._forced:
                self._globals[decl.name] = self._forced[decl.name][3]

    # ------------------------------------------------------------------ forcing
    def force(self, name: str, value: Any) -> None:
        kind, prog, key, dtype = self._resolve_force(name)
        v = coerce_value(value, dtype)
        self._forced[self._force_key(kind, prog, key)] = (kind, prog, key, v)
        self._apply_forces()

    def unforce(self, name: str) -> None:
        kind, prog, key, dtype = self._resolve_force(name)
        fkey = self._force_key(kind, prog, key)
        if fkey not in self._forced:
            raise ValueError(f"{name!r} is not forced")
        del self._forced[fkey]
        if kind == "input":
            self._inputs[key] = self._written[key]

    def forced(self) -> dict[str, Any]:
        return {k: v[3] for k, v in self._forced.items()}

    @staticmethod
    def _force_key(kind: str, prog: str | None, key: str) -> str:
        return f"{prog}.{key}" if kind == "local" else key

    def _resolve_force(self, name: str):
        text = str(name)
        spec = self._tagmap.get(text.upper())
        if spec is not None:
            return ("input" if spec.direction == "in" else "output"), None, spec.name, spec.dtype
        decl = self._global_decls.get(text.upper())
        if decl is not None:
            if decl.fb_type is not None:
                raise ValueError(f"cannot force function block instance {decl.name!r}")
            return "global", None, decl.name, decl.dtype
        if "." in text:
            pname, _, vname = text.partition(".")
            for ps in self._states:
                if ps.prog.name.upper() == pname.upper():
                    for d in ps.prog.locals:
                        if d.name.upper() == vname.upper():
                            if d.fb_type is not None:
                                raise ValueError(
                                    f"cannot force function block instance {text!r}")
                            return "local", ps.prog.name, d.name, d.dtype
                    raise ValueError(f"program {ps.prog.name!r} has no variable {vname!r}")
        if text.upper() in SYS_VARS:
            raise ValueError(f"system variable {text!r} cannot be forced")
        raise ValueError(f"unknown tag or variable {name!r} "
                         f"(use 'program.variable' for a local variable)")

    def _apply_forces(self) -> None:
        for kind, prog, key, value in self._forced.values():
            if kind == "input":
                self._inputs[key] = value
            elif kind == "output":
                self._outputs[key] = value
            elif kind == "global":
                self._globals[key] = value
            else:
                for ps in self._states:
                    if ps.prog.name == prog:
                        ps.locals[key] = value
                        break


def _expand(out: dict, name: str, value: Any) -> None:
    if isinstance(value, FunctionBlock):
        for f in value.fields:
            out[f"{name}.{f}"] = getattr(value, f)
    else:
        out[name] = value
