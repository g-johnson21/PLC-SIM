// Minimal hand-rolled highlighter for the ST grammar in docs/plc-language.md S4.1.
// Not a full parser -- just enough tokenisation for readable syntax colouring.
import { StreamLanguage, type StringStream } from '@codemirror/language';

// exported for unit testing the tokenizer directly (stLanguage.test.ts)
export interface StState {
  commentDepth: number;
}

const KEYWORDS = new Set([
  'PROGRAM', 'END_PROGRAM', 'VAR', 'VAR_GLOBAL', 'VAR_RETAIN', 'CONSTANT', 'END_VAR',
  'IF', 'THEN', 'ELSIF', 'ELSE', 'END_IF', 'CASE', 'OF', 'END_CASE',
  'FOR', 'TO', 'BY', 'DO', 'END_FOR', 'WHILE', 'END_WHILE', 'REPEAT', 'UNTIL', 'END_REPEAT',
  'EXIT', 'RETURN', 'AND', 'OR', 'XOR', 'NOT', 'MOD',
]);

const TYPES = new Set([
  'BOOL', 'INT', 'DINT', 'REAL', 'LREAL', 'TIME', 'STRING',
  'TON', 'TOF', 'TP', 'CTU', 'CTD', 'CTUD', 'R_TRIG', 'F_TRIG', 'SR', 'RS',
]);

export function token(stream: StringStream, state: StState): string | null {
  if (state.commentDepth > 0) {
    if (stream.match('(*')) {
      state.commentDepth += 1;
      return 'comment';
    }
    if (stream.match('*)')) {
      state.commentDepth -= 1;
      return 'comment';
    }
    stream.next();
    return 'comment';
  }
  if (stream.eatSpace()) return null;
  if (stream.match('(*')) {
    state.commentDepth = 1;
    return 'comment';
  }
  if (stream.match('//')) {
    stream.skipToEnd();
    return 'comment';
  }
  if (stream.match(/^(TIME|T)#-?[0-9A-Za-z_.]*/i)) return 'atom';
  if (stream.match(/^\d+#[0-9A-Za-z_]+/)) return 'number';
  if (stream.match(/^\d+(\.\d+)?([eE][+-]?\d+)?/)) return 'number';
  if (stream.match(/^'([^'$]|\$.)*'/)) return 'string';
  if (stream.match(/^[A-Za-z_][A-Za-z0-9_]*/)) {
    const word = stream.current().toUpperCase();
    if (word === 'TRUE' || word === 'FALSE') return 'atom';
    if (KEYWORDS.has(word)) return 'keyword';
    if (TYPES.has(word)) return 'typeName';
    return 'variableName';
  }
  if (stream.match(/^(:=|<=|>=|<>|\*\*|[-+*/<>=&.,;()])/)) return 'operator';
  stream.next();
  return null;
}

export const stLanguage = StreamLanguage.define<StState>({
  startState: () => ({ commentDepth: 0 }),
  token,
  languageData: {
    commentTokens: { line: '//', block: { open: '(*', close: '*)' } },
  },
});
