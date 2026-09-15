from __future__ import annotations

from typing import Any

from . import nodes as N
from .compiler import ERR, StCompiler, Sym, VarDecl
from .errors import CompileError
from .lexer import parse_time_literal
from .nodes import GLOBAL, INPUT, LOCAL, OUTPUT, SYS
from .types import BOOL, INT, INT_TYPES, REAL, TIME, assignable, coerce_value


def jp(*parts) -> str:
    """RFC 6901 JSON pointer. A part that is already a pointer is appended verbatim,
    so jp(path, "operand") extends a pointer instead of escaping it."""
    out = ""
    for p in parts:
        s = str(p)
        if s.startswith("/"):
            out += s
        else:
            out += "/" + s.replace("~", "~0").replace("/", "~1")
    return out


class JsonCompiler:
    """Shared plumbing for the two JSON-document languages (LD and SFC)."""

    def __init__(self, doc: dict, tags, errors: list[CompileError], program: str | None):
        self.doc = doc
        self.errors = errors
        self.program = program
        self.ids: dict[str, str] = {}
        self.st = StCompiler(tags, errors, program=program,
                             member_resolver=self.resolve_member)

    def resolve_member(self, base: str, field: str, p):
        return None

    def err(self, msg: str, path: str) -> None:
        self.errors.append(CompileError(msg, path=path, program=self.program))

    def note_id(self, raw: Any, path: str) -> str | None:
        if raw is None:
            return None
        if not isinstance(raw, str):
            self.err("'id' must be a string", jp(path, "id"))
            return None
        if raw in self.ids:
            self.err(f"duplicate id {raw!r} (also at {self.ids[raw]})", jp(path, "id"))
        else:
            self.ids[raw] = path
        return raw

    # -------------------------------------------------------------- declarations
    def declare_vars(self) -> None:
        vars_ = self.doc.get("vars", [])
        if not isinstance(vars_, list):
            self.err("'vars' must be a list", jp("vars"))
            return
        for i, v in enumerate(vars_):
            path = jp("vars", i)
            if not isinstance(v, dict):
                self.err("variable declaration must be an object", path)
                continue
            name = v.get("name")
            if not isinstance(name, str) or not name:
                self.err("variable declaration needs a 'name' string", jp(path, "name"))
                continue
            tname = v.get("type")
            if not isinstance(tname, str):
                self.err(f"variable {name!r} needs a 'type'", jp(path, "type"))
                continue
            scope = v.get("scope", "VAR")
            if scope not in ("VAR", "VAR_GLOBAL", "VAR_RETAIN"):
                self.err(f"variable {name!r}: scope must be VAR, VAR_GLOBAL or VAR_RETAIN",
                         jp(path, "scope"))
                scope = "VAR"
            self.declare(name, tname, v.get("init"), scope, path)

    def declare(self, name: str, tname: str, init: Any, scope: str, path: str) -> None:
        key = name.upper()
        if key in self.st.symbols:
            self.err(f"duplicate declaration of {name!r}", path)
            return
        if key in self.st.tags:
            self.err(f"{name!r} is already a tag name", path)
            return
        before = len(self.errors)
        dtype, fb_type = self.st.resolve_type(tname, None)
        if len(self.errors) > before:
            del self.errors[before:]
            self.err(f"unknown data type {tname!r}", path)
            return
        value = None
        if init is not None:
            if fb_type is not None:
                self.err(f"function block instance {name!r} cannot have an 'init'", path)
            else:
                value = self.literal_value(init, dtype, path)
        sc = GLOBAL if scope == "VAR_GLOBAL" else LOCAL
        (self.st.globals if sc == GLOBAL else self.st.locals).append(
            VarDecl(name, sc, dtype, fb_type, value))
        self.st.symbols[key] = Sym(name, sc, dtype, fb_type, False)

    def hidden(self, name: str, value) -> str:
        self.st.locals.append(VarDecl(name, LOCAL, None, None, value))
        return name

    # -------------------------------------------------------------- values
    def literal(self, raw: Any, path: str) -> N.Lit | None:
        if isinstance(raw, bool):
            return N.Lit(raw, BOOL)
        if isinstance(raw, int):
            return N.Lit(raw, INT)
        if isinstance(raw, float):
            return N.Lit(raw, REAL)
        if isinstance(raw, str) and _is_time_text(raw):
            try:
                return N.Lit(parse_time_literal(raw), TIME)
            except ValueError as exc:
                self.err(str(exc), path)
                return None
        self.err(f"expected a literal (number, boolean or 'T#...' string), got {raw!r}", path)
        return None

    def literal_value(self, raw: Any, dtype: str | None, path: str):
        lit = self.literal(raw, path)
        if lit is None:
            return None
        if dtype is not None and dtype != ERR and not assignable(lit.type, dtype):
            self.err(f"initial value of type {lit.type} is not assignable to {dtype}", path)
            return None
        return coerce_value(lit.value, dtype)

    def operand(self, raw: Any, path: str) -> N.Expr:
        """number/bool -> literal, 'T#...' -> TIME literal, any other string -> name."""
        if isinstance(raw, dict):
            if "var" in raw:
                return self.name_ref(raw["var"], path)
            if "const" in raw:
                lit = self.literal(raw["const"], path)
                return lit if lit is not None else N.Lit(None, ERR)
            if "time" in raw:
                try:
                    return N.Lit(parse_time_literal(str(raw["time"])), TIME)
                except ValueError as exc:
                    self.err(str(exc), path)
                    return N.Lit(None, ERR)
            self.err("operand object must have one of 'var', 'const' or 'time'", path)
            return N.Lit(None, ERR)
        if isinstance(raw, str) and not _is_time_text(raw):
            return self.name_ref(raw, path)
        lit = self.literal(raw, path)
        return lit if lit is not None else N.Lit(None, ERR)

    def name_ref(self, name: Any, path: str) -> N.Expr:
        if not isinstance(name, str):
            self.err(f"expected a variable or tag name, got {name!r}", path)
            return N.Lit(None, ERR)
        sym = self.st.lookup(name)
        if sym is None:
            self.err(f"unknown identifier {name!r}", path)
            return N.Lit(None, ERR)
        if sym.dtype is None:
            self.err(f"{name!r} is a function block instance, not a value", path)
            return N.Lit(None, ERR)
        return N.VarRef(sym.scope, sym.name, sym.dtype, sym.name)

    def target(self, name: Any, path: str, want: str | None = None):
        """Resolve a writable destination -> (scope, key, dtype), or None."""
        if isinstance(name, dict):
            name = name.get("var", name)
        if not isinstance(name, str):
            self.err(f"expected a variable or tag name, got {name!r}", path)
            return None
        sym = self.st.lookup(name)
        if sym is None:
            self.err(f"unknown identifier {name!r}", path)
            return None
        if sym.scope == INPUT:
            self.err(f"cannot write to {sym.name!r}: it is an input tag (direction 'in')", path)
            return None
        if sym.scope == SYS:
            self.err(f"cannot write to system variable {sym.name!r}: it is read-only", path)
            return None
        if sym.dtype is None:
            self.err(f"cannot write to function block instance {sym.name!r}", path)
            return None
        if sym.constant:
            self.err(f"cannot write to CONSTANT {sym.name!r}", path)
            return None
        if want is not None and sym.dtype != want:
            self.err(f"{sym.name!r} is {sym.dtype}, expected {want}", path)
            return None
        if sym.scope == OUTPUT:
            self.st.output_writes.add(sym.name)
        return sym.scope, sym.name, sym.dtype

    def conv_for(self, src: str, dst: str, path: str, what: str):
        if src == ERR or dst == ERR:
            return None
        if not assignable(src, dst):
            self.err(f"cannot store {src} into {what} of type {dst}", path)
            return None
        return float if (dst == REAL and src in INT_TYPES) else None

    def check_header(self, language: str, version_max: int) -> None:
        version = self.doc.get("version")
        if version is None:
            self.err("document is missing 'version'", jp("version"))
        elif not isinstance(version, int) or version < 1 or version > version_max:
            self.err(f"unsupported {language} document version {version!r} "
                     f"(this engine speaks version {version_max})", jp("version"))
        lang = str(self.doc.get("language", language)).upper()
        if lang != language:
            self.err(f'\'language\' must be "{language}", got {self.doc.get("language")!r}',
                     jp("language"))


def _is_time_text(s: str) -> bool:
    u = s.upper()
    return u.startswith("T#") or u.startswith("TIME#")
