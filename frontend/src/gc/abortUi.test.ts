import { describe, expect, it } from 'vitest';
import type { PanelAction } from './abortUi';
import { abortOff, allAbortOff, isLatched, lockoutReason, showReturnNotice, waitingOn } from './abortUi';
import type { StateMsg } from '../protocol/types';

type Overrides = {
  running?: boolean;
  latched?: boolean;
  waiting_on?: string[];
  tripped?: StateMsg['abort']['tripped'];
  active_sequence?: string | null;
  manual_allowed?: boolean;
  loxOff?: string[];
  fuelOff?: string[];
};

function state(o: Overrides = {}): StateMsg {
  const loop = { setpoint: 900, deadband: 15, enable: false, state: 'OFF' as const };
  return {
    type: 'state',
    t: 10,
    scan: 500,
    scan_hz: 50,
    paused: false,
    inputs: {},
    outputs: {},
    plc: { running: o.running ?? true, abort_active: o.latched ?? false, faults: [], halted: [], sfc: {}, globals: {}, forced: {} },
    hmi: {
      abort: false,
      bb: { lox: { ...loop, abort_off: o.loxOff ?? [] }, fuel: { ...loop, abort_off: o.fuelOff ?? [] } },
      manual_allowed: o.manual_allowed ?? !(o.latched ?? false),
      active_sequence: o.active_sequence ?? null,
    },
    abort: { thresholds: [], tripped: o.tripped ?? null, latched: o.latched ?? false, waiting_on: o.waiting_on ?? [] },
    nonfinite: [],
  };
}

const manualTrip = { tag: 'hmi.abort', value: true, threshold: null, t: 4.2, source: 'manual' as const };
const LATCH_REFUSED: PanelAction[] = ['valve', 'sequence', 'plcStop', 'plcReset', 'programLoad', 'forceOutput', 'loopEnable'];

describe('abort lockouts (D12/D14)', () => {
  it('ABORT is unavailable while the PLC is stopped and available while it runs, latched or not', () => {
    expect(lockoutReason(state({ running: false }), 'abort')).toMatch(/PLC stopped/);
    expect(lockoutReason(state(), 'abort')).toBeNull();
    expect(lockoutReason(state({ latched: true, tripped: manualTrip }), 'abort')).toBeNull();
  });

  it('locks out every action the backend refuses while latched', () => {
    const s = state({ latched: true, tripped: manualTrip });
    for (const action of LATCH_REFUSED) {
      expect(lockoutReason(s, action, 'lox'), action).toMatch(/abort latched/);
    }
  });

  it('accepts the same actions once control has returned', () => {
    const s = state({ tripped: manualTrip });
    for (const action of LATCH_REFUSED) {
      expect(lockoutReason(s, action, 'lox'), action).toBeNull();
    }
  });

  it('reports no connection before the first state', () => {
    expect(lockoutReason(null, 'abort')).toBe('no connection');
    expect(lockoutReason(undefined, 'valve')).toBe('no connection');
  });

  it('keeps a loop an abort switched off locked until reset, and only that loop', () => {
    const s = state({ tripped: manualTrip, loxOff: ['bangbang_lox'] });
    expect(lockoutReason(s, 'loopEnable', 'lox')).toMatch(/bangbang_lox.*PLC reset re-arms/);
    expect(lockoutReason(s, 'loopEnable', 'fuel')).toBeNull();
    expect(abortOff(s, 'lox')).toEqual(['bangbang_lox']);
  });

  it('lists each switched-off program once across both loops', () => {
    const s = state({ loxOff: ['regulation', 'bangbang_lox'], fuelOff: ['regulation'] });
    expect(allAbortOff(s)).toEqual(['regulation', 'bangbang_lox']);
  });

  it('keeps the pre-existing manual valve rules outside an abort', () => {
    expect(lockoutReason(state({ active_sequence: 'hotfire' }), 'valve')).toMatch(/hotfire/);
    expect(lockoutReason(state({ running: false }), 'valve')).toBe('PLC stopped');
    expect(lockoutReason(state({ manual_allowed: false }), 'valve')).toMatch(/manual/);
  });
});

describe('abort state display', () => {
  it('shows waiting_on only while latched', () => {
    const reasons = ['hotfire at ABORT', 'PT1 > 100 still tripped'];
    expect(waitingOn(state({ latched: true, waiting_on: reasons }))).toEqual(reasons);
    expect(waitingOn(state({ waiting_on: reasons }))).toEqual([]);
    expect(isLatched(state({ latched: true }))).toBe(true);
    expect(isLatched(null)).toBe(false);
  });

  it('announces the return of control until dismissed, even if the latch was never seen', () => {
    expect(showReturnNotice(state(), null)).toBe(false);
    expect(showReturnNotice(state({ latched: true, tripped: manualTrip }), null)).toBe(false);
    expect(showReturnNotice(state({ tripped: manualTrip }), null)).toBe(true);
    expect(showReturnNotice(state({ tripped: manualTrip }), 4.2)).toBe(false);
    expect(showReturnNotice(state({ tripped: { ...manualTrip, t: 9.0 } }), 4.2)).toBe(true);
  });
});
