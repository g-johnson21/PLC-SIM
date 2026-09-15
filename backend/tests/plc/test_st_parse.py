"""ST lexing and parsing (spec §4.1) and CompileError positions (§8)."""

import pytest

from draco_sim.plc import compile_program

from .helpers import TAGS, compile_error, run_st, same, scan_n, st_value, var


def test_program_header_names_the_program():
    prog = compile_program("PROGRAM hdr\nVAR x : INT; END_VAR\nx := 1;\nEND_PROGRAM", "ST", TAGS)
    assert (prog.name, prog.language, prog.is_sfc) == ("hdr", "ST", False)


def test_headerless_program_with_var_blocks():
    rt = run_st("VAR x : INT; END_VAR\nx := x + 1;")
    scan_n(rt, 3)
    assert var(rt, "x") == 3


@pytest.mark.parametrize("expr,expected", [
    ("16#FF", 255), ("2#1010", 10), ("8#17", 15), ("1_000", 1000), ("16#7FFF_FFFF", 2147483647),
])
def test_integer_literals(expr, expected):
    assert same(st_value(expr, "DINT"), expected)


@pytest.mark.parametrize("expr,expected", [
    ("T#500ms", 0.5), ("T#1s500ms", 1.5), ("T#2.5s", 2.5), ("T#-5s", -5.0), ("TIME#1m", 60.0),
    ("T#1h", 3600.0), ("T#1d", 86400.0), ("T#1us", 1e-6), ("T#1ns", 1e-9),
])
def test_time_literals_are_seconds(expr, expected):
    assert st_value(expr, "TIME") == pytest.approx(expected, rel=1e-9, abs=0)


def test_string_literal_escapes():
    rt = run_st("VAR s : STRING; ok : BOOL; END_VAR\ns := 'it$'s $$5';\nok := s = 'it$'s $$5';")
    rt.scan(0.01)
    assert var(rt, "s") == "it's $5" and var(rt, "ok") is True


def test_nested_block_comments_and_line_comments():
    rt = run_st(
        "VAR x : INT; END_VAR\n"
        "(* outer (* inner *) x := 100; still comment *)\n"
        "x := 1; // x := 2;\n"
        "x := x + 1;\n"
    )
    rt.scan(0.01)
    assert var(rt, "x") == 2


def test_keywords_are_case_insensitive():
    rt = run_st("var x : int; end_var\nif true then x := 7; End_If\nfor x := x to 9 do ; end_for")
    rt.scan(0.01)
    assert var(rt, "x") == 10


@pytest.mark.parametrize("expr,type_,expected", [
    ("-2 ** 2", "REAL", -4.0),
    ("2 ** 3 ** 2", "REAL", 512.0),
    ("2 ** -1", "REAL", 0.5),
    ("1 + 2 * 3", "INT", 7),
    ("(1 + 2) * 3", "INT", 9),
    ("7 + 5 MOD 3", "INT", 9),
    ("10 - 4 - 3", "INT", 3),
    ("NOT FALSE AND FALSE", "BOOL", False),
    ("TRUE OR TRUE XOR TRUE", "BOOL", True),
    ("TRUE XOR TRUE AND FALSE", "BOOL", True),
    ("TRUE XOR TRUE & FALSE", "BOOL", True),
    ("1 < 2 = TRUE", "BOOL", True),
    ("2 * 3 > 5 AND 1 + 1 = 2", "BOOL", True),
])
def test_operator_precedence(expr, type_, expected):
    assert same(st_value(expr, type_), expected)


def test_empty_statements_and_optional_trailing_semicolons():
    rt = run_st(
        "VAR x : INT; END_VAR\n;;\n"
        "IF x = 0 THEN x := 1; ELSIF x = 1 THEN x := 2; ELSE x := 3; END_IF\n"
        "WHILE x < 0 DO x := 0; END_WHILE;\n"
    )
    scan_n(rt, 3)
    assert var(rt, "x") == 3


@pytest.mark.parametrize("sel,expected", [(-2, 1), (0, 2), (2, 2), (5, 3), (6, 4), (7, 3)])
def test_case_label_lists_ranges_and_negatives(sel, expected):
    rt = run_st(
        "VAR k : INT; r : INT; END_VAR\n"
        f"k := {sel};\n"
        "CASE k OF\n  -3..-1: r := 1;\n  0..2: r := 2;\n  5, 7: r := 3;\nELSE r := 4;\nEND_CASE"
    )
    rt.scan(0.01)
    assert var(rt, "r") == expected


@pytest.mark.parametrize("header,expected", [
    ("FOR i := 1 TO 5 DO", 15),
    ("FOR i := 1 TO 10 BY 2 DO", 25),
    ("FOR i := 10 TO 1 BY -3 DO", 22),
    ("FOR i := 5 TO 1 DO", 0),
])
def test_for_loops(header, expected):
    rt = run_st(f"VAR i : INT; s : INT; END_VAR\ns := 0;\n{header} s := s + i; END_FOR")
    rt.scan(0.01)
    assert var(rt, "s") == expected


def test_while_checks_first_repeat_runs_once():
    rt = run_st(
        "VAR w : INT; r : INT; END_VAR\n"
        "w := 0; WHILE w > 100 DO w := 1; END_WHILE\n"
        "r := 10; REPEAT r := r + 1; UNTIL TRUE END_REPEAT"
    )
    rt.scan(0.01)
    assert (var(rt, "w"), var(rt, "r")) == (0, 11)


def test_syntax_error_line_and_column():
    e = compile_error("VAR x : INT; END_VAR\nx := 1;\nx := * 2;")
    assert (e.line, e.col, e.path, e.program) == (3, 6, None, "bad")


def test_semantic_error_renders_program_line_col():
    e = compile_error("VAR x : INT; END_VAR\n    AI1 := 1.0;")
    assert (e.line, e.col) == (2, 5)
    assert str(e) == f"bad:2:5: {e.message}" and "AI1" in e.message
    assert e.errors == [e]
    assert e.as_dict() == {"message": e.message, "line": 2, "col": 5, "path": None, "program": "bad"}


def test_illegal_character_position():
    e = compile_error("VAR x : INT; END_VAR\nx := 1 @ 2;")
    assert (e.line, e.col) == (2, 8)


@pytest.mark.parametrize("line2", ["x := T#5parsecs;", "x := 1; (* never closed", "s := 'open;"])
def test_bad_literal_or_unterminated_token(line2):
    e = compile_error("VAR x : TIME; s : STRING; END_VAR\n" + line2)
    assert e.line == 2


@pytest.mark.parametrize("src", [
    "IF TRUE THEN x := 1;",
    "x := (1 + 2;",
    "VAR y : INT END_VAR\nx := 1;",
    "x := 1 x := 2;",
    "CASE x OF 1: x := 2;",
])
def test_malformed_programs_raise(src):
    compile_error("VAR x : INT; END_VAR\n" + src)


def test_semantic_errors_are_all_collected():
    e = compile_error(
        "VAR x : INT; b : BOOL; END_VAR\n"
        "b := x AND b;\n"
        "x := 1;\n"
        "nope := 2;\n"
        "AI1 := 3.0;\n"
    )
    assert [d.line for d in e.errors] == [2, 4, 5]
    assert all(d.program == "bad" for d in e.errors)


def test_parser_recovers_at_statement_boundaries():
    e = compile_error("VAR x : INT; END_VAR\nx := ;\nx := 1;\nx := (2;\n")
    assert [d.line for d in e.errors] == [2, 4]
