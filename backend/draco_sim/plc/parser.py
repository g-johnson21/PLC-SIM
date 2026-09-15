from __future__ import annotations

from .errors import CompileError
from .lexer import Token, tokenize
from .types import BOOL, INT, REAL, STRING, TIME


class P:
    __slots__ = ("line", "col")

    def __init__(self, line=0, col=0):
        self.line = line
        self.col = col


class PLit(P):
    __slots__ = ("value", "type")

    def __init__(self, value, type_, line, col):
        super().__init__(line, col)
        self.value = value
        self.type = type_


class PName(P):
    __slots__ = ("name",)

    def __init__(self, name, line, col):
        super().__init__(line, col)
        self.name = name


class PMember(P):
    __slots__ = ("base", "field")

    def __init__(self, base, field, line, col):
        super().__init__(line, col)
        self.base = base
        self.field = field


class PUnary(P):
    __slots__ = ("op", "x")

    def __init__(self, op, x, line, col):
        super().__init__(line, col)
        self.op = op
        self.x = x


class PBin(P):
    __slots__ = ("op", "l", "r")

    def __init__(self, op, l, r, line, col):
        super().__init__(line, col)
        self.op = op
        self.l = l
        self.r = r


class PCall(P):
    __slots__ = ("name", "args")

    def __init__(self, name, args, line, col):
        super().__init__(line, col)
        self.name = name
        self.args = args


class PAssign(P):
    __slots__ = ("target", "expr")

    def __init__(self, target, expr, line, col):
        super().__init__(line, col)
        self.target = target
        self.expr = expr


class PFbCall(P):
    __slots__ = ("name", "args")

    def __init__(self, name, args, line, col):
        super().__init__(line, col)
        self.name = name
        self.args = args  # list[(param_name|None, expr)]


class PIf(P):
    __slots__ = ("branches", "orelse")

    def __init__(self, branches, orelse, line, col):
        super().__init__(line, col)
        self.branches = branches
        self.orelse = orelse


class PCase(P):
    __slots__ = ("selector", "branches", "orelse")

    def __init__(self, selector, branches, orelse, line, col):
        super().__init__(line, col)
        self.selector = selector
        self.branches = branches
        self.orelse = orelse


class PFor(P):
    __slots__ = ("var", "start", "end", "by", "body")

    def __init__(self, var, start, end, by, body, line, col):
        super().__init__(line, col)
        self.var = var
        self.start = start
        self.end = end
        self.by = by
        self.body = body


class PWhile(P):
    __slots__ = ("cond", "body")

    def __init__(self, cond, body, line, col):
        super().__init__(line, col)
        self.cond = cond
        self.body = body


class PRepeat(P):
    __slots__ = ("body", "cond")

    def __init__(self, body, cond, line, col):
        super().__init__(line, col)
        self.body = body
        self.cond = cond


class PExit(P):
    __slots__ = ()


class PReturn(P):
    __slots__ = ()


class PVarDecl(P):
    __slots__ = ("name", "type_name", "init", "scope", "constant")

    def __init__(self, name, type_name, init, scope, constant, line, col):
        super().__init__(line, col)
        self.name = name
        self.type_name = type_name
        self.init = init
        self.scope = scope
        self.constant = constant


class PProgram:
    __slots__ = ("name", "decls", "body", "line", "col")

    def __init__(self, name, decls, body, line=0, col=0):
        self.name = name
        self.decls = decls
        self.body = body
        self.line = line
        self.col = col


class _ParseError(Exception):
    pass


_STMT_START = frozenset(("IF", "CASE", "FOR", "WHILE", "REPEAT", "EXIT", "RETURN"))
_BLOCK_END = frozenset(("END_IF", "END_CASE", "END_FOR", "END_WHILE", "END_REPEAT",
                        "END_PROGRAM", "END_VAR", "ELSE", "ELSIF", "UNTIL", "THEN", "DO", "OF"))


class Parser:
    def __init__(self, src: str):
        self.errors: list[CompileError] = []
        self.toks: list[Token] = tokenize(src, self.errors)
        self.i = 0

    # ------------------------------------------------------------------ helpers
    @property
    def tok(self) -> Token:
        return self.toks[self.i]

    def peek(self, k: int = 1) -> Token:
        j = min(self.i + k, len(self.toks) - 1)
        return self.toks[j]

    def advance(self) -> Token:
        t = self.toks[self.i]
        if t.kind != "eof":
            self.i += 1
        return t

    def at_op(self, op: str) -> bool:
        t = self.tok
        return t.kind == "op" and t.text == op

    def at_kw(self, kw: str) -> bool:
        t = self.tok
        return t.kind == "kw" and t.upper == kw

    def accept_op(self, op: str) -> bool:
        if self.at_op(op):
            self.advance()
            return True
        return False

    def accept_kw(self, kw: str) -> bool:
        if self.at_kw(kw):
            self.advance()
            return True
        return False

    def error(self, msg: str, tok: Token | None = None) -> _ParseError:
        t = tok or self.tok
        self.errors.append(CompileError(msg, t.line, t.col))
        return _ParseError()

    def expect_op(self, op: str) -> Token:
        if not self.at_op(op):
            raise self.error(f"expected {op!r}, got {self._describe(self.tok)}")
        return self.advance()

    def expect_kw(self, kw: str) -> Token:
        if not self.at_kw(kw):
            raise self.error(f"expected {kw}, got {self._describe(self.tok)}")
        return self.advance()

    def expect_ident(self) -> Token:
        if self.tok.kind != "ident":
            raise self.error(f"expected an identifier, got {self._describe(self.tok)}")
        return self.advance()

    @staticmethod
    def _describe(t: Token) -> str:
        if t.kind == "eof":
            return "end of input"
        return repr(t.text)

    def sync(self) -> None:
        while True:
            t = self.tok
            if t.kind == "eof":
                return
            if t.kind == "op" and t.text == ";":
                self.advance()
                return
            if t.kind == "kw" and (t.upper in _STMT_START or t.upper in _BLOCK_END):
                return
            self.advance()

    # ------------------------------------------------------------------ program
    def parse_program(self) -> PProgram:
        while self.tok.kind == "op" and self.tok.text == ";":
            self.advance()
        name = None
        line, col = self.tok.line, self.tok.col
        if self.at_kw("PROGRAM"):
            self.advance()
            try:
                name = self.expect_ident().text
            except _ParseError:
                self.sync()
        decls = self.parse_var_blocks()
        body = self.parse_stmts()
        if name is not None:
            if not self.accept_kw("END_PROGRAM"):
                self.errors.append(CompileError(
                    f"expected END_PROGRAM, got {self._describe(self.tok)}",
                    self.tok.line, self.tok.col))
        if self.tok.kind != "eof":
            self.errors.append(CompileError(
                f"unexpected {self._describe(self.tok)} after end of program",
                self.tok.line, self.tok.col))
        return PProgram(name, decls, body, line, col)

    def parse_var_blocks(self) -> list[PVarDecl]:
        decls: list[PVarDecl] = []
        while self.tok.kind == "kw" and self.tok.upper.startswith("VAR"):
            kw = self.tok.upper
            self.advance()
            if kw in ("VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR_EXTERNAL", "VAR_TEMP"):
                self.errors.append(CompileError(
                    f"{kw} is not supported (no user-defined function blocks); "
                    f"use VAR, VAR_GLOBAL or VAR_RETAIN",
                    self.toks[self.i - 1].line, self.toks[self.i - 1].col))
                kw = "VAR"
            scope = "VAR_GLOBAL" if kw == "VAR_GLOBAL" else "VAR"
            constant = self.accept_kw("CONSTANT")
            while not self.at_kw("END_VAR") and self.tok.kind != "eof":
                try:
                    decls.extend(self.parse_var_decl(scope, constant))
                except _ParseError:
                    self.sync()
            if not self.accept_kw("END_VAR"):
                self.errors.append(CompileError("expected END_VAR", self.tok.line, self.tok.col))
                return decls
        return decls

    def parse_var_decl(self, scope: str, constant: bool) -> list[PVarDecl]:
        names: list[Token] = [self.expect_ident()]
        while self.accept_op(","):
            names.append(self.expect_ident())
        self.expect_op(":")
        tname = self.tok
        if tname.kind not in ("ident", "kw"):
            raise self.error(f"expected a type name, got {self._describe(tname)}")
        self.advance()
        init = None
        if self.accept_op(":="):
            init = self.parse_expr()
        self.expect_op(";")
        return [PVarDecl(t.text, tname.text, init, scope, constant, t.line, t.col) for t in names]

    # ------------------------------------------------------------------ statements
    def parse_stmts(self, stop: frozenset[str] = frozenset(), stop_int: bool = False) -> list:
        out: list = []
        while True:
            t = self.tok
            if t.kind == "eof":
                return out
            if t.kind == "kw" and (t.upper in stop or t.upper in _BLOCK_END):
                return out
            if stop_int and (t.kind == "int"
                             or (t.kind == "op" and t.text == "-" and self.peek().kind == "int")):
                return out
            if t.kind == "op" and t.text == ";":
                self.advance()
                continue
            try:
                out.append(self.parse_stmt())
            except _ParseError:
                self.sync()
        return out

    def parse_stmt(self):
        t = self.tok
        if t.kind == "kw":
            up = t.upper
            if up == "IF":
                return self.parse_if()
            if up == "CASE":
                return self.parse_case()
            if up == "FOR":
                return self.parse_for()
            if up == "WHILE":
                return self.parse_while()
            if up == "REPEAT":
                return self.parse_repeat()
            if up == "EXIT":
                self.advance()
                self.expect_op(";")
                return PExit(t.line, t.col)
            if up == "RETURN":
                self.advance()
                self.expect_op(";")
                return PReturn(t.line, t.col)
            raise self.error(f"unexpected keyword {t.text!r}")
        if t.kind != "ident":
            raise self.error(f"unexpected {self._describe(t)} at start of statement")

        name = self.advance()
        if self.at_op("("):
            args = self.parse_call_args()
            self.expect_op(";")
            return PFbCall(name.text, args, name.line, name.col)
        target: P = PName(name.text, name.line, name.col)
        while self.accept_op("."):
            field = self.expect_ident()
            target = PMember(target, field.text, name.line, name.col)
        self.expect_op(":=")
        expr = self.parse_expr()
        self.expect_op(";")
        return PAssign(target, expr, name.line, name.col)

    def parse_call_args(self) -> list:
        self.expect_op("(")
        args: list = []
        if self.accept_op(")"):
            return args
        while True:
            pname = None
            if self.tok.kind == "ident" and self.peek().kind == "op" and self.peek().text == ":=":
                pname = self.advance().text
                self.advance()
            args.append((pname, self.parse_expr()))
            if self.accept_op(","):
                continue
            self.expect_op(")")
            return args

    def parse_if(self):
        t = self.expect_kw("IF")
        branches = []
        cond = self.parse_expr()
        self.expect_kw("THEN")
        body = self.parse_stmts(frozenset(("ELSIF", "ELSE", "END_IF")))
        branches.append((cond, body))
        orelse: list = []
        while self.at_kw("ELSIF"):
            self.advance()
            c = self.parse_expr()
            self.expect_kw("THEN")
            b = self.parse_stmts(frozenset(("ELSIF", "ELSE", "END_IF")))
            branches.append((c, b))
        if self.accept_kw("ELSE"):
            orelse = self.parse_stmts(frozenset(("END_IF",)))
        self.expect_kw("END_IF")
        self.accept_op(";")
        return PIf(branches, orelse, t.line, t.col)

    def parse_case(self):
        t = self.expect_kw("CASE")
        sel = self.parse_expr()
        self.expect_kw("OF")
        branches = []
        orelse: list = []
        while not self.at_kw("END_CASE") and not self.at_kw("ELSE") and self.tok.kind != "eof":
            ranges = [self.parse_case_label()]
            while self.accept_op(","):
                ranges.append(self.parse_case_label())
            self.expect_op(":")
            body = self.parse_stmts(frozenset(("ELSE", "END_CASE")), stop_int=True)
            branches.append((ranges, body))
        if self.accept_kw("ELSE"):
            orelse = self.parse_stmts(frozenset(("END_CASE",)))
        self.expect_kw("END_CASE")
        self.accept_op(";")
        return PCase(sel, branches, orelse, t.line, t.col)

    def parse_case_label(self):
        lo = self.parse_case_const()
        hi = lo
        if self.accept_op(".."):
            hi = self.parse_case_const()
        return (lo, hi)

    def parse_case_const(self) -> int:
        neg = False
        if self.accept_op("-"):
            neg = True
        t = self.tok
        if t.kind != "int":
            raise self.error(f"CASE labels must be integer constants, got {self._describe(t)}")
        self.advance()
        return -t.value if neg else t.value

    def parse_for(self):
        t = self.expect_kw("FOR")
        var = self.expect_ident()
        self.expect_op(":=")
        start = self.parse_expr()
        self.expect_kw("TO")
        end = self.parse_expr()
        by = None
        if self.accept_kw("BY"):
            by = self.parse_expr()
        self.expect_kw("DO")
        body = self.parse_stmts(frozenset(("END_FOR",)))
        self.expect_kw("END_FOR")
        self.accept_op(";")
        return PFor(PName(var.text, var.line, var.col), start, end, by, body, t.line, t.col)

    def parse_while(self):
        t = self.expect_kw("WHILE")
        cond = self.parse_expr()
        self.expect_kw("DO")
        body = self.parse_stmts(frozenset(("END_WHILE",)))
        self.expect_kw("END_WHILE")
        self.accept_op(";")
        return PWhile(cond, body, t.line, t.col)

    def parse_repeat(self):
        t = self.expect_kw("REPEAT")
        body = self.parse_stmts(frozenset(("UNTIL",)))
        self.expect_kw("UNTIL")
        cond = self.parse_expr()
        self.expect_kw("END_REPEAT")
        self.accept_op(";")
        return PRepeat(body, cond, t.line, t.col)

    # ------------------------------------------------------------------ expressions
    def parse_expr(self):
        return self.parse_or()

    def _binary_level(self, sub, ops_kw=(), ops_op=()):
        left = sub()
        while True:
            t = self.tok
            if t.kind == "kw" and t.upper in ops_kw:
                self.advance()
                left = PBin(t.upper, left, sub(), t.line, t.col)
            elif t.kind == "op" and t.text in ops_op:
                self.advance()
                op = "AND" if t.text == "&" else t.text
                left = PBin(op, left, sub(), t.line, t.col)
            else:
                return left

    def parse_or(self):
        return self._binary_level(self.parse_xor, ops_kw=("OR",))

    def parse_xor(self):
        return self._binary_level(self.parse_and, ops_kw=("XOR",))

    def parse_and(self):
        return self._binary_level(self.parse_eq, ops_kw=("AND",), ops_op=("&",))

    def parse_eq(self):
        return self._binary_level(self.parse_rel, ops_op=("=", "<>"))

    def parse_rel(self):
        return self._binary_level(self.parse_add, ops_op=("<", ">", "<=", ">="))

    def parse_add(self):
        return self._binary_level(self.parse_term, ops_op=("+", "-"))

    def parse_term(self):
        return self._binary_level(self.parse_unary, ops_kw=("MOD",), ops_op=("*", "/"))

    def parse_unary(self):
        t = self.tok
        if t.kind == "op" and t.text in ("-", "+"):
            self.advance()
            return PUnary(t.text, self.parse_unary(), t.line, t.col)
        if t.kind == "kw" and t.upper == "NOT":
            self.advance()
            return PUnary("NOT", self.parse_unary(), t.line, t.col)
        return self.parse_power()

    def parse_power(self):
        base = self.parse_primary()
        if self.at_op("**"):
            t = self.advance()
            return PBin("**", base, self.parse_unary(), t.line, t.col)
        return base

    def parse_primary(self):
        t = self.tok
        if t.kind == "int":
            self.advance()
            return PLit(t.value, INT, t.line, t.col)
        if t.kind == "real":
            self.advance()
            return PLit(t.value, REAL, t.line, t.col)
        if t.kind == "time":
            self.advance()
            return PLit(t.value, TIME, t.line, t.col)
        if t.kind == "str":
            self.advance()
            return PLit(t.value, STRING, t.line, t.col)
        if t.kind == "kw" and t.upper in ("TRUE", "FALSE"):
            self.advance()
            return PLit(t.upper == "TRUE", BOOL, t.line, t.col)
        if t.kind == "op" and t.text == "(":
            self.advance()
            e = self.parse_expr()
            self.expect_op(")")
            return e
        if t.kind == "ident":
            self.advance()
            if self.at_op("("):
                return PCall(t.text, [a for _, a in self.parse_call_args()], t.line, t.col)
            node: P = PName(t.text, t.line, t.col)
            while self.at_op("."):
                self.advance()
                f = self.expect_ident()
                node = PMember(node, f.text, t.line, t.col)
            return node
        raise self.error(f"unexpected {self._describe(t)} in expression")


def parse_program_text(src: str) -> tuple[PProgram, list[CompileError]]:
    p = Parser(src)
    prog = p.parse_program()
    return prog, p.errors


def parse_statements_text(src: str) -> tuple[list, list[CompileError]]:
    p = Parser(src)
    body = p.parse_stmts()
    if p.tok.kind != "eof":
        p.errors.append(CompileError(f"unexpected {Parser._describe(p.tok)}", p.tok.line, p.tok.col))
    return body, p.errors


def parse_expression_text(src: str) -> tuple[object | None, list[CompileError]]:
    p = Parser(src)
    try:
        e = p.parse_expr()
    except _ParseError:
        return None, p.errors
    if p.tok.kind != "eof":
        p.errors.append(CompileError(
            f"unexpected {Parser._describe(p.tok)} after expression", p.tok.line, p.tok.col))
    return e, p.errors
