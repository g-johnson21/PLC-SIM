import type { UseSimResult } from '../protocol/useSim';
import { isLatched } from './abortUi';

interface Props {
  sim: UseSimResult;
}

export function StatusStrip({ sim }: Props) {
  const state = sim.state;
  const plc = state?.plc;
  const latched = isLatched(state);

  return (
    <div className="gc-status-strip">
      <span>t={state ? state.t.toFixed(2) : '—'}s</span>
      <span>scan={state?.scan ?? '—'}</span>
      <span className={plc?.running ? 'gc-status-ok' : 'gc-status-dim'}>PLC {plc?.running ? 'RUNNING' : 'STOPPED'}</span>
      <span className={latched ? 'gc-status-bad' : 'gc-status-ok'}>ABORT {latched ? 'LATCHED' : 'clear'}</span>
      <span className={state?.hmi.manual_allowed ? 'gc-status-ok' : 'gc-status-dim'}>
        manual {state?.hmi.manual_allowed ? 'allowed' : 'blocked'}
      </span>
      <span>sequence: {state?.hmi.active_sequence ?? '—'}</span>
      {state && state.nonfinite.length > 0 && <span className="gc-status-bad">non-finite: {state.nonfinite.join(', ')}</span>}
    </div>
  );
}
