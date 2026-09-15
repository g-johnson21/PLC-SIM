from __future__ import annotations

from .errors import PlcFaultSignal
from .types import BOOL, wrap32

# store indices used by every variable reference
LOCAL, GLOBAL, INPUT, OUTPUT, SYS = 0, 1, 2, 3, 4


class ExecContext:
    __slots__ = ("store", "locals", "globals", "inputs", "outputs", "sys", "dt", "steps",
                 "sfc", "scan", "program")

    def __init__(self, locals_, globals_, inputs, outputs, sys_, program=""):
        self.locals = locals_
        self.globals = globals_
        self.inputs = inputs
        self.outputs = outputs
        self.sys = sys_
        self.store = (locals_, globals_, inputs, outputs, sys_)
        self.dt = 0.0
        self.steps = None
        self.sfc = None
        self.scan = 0
        self.program = program


class ExitSignal(Exception):
    pass


class ReturnSignal(Exception):
    pass


class Node:
    __slots__ = ("line", "col")

    def __init__(self, line: int = 0, col: int = 0) -> None:
        self.line = line
        self.col = col

    def fault(self, kind: str, message: str) -> PlcFaultSignal:
        return PlcFaultSignal(kind, message, self.line, self.col)


# --------------------------------------------------------------------------- expressions

class Expr(Node):
    __slots__ = ("type",)

    def eval(self, ctx: ExecContext):  # pragma: no cover - abstract
        raise NotImplementedError


class Lit(Expr):
    __slots__ = ("value",)

    def __init__(self, value, type_, line=0, col=0):
        super().__init__(line, col)
        self.value = value
        self.type = type_

    def eval(self, ctx):
        return self.value


class VarRef(Expr):
    __slots__ = ("scope", "key", "name")

    def __init__(self, scope, key, type_, name, line=0, col=0):
        super().__init__(line, col)
        self.scope = scope
        self.key = key
        self.type = type_
        self.name = name

    def eval(self, ctx):
        return ctx.store[self.scope][self.key]


class FieldRef(Expr):
    """Function-block output/input field, e.g. T1.Q"""

    __slots__ = ("scope", "key", "field", "name")

    def __init__(self, scope, key, field, type_, name, line=0, col=0):
        super().__init__(line, col)
        self.scope = scope
        self.key = key
        self.field = field
        self.type = type_
        self.name = name

    def eval(self, ctx):
        return getattr(ctx.store[self.scope][self.key], self.field)


class StepRef(Expr):
    """SFC step state: StepName.X (BOOL) or StepName.T (TIME)."""

    __slots__ = ("index", "field", "name")

    def __init__(self, index, field, type_, name, line=0, col=0):
        super().__init__(line, col)
        self.index = index
        self.field = field
        self.type = type_
        self.name = name

    def eval(self, ctx):
        step = ctx.steps[self.index]
        return step.active if self.field == "X" else step.t


class Unary(Expr):
    __slots__ = ("op", "operand", "fn")

    def __init__(self, op, operand, type_, fn, line=0, col=0):
        super().__init__(line, col)
        self.op = op
        self.operand = operand
        self.type = type_
        self.fn = fn

    def eval(self, ctx):
        try:
            return self.fn(self.operand.eval(ctx))
        except (ValueError, OverflowError, ZeroDivisionError) as exc:
            raise self.fault("math", f"{self.op}: {exc}") from None


class Binary(Expr):
    __slots__ = ("op", "l", "r", "fn")

    def __init__(self, op, l, r, type_, fn, line=0, col=0):
        super().__init__(line, col)
        self.op = op
        self.l = l
        self.r = r
        self.type = type_
        self.fn = fn

    def eval(self, ctx):
        try:
            return self.fn(self.l.eval(ctx), self.r.eval(ctx))
        except ZeroDivisionError:
            raise self.fault("div_zero", f"division by zero in '{self.op}'") from None
        except (ValueError, OverflowError) as exc:
            raise self.fault("math", f"{self.op}: {exc}") from None


class AndExpr(Expr):
    __slots__ = ("l", "r")

    def __init__(self, l, r, line=0, col=0):
        super().__init__(line, col)
        self.l = l
        self.r = r
        self.type = BOOL

    def eval(self, ctx):
        return self.l.eval(ctx) and self.r.eval(ctx)


class OrExpr(Expr):
    __slots__ = ("l", "r")

    def __init__(self, l, r, line=0, col=0):
        super().__init__(line, col)
        self.l = l
        self.r = r
        self.type = BOOL

    def eval(self, ctx):
        return self.l.eval(ctx) or self.r.eval(ctx)


class XorExpr(Expr):
    __slots__ = ("l", "r")

    def __init__(self, l, r, line=0, col=0):
        super().__init__(line, col)
        self.l = l
        self.r = r
        self.type = BOOL

    def eval(self, ctx):
        return bool(self.l.eval(ctx)) != bool(self.r.eval(ctx))


class FuncCall(Expr):
    __slots__ = ("name", "args", "fn")

    def __init__(self, name, args, type_, fn, line=0, col=0):
        super().__init__(line, col)
        self.name = name
        self.args = args
        self.type = type_
        self.fn = fn

    def eval(self, ctx):
        try:
            return self.fn(*[a.eval(ctx) for a in self.args])
        except ZeroDivisionError:
            raise self.fault("div_zero", f"division by zero in {self.name}()") from None
        except (ValueError, OverflowError) as exc:
            raise self.fault("math", f"{self.name}(): {exc}") from None


# --------------------------------------------------------------------------- statements

class Stmt(Node):
    __slots__ = ()

    def exec(self, ctx: ExecContext) -> None:  # pragma: no cover - abstract
        raise NotImplementedError


class Assign(Stmt):
    __slots__ = ("scope", "key", "expr", "conv", "name")

    def __init__(self, scope, key, expr, conv, name, line=0, col=0):
        super().__init__(line, col)
        self.scope = scope
        self.key = key
        self.expr = expr
        self.conv = conv
        self.name = name

    def exec(self, ctx):
        v = self.expr.eval(ctx)
        if self.conv is not None:
            v = self.conv(v)
        ctx.store[self.scope][self.key] = v


class AssignField(Stmt):
    """Assignment to a function block input field, e.g. T1.PT := x"""

    __slots__ = ("scope", "key", "field", "expr", "conv", "name")

    def __init__(self, scope, key, field, expr, conv, name, line=0, col=0):
        super().__init__(line, col)
        self.scope = scope
        self.key = key
        self.field = field
        self.expr = expr
        self.conv = conv
        self.name = name

    def exec(self, ctx):
        v = self.expr.eval(ctx)
        setattr(ctx.store[self.scope][self.key], self.field,
                self.conv(v) if self.conv is not None else v)


class FbCall(Stmt):
    __slots__ = ("scope", "key", "args", "name")

    def __init__(self, scope, key, args, name, line=0, col=0):
        super().__init__(line, col)
        self.scope = scope
        self.key = key
        self.args = args  # list[(field, expr, conv)]
        self.name = name

    def exec(self, ctx):
        inst = ctx.store[self.scope][self.key]
        for field, expr, conv in self.args:
            v = expr.eval(ctx)
            setattr(inst, field, conv(v) if conv is not None else v)
        inst.execute(ctx.dt)


class If(Stmt):
    __slots__ = ("branches", "orelse")

    def __init__(self, branches, orelse, line=0, col=0):
        super().__init__(line, col)
        self.branches = branches
        self.orelse = orelse

    def exec(self, ctx):
        for cond, body in self.branches:
            if cond.eval(ctx):
                for s in body:
                    s.exec(ctx)
                return
        for s in self.orelse:
            s.exec(ctx)


class Case(Stmt):
    __slots__ = ("selector", "branches", "orelse")

    def __init__(self, selector, branches, orelse, line=0, col=0):
        super().__init__(line, col)
        self.selector = selector
        self.branches = branches  # list[(ranges, body)] with ranges list[(lo, hi)]
        self.orelse = orelse

    def exec(self, ctx):
        v = self.selector.eval(ctx)
        for ranges, body in self.branches:
            for lo, hi in ranges:
                if lo <= v <= hi:
                    for s in body:
                        s.exec(ctx)
                    return
        for s in self.orelse:
            s.exec(ctx)


class For(Stmt):
    __slots__ = ("scope", "key", "start", "end", "step", "body", "cap", "conv")

    def __init__(self, scope, key, start, end, step, body, cap, conv, line=0, col=0):
        super().__init__(line, col)
        self.scope = scope
        self.key = key
        self.start = start
        self.end = end
        self.step = step
        self.body = body
        self.cap = cap
        self.conv = conv

    def exec(self, ctx):
        store = ctx.store[self.scope]
        i = self.start.eval(ctx)
        end = self.end.eval(ctx)
        step = self.step.eval(ctx) if self.step is not None else 1
        if step == 0:
            raise self.fault("loop", "FOR loop increment is zero")
        conv = self.conv
        n = 0
        cap = self.cap
        while (i <= end) if step > 0 else (i >= end):
            if n >= cap:
                raise self.fault("loop", f"FOR loop exceeded {cap} iterations")
            n += 1
            store[self.key] = conv(i) if conv is not None else i
            try:
                for s in self.body:
                    s.exec(ctx)
            except ExitSignal:
                return
            i = store[self.key] + step
        store[self.key] = conv(i) if conv is not None else i


class While(Stmt):
    __slots__ = ("cond", "body", "cap")

    def __init__(self, cond, body, cap, line=0, col=0):
        super().__init__(line, col)
        self.cond = cond
        self.body = body
        self.cap = cap

    def exec(self, ctx):
        n = 0
        cap = self.cap
        while self.cond.eval(ctx):
            if n >= cap:
                raise self.fault("loop", f"WHILE loop exceeded {cap} iterations")
            n += 1
            try:
                for s in self.body:
                    s.exec(ctx)
            except ExitSignal:
                return


class Repeat(Stmt):
    __slots__ = ("cond", "body", "cap")

    def __init__(self, cond, body, cap, line=0, col=0):
        super().__init__(line, col)
        self.cond = cond
        self.body = body
        self.cap = cap

    def exec(self, ctx):
        n = 0
        cap = self.cap
        while True:
            if n >= cap:
                raise self.fault("loop", f"REPEAT loop exceeded {cap} iterations")
            n += 1
            try:
                for s in self.body:
                    s.exec(ctx)
            except ExitSignal:
                return
            if self.cond.eval(ctx):
                return


class Exit(Stmt):
    __slots__ = ()

    def exec(self, ctx):
        raise ExitSignal


class Return(Stmt):
    __slots__ = ()

    def exec(self, ctx):
        raise ReturnSignal


# --------------------------------------------------------------------------- operator kernels

def idiv(a, b):
    q = abs(a) // abs(b)
    return wrap32(-q if (a < 0) != (b < 0) else q)


def imod(a, b):
    r = abs(a) % abs(b)
    return -r if a < 0 else r


def wrap_add(a, b):
    return wrap32(a + b)


def wrap_sub(a, b):
    return wrap32(a - b)


def wrap_mul(a, b):
    return wrap32(a * b)


def real_div(a, b):
    if b == 0:
        raise ZeroDivisionError
    return a / b
