import { useEffect, useRef, useState } from 'react';
import type { UseSimResult } from '../protocol/useSim';
import { ProtocolError } from '../protocol/client';
import { lockoutReason } from './abortUi';

interface Props {
  sim: UseSimResult;
}

export function SequencePanel({ sim }: Props) {
  const [names, setNames] = useState<string[]>([]);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const seqStartT = useRef<number | null>(null);

  async function refresh() {
    try {
      const result = await sim.sim.programList();
      const sfcNames = result.programs.filter((p) => p.language === 'SFC').map((p) => p.name);
      setNames(sfcNames);
      setSelected((cur) => (cur && sfcNames.includes(cur) ? cur : (sfcNames[0] ?? '')));
    } catch {
      /* connection not ready yet -- the mount effect below retries on status change */
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sim.status]);

  const activeSequence = sim.state?.hmi.active_sequence ?? null;
  useEffect(() => {
    if (activeSequence && seqStartT.current === null) seqStartT.current = sim.state?.t ?? 0;
    if (!activeSequence) seqStartT.current = null;
  }, [activeSequence, sim.state?.t]);

  function flash(text: string) {
    setToast(text);
    setTimeout(() => setToast((cur) => (cur === text ? null : cur)), 4500);
  }

  async function start() {
    if (!selected) return;
    setBusy(true);
    try {
      await sim.sim.sequenceStart(selected);
    } catch (e) {
      flash(e instanceof ProtocolError ? `${e.code} — ${e.message}` : (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    if (!selected) return;
    setBusy(true);
    try {
      await sim.sim.sequenceStop(selected);
    } catch (e) {
      flash(e instanceof ProtocolError ? `${e.code} — ${e.message}` : (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const blocked = sim.state ? lockoutReason(sim.state, 'sequence') : null;
  const liveSfc = activeSequence ? sim.state?.plc.sfc[activeSequence] : undefined;
  const tPlus = activeSequence && seqStartT.current !== null && sim.state ? sim.state.t - seqStartT.current : null;

  return (
    <div className="gc-panel sequence-panel">
      <div className="gc-panel-head">
        Sequence
        <button className="refresh-btn" onClick={() => void refresh()} title="Reload SFC program list">
          ↻
        </button>
      </div>
      <div className="sequence-controls">
        <select value={selected} onChange={(e) => setSelected(e.target.value)} disabled={names.length === 0}>
          {names.length === 0 && <option value="">no SFC programs loaded</option>}
          {names.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
        <button onClick={() => void start()} disabled={!selected || busy || blocked !== null || activeSequence === selected} title={blocked ?? undefined}>
          Start
        </button>
        <button onClick={() => void stop()} disabled={!selected || busy || blocked !== null || activeSequence !== selected} title={blocked ?? undefined}>
          Stop
        </button>
      </div>
      {blocked && <div className="lockout-note">{blocked}</div>}
      <div className="sequence-status">
        <div>
          active: <strong>{activeSequence ?? '—'}</strong>
        </div>
        <div>T+ {tPlus !== null ? tPlus.toFixed(2) : '—'}s</div>
      </div>
      {liveSfc && (
        <div className="sequence-steps">
          <div>steps: {liveSfc.active_steps.join(', ') || '—'}</div>
          {liveSfc.active_steps.map((s) => (
            <div key={s} className="sequence-step-time">
              {s}: {(liveSfc.step_times[s] ?? 0).toFixed(2)}s
            </div>
          ))}
          {liveSfc.aborted && <div className="sequence-aborted">chain aborted</div>}
        </div>
      )}
      {toast && <div className="panel-toast">{toast}</div>}
    </div>
  );
}
