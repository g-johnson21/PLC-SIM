from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .compiler import StCompiler, VarDecl
from .errors import CompileError
from .ladder import LadderCompiler
from .nodes import ExecContext, ReturnSignal
from .parser import parse_program_text
from .sfc import SfcBody, SfcCompiler
from .types import normalise_tags

LANGUAGES = ("ST", "LD", "SFC")


class StBody:
    __slots__ = ("stmts",)

    def __init__(self, stmts):
        self.stmts = stmts

    def execute(self, ctx: ExecContext) -> None:
        try:
            for s in self.stmts:
                s.exec(ctx)
        except ReturnSignal:
            pass


@dataclass
class CompiledProgram:
    name: str
    language: str
    locals: list[VarDecl]
    globals: list[VarDecl]
    executable: Any
    source: Any = None
    sfc: SfcBody | None = None
    tag_names: frozenset[str] = frozenset()
    output_writes: frozenset[str] = frozenset()
    abort_writes: frozenset[str] = frozenset()

    @property
    def variable_count(self) -> int:
        return len([d for d in self.locals if not d.name.startswith("#")]) + len(self.globals)

    @property
    def is_sfc(self) -> bool:
        return self.sfc is not None

    def __repr__(self) -> str:
        return (f"CompiledProgram({self.name!r}, {self.language}, "
                f"{self.variable_count} variables)")


def compile_program(source: str | dict, language: str, tags, *,
                    name: str | None = None) -> CompiledProgram:
    lang = str(language).upper()
    if lang not in LANGUAGES:
        raise ValueError(f"language must be one of {LANGUAGES}, got {language!r}")
    specs = normalise_tags(tags)
    tagmap = {t.name.upper(): t for t in specs}
    tag_names = frozenset(tagmap)
    errors: list[CompileError] = []

    if lang == "ST":
        tree, perrs = parse_program_text(source if isinstance(source, str) else str(source))
        errors.extend(perrs)
        pname = name or tree.name
        if pname is None:
            raise CompileError("program has no name: use PROGRAM <name> ... END_PROGRAM "
                               "or pass name=...", 1, 1)
        if errors:
            CompileError.raise_all(errors, pname)
        st = StCompiler(tagmap, errors, program=pname)
        st.declare(tree.decls)
        body = st.body(tree.body)
        CompileError.raise_all(errors, pname)
        return CompiledProgram(pname, "ST", st.locals, st.globals, StBody(body),
                               source, None, tag_names,
                               frozenset(st.output_writes))

    doc = _as_doc(source)
    pname = name or doc.get("name")
    if not isinstance(pname, str) or not pname:
        raise CompileError("document has no 'name'", path="/name")
    if lang == "LD":
        lc = LadderCompiler(doc, tagmap, errors, pname)
        body = lc.compile()
        CompileError.raise_all(errors, pname)
        return CompiledProgram(pname, "LD", lc.st.locals, lc.st.globals, body,
                               doc, None, tag_names,
                               frozenset(lc.st.output_writes))

    sc = SfcCompiler(doc, tagmap, errors, pname)
    body = sc.compile()
    CompileError.raise_all(errors, pname)
    return CompiledProgram(pname, "SFC", sc.st.locals, sc.st.globals, body,
                           doc, body, tag_names, frozenset(sc.st.output_writes),
                           sc.abort_writes)


def compile_file(path: str, tags, *, name: str | None = None,
                 language: str | None = None) -> CompiledProgram:
    """Compile a program file; the language comes from the extension unless given."""
    import os

    low = str(path).lower()
    if language is None:
        if low.endswith(".ld.json"):
            language = "LD"
        elif low.endswith(".sfc.json"):
            language = "SFC"
        elif low.endswith(".st"):
            language = "ST"
        else:
            raise ValueError(f"cannot infer language from {os.path.basename(path)!r}; "
                             f"use .st, .ld.json or .sfc.json, or pass language=")
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    return compile_program(text, language, tags, name=name)


def _as_doc(source: str | dict) -> dict:
    if isinstance(source, dict):
        return source
    if isinstance(source, (bytes, bytearray)):
        source = source.decode("utf-8")
    if not isinstance(source, str):
        raise CompileError(f"expected a JSON document or string, got {type(source).__name__}",
                           path="")
    try:
        doc = json.loads(source)
    except json.JSONDecodeError as exc:
        raise CompileError(f"invalid JSON: {exc.msg}", exc.lineno, exc.colno, path="") from None
    if not isinstance(doc, dict):
        raise CompileError("document must be a JSON object", path="")
    return doc
