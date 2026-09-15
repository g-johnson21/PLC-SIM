import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ProtocolError, SimClient } from './client';
import type { ClientMsg } from './types';
import { showReturnNotice } from '../gc/abortUi';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

type Reply = { ok: true } | { ok: false; code: string; details?: Record<string, unknown> };

async function send(client: SimClient, msg: ClientMsg): Promise<Reply> {
  const outcome = client.request(msg).then(
    (): Reply => ({ ok: true }),
    (e: ProtocolError): Reply => ({ ok: false, code: e.code, details: e.details }),
  );
  await vi.advanceTimersByTimeAsync(0);
  return outcome;
}

async function connected(): Promise<SimClient> {
  const client = new SimClient({ forceMock: true });
  await vi.advanceTimersByTimeAsync(30);
  return client;
}

const SCAN_MS = 100; // the client subscribes at 10 Hz

describe('mock transport: abort lifecycle', () => {
  it('rejects ABORT while the PLC is stopped', async () => {
    const client = await connected();
    expect(await send(client, { type: 'abort' })).toEqual({ ok: false, code: 'rejected', details: undefined });
    expect(await send(client, { type: 'write', values: { 'hmi.abort': true } })).toMatchObject({ ok: false, code: 'rejected' });
    await vi.advanceTimersByTimeAsync(SCAN_MS);
    expect(client.snapshot.state?.abort).toMatchObject({ latched: false, tripped: null, waiting_on: [] });
  });

  it('latches, refuses what the backend refuses, then returns control by itself', async () => {
    const client = await connected();
    await send(client, { type: 'plc.run' });
    await send(client, { type: 'write', values: { 'hmi.bb.lox.enable': true } });
    expect(await send(client, { type: 'abort' })).toEqual({ ok: true });

    await vi.advanceTimersByTimeAsync(SCAN_MS);
    expect(client.snapshot.state?.abort).toMatchObject({ latched: true, waiting_on: [], tripped: { source: 'manual' } });

    const refused: ClientMsg[] = [
      { type: 'write', values: { PB2: true } },
      { type: 'write', values: { 'hmi.bb.fuel.enable': true } },
      { type: 'sequence', action: 'start', name: 'hotfire' },
      { type: 'plc.stop' },
      { type: 'plc.reset' },
      { type: 'program.load', programs: [] },
      { type: 'plc.force', name: 'PB2', value: true },
    ];
    for (const msg of refused) {
      expect(await send(client, msg), msg.type).toMatchObject({ ok: false, code: 'abort_active' });
    }
    expect(await send(client, { type: 'abort.clear' })).toMatchObject({ ok: false, code: 'rejected', details: { waiting_on: [] } });

    const accepted: ClientMsg[] = [
      { type: 'write', values: { 'hmi.bb.lox.setpoint': 904 } },
      { type: 'plc.force', name: 'PT3', value: 0 },
      { type: 'abort.config', thresholds: [] },
    ];
    for (const msg of accepted) {
      expect(await send(client, msg), msg.type).toEqual({ ok: true });
    }

    await vi.advanceTimersByTimeAsync(SCAN_MS);
    const s = client.snapshot.state!;
    expect(s.abort.latched).toBe(false);
    expect(s.hmi.manual_allowed).toBe(true);
    expect(s.hmi.bb.lox).toMatchObject({ enable: false, setpoint: 904 });
    expect(showReturnNotice(s, null)).toBe(true);
    expect(client.snapshot.events.some((e) => e.text.includes('operator in control'))).toBe(true);

    expect(await send(client, { type: 'write', values: { PB2: true } })).toEqual({ ok: true });
    expect(await send(client, { type: 'plc.reset' })).toEqual({ ok: true });
    await vi.advanceTimersByTimeAsync(SCAN_MS);
    expect(client.snapshot.state?.abort.tripped).toBeNull();
  });

  it('acknowledges abort.clear when not latched and refuses writing hmi.abort false', async () => {
    const client = await connected();
    expect(await send(client, { type: 'abort.clear' })).toEqual({ ok: true });
    expect(await send(client, { type: 'write', values: { 'hmi.abort': false } })).toMatchObject({ ok: false, code: 'rejected' });
  });
});
