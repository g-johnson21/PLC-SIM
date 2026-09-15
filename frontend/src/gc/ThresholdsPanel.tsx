import { useEffect, useState } from 'react';
import type { UseSimResult } from '../protocol/useSim';
import type { AbortThreshold } from '../protocol/types';
import { ProtocolError } from '../protocol/client';
import { isLatched } from './abortUi';

interface Props {
  sim: UseSimResult;
}

const OPS: AbortThreshold['op'][] = ['>', '>=', '<', '<=', '=', '!='];

export function ThresholdsPanel({ sim }: Props) {
  const inputTags = (sim.welcome?.tags ?? []).filter((t) => t.kind === 'analog_in' || t.kind === 'derived');
  const serverThresholds = sim.state?.abort.thresholds ?? [];
  const [draft, setDraft] = useState<AbortThreshold[]>(serverThresholds);
  const [dirty, setDirty] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (!dirty) setDraft(serverThresholds);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sim.state?.abort.thresholds]);

  function update(i: number, patch: Partial<AbortThreshold>) {
    setDirty(true);
    setDraft((rows) => rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  }

  function addRow() {
    setDirty(true);
    setDraft((rows) => [...rows, { tag: inputTags[0]?.tag ?? 'PT0', op: '>', value: 0, enabled: false, label: '' }]);
  }

  function removeRow(i: number) {
    setDirty(true);
    setDraft((rows) => rows.filter((_, idx) => idx !== i));
  }

  async function apply() {
    try {
      await sim.sim.abortConfig(draft);
      setDirty(false);
    } catch (e) {
      setToast(e instanceof ProtocolError ? `${e.code} — ${e.message}` : (e as Error).message);
      setTimeout(() => setToast(null), 5000);
    }
  }

  return (
    <div className="gc-panel thresholds-panel">
      <div className="gc-panel-head">Auto-abort thresholds</div>
      {isLatched(sim.state) && (
        <div className="lockout-note">
          A threshold still tripped holds the latch. If its sensor has failed, untick the row and Apply to release it.
        </div>
      )}
      <table className="thresholds-table">
        <thead>
          <tr>
            <th>tag</th>
            <th>op</th>
            <th>value</th>
            <th>on</th>
            <th>label</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {draft.map((row, i) => (
            <tr key={i}>
              <td>
                <select value={row.tag} onChange={(e) => update(i, { tag: e.target.value })}>
                  {inputTags.map((t) => (
                    <option key={t.tag} value={t.tag}>
                      {t.tag}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <select value={row.op} onChange={(e) => update(i, { op: e.target.value as AbortThreshold['op'] })}>
                  {OPS.map((op) => (
                    <option key={op} value={op}>
                      {op}
                    </option>
                  ))}
                </select>
              </td>
              <td>
                <input
                  type="number"
                  value={row.value}
                  onChange={(e) => update(i, { value: Number(e.target.value) })}
                />
              </td>
              <td>
                <input type="checkbox" checked={row.enabled} onChange={(e) => update(i, { enabled: e.target.checked })} />
              </td>
              <td>
                <input value={row.label} onChange={(e) => update(i, { label: e.target.value })} />
              </td>
              <td>
                <button onClick={() => removeRow(i)}>✕</button>
              </td>
            </tr>
          ))}
          {draft.length === 0 && (
            <tr>
              <td colSpan={6} className="empty">
                No thresholds configured.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <div className="thresholds-actions">
        <button onClick={addRow}>+ row</button>
        <button onClick={() => void apply()} disabled={!dirty}>
          Apply
        </button>
      </div>
      {toast && <div className="panel-toast">{toast}</div>}
    </div>
  );
}
