"""CompileError locations for LD and SFC documents (spec §8) and read-only input tags (§1.4)."""

import pytest

from .helpers import (action, coil, compile_error, contact, element, ld, parallel, series, sfc,
                      step, trans)


def doc_ld(*logics, **extra):
    return {**ld(*logics, name="bad"), **extra}


def doc_sfc(steps, transitions=(), **extra):
    return sfc(steps, list(transitions), name="bad", **extra)


A_B = [step("A", initial=True), step("B")]


@pytest.mark.parametrize("language,source,location,verb", [
    ("ST", "VAR n : INT; END_VAR\nn := 1;\nDI1 := TRUE;", (None, 3, 1), "assign to"),
    ("LD", doc_ld(series(contact("DO1"), coil("DI1"))), ("/rungs/0/logic/elements/1/operand", None, None),
     "write to"),
    ("SFC", doc_sfc([step("A", action("DI1 := TRUE;"), initial=True)]), ("/steps/0/actions/0/body", 1, 1),
     "assign to"),
])
def test_input_tags_are_read_only_in_every_language(language, source, location, verb):
    e = compile_error(source, language)
    assert (e.path, e.line, e.col) == location
    assert e.message == f"cannot {verb} 'DI1': it is an input tag (direction 'in')"


def test_ladder_diagnostic_renders_program_and_pointer():
    e = compile_error(doc_ld(series(contact("DI1"), coil("DI2"))), "LD")
    assert e.errors == [e] and e.program == "bad"
    assert str(e) == f"bad:/rungs/0/logic/elements/1/operand: {e.message}"


@pytest.mark.parametrize("elem,field", [
    (coil("DI2", "SET"), "operand"),
    (element("move", src=1.0, dst="AI1"), "dst"),
    (element("math", op="ADD", a=1.0, b=2.0, dst="AI2"), "dst"),
    (element("timer", "tm", fb="TON", pt="T#1s", q="DI1"), "q"),
    (element("counter", "ct", fb="CTU", pv=3, q="DI2"), "q"),
])
def test_no_ladder_destination_may_be_an_input_tag(elem, field):
    e = compile_error(doc_ld(series(contact("DO1"), elem)), "LD")
    assert len(e.errors) == 1 and e.path == f"/rungs/0/logic/elements/1/{field}"
    assert "input tag" in e.message


@pytest.mark.parametrize("doc,path", [
    (doc_ld(series(contact("DI1", "XX"), coil("DO1"))), "/rungs/0/logic/elements/0/kind"),
    (doc_ld(series({"type": "widget"}, coil("DO1"))), "/rungs/0/logic/elements/0/type"),
    (doc_ld(series(contact("AI1"), coil("DO1"))), "/rungs/0/logic/elements/0/operand"),
    (doc_ld(series(element("compare", op="XX", a=1.0, b=2.0), coil("DO1"))), "/rungs/0/logic/elements/0/op"),
    (doc_ld(series(contact("DI1", id="a"), coil("DO1", id="a"))), "/rungs/0/logic/elements/1/id"),
    (doc_ld(series(contact("DI1"), coil("DO1")), version=2), "/version"),
])
def test_ladder_diagnostics_point_at_the_offending_field(doc, path):
    e = compile_error(doc, "LD")
    assert (len(e.errors), e.path, e.line, e.col) == (1, path, None, None)


def test_every_ladder_diagnostic_is_collected_with_its_own_pointer():
    e = compile_error(doc_ld(
        series(contact("nope"), coil("DO1")),
        series(parallel(contact("DI1"), series(contact("DI2"), coil("DI1"))), coil("DO2")),
        series(contact("DI1", "XX"), coil("DO3")),
    ), "LD")
    assert [d.path for d in e.errors] == [
        "/rungs/0/logic/elements/0/operand",
        "/rungs/1/logic/elements/0/branches/1/elements/1/operand",
        "/rungs/2/logic/elements/0/kind",
    ]
    assert all(d.program == "bad" for d in e.errors)


@pytest.mark.parametrize("doc,path", [
    (doc_sfc(A_B, [trans("A", "ZZ")]), "/transitions/0/to"),
    (doc_sfc(A_B, [trans(["A", "ZZ"], "B")]), "/transitions/0/from/1"),
    (doc_sfc(A_B, [trans("A", "B", "AI1 + 1.0")]), "/transitions/0/condition"),
    (doc_sfc([step("DO1", initial=True)]), "/steps/0/name"),
    (doc_sfc([step("A", initial=True), step("A")]), "/steps/1/name"),
    (doc_sfc([step("A"), step("B")]), "/steps"),
    (doc_sfc([step("A", initial=True), step("B", initial=True)]), "/steps/1/initial"),
    (doc_sfc([step("A", action("DO1 := TRUE;", "D"), initial=True)]), "/steps/0/actions/0/delay"),
    (doc_sfc([step("A", action("DO1 := TRUE;", "X"), initial=True)]), "/steps/0/actions/0/qualifier"),
    (doc_sfc(A_B, abort_step="ZZ"), "/abort_step"),
    (doc_sfc(A_B, [trans("B", "A")], abort_step="B"), "/abort_step"),
])
def test_sfc_diagnostics_point_at_the_offending_field(doc, path):
    e = compile_error(doc, "SFC")
    assert (len(e.errors), e.path) == (1, path)


BODY_SYNTAX = doc_sfc([step("A", initial=True), step("B", action("DO1 := TRUE;\n  DO2 := * 1;"))],
                      [trans("A", "B")])
CONDITION_SYNTAX = doc_sfc(A_B, [trans("A", "B", "DI1 AND")])
BODY_SEMANTIC = doc_sfc([step("A", action("DO1 := TRUE;\n  AI1 := 1.0;"), initial=True)])

STALE_RENDER = pytest.mark.xfail(strict=True, reason=(
    "engine bug: CompileError.__init__ freezes str() via super().__init__(self._render()) and has no "
    "__str__; program/path are set on parser diagnostics after construction (raise_all sets "
    "e.program), so syntax errors render as 'line:col: message' without the §8 program:pointer prefix"))


@pytest.mark.parametrize("doc,path,position", [
    (BODY_SYNTAX, "/steps/1/actions/0/body", (2, 10)),
    (CONDITION_SYNTAX, "/transitions/0/condition", (1, 8)),
    (BODY_SEMANTIC, "/steps/0/actions/0/body", (2, 3)),
])
def test_st_fragments_carry_pointer_and_fragment_relative_position(doc, path, position):
    e = compile_error(doc, "SFC")
    assert (e.path, e.line, e.col) == (path, *position)


@pytest.mark.parametrize("language,source,location", [
    ("SFC", BODY_SEMANTIC, "bad:/steps/0/actions/0/body:2:3"),
    pytest.param("SFC", BODY_SYNTAX, "bad:/steps/1/actions/0/body:2:10", marks=STALE_RENDER),
    pytest.param("SFC", CONDITION_SYNTAX, "bad:/transitions/0/condition:1:8", marks=STALE_RENDER),
    pytest.param("ST", "VAR x : INT; END_VAR\nx := * 2;", "bad:2:6", marks=STALE_RENDER),
])
def test_diagnostics_render_program_pointer_and_position(language, source, location):
    e = compile_error(source, language)
    assert str(e) == f"{location}: {e.message}"


def test_malformed_json_text_is_a_compile_error():
    assert compile_error('{"version": 1, ', "LD").line == 1
