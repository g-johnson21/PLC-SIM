import { useState } from 'react';
import type { UseSimResult } from '../protocol/useSim';
import { ProtocolError } from '../protocol/client';
import { allAbortOff, isLatched, lockoutReason } from './abortUi';

interface Props {
  sim: UseSimResult;
}

const RESET_FIELDS: Array<{ key: string; label: string; unit: string }> = [
  { key: 'bottle_psi', label: 'GN2 bottle', unit: 'psi' },
  { key: 'lox_ullage_psi', label: 'LOX ullage', unit: 'psi' },
  { key: 'fuel_ullage_psi', label: 'Fuel ullage', unit: 'psi' },
  { key: 'lox_mass_lbm', label: 'LOX mass', unit: 'lbm' },
  { key: 'fuel_mass_lbm', label: 'Fuel mass', unit: 'lbm' },
  { key: 'muscle_bus_psi', label: 'Muscle bus', unit: 'psi' },
];

export function PlcSimPanel({ sim }: Props) {
  const [toast, setToast] = useState<string | null>(null);
  const [scanHzDraft, setScanHzDraft] = useState('');
  const [speedDraft, setSpeedDraft] = useState('');
  const [realtimeDraft, setRealtimeDraft] = useState<'unchanged' | 'true' | 'false'>('unchanged');
  const [resetDraft, setResetDraft] = useState<Record<string, string>>({});

  const plc = sim.state?.plc;
  const running = Boolean(plc?.running);
  const paused = Boolean(sim.state?.paused);
  const latched = isLatched(sim.state);
  const stopBlocked = sim.state ? lockoutReason(sim.state, 'plcStop') : null;
  const resetBlocked = sim.state ? lockoutReason(sim.state, 'plcReset') : null;
  const leftOff = allAbortOff(sim.state);

  function flash(text: string) {
    setToast(text);
    setTimeout(() => setToast((cur) => (cur === text ? null : cur)), 5000);
  }

  async function run(fn: () => Promise<unknown>) {
    try {
      await fn();
    } catch (e) {
      flash(e instanceof ProtocolError ? `${e.code} — ${e.message}` : (e as Error).message);
    }
  }

  async function applyRate() {
    const opts: { scan_hz?: number; realtime?: boolean; speed?: number } = {};
    if (scanHzDraft.trim()) opts.scan_hz = Number(scanHzDraft);
    if (speedDraft.trim()) opts.speed = Number(speedDraft);
    if (realtimeDraft !== 'unchanged') opts.realtime = realtimeDraft === 'true';
    if (Object.keys(opts).length === 0) return;
    await run(() => sim.sim.simRate(opts));
  }

  async function applyReset() {
    const initial: Record<string, number> = {};
    for (const f of RESET_FIELDS) {
      const v = resetDraft[f.key];
      if (v && v.trim() !== '') initial[f.key] = Number(v);
    }
    await run(() => sim.sim.simReset(Object.keys(initial).length ? initial : undefined));
  }

  return (
    <div className="gc-panel plc-sim-panel">
      <div className="gc-panel-head">PLC / Sim</div>
      <div className="plc-sim-row">
        <button onClick={() => void run(() => sim.sim.run())} disabled={running}>
          Run
        </button>
        <button onClick={() => void run(() => sim.sim.stop())} disabled={!running || stopBlocked !== null} title={stopBlocked ?? undefined}>
          Stop
        </button>
        <button
          onClick={() => void run(() => sim.sim.reset())}
          disabled={resetBlocked !== null}
          title={resetBlocked ?? 'Clears manual commands and re-arms programs an abort switched off'}
        >
          Reset
        </button>
        <button onClick={() => void run(() => sim.sim.clearFaults())}>Clear faults</button>
      </div>
      {latched && (
        <div className="lockout-note">
          Abort latched: PLC Stop and Reset are refused until control returns. Reset plant (below) is the instructor
          reset and clears the latch.
        </div>
      )}
      {!latched && leftOff.length > 0 && <div className="lockout-note">PLC Reset re-arms: {leftOff.join(', ')}</div>}
      <div className="plc-sim-row">
        <button onClick={() => void run(() => sim.sim.simPause())} disabled={paused}>
          Pause sim
        </button>
        <button onClick={() => void run(() => sim.sim.simResume())} disabled={!paused}>
          Resume sim
        </button>
      </div>

      {(plc?.faults.length ?? 0) > 0 && (
        <div className="plc-faults">
          {plc!.faults.map((f, i) => (
            <div key={i} className="plc-fault-row">
              {JSON.stringify(f)}
            </div>
          ))}
        </div>
      )}
      {(plc?.halted.length ?? 0) > 0 && <div className="plc-halted">halted: {plc!.halted.join(', ')}</div>}

      <details className="plc-sim-details">
        <summary>Scan rate / speed</summary>
        <div className="field">
          scan_hz (10-100){' '}
          <input placeholder={String(sim.state?.scan_hz ?? '')} value={scanHzDraft} onChange={(e) => setScanHzDraft(e.target.value)} />
        </div>
        <div className="field">
          speed <input placeholder="1.0" value={speedDraft} onChange={(e) => setSpeedDraft(e.target.value)} />
        </div>
        <div className="field">
          pacing
          <select value={realtimeDraft} onChange={(e) => setRealtimeDraft(e.target.value as typeof realtimeDraft)}>
            <option value="unchanged">unchanged</option>
            <option value="true">realtime</option>
            <option value="false">as fast as possible</option>
          </select>
        </div>
        <button onClick={() => void applyRate()}>Apply</button>
      </details>

      <details className="plc-sim-details">
        <summary>Reset plant (initial conditions)</summary>
        {RESET_FIELDS.map((f) => (
          <div className="field" key={f.key}>
            {f.label} ({f.unit})
            <input
              placeholder="backend default"
              value={resetDraft[f.key] ?? ''}
              onChange={(e) => setResetDraft((d) => ({ ...d, [f.key]: e.target.value }))}
            />
          </div>
        ))}
        <button onClick={() => void applyReset()}>Reset plant</button>
      </details>
      {toast && <div className="panel-toast">{toast}</div>}
    </div>
  );
}
