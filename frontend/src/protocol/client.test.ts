import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SimClient } from './client';

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  url: string;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  // A real WebSocket.close() never synchronously fires onclose -- it's always a
  // later task. Faking that asynchrony out entirely (never auto-firing) keeps
  // ordering deterministic and matches production behaviour closely enough that
  // tests must explicitly call triggerClose() to simulate a drop.
  close() {}
  triggerOpen() {
    this.onopen?.();
  }
  triggerClose() {
    this.onclose?.();
  }
  sentMessages(): Array<Record<string, unknown>> {
    return this.sent.map((s) => JSON.parse(s));
  }
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeWebSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeWebSocket as unknown as typeof WebSocket);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('SimClient: dev fallback', () => {
  it('falls back to the in-process mock after the first-connect timeout', async () => {
    const client = new SimClient({ endpoint: 'ws://fake/ws', dev: true });
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(client.snapshot.status).toBe('connecting');

    await vi.advanceTimersByTimeAsync(2000); // FIRST_CONNECT_TIMEOUT_MS
    // handleInitialFailure -> connectMock('fallback') + startProbing(), both synchronous
    expect(client.snapshot.mockFallback).toEqual({ endpoint: 'ws://fake/ws', backendReachable: false });
    expect(FakeWebSocket.instances.length).toBeGreaterThanOrEqual(2); // original real attempt + first probe

    await vi.advanceTimersByTimeAsync(30); // the mock's own connect() delay
    expect(client.snapshot.status).toBe('mock');
  });

  it('never falls back to the mock on its own once genuinely connected', async () => {
    const client = new SimClient({ endpoint: 'ws://fake/ws', dev: true });
    FakeWebSocket.instances[0].triggerOpen();
    expect(client.snapshot.status).toBe('connected');
    await vi.advanceTimersByTimeAsync(5000);
    expect(client.snapshot.status).toBe('connected');
    expect(client.snapshot.mockFallback).toBeNull();
  });
});

describe('SimClient: production never falls back', () => {
  it('keeps status connecting/reconnecting and retries the real endpoint forever', async () => {
    const client = new SimClient({ endpoint: 'ws://fake/ws', dev: false });

    await vi.advanceTimersByTimeAsync(2000); // first-attempt timeout
    expect(client.snapshot.status).toBe('reconnecting');
    expect(client.snapshot.mockFallback).toBeNull();

    await vi.advanceTimersByTimeAsync(500); // first backoff step (starts at 500ms)
    expect(FakeWebSocket.instances).toHaveLength(2); // original attempt + one retry, both real
    expect(client.snapshot.status).not.toBe('mock');
    expect(client.snapshot.mockFallback).toBeNull();

    // A retry that opens and later drops is retried again without limit.
    FakeWebSocket.instances.at(-1)!.triggerOpen();
    expect(client.snapshot.status).toBe('connected');
    FakeWebSocket.instances.at(-1)!.triggerClose();
    expect(client.snapshot.status).toBe('reconnecting');
    await vi.advanceTimersByTimeAsync(1000);
    expect(FakeWebSocket.instances).toHaveLength(3);
    expect(client.snapshot.status).not.toBe('mock');
  });

  it('BUG (found by this test, reported not fixed): a retry that is refused outright -- ' +
    'onclose fires without onopen ever having fired, same as a real browser reports ' +
    'connection-refused -- is silently swallowed and no further retry is ever scheduled', async () => {
    const client = new SimClient({ endpoint: 'ws://fake/ws', dev: false });
    await vi.advanceTimersByTimeAsync(2000); // first attempt times out -> reconnecting, 1 retry scheduled
    await vi.advanceTimersByTimeAsync(500); // the retry fires: instance #2 created
    expect(FakeWebSocket.instances).toHaveLength(2);

    // connectReal()'s `settled` guard on ws.onclose is only meant to stop the first
    // attempt's timeout and its onclose from both firing scheduleReconnect(); it is not
    // re-armed for attempt #2+, so `settled` stays false there and this onclose (which
    // never got a matching onopen) is discarded instead of triggering scheduleReconnect().
    FakeWebSocket.instances.at(-1)!.triggerClose();
    expect(client.snapshot.status).toBe('reconnecting'); // still says "reconnecting"...
    await vi.advanceTimersByTimeAsync(60_000); // ...but no third attempt ever comes, at any delay
    expect(FakeWebSocket.instances).toHaveLength(2); // stuck forever, contrary to "keeps reconnecting"
  });

  it('VITE_SIM_MOCK-equivalent forceMock still works in a "production" client', async () => {
    const client = new SimClient({ endpoint: 'ws://fake/ws', dev: false, forceMock: true });
    expect(FakeWebSocket.instances).toHaveLength(0); // mock never touches the WebSocket global
    await vi.advanceTimersByTimeAsync(30);
    expect(client.snapshot.status).toBe('mock');
    expect(client.snapshot.mockFallback).toBeNull(); // forced, not a fallback -- no banner
  });
});

describe('SimClient: backend-reachable banner and switch-back', () => {
  async function givenFallenBackToMock() {
    const client = new SimClient({ endpoint: 'ws://fake/ws', dev: true });
    await vi.advanceTimersByTimeAsync(2000);
    await vi.advanceTimersByTimeAsync(30);
    expect(client.snapshot.status).toBe('mock');
    const probe = FakeWebSocket.instances[1];
    return { client, probe };
  }

  it('marks the backend reachable without leaving the mock (no silent switch)', async () => {
    const { client, probe } = await givenFallenBackToMock();
    probe.triggerOpen();
    expect(client.snapshot.mockFallback).toEqual({ endpoint: 'ws://fake/ws', backendReachable: true });
    expect(client.snapshot.status).toBe('mock'); // still on the mock -- operator must choose to switch
  });

  it('switchToRealBackend tears down the mock, rejects pending requests, and reconnects for real', async () => {
    const { client, probe } = await givenFallenBackToMock();
    probe.triggerOpen();

    const pending = client.request({ type: 'plc.run' });
    const rejection = expect(pending).rejects.toThrow();

    client.switchToRealBackend();
    await rejection;
    expect(client.snapshot.status).toBe('connecting');
    expect(client.snapshot.mockFallback).toBeNull();

    const newSocket = FakeWebSocket.instances.at(-1)!;
    expect(newSocket).not.toBe(probe);
    newSocket.triggerOpen();

    expect(client.snapshot.status).toBe('connected');
    const messages = newSocket.sentMessages();
    expect(messages[0]).toMatchObject({ type: 'hello', client: 'ide', protocol: 1 });
    expect(messages[1]).toMatchObject({ type: 'subscribe' });
  });

  it('a failed switch attempt falls back to the mock again (banner reappears, not silent)', async () => {
    const { client } = await givenFallenBackToMock();
    client.switchToRealBackend();
    // the new real attempt also never answers
    await vi.advanceTimersByTimeAsync(2000);
    await vi.advanceTimersByTimeAsync(30);
    expect(client.snapshot.status).toBe('mock');
    expect(client.snapshot.mockFallback?.backendReachable).toBe(false);
  });
});

describe('SimClient + mock: program.load', () => {
  it('replies with program_list, not a bare ack', async () => {
    const client = new SimClient({ forceMock: true });
    await vi.advanceTimersByTimeAsync(30);

    const programs = [{ name: 'bangbang_lox', language: 'ST' as const, source: 'PROGRAM p END_PROGRAM' }];
    const replyPromise = client.request({ type: 'program.load', programs });
    await vi.advanceTimersByTimeAsync(0);
    const reply = await replyPromise;

    expect(reply).toMatchObject({ type: 'program_list' });
    expect((reply as { programs: unknown[] }).programs).toHaveLength(1);
    expect((reply as { programs: Array<{ name: string }> }).programs[0].name).toBe('bangbang_lox');
  });
});
