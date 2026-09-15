import { HighlightStyle, syntaxHighlighting } from '@codemirror/language';
import { EditorView } from '@codemirror/view';
import { tags as t } from '@lezer/highlight';

// Control-room dark theme: legible on 1366x768 as well as 1920x1080, high
// contrast for keywords/comments since operators skim this under stress.
export const stTheme = EditorView.theme(
  {
    '&': {
      color: '#d7e0e8',
      backgroundColor: '#111820',
      height: '100%',
      fontSize: '13px',
    },
    '.cm-content': { fontFamily: "'Cascadia Code', 'Consolas', monospace", caretColor: '#8fd0ff' },
    '.cm-gutters': { backgroundColor: '#0c1218', color: '#5a6b7a', border: 'none' },
    '.cm-activeLine': { backgroundColor: '#17212b' },
    '.cm-activeLineGutter': { backgroundColor: '#17212b' },
    '.cm-selectionBackground, ::selection': { backgroundColor: '#294a63 !important' },
    '.cm-cursor': { borderLeftColor: '#8fd0ff' },
    '.cm-lintRange-error': {
      backgroundImage: 'none',
      textDecoration: 'underline wavy #ff6b6b',
    },
    '.cm-tooltip-lint': { backgroundColor: '#241417', color: '#ffb4b4', border: '1px solid #6a2a2a' },
  },
  { dark: true },
);

export const stHighlight = syntaxHighlighting(
  HighlightStyle.define([
    { tag: t.keyword, color: '#ff9d5c', fontWeight: 'bold' },
    { tag: t.typeName, color: '#7ec7ff' },
    { tag: t.comment, color: '#6a7f8f', fontStyle: 'italic' },
    { tag: t.number, color: '#b5e07f' },
    { tag: t.string, color: '#e0c47f' },
    { tag: t.atom, color: '#d59bff' },
    { tag: t.operator, color: '#d7e0e8' },
    { tag: t.variableName, color: '#d7e0e8' },
  ]),
);
