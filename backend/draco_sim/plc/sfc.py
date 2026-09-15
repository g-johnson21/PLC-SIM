from __future__ import annotations

from typing import Any

from . import nodes as N
from .compiler import ERR
from .errors import CompileError
from .jsondoc import JsonCompiler, jp
from .lexer import parse_time_literal
from .parser import parse_expression_text, parse_statements_text
from .types import BOOL, TIME, accumulate

SFC_VERSION = 1
QUALIFIERS = ("N", "S", "R", "P", "P0", "D")


class StepState:
    __slots__ = ("active", "t", "_raw", "_comp", "activated_scan", "fresh")

    def __init__(self) -> None:
        self.active = False
        self.t = 0.0
        self._raw = 0.0
        self._comp = 0.0
        self.activated_scan = -1
        self.fresh = False

    def reset(self) -> None:
        self.active = False
        self.t = 0.0
        self._raw = 0.0
        self._comp = 0.0
        self.activated_scan = -1
        self.fresh = False

    def activate(self, scan: int) -> None:
        self.active = True
        self.t = 0.0
        self._raw = 0.0
        self._comp = 0.0
        self.activated_scan = scan
        self.fresh = True

    def advance(self, dt: float) -> None:
        self._raw, self._comp = accumulate(self._raw, self._comp, dt)
        self.t = self._raw + self._comp

    def snapshot(self) -> tuple:
        return (self.active, self.t, self._raw, self._comp, self.activated_scan, self.fresh)

    def restore(self, s: tuple) -> None:
        (self.active, self.t, self._raw, self._comp, self.activated_scan, self.fresh) = s


class SfcState:
    __slots__ = ("steps", "running", "aborted", "stored", "pending_entered")

    def __init__(self, n: int) -> None:
        self.steps = [StepState() for _ in range(n)]
        self.running = False
        self.aborted = False
        self.stored: list[str] = []
        self.pending_entered: list[int] = []

    def snapshot(self) -> tuple:
        return ([s.snapshot() for s in self.steps], self.running, self.aborted,
                list(self.stored), list(self.pending_entered))

    def restore(self, snap: tuple) -> None:
        states, self.running, self.aborted, stored, pending = snap
        for s, v in zip(self.steps, states):
            s.restore(v)
        self.stored = list(stored)
        self.pending_entered = list(pending)


class Action:
    __slots__ = ("qualifier", "name", "body", "delay")

    def __init__(self, qualifier, name, body, delay=0.0):
        self.qualifier = qualifier
        self.name = name
        self.body = body
        self.delay = delay


class Step:
    __slots__ = ("name", "index", "id", "comment", "actions", "entry", "exit", "cont")

    def __init__(self, name, index, id_, comment, actions):
        self.name = name
        self.index = index
        self.id = id_
        self.comment = comment
        self.actions = actions
        self.entry = [a for a in actions if a.qualifier in ("S", "R", "P")]
        self.exit = [a for a in actions if a.qualifier == "P0"]
        self.cont = [a for a in actions if a.qualifier in ("N", "D")]


class Transition:
    __slots__ = ("id", "froms", "tos", "cond", "comment", "in_abort")

    def __init__(self, id_, froms, tos, cond, comment):
        self.id = id_
        self.froms = froms
        self.tos = tos
        self.cond = cond
        self.comment = comment
        self.in_abort = False


class SfcBody:
    """Executable SFC. State lives in ctx.sfc / ctx.steps so it can be snapshotted."""

    __slots__ = ("steps", "transitions", "initial", "abort_step", "abort_set", "autostart", "name")

    def __init__(self, name, steps, transitions, initial, abort_step, abort_set, autostart):
        self.name = name
        self.steps = steps
        self.transitions = transitions
        self.initial = initial
        self.abort_step = abort_step
        self.abort_set = abort_set
        self.autostart = autostart

    # -------------------------------------------------------------- control
    def start(self, state: SfcState) -> None:
        for s in state.steps:
            s.reset()
        state.stored.clear()
        state.pending_entered.clear()
        state.aborted = False
        state.running = True
        st = state.steps[self.initial]
        st.activate(-1)  # may fire an outgoing transition on the very first scan
        state.pending_entered.append(self.initial)

    def stop(self, state: SfcState) -> None:
        for s in state.steps:
            s.reset()
        state.running = False
        state.stored.clear()
        state.pending_entered.clear()

    def apply_abort(self, state: SfcState, scan: int) -> None:
        for s in state.steps:
            s.reset()
        state.stored.clear()
        state.pending_entered.clear()
        state.aborted = True
        if self.abort_step is None:
            state.running = False
            return
        state.running = True
        state.steps[self.abort_step].activate(scan)
        state.pending_entered.append(self.abort_step)

    # -------------------------------------------------------------- scan
    def execute(self, ctx) -> None:
        state: SfcState = ctx.sfc
        if not state.running:
            return
        steps = state.steps
        scan = ctx.scan
        dt = ctx.dt

        for s in steps:
            if s.active and not s.fresh:
                s.advance(dt)

        pending = list(state.pending_entered)
        state.pending_entered.clear()

        fireable: list[Transition] = []
        consumed: set[int] = set()
        aborted = state.aborted
        for tr in self.transitions:
            if aborted and not tr.in_abort:
                continue
            ready = True
            for i in tr.froms:
                s = steps[i]
                if not s.active or i in consumed or s.activated_scan == scan:
                    ready = False
                    break
            if not ready:
                continue
            if tr.cond.eval(ctx):
                fireable.append(tr)
                consumed.update(tr.froms)

        exited: list[int] = []
        entered: list[int] = []
        for tr in fireable:
            for i in tr.froms:
                if steps[i].active:
                    steps[i].active = False
                    exited.append(i)
        for tr in fireable:
            for i in tr.tos:
                if not steps[i].active:
                    steps[i].activate(scan)
                    entered.append(i)

        for i in pending:
            self._entry(ctx, steps[i], self.steps[i], state)
        for i in exited:
            for a in self.steps[i].exit:
                self._run(ctx, a.body)
        for i in entered:
            self._entry(ctx, steps[i], self.steps[i], state)
        for sd in self.steps:
            if steps[sd.index].active and sd.cont:
                t = steps[sd.index].t
                for a in sd.cont:
                    if a.qualifier == "N" or t >= a.delay:
                        self._run(ctx, a.body)

    def _entry(self, ctx, sstate: StepState, sdef: Step, state: SfcState) -> None:
        sstate.fresh = False
        for a in sdef.entry:
            if a.qualifier == "S":
                if a.name and a.name not in state.stored:
                    state.stored.append(a.name)
            elif a.qualifier == "R" and a.name and a.name in state.stored:
                state.stored.remove(a.name)
            self._run(ctx, a.body)

    @staticmethod
    def _run(ctx, body) -> None:
        for s in body:
            s.exec(ctx)


# --------------------------------------------------------------------------- compiler

class SfcCompiler(JsonCompiler):
    def __init__(self, doc: dict, tags, errors: list[CompileError], program: str | None):
        self.step_index: dict[str, int] = {}
        self.step_names: list[str] = []
        super().__init__(doc, tags, errors, program)

    def resolve_member(self, base: str, field: str, p) -> N.Expr | None:
        idx = self.step_index.get(base.upper())
        if idx is None:
            return None
        f = field.upper()
        if f == "X":
            return N.StepRef(idx, "X", BOOL, f"{self.step_names[idx]}.X", p.line, p.col)
        if f == "T":
            return N.StepRef(idx, "T", TIME, f"{self.step_names[idx]}.T", p.line, p.col)
        self.st.err(f"step {self.step_names[idx]!r} has no field {field!r} (use .X or .T)", p)
        return N.Lit(None, ERR)

    # -------------------------------------------------------------- ST fragments
    def compile_body(self, text: Any, path: str) -> list:
        if text is None:
            return []
        if not isinstance(text, str):
            self.err("action 'body' must be a string of Structured Text", path)
            return []
        stmts, errs = parse_statements_text(text)
        if errs:
            self._stamp(errs, path)
            return []
        before = len(self.errors)
        saved, self.st.path = self.st.path, path
        out = self.st.body(stmts)
        self.st.path = saved
        return [] if len(self.errors) > before else out

    def compile_condition(self, text: Any, path: str) -> N.Expr:
        if not isinstance(text, str) or not text.strip():
            self.err("transition needs a 'condition' (a boolean ST expression)", path)
            return N.Lit(False, BOOL)
        expr, errs = parse_expression_text(text)
        if errs or expr is None:
            self._stamp(errs, path)
            return N.Lit(False, BOOL)
        saved, self.st.path = self.st.path, path
        node = self.st.expr(expr)
        self.st.path = saved
        if node.type not in (BOOL, ERR):
            self.err(f"transition condition must be BOOL, got {node.type}", path)
            return N.Lit(False, BOOL)
        return node

    def _stamp(self, errs: list[CompileError], path: str) -> None:
        for e in errs:
            e.path = path
            e.program = self.program
            self.errors.append(e)

    # -------------------------------------------------------------- top level
    def compile(self) -> SfcBody:
        doc = self.doc
        self.abort_writes: frozenset[str] = frozenset()
        self.check_header("SFC", SFC_VERSION)
        self.declare_vars()

        steps_json = doc.get("steps")
        if not isinstance(steps_json, list) or not steps_json:
            self.err("document needs a non-empty 'steps' list", jp("steps"))
            return SfcBody(self.program, [], [], 0, None, frozenset(), False)

        initial = None
        for i, s in enumerate(steps_json):
            path = jp("steps", i)
            if not isinstance(s, dict):
                self.err("step must be an object", path)
                self.step_names.append(f"#bad{i}")
                continue
            name = s.get("name")
            if not isinstance(name, str) or not name or not (name[0].isalpha() or name[0] == "_") \
                    or not all(c.isalnum() or c == "_" for c in name):
                self.err("step 'name' must be a valid identifier", jp(path, "name"))
                name = f"#bad{i}"
            if name.upper() in self.step_index:
                self.err(f"duplicate step name {name!r}", jp(path, "name"))
            if name.upper() in self.st.symbols or name.upper() in self.st.tags:
                self.err(f"step name {name!r} collides with a variable or tag name",
                         jp(path, "name"))
            self.step_index[name.upper()] = i
            self.step_names.append(name)
            self.note_id(s.get("id"), path)
            if s.get("initial"):
                if initial is not None:
                    self.err(f"more than one initial step ({self.step_names[initial]} and {name})",
                             jp(path, "initial"))
                else:
                    initial = i
        if initial is None:
            self.err('exactly one step must have "initial": true', jp("steps"))
            initial = 0

        steps: list[Step] = []
        # each step's actions compile against a fresh write set, so the output tags
        # written by any subset of steps (the abort chain) can be recovered later
        step_writes: list[set[str]] = []
        for i, s in enumerate(steps_json):
            path = jp("steps", i)
            actions = []
            chart_writes, self.st.output_writes = self.st.output_writes, set()
            if isinstance(s, dict):
                acts = s.get("actions", [])
                if not isinstance(acts, list):
                    self.err("'actions' must be a list", jp(path, "actions"))
                    acts = []
                for k, a in enumerate(acts):
                    apath = jp(path, "actions", k)
                    act = self.action(a, apath)
                    if act is not None:
                        actions.append(act)
            step_writes.append(self.st.output_writes)
            chart_writes |= self.st.output_writes
            self.st.output_writes = chart_writes
            steps.append(Step(self.step_names[i], i,
                              s.get("id") if isinstance(s, dict) else None,
                              s.get("comment") if isinstance(s, dict) else None, actions))

        transitions: list[Transition] = []
        trs = doc.get("transitions")
        if not isinstance(trs, list):
            self.err("document needs a 'transitions' list", jp("transitions"))
            trs = []
        for i, t in enumerate(trs):
            path = jp("transitions", i)
            if not isinstance(t, dict):
                self.err("transition must be an object", path)
                continue
            self.note_id(t.get("id"), path)
            froms = self.step_list(t.get("from"), jp(path, "from"))
            tos = self.step_list(t.get("to"), jp(path, "to"))
            cond = self.compile_condition(t.get("condition"), jp(path, "condition"))
            if froms is None or tos is None:
                continue
            transitions.append(Transition(t.get("id"), froms, tos, cond, t.get("comment")))

        abort_step = None
        abort_name = doc.get("abort_step")
        if abort_name is not None:
            if not isinstance(abort_name, str) or abort_name.upper() not in self.step_index:
                self.err(f"abort_step {abort_name!r} is not a declared step", jp("abort_step"))
            else:
                abort_step = self.step_index[abort_name.upper()]

        abort_set: set[int] = set()
        if abort_step is not None:
            frontier = [abort_step]
            while frontier:
                cur = frontier.pop()
                if cur in abort_set:
                    continue
                abort_set.add(cur)
                for tr in transitions:
                    if cur in tr.froms:
                        frontier.extend(tr.tos)
        for tr in transitions:
            tr.in_abort = bool(tr.froms) and all(i in abort_set for i in tr.froms)
        if abort_step is not None and initial in abort_set:
            self.err("the initial step is part of the abort chain", jp("abort_step"))
        self.abort_writes = frozenset(t for i in abort_set for t in step_writes[i])

        autostart = bool(doc.get("autostart", False))
        return SfcBody(self.program, steps, transitions, initial, abort_step,
                       frozenset(abort_set), autostart)

    def step_list(self, raw: Any, path: str) -> list[int] | None:
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list) or not raw:
            self.err("expected a step name or a non-empty list of step names", path)
            return None
        out: list[int] = []
        for i, nm in enumerate(raw):
            if not isinstance(nm, str) or nm.upper() not in self.step_index:
                self.err(f"unknown step {nm!r}", jp(path, i) if len(raw) > 1 else path)
                return None
            idx = self.step_index[nm.upper()]
            if idx in out:
                self.err(f"step {nm!r} listed twice", path)
                return None
            out.append(idx)
        return out

    def action(self, a: Any, path: str) -> Action | None:
        if not isinstance(a, dict):
            self.err("action must be an object", path)
            return None
        self.note_id(a.get("id"), path)
        q = str(a.get("qualifier", "N")).upper()
        if q not in QUALIFIERS:
            self.err(f"action qualifier must be one of {QUALIFIERS}", jp(path, "qualifier"))
            return None
        delay = 0.0
        if q == "D":
            raw = a.get("delay")
            if raw is None:
                self.err("a D action needs a 'delay'", jp(path, "delay"))
                return None
            try:
                delay = parse_time_literal(raw) if isinstance(raw, str) else float(raw)
            except (ValueError, TypeError):
                self.err(f"invalid 'delay' {raw!r}", jp(path, "delay"))
                return None
        name = a.get("name")
        if name is not None and not isinstance(name, str):
            self.err("action 'name' must be a string", jp(path, "name"))
            name = None
        body = self.compile_body(a.get("body"), jp(path, "body"))
        return Action(q, name, body, delay)
