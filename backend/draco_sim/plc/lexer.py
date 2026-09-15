from __future__ import annotations

from .errors import CompileError

KEYWORDS = frozenset("""
PROGRAM END_PROGRAM
VAR VAR_GLOBAL VAR_RETAIN VAR_INPUT VAR_OUTPUT VAR_IN_OUT VAR_EXTERNAL VAR_TEMP CONSTANT END_VAR
IF THEN ELSIF ELSE END_IF
CASE OF END_CASE
FOR TO BY DO END_FOR
WHILE END_WHILE
REPEAT UNTIL END_REPEAT
EXIT RETURN
AND OR XOR NOT MOD
TRUE FALSE
""".split())

# longest first
OPERATORS = ("**", "<=", ">=", "<>", ":=", "..",
             "+", "-", "*", "/", "<", ">", "=", "(", ")", ",", ";", ":", ".", "[", "]", "&")

TIME_UNITS = (("ms", 0.001), ("us", 1e-6), ("ns", 1e-9),
              ("d", 86400.0), ("h", 3600.0), ("m", 60.0), ("s", 1.0))


class Token:
    __slots__ = ("kind", "text", "value", "line", "col")

    def __init__(self, kind: str, text: str, value, line: int, col: int) -> None:
        self.kind = kind  # ident kw int real time str op eof
        self.text = text
        self.value = value
        self.line = line
        self.col = col

    @property
    def upper(self) -> str:
        return self.text.upper()

    def __repr__(self) -> str:  # debugging aid
        return f"<{self.kind} {self.text!r} @{self.line}:{self.col}>"


def _is_ident_start(c: str) -> bool:
    return c.isalpha() or c == "_"


def _is_ident(c: str) -> bool:
    return c.isalnum() or c == "_"


def tokenize(src: str, errors: list[CompileError] | None = None) -> list[Token]:
    """Lex ST source. Bad characters are reported and skipped so that a whole
    file's lexical errors surface in one compile."""
    collected: list[CompileError] = [] if errors is None else errors
    toks: list[Token] = []
    i = 0
    line = 1
    line_start = 0
    n = len(src)

    def col_of(pos: int) -> int:
        return pos - line_start + 1

    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            line_start = i
            continue
        if c in " \t\r\f\v":
            i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if c == "(" and i + 1 < n and src[i + 1] == "*":
            depth = 1
            start_line, start_col = line, col_of(i)
            i += 2
            while i < n and depth:
                if src[i] == "(" and i + 1 < n and src[i + 1] == "*":
                    depth += 1
                    i += 2
                elif src[i] == "*" and i + 1 < n and src[i + 1] == ")":
                    depth -= 1
                    i += 2
                else:
                    if src[i] == "\n":
                        line += 1
                        line_start = i + 1
                    i += 1
            if depth:
                collected.append(CompileError("unterminated (* comment", start_line, start_col))
            continue

        start = i
        scol = col_of(i)

        # TIME literal: T# / TIME# (# cannot appear in an identifier, so this is unambiguous)
        up = src[i:i + 5].upper()
        if up.startswith("T#") or up.startswith("TIME#"):
            i += 2 if up.startswith("T#") else 5
            j = i
            while j < n and (_is_ident(src[j]) or src[j] in "._-+"):
                j += 1
            body = src[i:j]
            try:
                value = _parse_time(body)
            except ValueError as exc:
                collected.append(CompileError(str(exc), line, scol))
                value = 0.0
            toks.append(Token("time", src[start:j], value, line, scol))
            i = j
            continue

        if _is_ident_start(c):
            j = i
            while j < n and _is_ident(src[j]):
                j += 1
            text = src[i:j]
            kind = "kw" if text.upper() in KEYWORDS else "ident"
            toks.append(Token(kind, text, text, line, scol))
            i = j
            continue

        if c.isdigit():
            tok, i = _lex_number(src, i, line, scol, collected)
            toks.append(tok)
            continue

        if c == "'":
            j = i + 1
            buf = []
            while j < n and src[j] != "'":
                if src[j] == "$" and j + 1 < n:
                    esc = src[j + 1]
                    buf.append({"$": "$", "'": "'", '"': '"', "L": "\n", "l": "\n",
                                "N": "\n", "n": "\n", "P": "\f", "p": "\f",
                                "R": "\r", "r": "\r", "T": "\t", "t": "\t"}.get(esc, esc))
                    j += 2
                    continue
                if src[j] == "\n":
                    break
                buf.append(src[j])
                j += 1
            if j >= n or src[j] != "'":
                collected.append(CompileError("unterminated string literal", line, scol))
                i = j
                continue
            toks.append(Token("str", src[i:j + 1], "".join(buf), line, scol))
            i = j + 1
            continue

        for op in OPERATORS:
            if src.startswith(op, i):
                toks.append(Token("op", op, op, line, scol))
                i += len(op)
                break
        else:
            collected.append(CompileError(f"unexpected character {c!r}", line, scol))
            i += 1

    toks.append(Token("eof", "", None, line, col_of(i)))
    if errors is None and collected:
        CompileError.raise_all(collected)
    return toks


def _lex_number(src: str, i: int, line: int, scol: int, errors: list[CompileError]):
    n = len(src)
    j = i
    while j < n and (src[j].isdigit() or src[j] == "_"):
        j += 1
    if j < n and src[j] == "#":
        base_text = src[i:j].replace("_", "")
        k = j + 1
        while k < n and (src[k].isalnum() or src[k] == "_"):
            k += 1
        digits = src[j + 1:k].replace("_", "")
        try:
            base = int(base_text)
            if base not in (2, 8, 16):
                raise ValueError
            value = int(digits, base)
        except ValueError:
            errors.append(CompileError(f"invalid based literal {src[i:k]!r}", line, scol))
            value = 0
        return Token("int", src[i:k], value, line, scol), k
    is_real = False
    if j < n and src[j] == "." and not src.startswith("..", j):
        is_real = True
        j += 1
        while j < n and (src[j].isdigit() or src[j] == "_"):
            j += 1
    if j < n and src[j] in "eE":
        k = j + 1
        if k < n and src[k] in "+-":
            k += 1
        if k < n and src[k].isdigit():
            is_real = True
            j = k
            while j < n and src[j].isdigit():
                j += 1
    text = src[i:j].replace("_", "")
    try:
        value = float(text) if is_real else int(text)
    except ValueError:
        errors.append(CompileError(f"invalid numeric literal {text!r}", line, scol))
        value = 0
    return Token("real" if is_real else "int", src[i:j], value, line, scol), j


def parse_time_literal(text: str) -> float:
    """Parse 'T#500ms' / 'TIME#1s500ms' / '2.5s' into seconds."""
    t = text.strip()
    up = t.upper()
    if up.startswith("TIME#"):
        t = t[5:]
    elif up.startswith("T#"):
        t = t[2:]
    return _parse_time(t)


def _parse_time(body: str) -> float:
    s = body.replace("_", "")
    if not s:
        raise ValueError("empty TIME literal")
    sign = 1.0
    if s[0] in "+-":
        sign = -1.0 if s[0] == "-" else 1.0
        s = s[1:]
    total = 0.0
    i = 0
    seen = False
    while i < len(s):
        j = i
        while j < len(s) and (s[j].isdigit() or s[j] == "."):
            j += 1
        if j == i:
            raise ValueError(f"invalid TIME literal 'T#{body}'")
        try:
            num = float(s[i:j])
        except ValueError:
            raise ValueError(f"invalid TIME literal 'T#{body}'") from None
        rest = s[j:]
        for unit, scale in TIME_UNITS:
            if rest.lower().startswith(unit):
                total += num * scale
                i = j + len(unit)
                seen = True
                break
        else:
            raise ValueError(f"invalid TIME unit in 'T#{body}' (use d h m s ms us ns)")
    if not seen:
        raise ValueError(f"invalid TIME literal 'T#{body}'")
    return sign * total
