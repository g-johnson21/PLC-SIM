import { useEffect, useMemo, useRef, useState } from 'react';
import type { CompileErrorEntry } from '../../protocol/types';
import { nearestIdForPointer } from '../../lib/jsonPointer';
import { historyInit, historyPush, historyRedo, historyUndo, type History } from '../../lib/history';
import type { LdDoc, LeafElement, Rung } from './types';
import { appendToEnd, findNetwork, insertAfter, mapNetwork, newRung, reorderRung, removeNetwork, wrapInParallel } from './model';
import { RungCanvas } from './RungCanvas';
import { Palette } from './Palette';
import { ElementForm } from './ElementForm';
import { VarsEditor } from '../shared/VarsEditor';
import type { ValueLookup } from './model';

interface Props {
  doc: LdDoc;
  onChange: (doc: LdDoc) => void;
  errors: CompileErrorEntry[];
  readOnly: boolean;
  lookup?: ValueLookup;
}

export function LdEditor({ doc, onChange, errors, readOnly, lookup }: Props) {
  const [selected, setSelected] = useState<{ rungId: string; elId: string } | null>(null);
  // `doc` is a controlled prop (the parent re-renders it on every edit and on
  // unrelated ticks alike), so the undo stack is its own state, seeded once from
  // the doc at mount and otherwise driven only by our own pushes -- exactly the
  // past/future bookkeeping this component always did, just as pure functions.
  const [history, setHistory] = useState<History<LdDoc>>(() => historyInit(doc));
  const historyRef = useRef(history);
  historyRef.current = history;

  /** Every internal mutation goes through here so Ctrl+Z/Ctrl+Y have something to undo. */
  function emitChange(next: LdDoc) {
    setHistory((h) => historyPush(h, next));
    onChange(next);
  }

  function undo() {
    const h = historyUndo(historyRef.current);
    if (h === historyRef.current) return; // nothing to undo
    setHistory(h);
    onChange(h.present);
  }

  function redo() {
    const h = historyRedo(historyRef.current);
    if (h === historyRef.current) return; // nothing to redo
    setHistory(h);
    onChange(h.present);
  }

  const errorIds = useMemo(() => {
    const set = new Set<string>();
    for (const e of errors) {
      if (!e.path) continue;
      const id = nearestIdForPointer(doc, e.path);
      if (id) set.add(id);
    }
    return set;
  }, [errors, doc]);

  function updateRung(rungId: string, fn: (r: Rung) => Rung) {
    emitChange({ ...doc, rungs: doc.rungs.map((r) => (r.id === rungId ? fn(r) : r)) });
  }

  function addRung() {
    emitChange({ ...doc, rungs: [...doc.rungs, newRung()] });
  }

  function deleteRung(rungId: string) {
    if (!confirm('Delete this rung?')) return;
    emitChange({ ...doc, rungs: doc.rungs.filter((r) => r.id !== rungId) });
    if (selected?.rungId === rungId) setSelected(null);
  }

  function moveRung(rungId: string, dir: -1 | 1) {
    const rungs = reorderRung(doc.rungs, rungId, dir);
    if (rungs === doc.rungs) return; // boundary: no-op
    emitChange({ ...doc, rungs });
  }

  function insertElement(rungId: string, el: LeafElement) {
    const targetId = selected && selected.rungId === rungId ? selected.elId : '';
    updateRung(rungId, (r) => ({
      ...r,
      logic: targetId ? insertAfter(r.logic, targetId, el) : appendToEnd(r.logic, el),
    }));
    setSelected({ rungId, elId: el.id });
  }

  function deleteSelected() {
    if (!selected?.elId) return;
    updateRung(selected.rungId, (r) => ({ ...r, logic: removeNetwork(r.logic, selected.elId) }));
    setSelected(null);
  }

  function wrapSelected() {
    if (!selected) return;
    updateRung(selected.rungId, (r) => ({ ...r, logic: wrapInParallel(r.logic, selected.elId) }));
  }

  function patchSelected(patch: Partial<LeafElement>) {
    if (!selected) return;
    updateRung(selected.rungId, (r) => ({
      ...r,
      logic: mapNetwork(r.logic, selected.elId, (n) => ({ ...n, ...patch }) as never),
    }));
  }

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (readOnly) return;
      const target = e.target as HTMLElement | null;
      if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
      if (e.key === 'Delete' && selected?.elId) {
        e.preventDefault();
        deleteSelected();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') {
        e.preventDefault();
        redo();
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, readOnly, doc, history]);

  const selectedRung = selected ? doc.rungs.find((r) => r.id === selected.rungId) : undefined;
  const selectedElement =
    selectedRung && selected ? (findNetwork(selectedRung.logic, selected.elId) as LeafElement | undefined) ?? null : null;

  return (
    <div className="ld-editor">
      <div className="ld-main">
        <Palette disabled={readOnly} onInsert={(el) => selected && insertElement(selected.rungId, el)} />
        <div className="rung-list">
          {doc.rungs.map((rung, i) => (
            <div key={rung.id} className={`rung-block${errorIds.has(rung.id) ? ' rung-error' : ''}`}>
              <div className="rung-header">
                <span className="rung-index">Rung {i}</span>
                <input
                  className="rung-comment"
                  placeholder="comment"
                  value={rung.comment ?? ''}
                  disabled={readOnly}
                  onChange={(e) => updateRung(rung.id, (r) => ({ ...r, comment: e.target.value || undefined }))}
                />
                <div className="rung-actions">
                  <button disabled={readOnly} onClick={() => moveRung(rung.id, -1)} title="move up">
                    ↑
                  </button>
                  <button disabled={readOnly} onClick={() => moveRung(rung.id, 1)} title="move down">
                    ↓
                  </button>
                  <button disabled={readOnly} onClick={() => deleteRung(rung.id)} title="delete rung">
                    ✕
                  </button>
                </div>
              </div>
              <div onClick={() => setSelected({ rungId: rung.id, elId: '' })}>
                <RungCanvas
                  logic={rung.logic}
                  selectedId={selected?.rungId === rung.id ? selected.elId : null}
                  errorIds={errorIds}
                  onSelect={(elId) => setSelected({ rungId: rung.id, elId })}
                  lookup={lookup}
                />
              </div>
            </div>
          ))}
          <button className="add-rung" disabled={readOnly} onClick={addRung}>
            + add rung
          </button>
        </div>
      </div>
      <div className="ld-side">
        <div className="side-toolbar">
          <button disabled={readOnly || history.past.length === 0} onClick={undo} title="Ctrl+Z">
            Undo
          </button>
          <button disabled={readOnly || history.future.length === 0} onClick={redo} title="Ctrl+Shift+Z">
            Redo
          </button>
          <button disabled={readOnly || !selected?.elId} onClick={deleteSelected}>
            Delete (Del)
          </button>
          <button disabled={readOnly || !selected?.elId} onClick={wrapSelected}>
            Add parallel branch
          </button>
        </div>
        <ElementForm element={selectedElement} onChange={patchSelected} />
        <VarsEditor vars={doc.vars} readOnly={readOnly} onChange={(vars) => emitChange({ ...doc, vars })} />
      </div>
    </div>
  );
}
