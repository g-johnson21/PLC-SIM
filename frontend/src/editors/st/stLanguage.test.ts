import { StringStream } from '@codemirror/language';
import { describe, expect, it } from 'vitest';
import { token, type StState } from './stLanguage';

interface Tok {
  text: string;
  style: string | null;
}

/** Drives `token()` exactly like CodeMirror's own StreamLanguage runner does:
 *  set stream.start, call token(), read the consumed text back out. */
function tokenizeLine(line: string, state: StState = { commentDepth: 0 }): Tok[] {
  const stream = new StringStream(line, 2, 2);
  const toks: Tok[] = [];
  let guard = 0;
  while (!stream.eol()) {
    stream.start = stream.pos;
    const style = token(stream, state);
    const text = stream.string.slice(stream.start, stream.pos);
    if (text.length === 0) {
      // token() must always consume at least one char (see the `stream.next()` fallback);
      // a stall here would hang the real editor too, so fail loudly instead of looping.
      throw new Error(`token() did not advance past position ${stream.pos} in ${JSON.stringify(line)}`);
    }
    toks.push({ text, style });
    guard += 1;
    if (guard > 10_000) throw new Error('tokenizer runaway');
  }
  return toks;
}

/** Only the styled tokens (drops whitespace, which reports style `null`). */
function styled(line: string, state?: StState): Tok[] {
  return tokenizeLine(line, state).filter((t) => t.style !== null);
}

describe('ST highlighter: keywords', () => {
  it('tags IEC keywords, case-insensitively, distinct from identifiers', () => {
    expect(styled('IF x THEN y END_IF')).toEqual([
      { text: 'IF', style: 'keyword' },
      { text: 'x', style: 'variableName' },
      { text: 'THEN', style: 'keyword' },
      { text: 'y', style: 'variableName' },
      { text: 'END_IF', style: 'keyword' },
    ]);
  });

  it('is case-insensitive per the language spec', () => {
    expect(styled('if then end_if')).toEqual([
      { text: 'if', style: 'keyword' },
      { text: 'then', style: 'keyword' },
      { text: 'end_if', style: 'keyword' },
    ]);
  });

  it('tags declared types distinctly from control keywords', () => {
    // NOTE: a bare ':' (the var_decl separator, e.g. "t1 : TON") is not in the
    // operator character class in stLanguage.ts and falls through unstyled --
    // found by this test, reported rather than silently patched here.
    expect(styled('VAR t1 : TON')).toEqual([
      { text: 'VAR', style: 'keyword' },
      { text: 't1', style: 'variableName' },
      { text: 'TON', style: 'typeName' },
    ]);
  });

  it('tags TRUE/FALSE as literals (atom), not as ordinary keywords or identifiers', () => {
    expect(styled('S1 := TRUE')).toEqual([
      { text: 'S1', style: 'variableName' },
      { text: ':=', style: 'operator' },
      { text: 'TRUE', style: 'atom' },
    ]);
  });
});

describe('ST highlighter: comments', () => {
  it('tags a // line comment as one span to the end of the line', () => {
    expect(styled('// LOX tank bang-bang')).toEqual([{ text: '// LOX tank bang-bang', style: 'comment' }]);
  });

  it('a // comment does not swallow a following line (state does not leak)', () => {
    const state: StState = { commentDepth: 0 };
    styled('S1 := TRUE; // comment', state);
    expect(styled('IF x THEN', state)).toEqual([
      { text: 'IF', style: 'keyword' },
      { text: 'x', style: 'variableName' },
      { text: 'THEN', style: 'keyword' },
    ]);
  });

  it('tags every character of a (* *) block comment as comment', () => {
    const toks = tokenizeLine('(* hi *)');
    expect(toks.every((t) => t.style === 'comment')).toBe(true);
  });

  it('resumes normal tokenising once a block comment closes', () => {
    const state: StState = { commentDepth: 0 };
    tokenizeLine('(* note *)', state);
    expect(state.commentDepth).toBe(0);
    expect(styled('THEN', state)).toEqual([{ text: 'THEN', style: 'keyword' }]);
  });

  it('nests (* *) comments: an inner close does not end the outer comment', () => {
    const state: StState = { commentDepth: 0 };
    // "(* outer (* inner *) still outer *)"
    tokenizeLine('(* outer (* inner *) still outer', state);
    expect(state.commentDepth).toBe(1); // still inside the outer comment
    const toks = tokenizeLine('(* outer (* inner *) still outer', { commentDepth: 0 });
    expect(toks.every((t) => t.style === 'comment')).toBe(true);
  });
});

describe('ST highlighter: time literals', () => {
  it.each(['T#500ms', 'T#1s500ms', 'T#2.5s', 'T#-5s', 'TIME#1s'])('tags %s as one atom token', (literal) => {
    expect(styled(literal)).toEqual([{ text: literal, style: 'atom' }]);
  });

  it('does not confuse a TIME literal with a plain identifier starting with T', () => {
    expect(styled('T#1s')).toEqual([{ text: 'T#1s', style: 'atom' }]);
    expect(styled('T1')).toEqual([{ text: 'T1', style: 'variableName' }]);
  });
});

describe('ST highlighter: numbers', () => {
  it.each(['42', '3.14', '0', '2#1010', '16#FF'])('tags %s as one number token', (literal) => {
    expect(styled(literal)).toEqual([{ text: literal, style: 'number' }]);
  });

  it('tags a based-integer prefix distinctly from division', () => {
    expect(styled('16#FF')).toEqual([{ text: '16#FF', style: 'number' }]);
  });
});

describe('ST highlighter: operators', () => {
  it.each([':=', '<=', '>=', '<>', '**'])('tags the multi-char operator %s as one token', (op) => {
    expect(styled(op)).toEqual([{ text: op, style: 'operator' }]);
  });
});
