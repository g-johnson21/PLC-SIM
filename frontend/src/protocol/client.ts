// Typed WebSocket client for docs/protocol.md. Falls back to the in-process mock
// (src/protocol/mock.ts) when VITE_SIM_MOCK=1 (any build), or -- dev builds only --
// when the real socket doesn't open within 2s on the first attempt. A production
// build never falls back silently: it keeps retrying the real endpoint forever.
// See README.md in this folder for the surface task 8 is expected to consume.
import { createStore } from '../lib/store';
import { createMockSocket, type SocketLike } from './mock';
import type {
  AbortThreshold,
  ClientMsg,
  EventMsg,
  Language,
  ProgramSource,
  ServerMsg,
  StateMsg,
  WelcomeMsg,
} from './types';

export type ConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'mock';

/** Present only while `status === 'mock'` because of an automatic dev fallback
 *  (never for a VITE_SIM_MOCK=1 forced mock, which is deliberate, not a fallback). */
export interface MockFallbackInfo {
  endpoint: string;
  backendReachable: boolean;
}

export interface SimSnapshot {
  status: ConnectionStatus;
  welcome: WelcomeMsg | null;
  state: StateMsg | null;
  events: EventMsg[];
  mockFallback: MockFallbackInfo | null;
}

interface Pending {
  resolve: (v: ServerMsg) => void;
  reject: (e: Error) => void;
}

const MAX_EVENTS = 500;
const REQUEST_TIMEOUT_MS = 8000;
const FIRST_CONNECT_TIMEOUT_MS = 2000;
const MAX_BACKOFF_MS = 10000;
// Once the backend is confirmed reachable behind the fallback mock, there is no
// urgency: re-check occasionally in case it drops again before the operator switches.
const REACHABLE_RECHECK_MS = MAX_BACKOFF_MS;

function endpoint(): string {
  return (import.meta.env.VITE_SIM_WS as string | undefined) || 'ws://localhost:8765/ws';
}

function wantsMock(): boolean {
  return import.meta.env.VITE_SIM_MOCK === '1';
}

function isDev(): boolean {
  return Boolean(import.meta.env.DEV);
}

/** Overrides for testing -- the real app always uses the defaults (real env vars). */
export interface SimClientOptions {
  endpoint?: string;
  dev?: boolean;
  forceMock?: boolean;
}

export class ProtocolError extends Error {
  code: string;
  details?: Record<string, unknown>;
  constructor(message: string, code: string, details?: Record<string, unknown>) {
    super(message);
    this.code = code;
    this.details = details;
  }
}

export class SimClient {
  private store = createStore<SimSnapshot>({
    status: 'connecting',
    welcome: null,
    state: null,
    events: [],
    mockFallback: null,
  });
  private socket: SocketLike | null = null;
  private pending = new Map<string, Pending>();
  private nextId = 1;
  private backoffMs = 500;
  private usingMock = false;
  /** Why the mock is active: a deliberate VITE_SIM_MOCK=1, or an automatic dev
   *  fallback after the real endpoint didn't answer. Only 'fallback' probes and banners. */
  private mockReason: 'forced' | 'fallback' | null = null;
  private firstAttemptDone = false;
  private probeSocket: WebSocket | null = null;
  private probeTimer: ReturnType<typeof setTimeout> | null = null;
  private endpointUrl: string;
  private devMode: boolean;

  constructor(opts: SimClientOptions = {}) {
    this.endpointUrl = opts.endpoint ?? endpoint();
    this.devMode = opts.dev ?? isDev();
    if (opts.forceMock ?? wantsMock()) this.connectMock('forced');
    else this.connectReal();
  }

  get snapshot(): SimSnapshot {
    return this.store.getState();
  }

  subscribeSnapshot(cb: () => void): () => void {
    return this.store.subscribe(cb);
  }

  private connectReal() {
    let settled = false;
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.endpointUrl);
    } catch {
      this.handleInitialFailure();
      return;
    }
    this.socket = ws as unknown as SocketLike;

    if (!this.firstAttemptDone) {
      setTimeout(() => {
        if (!settled) {
          settled = true;
          try {
            ws.close();
          } catch {
            /* already closing */
          }
          this.handleInitialFailure();
        }
      }, FIRST_CONNECT_TIMEOUT_MS);
    }

    ws.onopen = () => {
      settled = true;
      this.firstAttemptDone = true;
      this.backoffMs = 500;
      this.usingMock = false;
      this.mockReason = null;
      this.stopProbing();
      this.onOpen();
    };
    ws.onmessage = (ev) => this.onMessage(ev.data);
    ws.onclose = () => {
      if (this.usingMock) return; // this stray real socket is no longer the active transport
      if (!settled) return; // the 2s timer above will handle first-attempt failure
      this.scheduleReconnect();
    };
    ws.onerror = () => {
      /* onclose follows every onerror on WebSocket; nothing to do here */
    };
  }

  /** The real endpoint didn't answer on the very first attempt (this page load, or
   *  since the last explicit switch). Dev keeps the operator working via the mock
   *  while quietly retrying underneath; production just keeps retrying visibly --
   *  it must never hand an operator a mock without them choosing it. */
  private handleInitialFailure() {
    this.firstAttemptDone = true;
    if (this.devMode) {
      this.connectMock('fallback');
      this.startProbing();
    } else {
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect() {
    this.store.setState((s) => ({ ...s, status: 'reconnecting' }));
    this.rejectAllPending('connection lost, reconnecting');
    const delay = this.backoffMs;
    this.backoffMs = Math.min(this.backoffMs * 2, MAX_BACKOFF_MS);
    setTimeout(() => {
      if (!this.usingMock) this.connectReal();
    }, delay);
  }

  private connectMock(reason: 'forced' | 'fallback') {
    this.usingMock = true;
    this.mockReason = reason;
    this.firstAttemptDone = true;
    const mock = createMockSocket();
    this.socket = mock;
    mock.onopen = () => this.onOpen();
    mock.onmessage = (ev) => this.onMessage(ev.data);
    mock.connect();
    this.store.setState((s) => ({
      ...s,
      mockFallback: reason === 'fallback' ? { endpoint: this.endpointUrl, backendReachable: false } : null,
    }));
  }

  /** Background reachability check while on the fallback mock. Never touches the
   *  active mock transport or its pending requests -- it only opens a throwaway
   *  socket to find out whether the real backend would answer now. */
  private startProbing() {
    this.stopProbing();
    const attempt = () => {
      this.probeTimer = null;
      if (!this.usingMock || this.mockReason !== 'fallback') return; // switched away already
      let done = false;
      let probe: WebSocket;
      try {
        probe = new WebSocket(this.endpointUrl);
      } catch {
        this.scheduleNextProbe(false);
        return;
      }
      this.probeSocket = probe;
      const finish = (reachable: boolean) => {
        if (done) return;
        done = true;
        try {
          probe.close();
        } catch {
          /* already closing */
        }
        if (this.probeSocket === probe) this.probeSocket = null;
        if (!this.usingMock || this.mockReason !== 'fallback') return; // switched away while probing
        if (reachable) {
          this.backoffMs = 500;
          this.store.setState((s) => (s.mockFallback ? { ...s, mockFallback: { ...s.mockFallback, backendReachable: true } } : s));
        }
        this.scheduleNextProbe(reachable);
      };
      probe.onopen = () => finish(true);
      probe.onerror = () => finish(false);
      probe.onclose = () => finish(false);
    };
    attempt();
  }

  private scheduleNextProbe(lastWasReachable: boolean) {
    const delay = lastWasReachable ? REACHABLE_RECHECK_MS : this.backoffMs;
    if (!lastWasReachable) this.backoffMs = Math.min(this.backoffMs * 2, MAX_BACKOFF_MS);
    this.probeTimer = setTimeout(() => this.startProbing(), delay);
  }

  private stopProbing() {
    if (this.probeTimer) {
      clearTimeout(this.probeTimer);
      this.probeTimer = null;
    }
    if (this.probeSocket) {
      try {
        this.probeSocket.close();
      } catch {
        /* already closing */
      }
      this.probeSocket = null;
    }
  }

  /** Operator-initiated: tear down the fallback mock and connect for real. Never
   *  invoked automatically -- reachability alone only updates the banner. */
  switchToRealBackend(): void {
    if (!this.usingMock || this.mockReason !== 'fallback') return;
    this.stopProbing();
    const oldSocket = this.socket;
    this.usingMock = false;
    this.mockReason = null;
    this.rejectAllPending('switching to the real backend');
    try {
      oldSocket?.close();
    } catch {
      /* mock has no real connection to close; harmless either way */
    }
    this.backoffMs = 500;
    this.firstAttemptDone = false; // re-arm the first-attempt timeout/fallback for this attempt
    this.store.setState((s) => ({ ...s, status: 'connecting', welcome: null, state: null, events: [], mockFallback: null }));
    this.connectReal();
  }

  private onOpen() {
    this.store.setState((s) => ({ ...s, status: this.usingMock ? 'mock' : 'connected' }));
    this.sendRaw({ type: 'hello', client: 'ide', protocol: 1 });
    this.sendRaw({ type: 'subscribe', rate_hz: 10 });
  }

  private onMessage(data: string) {
    let msg: ServerMsg;
    try {
      msg = JSON.parse(data);
    } catch {
      return;
    }
    if (msg.type === 'welcome') {
      this.store.setState((s) => ({ ...s, welcome: msg }));
      return;
    }
    if (msg.type === 'state') {
      this.store.setState((s) => ({ ...s, state: msg }));
      return;
    }
    if (msg.type === 'event') {
      this.store.setState((s) => ({ ...s, events: [...s.events, msg].slice(-MAX_EVENTS) }));
      return;
    }
    if (msg.type === 'error') {
      const syntheticEvent: EventMsg = {
        type: 'event',
        t: this.snapshot.state?.t ?? 0,
        scan: this.snapshot.state?.scan ?? 0,
        level: 'fault',
        text: `[${msg.code}] ${msg.message}`,
        source: 'sim',
      };
      this.store.setState((s) => ({ ...s, events: [...s.events, syntheticEvent].slice(-MAX_EVENTS) }));
    }
    const id = 'id' in msg ? msg.id : undefined;
    if (id && this.pending.has(id)) {
      const p = this.pending.get(id)!;
      this.pending.delete(id);
      if (msg.type === 'error') p.reject(new ProtocolError(msg.message, msg.code, msg.details));
      else p.resolve(msg);
    }
  }

  private sendRaw(msg: ClientMsg) {
    this.socket?.send(JSON.stringify(msg));
  }

  private rejectAllPending(reason: string) {
    for (const [, p] of this.pending) p.reject(new Error(reason));
    this.pending.clear();
  }

  request<T extends ServerMsg = ServerMsg>(msg: ClientMsg): Promise<T> {
    const id = String(this.nextId++);
    const withId = { ...msg, id };
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as (v: ServerMsg) => void, reject });
      this.sendRaw(withId);
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id);
          reject(new Error(`request timed out: ${msg.type}`));
        }
      }, REQUEST_TIMEOUT_MS);
    });
  }
}

export const simClient = new SimClient();

// Convenience request helpers, all going through the same correlated request().
export const sim = {
  compile: (name: string, language: Language, source: string | Record<string, unknown>) =>
    simClient.request<import('./types').CompileResultMsg>({ type: 'program.compile', name, language, source }),
  // The server replies to program.load with program_list (the freshly-loaded set), not a bare ack.
  load: (programs: ProgramSource[]) =>
    simClient.request<import('./types').ProgramListResultMsg>({ type: 'program.load', programs }),
  programList: () => simClient.request<import('./types').ProgramListResultMsg>({ type: 'program.list' }),
  run: () => simClient.request({ type: 'plc.run' }),
  stop: () => simClient.request({ type: 'plc.stop' }),
  reset: () => simClient.request({ type: 'plc.reset' }),
  clearFaults: () => simClient.request({ type: 'plc.clear_faults' }),
  write: (values: Record<string, number | boolean | string>) => simClient.request({ type: 'write', values }),
  force: (name: string, value: number | boolean) => simClient.request({ type: 'plc.force', name, value }),
  unforce: (name: string) => simClient.request({ type: 'plc.unforce', name }),
  abort: () => simClient.request({ type: 'abort' }),
  abortClear: () => simClient.request({ type: 'abort.clear' }),
  abortConfig: (thresholds: AbortThreshold[]) => simClient.request({ type: 'abort.config', thresholds }),
  sequenceStart: (name: string) => simClient.request({ type: 'sequence', action: 'start', name }),
  sequenceStop: (name: string) => simClient.request({ type: 'sequence', action: 'stop', name }),
  read: (names: string[]) => simClient.request<import('./types').ReadResultMsg>({ type: 'read', names }),
  simReset: (initial?: Record<string, number>) => simClient.request({ type: 'sim.reset', initial }),
  simRate: (opts: { scan_hz?: number; realtime?: boolean; speed?: number }) =>
    simClient.request({ type: 'sim.rate', ...opts }),
  simPause: () => simClient.request({ type: 'sim.pause' }),
  simResume: () => simClient.request({ type: 'sim.resume' }),
};
