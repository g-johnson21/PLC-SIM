// Abort lifecycle and manual-control lockouts as the panel sees them (docs/protocol.md, D12/D14/D17).
// Every lockout here mirrors a refusal the backend makes; the backend stays the authority.
import type { StateMsg } from '../protocol/types';

export type Loop = 'lox' | 'fuel';

/** Each bang-bang loop's solenoid (the backend's SimConfig.bb_globals). An enabled loop owns it (D17). */
export const LOOP_SOLENOID: Record<Loop, string> = { lox: 'S1', fuel: 'S2' };

export type PanelAction =
  | 'abort'
  | 'valve'
  | 'sequence'
  | 'plcStop'
  | 'plcReset'
  | 'programLoad'
  | 'forceOutput'
  | 'loopEnable';

const LATCHED_REASON: Record<Exclude<PanelAction, 'abort'>, string> = {
  valve: 'abort latched: the abort sequence owns every output',
  sequence: 'abort latched: sequences cannot start or stop until control returns',
  plcStop: 'abort latched: the PLC cannot stop until the abort sequence is over',
  plcReset: 'abort latched: the PLC cannot reset until the abort sequence is over',
  programLoad: 'abort latched: programs cannot load until the abort sequence is over',
  forceOutput: 'abort latched: output forces are refused',
  loopEnable: 'abort latched: bang-bang loops stay off',
};

export function isLatched(state: StateMsg | null | undefined): boolean {
  return Boolean(state?.abort.latched);
}

export function waitingOn(state: StateMsg | null | undefined): string[] {
  return state?.abort.latched ? (state.abort.waiting_on ?? []) : [];
}

export function abortOff(state: StateMsg | null | undefined, loop: Loop): string[] {
  return state?.hmi.bb[loop]?.abort_off ?? [];
}

/** Programs left off by an abort across both loops, deduplicated. */
export function allAbortOff(state: StateMsg | null | undefined): string[] {
  return [...new Set([...abortOff(state, 'lox'), ...abortOff(state, 'fuel')])];
}

/** Why the backend would refuse this action right now, or null when it would accept it. */
export function lockoutReason(
  state: StateMsg | null | undefined,
  action: PanelAction,
  loop?: Loop,
  tag?: string,
): string | null {
  if (!state) return 'no connection';
  if (action === 'abort') {
    return state.plc.running ? null : 'PLC stopped: every output is already fail-safe, nothing to abort';
  }
  if (isLatched(state)) return LATCHED_REASON[action];
  if (action === 'loopEnable' && loop) {
    const off = abortOff(state, loop);
    if (off.length) return `${off.join(', ')} off since the abort: PLC reset re-arms it`;
  }
  if (action === 'valve') {
    if (state.hmi.active_sequence) return `sequence "${state.hmi.active_sequence}" active`;
    if (!state.plc.running) return 'PLC stopped';
    if (!state.hmi.manual_allowed) return 'manual control unavailable';
    const owner = (Object.keys(LOOP_SOLENOID) as Loop[]).find((l) => LOOP_SOLENOID[l] === tag);
    if (owner && state.hmi.bb[owner]?.enable) {
      return `${owner.toUpperCase()} bang-bang loop enabled: disable it to actuate ${tag} by hand`;
    }
  }
  return null;
}

/** The last abort is over and control is back with the operator. Keyed on `tripped`, which
 * survives the return until plc.reset or sim.reset, so a latch that dropped between two state
 * updates is still reported. `dismissedT` is the trip time the operator acknowledged. */
export function showReturnNotice(state: StateMsg | null | undefined, dismissedT: number | null): boolean {
  const tripped = state?.abort.tripped;
  return Boolean(tripped) && !isLatched(state) && tripped!.t !== dismissedT;
}
