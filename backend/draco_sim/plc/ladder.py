from __future__ import annotations

import json
from typing import Any

from .compiler import ERR, VarDecl
from .jsondoc import JsonCompiler, jp
from .nodes import LOCAL
from .types import BOOL, DINT, INT_TYPES, NUMERIC_TYPES, TIME, format_time

LD_VERSION = 1

CONTACT_KINDS = ("NO", "NC", "P", "N")
COIL_KINDS = ("COIL", "SET", "RESET", "NEGATED")
COMPARE_OPS = {"GT": ">", "GE": ">=", "EQ": "=", "NE": "<>", "LE": "<=", "LT": "<"}
MATH_OPS = ("ADD", "SUB", "MUL", "DIV")
TIMER_FBS = ("TON", "TOF", "TP")
COUNTER_FBS = ("CTU", "CTD")


# --------------------------------------------------------------------------- runtime elements

class Series:
    __slots__ = ("children",)

    def __init__(self, children):
        self.children = children

    def run(self, ctx, power):
        for c in self.children:
            power = c.run(ctx, power)
        return power


class Parallel:
    __slots__ = ("branches",)

    def __init__(self, branches):
        self.branches = branches

    def run(self, ctx, power):
        out = False
        for b in self.branches:  # every branch executes: no short-circuit
            if b.run(ctx, power):
                out = True
        return out


class Contact:
    __slots__ = ("kind", "operand", "key")

    def __init__(self, kind, operand, key):
        self.kind = kind
        self.operand = operand
        self.key = key

    def run(self, ctx, power):
        v = bool(self.operand.eval(ctx))
        if self.kind == "NO":
            return power and v
        if self.kind == "NC":
            return power and not v
        prev = ctx.locals[self.key]
        ctx.locals[self.key] = v
        edge = (v and not prev) if self.kind == "P" else (prev and not v)
        return power and edge


class Coil:
    __slots__ = ("kind", "scope", "key")

    def __init__(self, kind, scope, key):
        self.kind = kind
        self.scope = scope
        self.key = key

    def run(self, ctx, power):
        store = ctx.store[self.scope]
        if self.kind == "COIL":
            store[self.key] = power
        elif self.kind == "NEGATED":
            store[self.key] = not power
        elif power:
            store[self.key] = self.kind == "SET"
        return power


class TimerBlock:
    __slots__ = ("key", "pt", "in_expr", "outs")

    def __init__(self, key, pt, in_expr, outs):
        self.key = key
        self.pt = pt
        self.in_expr = in_expr
        self.outs = outs

    def run(self, ctx, power):
        inst = ctx.locals[self.key]
        inst.IN = bool(self.in_expr.eval(ctx)) if self.in_expr is not None else power
        inst.PT = self.pt.eval(ctx)
        inst.execute(ctx.dt)
        for field, scope, key, conv in self.outs:
            v = getattr(inst, field)
            ctx.store[scope][key] = conv(v) if conv is not None else v
        return inst.Q


class CounterBlock:
    __slots__ = ("key", "fb", "pv", "cin", "rst", "outs")

    def __init__(self, key, fb, pv, cin, rst, outs):
        self.key = key
        self.fb = fb
        self.pv = pv
        self.cin = cin
        self.rst = rst
        self.outs = outs

    def run(self, ctx, power):
        inst = ctx.locals[self.key]
        drive = bool(self.cin.eval(ctx)) if self.cin is not None else power
        if self.fb == "CTU":
            inst.CU = drive
            inst.R = bool(self.rst.eval(ctx)) if self.rst is not None else False
        else:
            inst.CD = drive
            inst.LD = bool(self.rst.eval(ctx)) if self.rst is not None else False
        inst.PV = self.pv.eval(ctx)
        inst.execute(ctx.dt)
        for field, scope, key, conv in self.outs:
            v = getattr(inst, field)
            ctx.store[scope][key] = conv(v) if conv is not None else v
        return inst.Q


class Compare:
    __slots__ = ("expr",)

    def __init__(self, expr):
        self.expr = expr

    def run(self, ctx, power):
        return power and bool(self.expr.eval(ctx))


class Move:
    __slots__ = ("src", "scope", "key", "conv")

    def __init__(self, src, scope, key, conv):
        self.src = src
        self.scope = scope
        self.key = key
        self.conv = conv

    def run(self, ctx, power):
        if power:
            v = self.src.eval(ctx)
            ctx.store[self.scope][self.key] = self.conv(v) if self.conv is not None else v
        return power


class Math:
    __slots__ = ("expr", "scope", "key", "conv")

    def __init__(self, expr, scope, key, conv):
        self.expr = expr
        self.scope = scope
        self.key = key
        self.conv = conv

    def run(self, ctx, power):
        if power:
            v = self.expr.eval(ctx)
            ctx.store[self.scope][self.key] = self.conv(v) if self.conv is not None else v
        return power


class LadderBody:
    __slots__ = ("rungs",)

    def __init__(self, rungs):
        self.rungs = rungs

    def execute(self, ctx):
        for root in self.rungs:
            root.run(ctx, True)


# --------------------------------------------------------------------------- compiler

class LadderCompiler(JsonCompiler):
    # -------------------------------------------------------------- network
    def network(self, node: Any, path: str):
        if not isinstance(node, dict):
            self.err("network node must be an object", path)
            return Series([])
        t = str(node.get("type", "")).lower()
        if t == "series":
            items = node.get("elements")
            if not isinstance(items, list):
                self.err("series node needs an 'elements' list", jp(path, "elements"))
                return Series([])
            return Series([self.network(e, jp(path, "elements", i)) for i, e in enumerate(items)])
        if t == "parallel":
            items = node.get("branches")
            if not isinstance(items, list) or not items:
                self.err("parallel node needs a non-empty 'branches' list", jp(path, "branches"))
                return Series([])
            return Parallel([self.network(e, jp(path, "branches", i)) for i, e in enumerate(items)])
        return self.element(node, path, t)

    def element(self, node: dict, path: str, t: str):
        eid = self.note_id(node.get("id"), path)
        key_base = eid if eid else path

        if t == "contact":
            kind = str(node.get("kind", "NO")).upper()
            if kind not in CONTACT_KINDS:
                self.err(f"contact kind must be one of {CONTACT_KINDS}", jp(path, "kind"))
                kind = "NO"
            op = self.operand(node.get("operand"), jp(path, "operand"))
            if op.type not in (BOOL, ERR):
                self.err(f"contact operand must be BOOL, got {op.type}", jp(path, "operand"))
            ekey = ""
            if kind in ("P", "N"):
                ekey = self.hidden(f"#edge:{key_base}", False)
            return Contact(kind, op, ekey)

        if t == "coil":
            kind = str(node.get("kind", "COIL")).upper()
            if kind not in COIL_KINDS:
                self.err(f"coil kind must be one of {COIL_KINDS}", jp(path, "kind"))
                kind = "COIL"
            tgt = self.target(node.get("operand"), jp(path, "operand"), want=BOOL)
            if tgt is None:
                return Series([])
            return Coil(kind, tgt[0], tgt[1])

        if t == "timer":
            fb = str(node.get("fb", "")).upper()
            if fb not in TIMER_FBS:
                self.err(f"timer 'fb' must be one of {TIMER_FBS}", jp(path, "fb"))
                return Series([])
            key = self.fb_instance(node, path, fb, key_base)
            pt = self.operand(node.get("pt", 0.0), jp(path, "pt"))
            if pt.type not in (TIME, ERR) and pt.type not in NUMERIC_TYPES:
                self.err(f"timer 'pt' must be TIME, got {pt.type}", jp(path, "pt"))
            in_expr = None
            if node.get("in") is not None:
                in_expr = self.operand(node["in"], jp(path, "in"))
            outs = self.block_outs(node, path, {"q": ("Q", BOOL), "et": ("ET", TIME)})
            return TimerBlock(key, pt, in_expr, outs)

        if t == "counter":
            fb = str(node.get("fb", "")).upper()
            if fb not in COUNTER_FBS:
                self.err(f"counter 'fb' must be one of {COUNTER_FBS}", jp(path, "fb"))
                return Series([])
            key = self.fb_instance(node, path, fb, key_base)
            pv = self.operand(node.get("pv", 0), jp(path, "pv"))
            if pv.type not in INT_TYPES and pv.type != ERR:
                self.err(f"counter 'pv' must be INT/DINT, got {pv.type}", jp(path, "pv"))
            drive_field = "cu" if fb == "CTU" else "cd"
            cin = self.operand(node[drive_field], jp(path, drive_field)) \
                if node.get(drive_field) is not None else None
            rst_field = "reset" if fb == "CTU" else "load"
            rst = self.operand(node[rst_field], jp(path, rst_field)) \
                if node.get(rst_field) is not None else None
            outs = self.block_outs(node, path, {"q": ("Q", BOOL), "cv": ("CV", DINT)})
            return CounterBlock(key, fb, pv, cin, rst, outs)

        if t == "compare":
            op = str(node.get("op", "")).upper()
            if op not in COMPARE_OPS:
                self.err(f"compare 'op' must be one of {tuple(COMPARE_OPS)}", jp(path, "op"))
                return Series([])
            a = self.operand(node.get("a"), jp(path, "a"))
            b = self.operand(node.get("b"), jp(path, "b"))
            if a.type == ERR or b.type == ERR:
                return Series([])
            expr = self.st.binary_nodes(a, b, COMPARE_OPS[op], path)
            if expr is None:
                return Series([])
            return Compare(expr)

        if t == "move":
            src = self.operand(node.get("src"), jp(path, "src"))
            tgt = self.target(node.get("dst"), jp(path, "dst"))
            if tgt is None or src.type == ERR:
                return Series([])
            conv = self.conv_for(src.type, tgt[2], jp(path, "dst"), f"{tgt[1]!r}")
            return Move(src, tgt[0], tgt[1], conv)

        if t == "math":
            op = str(node.get("op", "")).upper()
            if op not in MATH_OPS:
                self.err(f"math 'op' must be one of {MATH_OPS}", jp(path, "op"))
                return Series([])
            a = self.operand(node.get("a"), jp(path, "a"))
            b = self.operand(node.get("b"), jp(path, "b"))
            tgt = self.target(node.get("dst"), jp(path, "dst"))
            if tgt is None or a.type == ERR or b.type == ERR:
                return Series([])
            sym = {"ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/"}[op]
            expr = self.st.binary_nodes(a, b, sym, path)
            if expr is None:
                return Series([])
            conv = self.conv_for(expr.type, tgt[2], jp(path, "dst"), f"{tgt[1]!r}")
            return Math(expr, tgt[0], tgt[1], conv)

        self.err(f"unknown element type {node.get('type')!r}", jp(path, "type"))
        return Series([])

    def fb_instance(self, node: dict, path: str, fb: str, key_base: str) -> str:
        name = node.get("instance")
        if name is None:
            name = f"#{fb}:{key_base}"
            self.st.locals.append(VarDecl(name, LOCAL, None, fb, None))
            return name
        if not isinstance(name, str):
            self.err("'instance' must be a string", jp(path, "instance"))
            name = f"#{fb}:{key_base}"
            self.st.locals.append(VarDecl(name, LOCAL, None, fb, None))
            return name
        sym = self.st.symbols.get(name.upper())
        if sym is None:
            self.declare(name, fb, None, "VAR", jp(path, "instance"))
            return name
        if sym.fb_type != fb:
            self.err(f"instance {name!r} is already declared as "
                     f"{sym.fb_type or sym.dtype}, not {fb}", jp(path, "instance"))
            return name
        if sym.scope != LOCAL:
            self.err(f"instance {name!r} must be a local VAR", jp(path, "instance"))
        return sym.name

    def block_outs(self, node: dict, path: str, mapping: dict[str, tuple[str, str]]):
        outs = []
        for field, (attr, dtype) in mapping.items():
            if node.get(field) is None:
                continue
            tgt = self.target(node[field], jp(path, field))
            if tgt is None:
                continue
            conv = self.conv_for(dtype, tgt[2], jp(path, field), f"{tgt[1]!r}")
            outs.append((attr, tgt[0], tgt[1], conv))
        return outs

    # -------------------------------------------------------------- top level
    def compile(self) -> LadderBody:
        self.check_header("LD", LD_VERSION)
        self.declare_vars()
        rungs_json = self.doc.get("rungs")
        rungs = []
        if not isinstance(rungs_json, list):
            self.err("document needs a 'rungs' list", jp("rungs"))
            return LadderBody([])
        for i, r in enumerate(rungs_json):
            path = jp("rungs", i)
            if not isinstance(r, dict):
                self.err("rung must be an object", path)
                continue
            self.note_id(r.get("id"), path)
            if "logic" not in r:
                self.err("rung needs a 'logic' network", jp(path, "logic"))
                continue
            rungs.append(self.network(r["logic"], jp(path, "logic")))
        return LadderBody(rungs)


# --------------------------------------------------------------------------- ASCII rendering

def _fmt_operand(raw: Any, as_time: bool = False) -> str:
    if as_time and isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return format_time(float(raw))
    if isinstance(raw, dict):
        for k in ("var", "const", "time"):
            if k in raw:
                return _fmt_operand(raw[k])
        return "?"
    if isinstance(raw, bool):
        return "TRUE" if raw else "FALSE"
    if isinstance(raw, float):
        return f"{raw:g}"
    if raw is None:
        return "?"
    return str(raw)


def _cell(label: str, symbol: str) -> tuple[list[str], int]:
    w = max(len(label), len(symbol)) + 4
    return [label.center(w), symbol.center(w, "-")], 1


def _leaf_lines(node: dict) -> tuple[list[str], int]:
    t = str(node.get("type", "")).lower()
    if t == "contact":
        kind = str(node.get("kind", "NO")).upper()
        sym = {"NO": "] [", "NC": "]/[", "P": "]P[", "N": "]N["}.get(kind, "] [")
        return _cell(_fmt_operand(node.get("operand")), sym)
    if t == "coil":
        kind = str(node.get("kind", "COIL")).upper()
        sym = {"COIL": "( )", "SET": "(S)", "RESET": "(R)", "NEGATED": "(/)"}.get(kind, "( )")
        return _cell(_fmt_operand(node.get("operand")), sym)
    if t == "timer":
        fb = str(node.get("fb", "TON")).upper()
        label = f"{node.get('instance', fb)} PT={_fmt_operand(node.get('pt'), True)}"
        return _cell(label, f"[{fb}]")
    if t == "counter":
        fb = str(node.get("fb", "CTU")).upper()
        label = f"{node.get('instance', fb)} PV={_fmt_operand(node.get('pv'))}"
        return _cell(label, f"[{fb}]")
    if t == "compare":
        op = str(node.get("op", "EQ")).upper()
        label = f"{_fmt_operand(node.get('a'))} {COMPARE_OPS.get(op, op)} {_fmt_operand(node.get('b'))}"
        return _cell(label, f"[{op}]")
    if t == "move":
        label = f"{_fmt_operand(node.get('src'))} => {_fmt_operand(node.get('dst'))}"
        return _cell(label, "[MOVE]")
    if t == "math":
        op = str(node.get("op", "ADD")).upper()
        sym = {"ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/"}.get(op, op)
        label = (f"{_fmt_operand(node.get('a'))} {sym} {_fmt_operand(node.get('b'))}"
                 f" => {_fmt_operand(node.get('dst'))}")
        return _cell(label, f"[{op}]")
    return _cell(str(node.get("type", "?")), "[??]")


def _node_lines(node: Any) -> tuple[list[str], int]:
    if not isinstance(node, dict):
        return _cell("?", "[??]")
    t = str(node.get("type", "")).lower()
    if t == "series":
        parts = [_node_lines(e) for e in node.get("elements", [])]
        if not parts:
            return _cell("", "---")
        top = max(p[1] for p in parts)
        bottom = max(len(p[0]) - p[1] - 1 for p in parts)
        cols = []
        for lines, prow in parts:
            w = len(lines[0])
            pad_top = [" " * w] * (top - prow)
            pad_bot = [" " * w] * (bottom - (len(lines) - prow - 1))
            cols.append(pad_top + lines + pad_bot)
        height = top + bottom + 1
        out = ["".join(col[r] for col in cols) for r in range(height)]
        return out, top
    if t == "parallel":
        parts = [_node_lines(b) for b in node.get("branches", [])]
        if not parts:
            return _cell("", "---")
        w = max(len(p[0][0]) for p in parts)
        grid: list[str] = []
        prows: list[int] = []
        for lines, prow in parts:
            prows.append(len(grid) + prow)
            for i, ln in enumerate(lines):
                grid.append(ln.ljust(w, "-") if i == prow else ln.ljust(w))
        first, last = prows[0], prows[-1]
        out = []
        for i, ln in enumerate(grid):
            if i in prows:
                edge = "+"
            elif first < i < last:
                edge = "|"
            else:
                edge = " "
            out.append(edge + ln + edge)
        return out, first
    return _leaf_lines(node)


def ladder_to_text(doc: dict | str) -> str:
    """Plain-ASCII rendering of a ladder document (debugging / documentation aid)."""
    if isinstance(doc, str):
        doc = json.loads(doc)
    out: list[str] = []
    name = doc.get("name", "(unnamed)")
    out.append(f"LD {name}")
    if doc.get("description"):
        out.append(f"   {doc['description']}")
    for i, rung in enumerate(doc.get("rungs", [])):
        out.append("")
        head = f"Rung {i}"
        if rung.get("id"):
            head += f" [{rung['id']}]"
        if rung.get("comment"):
            head += f"  {rung['comment']}"
        out.append(head)
        lines, prow = _node_lines(rung.get("logic"))
        for j, ln in enumerate(lines):
            left = "|--" if j == prow else "   "
            right = "--|" if j == prow else "   "
            out.append("  " + left + ln + right)
    return "\n".join(out)
