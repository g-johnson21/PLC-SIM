import { useState } from 'react';
import type { UseSimResult } from '../protocol/useSim';
import { ProtocolError } from '../protocol/client';
import { StripChart } from './StripChart';
import { useSeriesBuffer } from './useSeriesBuffer';
import { findTag } from './tagHelpers';
import { abortOff, isLatched, lockoutReason } from './abortUi';

const WINDOW_SEC = 60;

const LOOP_META = {
  lox: { label: 'LOX', feedbackTag: 'PT3', solenoid: 'S1' },
  fuel: { label: 'FUEL', feedbackTag: 'PT13', solenoid: 'S2' },
} as const;

interface Props {
  sim: UseSimResult;
  loop: 'lox' | 'fuel';
}

export function BangBangPanel({ sim, loop }: Props) {
  const meta = LOOP_META[loop];
  const bb = sim.state?.hmi.bb[loop];
  const feedback = sim.state?.inputs[meta.feedbackTag];
  const tag = findTag(sim.welcome?.tags, meta.feedbackTag);
  const domain: [number, number] = tag?.range ?? [0, 1500];
  const latched = isLatched(sim.state);
  const offSinceAbort = abortOff(sim.state, loop);
  // turning a loop off is always accepted; only enabling it is refused
  const enableBlocked = bb && !bb.enable ? lockoutReason(sim.state, 'loopEnable', loop) : null;

  // Local override while the operator is actively editing; cleared on blur so the
  // field then just reflects live state again (no effect needed to resync it).
  const [spOverride, setSpOverride] = useState<string | null>(null);
  const [dbOverride, setDbOverride] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const spDraft = spOverride ?? String(bb?.setpoint ?? '');
  const dbDraft = dbOverride ?? String(bb?.deadband ?? '');

  const points = useSeriesBuffer(sim.state?.t, feedback, WINDOW_SEC);

  function flash(text: string) {
    setToast(text);
    setTimeout(() => setToast((cur) => (cur === text ? null : cur)), 4500);
  }

  async function commit(field: 'setpoint' | 'deadband', raw: string) {
    const value = Number(raw);
    if (Number.isNaN(value)) return;
    try {
      await sim.sim.write({ [`hmi.bb.${loop}.${field}`]: value });
    } catch (e) {
      flash(e instanceof ProtocolError ? `${e.code} — ${e.message}` : (e as Error).message);
    }
  }

  async function toggleEnable() {
    if (!bb) return;
    try {
      await sim.sim.write({ [`hmi.bb.${loop}.enable`]: !bb.enable });
    } catch (e) {
      flash(e instanceof ProtocolError ? `${e.code} — ${e.message}` : (e as Error).message);
    }
  }

  const stateClass = bb ? `bb-state bb-state-${bb.state.toLowerCase()}` : 'bb-state';

  return (
    <div className="bb-panel">
      <div className="bb-panel-head">
        <span className="bb-panel-title">{meta.label} bang-bang</span>
        <span className={stateClass}>{bb?.state ?? '—'}</span>
      </div>
      <div className="bb-feedback">
        <span className="bb-feedback-value">{feedback !== undefined ? feedback.toFixed(1) : '—'}</span>
        <span className="bb-feedback-unit">{tag?.units ?? 'psi'}</span>
        <span className="bb-feedback-tag">{meta.feedbackTag}</span>
      </div>
      <StripChart points={points} nowT={sim.state?.t} windowSec={WINDOW_SEC} domain={domain} setpoint={bb?.setpoint} deadband={bb?.deadband} unit={tag?.units ?? ''} />
      <div className="bb-fields">
        <label className="field">
          setpoint
          <input
            value={spDraft}
            onChange={(e) => setSpOverride(e.target.value)}
            onBlur={() => {
              void commit('setpoint', spDraft);
              setSpOverride(null);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
            }}
          />
        </label>
        <label className="field">
          deadband
          <input
            value={dbDraft}
            onChange={(e) => setDbOverride(e.target.value)}
            onBlur={() => {
              void commit('deadband', dbDraft);
              setDbOverride(null);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
            }}
          />
        </label>
        <button
          className={bb?.enable ? 'bb-enable on' : 'bb-enable'}
          onClick={toggleEnable}
          disabled={!bb || enableBlocked !== null}
          title={enableBlocked ?? undefined}
        >
          {bb?.enable ? 'Enabled' : 'Disabled'}
        </button>
      </div>
      {latched && <div className="lockout-note">Abort latched: the loop stays off. Setpoint and deadband stay editable.</div>}
      {!latched && offSinceAbort.length > 0 && (
        <div className="lockout-note">
          Switched off by the abort ({offSinceAbort.join(', ')}). PLC Reset re-arms it.
        </div>
      )}
      {!latched && bb?.enable && (
        <div className="lockout-note">
          Enabled: the loop owns {meta.solenoid}. Disable it to actuate {meta.solenoid} by hand.
        </div>
      )}
      {toast && <div className="panel-toast">{toast}</div>}
    </div>
  );
}
