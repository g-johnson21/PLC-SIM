import { useEffect, useRef } from 'react';
import { EditorState, EditorSelection, type Extension } from '@codemirror/state';
import { EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter } from '@codemirror/view';
import { defaultKeymap, history, historyKeymap, indentWithTab as _unused } from '@codemirror/commands';
import { linter, lintGutter, setDiagnostics, type Diagnostic } from '@codemirror/lint';
import { stLanguage } from './stLanguage';
import { stTheme, stHighlight } from './theme';
import type { CompileErrorEntry } from '../../protocol/types';

void _unused; // not used: Tab must insert two literal spaces, not IEC-style smart indent

function insertTwoSpaces(view: EditorView): boolean {
  view.dispatch(
    view.state.changeByRange((range) => ({
      changes: { from: range.from, to: range.to, insert: '  ' },
      range: EditorSelection.cursor(range.from + 2),
    })),
  );
  return true;
}

function toDiagnostics(state: EditorState, errors: CompileErrorEntry[]): Diagnostic[] {
  const out: Diagnostic[] = [];
  for (const e of errors) {
    if (e.line == null) continue;
    const lineNo = Math.min(Math.max(e.line, 1), state.doc.lines);
    const line = state.doc.line(lineNo);
    const col = e.col != null ? Math.max(e.col - 1, 0) : 0;
    const from = Math.min(line.from + col, line.to);
    const to = Math.min(from + 1, line.to);
    out.push({ from, to: from === to ? Math.min(from + 1, state.doc.length) : to, severity: 'error', message: e.message });
  }
  return out;
}

export interface StEditorProps {
  value: string;
  onChange: (value: string) => void;
  errors?: CompileErrorEntry[];
  readOnly?: boolean;
  onSave?: () => void;
}

export function StEditor({ value, onChange, errors, readOnly, onSave }: StEditorProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  const onSaveRef = useRef(onSave);
  onChangeRef.current = onChange;
  onSaveRef.current = onSave;

  useEffect(() => {
    if (!hostRef.current) return;
    const extensions: Extension[] = [
      lineNumbers(),
      highlightActiveLine(),
      highlightActiveLineGutter(),
      history(),
      stLanguage,
      stHighlight,
      stTheme,
      lintGutter(),
      linter(() => []), // registers the lint field; diagnostics are pushed imperatively below
      keymap.of([
        { key: 'Tab', run: insertTwoSpaces },
        {
          key: 'Mod-s',
          run: () => {
            onSaveRef.current?.();
            return true;
          },
          preventDefault: true,
        },
        ...defaultKeymap,
        ...historyKeymap,
      ]),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) onChangeRef.current(update.state.doc.toString());
      }),
      EditorState.readOnly.of(Boolean(readOnly)),
      EditorView.lineWrapping,
    ];
    const state = EditorState.create({ doc: value, extensions });
    const view = new EditorView({ state, parent: hostRef.current });
    viewRef.current = view;
    return () => view.destroy();
    // Extensions capture readOnly/errors at creation only; both are re-applied below on change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    if (view.state.doc.toString() !== value) {
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value } });
    }
  }, [value]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    view.dispatch(setDiagnostics(view.state, toDiagnostics(view.state, errors ?? [])));
  }, [errors, value]);

  return <div ref={hostRef} style={{ height: '100%', overflow: 'auto' }} />;
}
