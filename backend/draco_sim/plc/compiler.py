from __future__ import annotations

import math
import operator
from dataclasses import dataclass
from typing import Any, Callable

from . import nodes as N
from .errors import CompileError
from .fb import FB_TYPES
from .funcs import resolve_function
from .nodes import GLOBAL, INPUT, LOCAL, OUTPUT, SYS
from .parser import (PAssign, PBin, PCall, PCase, PExit, PFbCall, PFor, PIf, PLit, PMember,
                     PName, PRepeat, PReturn, PUnary, PVarDecl, PWhile)
from .types import (BOOL, DINT, INT, INT_TYPES, NUMERIC_TYPES, REAL, STRING, TIME, TagSpec,
                    assignable, coerce_value, default_value, promote)

LOOP_LIMIT = 10000
ERR = "?"

SYS_VARS = {
    "SYS_ABORT": BOOL,
    "SYS_SCAN_TIME": REAL,
    "SYS_FIRST_SCAN": BOOL,
    "SYS_TIME": REAL,
}

_TYPE_ALIASES = {"LREAL": REAL, "TIME": TIME, "BOOL": BOOL, "INT": INT, "DINT": DINT,
                 "REAL": REAL, "STRING": STRING}


@dataclass
class Sym:
    name: str          # canonical spelling, also the dict key in the runtime store
    scope: int
    dtype: str | None  # None for function block instances
    fb_type: str | None = None
    constant: bool = False


@dataclass
class VarDecl:
    name: str
    scope: int
    dtype: str | None
    fb_type: str | None
    init: Any
    constant: bool = False

    def make(self) -> Any:
        if self.fb_type is not None:
            return FB_TYPES[self.fb_type]()
        return self.init if self.init is not None else default_value(self.dtype)


def _pow(a, b):
    return math.pow(a, b)


class _PreBin:
    """Binary operator over operands that are already compiled nodes."""

    __slots__ = ("op", "l", "r", "line", "col")

    def __init__(self, op, l, r):
        self.op = op
        self.l = l
        self.r = r
        self.line = getattr(l, "line", None)
        self.col = getattr(l, "col", None)


class StCompiler:
    """Resolves names, checks types and emits executable nodes."""

    def __init__(self, tags: dict[str, TagSpec], errors: list[CompileError],
                 program: str | None = None, path: str | None = None,
                 member_resolver: Callable[[str, str, Any], Any] | None = None):
        self.tags = tags  # upper name -> TagSpec
        self.errors = errors
        self.program = program
        self.path = path
        self.member_resolver = member_resolver
        self.symbols: dict[str, Sym] = {}
        self.locals: list[VarDecl] = []
        self.globals: list[VarDecl] = []
        self.loop_depth = 0
        # output tags this program can write, collected as destinations resolve
        self.output_writes: set[str] = set()

    # ------------------------------------------------------------------ diagnostics
    def err(self, msg: str, node=None, path: str | None = None) -> None:
        line = getattr(node, "line", None) if node is not None else None
        col = getattr(node, "col", None) if node is not None else None
        self.errors.append(CompileError(msg, line, col, path=path or self.path,
                                        program=self.program))

    def bad(self, msg: str, node=None) -> N.Expr:
        self.err(msg, node)
        return N.Lit(None, ERR, getattr(node, "line", 0), getattr(node, "col", 0))

    # ------------------------------------------------------------------ declarations
    def resolve_type(self, tname: str, node) -> tuple[str | None, str | None]:
        up = tname.upper()
        if up in _TYPE_ALIASES:
            return _TYPE_ALIASES[up], None
        if up in FB_TYPES:
            return None, up
        self.err(f"unknown data type {tname!r}", node)
        return ERR, None

    def declare(self, decls: list[PVarDecl]) -> None:
        for d in decls:
            self.declare_one(d.name, d.type_name, d.init, d.scope, d.constant, d)

    def declare_one(self, name: str, type_name: str, init, scope_name: str,
                    constant: bool, node) -> None:
        key = name.upper()
        if key in self.symbols:
            self.err(f"duplicate declaration of {name!r}", node)
            return
        if key in self.tags:
            self.err(f"{name!r} is already a tag name and cannot be declared as a variable", node)
            return
        if key in SYS_VARS:
            self.err(f"{name!r} is a system variable and cannot be declared", node)
            return
        dtype, fb_type = self.resolve_type(type_name, node)
        scope = GLOBAL if scope_name == "VAR_GLOBAL" else LOCAL
        value = None
        if init is not None:
            if fb_type is not None:
                self.err(f"function block instance {name!r} cannot have an initial value", node)
            else:
                value = self.const_value(init, dtype, node)
        if constant and value is None and fb_type is None:
            self.err(f"CONSTANT {name!r} needs an initial value", node)
        decl = VarDecl(name, scope, dtype, fb_type, value, constant)
        (self.globals if scope == GLOBAL else self.locals).append(decl)
        self.symbols[key] = Sym(name, scope, dtype, fb_type, constant)

    def const_value(self, p, dtype: str | None, node) -> Any:
        """Initialisers must be literal constants (optionally signed)."""
        sign = 1
        while isinstance(p, PUnary) and p.op in ("-", "+"):
            if p.op == "-":
                sign = -sign
            p = p.x
        if not isinstance(p, PLit):
            self.err("initial value must be a literal constant", p)
            return None
        v = p.value
        if isinstance(v, bool):
            if sign < 0:
                self.err("cannot negate a BOOL literal", p)
            src = BOOL
        elif isinstance(v, str):
            src = STRING
        else:
            v = sign * v
            src = p.type
        if dtype not in (None, ERR) and not assignable(src, dtype):
            self.err(f"initial value of type {src} is not assignable to {dtype}", p)
            return None
        try:
            return coerce_value(v, dtype)
        except (ValueError, TypeError):
            self.err(f"invalid initial value for type {dtype}", p)
            return None

    # ------------------------------------------------------------------ name lookup
    def lookup(self, name: str) -> Sym | None:
        key = name.upper()
        sym = self.symbols.get(key)
        if sym is not None:
            return sym
        tag = self.tags.get(key)
        if tag is not None:
            return Sym(tag.name, INPUT if tag.direction == "in" else OUTPUT, tag.dtype)
        if key in SYS_VARS:
            return Sym(key, SYS, SYS_VARS[key])
        return None

    def ref(self, p: PName) -> N.Expr:
        sym = self.lookup(p.name)
        if sym is None:
            return self.bad(f"unknown identifier {p.name!r}", p)
        if sym.dtype is None:
            return self.bad(f"{p.name!r} is a {sym.fb_type} instance; "
                            f"read one of its fields (e.g. {p.name}.Q)", p)
        return N.VarRef(sym.scope, sym.name, sym.dtype, sym.name, p.line, p.col)

    # ------------------------------------------------------------------ expressions
    def expr(self, p) -> N.Expr:
        if isinstance(p, PLit):
            return N.Lit(p.value, p.type, p.line, p.col)
        if isinstance(p, PName):
            return self.ref(p)
        if isinstance(p, PMember):
            return self.member(p)
        if isinstance(p, PUnary):
            return self.unary(p)
        if isinstance(p, PBin):
            return self.binary(p)
        if isinstance(p, PCall):
            return self.call(p)
        return self.bad("unsupported expression", p)

    def member(self, p: PMember) -> N.Expr:
        if not isinstance(p.base, PName):
            return self.bad("nested field access is not supported", p)
        base = p.base.name
        sym = self.symbols.get(base.upper())
        if sym is not None and sym.fb_type is not None:
            cls = FB_TYPES[sym.fb_type]
            ftype = cls.FIELD_TYPES.get(p.field.upper())
            if ftype is None:
                return self.bad(
                    f"{sym.fb_type} has no field {p.field!r} "
                    f"(fields: {', '.join(cls.INPUTS + cls.OUTPUTS)})", p)
            return N.FieldRef(sym.scope, sym.name, p.field.upper(), ftype,
                              f"{sym.name}.{p.field.upper()}", p.line, p.col)
        if self.member_resolver is not None:
            node = self.member_resolver(base, p.field, p)
            if node is not None:
                return node
        if sym is not None or self.lookup(base) is not None:
            return self.bad(f"{base!r} is not a function block instance, so {base}.{p.field} "
                            f"cannot be read", p)
        return self.bad(f"unknown identifier {base!r}", p)

    def unary(self, p: PUnary) -> N.Expr:
        x = self.expr(p.x)
        if x.type == ERR:
            return x
        if p.op == "NOT":
            if x.type != BOOL:
                return self.bad(f"NOT expects BOOL, got {x.type}", p)
            return N.Unary("NOT", x, BOOL, operator.not_, p.line, p.col)
        if x.type not in NUMERIC_TYPES and x.type != TIME:
            return self.bad(f"unary {p.op} expects a numeric or TIME operand, got {x.type}", p)
        if p.op == "+":
            return x
        return N.Unary("-", x, x.type, operator.neg, p.line, p.col)

    def binary(self, p: PBin) -> N.Expr:
        return self.binop(p.op, self.expr(p.l), self.expr(p.r), p)

    def binop(self, op: str, l: N.Expr, r: N.Expr, p) -> N.Expr:
        if op in ("AND", "OR", "XOR"):
            for side in (l, r):
                if side.type not in (BOOL, ERR):
                    return self.bad(f"{op} expects BOOL operands, got {side.type} "
                                    f"(this engine has no bitwise operators)", p)
            if op == "AND":
                return N.AndExpr(l, r, p.line, p.col)
            if op == "OR":
                return N.OrExpr(l, r, p.line, p.col)
            return N.XorExpr(l, r, p.line, p.col)

        if l.type == ERR or r.type == ERR:
            return N.Lit(None, ERR, p.line, p.col)
        lt, rt = l.type, r.type

        if op in ("=", "<>", "<", ">", "<=", ">="):
            ok = False
            if lt in NUMERIC_TYPES and rt in NUMERIC_TYPES:
                ok = True
            elif lt == rt and lt in (TIME, STRING):
                ok = True
            elif lt == rt == BOOL and op in ("=", "<>"):
                ok = True
            if not ok:
                return self.bad(f"cannot compare {lt} with {rt} using {op}", p)
            fn = {"=": operator.eq, "<>": operator.ne, "<": operator.lt,
                  ">": operator.gt, "<=": operator.le, ">=": operator.ge}[op]
            return N.Binary(op, l, r, BOOL, fn, p.line, p.col)

        if op == "**":
            if lt not in NUMERIC_TYPES or rt not in NUMERIC_TYPES:
                return self.bad(f"** expects numeric operands, got {lt} and {rt}", p)
            return N.Binary("**", l, r, REAL, _pow, p.line, p.col)

        if op == "MOD":
            if lt not in INT_TYPES or rt not in INT_TYPES:
                return self.bad(f"MOD expects INT/DINT operands, got {lt} and {rt}", p)
            return N.Binary("MOD", l, r, DINT, N.imod, p.line, p.col)

        # + - * /
        rtype = None
        if lt == TIME and rt == TIME:
            rtype = TIME if op in ("+", "-") else (REAL if op == "/" else None)
        elif lt == TIME and rt in NUMERIC_TYPES and op in ("*", "/"):
            rtype = TIME
        elif rt == TIME and lt in NUMERIC_TYPES and op == "*":
            rtype = TIME
        elif lt in NUMERIC_TYPES and rt in NUMERIC_TYPES:
            rtype = promote(lt, rt)
        if rtype is None:
            return self.bad(f"cannot apply {op} to {lt} and {rt}", p)
        if rtype in INT_TYPES:
            fn = {"+": N.wrap_add, "-": N.wrap_sub, "*": N.wrap_mul, "/": N.idiv}[op]
        else:
            fn = {"+": operator.add, "-": operator.sub, "*": operator.mul, "/": N.real_div}[op]
        return N.Binary(op, l, r, rtype, fn, p.line, p.col)

    def binary_nodes(self, a: N.Expr, b: N.Expr, op: str, path: str | None = None) -> N.Expr | None:
        """Type-check and build a Binary from already-compiled operands (used by LD/SFC)."""
        before = len(self.errors)
        saved, self.path = self.path, path or self.path
        node = self.binop(op, a, b, _PreBin(op, a, b))
        self.path = saved
        if len(self.errors) > before or node.type == ERR:
            return None
        return node

    def call(self, p: PCall) -> N.Expr:
        args = [self.expr(a) for a in p.args]
        if any(a.type == ERR for a in args):
            return N.Lit(None, ERR, p.line, p.col)
        if p.name.upper() in FB_TYPES or (
                self.symbols.get(p.name.upper()) is not None
                and self.symbols[p.name.upper()].fb_type is not None):
            return self.bad(f"{p.name!r} is a function block; invoke it as a statement "
                            f"({p.name}(IN := ...);) and read its outputs", p)
        try:
            rtype, fn = resolve_function(p.name, [a.type for a in args])
        except ValueError as exc:
            return self.bad(str(exc), p)
        return N.FuncCall(p.name.upper(), args, rtype, fn, p.line, p.col)

    # ------------------------------------------------------------------ statements
    def body(self, stmts: list) -> list[N.Stmt]:
        out: list[N.Stmt] = []
        for s in stmts:
            node = self.stmt(s)
            if node is not None:
                out.append(node)
        return out

    def stmt(self, p) -> N.Stmt | None:
        if isinstance(p, PAssign):
            return self.assign(p)
        if isinstance(p, PFbCall):
            return self.fb_call(p)
        if isinstance(p, PIf):
            branches = [(self.cond(c), self.body(b)) for c, b in p.branches]
            return N.If(branches, self.body(p.orelse), p.line, p.col)
        if isinstance(p, PCase):
            return self.case(p)
        if isinstance(p, PFor):
            return self.for_(p)
        if isinstance(p, PWhile):
            cond = self.cond(p.cond)
            self.loop_depth += 1
            body = self.body(p.body)
            self.loop_depth -= 1
            return N.While(cond, body, LOOP_LIMIT, p.line, p.col)
        if isinstance(p, PRepeat):
            self.loop_depth += 1
            body = self.body(p.body)
            self.loop_depth -= 1
            return N.Repeat(self.cond(p.cond), body, LOOP_LIMIT, p.line, p.col)
        if isinstance(p, PExit):
            if self.loop_depth == 0:
                self.err("EXIT outside a loop", p)
                return None
            return N.Exit(p.line, p.col)
        if isinstance(p, PReturn):
            return N.Return(p.line, p.col)
        self.err("unsupported statement", p)
        return None

    def cond(self, p) -> N.Expr:
        e = self.expr(p)
        if e.type not in (BOOL, ERR):
            self.err(f"condition must be BOOL, got {e.type}", p)
        return e

    def conversion(self, src: str, dst: str, what: str, node) -> Callable | None | bool:
        if src == ERR or dst == ERR:
            return None
        if not assignable(src, dst):
            hint = ""
            if src == REAL and dst in INT_TYPES:
                hint = " (use REAL_TO_INT or TRUNC)"
            elif src in INT_TYPES and dst == TIME:
                hint = " (use REAL_TO_TIME)"
            elif src == TIME and dst == REAL:
                hint = " (use TIME_TO_REAL)"
            elif src == BOOL and dst in NUMERIC_TYPES:
                hint = " (use BOOL_TO_INT)"
            self.err(f"cannot assign {src} to {what} of type {dst}{hint}", node)
            return False
        if dst == REAL and src in INT_TYPES:
            return float
        return None

    def assign(self, p: PAssign) -> N.Stmt | None:
        if isinstance(p.target, PMember):
            return self.assign_field(p)
        sym = self.lookup(p.target.name)
        if sym is None:
            self.err(f"unknown identifier {p.target.name!r}", p.target)
            return None
        if sym.scope == INPUT:
            self.err(f"cannot assign to {sym.name!r}: it is an input tag (direction 'in')", p.target)
            return None
        if sym.scope == SYS:
            self.err(f"cannot assign to system variable {sym.name!r}: it is read-only", p.target)
            return None
        if sym.constant:
            self.err(f"cannot assign to CONSTANT {sym.name!r}", p.target)
            return None
        if sym.dtype is None:
            self.err(f"cannot assign to function block instance {sym.name!r}", p.target)
            return None
        e = self.expr(p.expr)
        conv = self.conversion(e.type, sym.dtype, f"{sym.name!r}", p)
        if conv is False:
            return None
        if sym.scope == OUTPUT:
            self.output_writes.add(sym.name)
        return N.Assign(sym.scope, sym.name, e, conv, sym.name, p.line, p.col)

    def assign_field(self, p: PAssign) -> N.Stmt | None:
        m: PMember = p.target
        if not isinstance(m.base, PName):
            self.err("nested field assignment is not supported", p)
            return None
        sym = self.symbols.get(m.base.name.upper())
        if sym is None or sym.fb_type is None:
            self.err(f"{m.base.name}.{m.field} is not a function block field", p)
            return None
        cls = FB_TYPES[sym.fb_type]
        fld = m.field.upper()
        if fld not in cls.INPUTS:
            self.err(f"{sym.fb_type}.{m.field} is not an input field "
                     f"(assignable: {', '.join(cls.INPUTS)})", p)
            return None
        e = self.expr(p.expr)
        conv = self.conversion(e.type, cls.FIELD_TYPES[fld], f"{sym.name}.{fld}", p)
        if conv is False:
            return None
        return N.AssignField(sym.scope, sym.name, fld, e, conv, sym.name, p.line, p.col)

    def fb_call(self, p: PFbCall) -> N.Stmt | None:
        sym = self.symbols.get(p.name.upper())
        if sym is None:
            if self.lookup(p.name) is not None:
                self.err(f"{p.name!r} is not a function block instance", p)
            elif p.name.upper() in FB_TYPES:
                self.err(f"{p.name} is a function block type; declare an instance "
                         f"(VAR t : {p.name.upper()}; END_VAR) and call that", p)
            else:
                self.err(f"unknown function block instance {p.name!r}", p)
            return None
        if sym.fb_type is None:
            self.err(f"{p.name!r} is a variable, not a function block instance", p)
            return None
        cls = FB_TYPES[sym.fb_type]
        args: list[tuple[str, N.Expr, Callable | None]] = []
        used: set[str] = set()
        positional = 0
        for pname, pexpr in p.args:
            if pname is None:
                if positional >= len(cls.INPUTS):
                    self.err(f"{sym.fb_type} takes {len(cls.INPUTS)} inputs "
                             f"({', '.join(cls.INPUTS)})", p)
                    return None
                field = cls.INPUTS[positional]
                positional += 1
            else:
                field = pname.upper()
                if field not in cls.INPUTS:
                    self.err(f"{sym.fb_type} has no input {pname!r} "
                             f"(inputs: {', '.join(cls.INPUTS)})", p)
                    continue
            if field in used:
                self.err(f"input {field} assigned twice in call to {sym.name}", p)
                continue
            used.add(field)
            e = self.expr(pexpr)
            conv = self.conversion(e.type, cls.FIELD_TYPES[field], f"{sym.fb_type}.{field}", p)
            if conv is False:
                continue
            args.append((field, e, conv))
        return N.FbCall(sym.scope, sym.name, args, sym.name, p.line, p.col)

    def case(self, p: PCase) -> N.Stmt | None:
        sel = self.expr(p.selector)
        if sel.type not in INT_TYPES and sel.type != ERR:
            self.err(f"CASE selector must be INT or DINT, got {sel.type} "
                     f"(use REAL_TO_INT for a REAL)", p)
        branches = []
        seen: list[tuple[int, int]] = []
        for ranges, stmts in p.branches:
            for lo, hi in ranges:
                if lo > hi:
                    self.err(f"CASE range {lo}..{hi} is empty", p)
                for a, b in seen:
                    if lo <= b and a <= hi:
                        self.err(f"CASE label {lo}..{hi} overlaps {a}..{b}", p)
                        break
                seen.append((lo, hi))
            branches.append((ranges, self.body(stmts)))
        return N.Case(sel, branches, self.body(p.orelse), p.line, p.col)

    def for_(self, p: PFor) -> N.Stmt | None:
        sym = self.lookup(p.var.name)
        if sym is None:
            self.err(f"unknown identifier {p.var.name!r}", p.var)
            return None
        if sym.scope in (INPUT, SYS) or sym.constant or sym.dtype not in INT_TYPES:
            self.err(f"FOR control variable {p.var.name!r} must be a writable INT/DINT variable",
                     p.var)
            return None
        start, end = self.expr(p.start), self.expr(p.end)
        by = self.expr(p.by) if p.by is not None else None
        for e, what in ((start, "FOR start"), (end, "FOR limit")) + (
                ((by, "FOR step"),) if by is not None else ()):
            if e.type not in INT_TYPES and e.type != ERR:
                self.err(f"{what} must be INT/DINT, got {e.type}", p)
        self.loop_depth += 1
        body = self.body(p.body)
        self.loop_depth -= 1
        return N.For(sym.scope, sym.name, start, end, by, body, LOOP_LIMIT, None, p.line, p.col)
