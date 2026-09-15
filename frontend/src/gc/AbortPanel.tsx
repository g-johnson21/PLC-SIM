import { useState } from 'react';
import type { UseSimResult } from '../protocol/useSim';
import type { AbortInfo } from '../protocol/types';
import { ProtocolError } from '../protocol/client';
import { allAbortOff, isLatched, lockoutReason, showReturnNotice, waitingOn } from './abortUi';

interface Props {
  sim: UseSimResult;
}

function formatTripped(tripped: NonNullable<AbortInfo['tripped']>): string {
  const at = `@ t=${tripped.t.toFixed(2)}s`;
  if (typeof tripped.value === 'number' && typeof tripped.threshold === 'number') {
    return `${tripped.tag} ${tripped.value.toFixed(1)} ${tripped.op ?? 'vs'} ${tripped.threshold.toFixed(1)} (${tripped.label ?? 'threshold'}) ${at}`;
  }
  return `${tripped.tag} — ${tripped.label ?? tripped.source ?? 'trip'} ${at}`;
}

export function AbortPanel({ sim }: Props) {
  const [toast, setToast] = useState<string | null>(null);
  const [dismissedT, setDismissedT] = useState<number | null>(null);
  const state = sim.state;
  const latched = isLatched(state);
  const tripped = state?.abort.tripped ?? null;
  const waiting = waitingOn(state);
  const leftOff = allAbortOff(state);
  const abortBlocked = lockoutReason(state, 'abort');
  const returned = showReturnNotice(state, dismissedT);

  function flash(text: string) {
    setToast(text);
    setTimeout(() => setToast((cur) => (cur === text ? null : cur)), 5000);
  }

  async function doAbort() {
    try {
      await sim.sim.abort();
    } catch (e) {
      flash(e instanceof ProtocolError ? `${e.code} — ${e.message}` : (e as Error).message);
    }
  }

  return (
    <div className={`abort-panel ${latched ? 'latched' : returned ? 'returned' : ''}`}>
      <button className="big-abort-button" onClick={() => void doAbort()} disabled={abortBlocked !== null} title={abortBlocked ?? undefined}>
        ABORT
      </button>
      <div className="abort-details">
        <div className="abort-latch">{latched ? 'ABORT LATCHED' : returned ? 'OPERATOR IN CONTROL' : 'clear'}</div>
        <div className="abort-cause">{tripped ? formatTripped(tripped) : 'no trip recorded'}</div>
        {latched && (
          <div className="abort-waiting">
            <span>Control returns by itself when the abort sequence is over. Waiting on:</span>
            {waiting.length > 0 ? (
              <ul>
                {waiting.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            ) : (
              <span className="abort-note">nothing — returning this scan</span>
            )}
          </div>
        )}
        {returned && tripped && (
          <div className="abort-returned">
            <span>Abort sequence complete: stand safe, operator in control.</span>
            <button className="abort-dismiss" onClick={() => setDismissedT(tripped.t)} title="Dismiss">
              ✕
            </button>
          </div>
        )}
        {!latched && leftOff.length > 0 && (
          <div className="abort-note">Left off since the abort: {leftOff.join(', ')}. PLC Reset re-arms them.</div>
        )}
        {state && abortBlocked && <div className="abort-note">{abortBlocked}</div>}
        {toast && <div className="panel-toast">{toast}</div>}
      </div>
    </div>
  );
}
