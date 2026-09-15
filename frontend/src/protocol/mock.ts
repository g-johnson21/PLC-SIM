// Dev-only in-process transport speaking the same message shapes as the real
// WebSocket server (docs/protocol.md). No physics, no invented sensor values:
// inputs sit at 0, outputs sit at their normal (de-energized) functional state,
// and everything else is only what the operator writes through the protocol.
import { DRACO_TAGS } from './tags.generated';
import { EXAMPLES } from './examples.generated';
import type {
  AbortInfo,
  AbortThreshold,
  ClientMsg,
  ErrorCode,
  EventLevel,
  HmiState,
  ServerMsg,
  TagEntry,
} from './types';

export interface SocketLike {
  send(data: string): void;
  close(): void;
  onopen: (() => void) | null;
  onmessage: ((ev: { data: string }) => void) | null;
  onclose: (() => void) | null;
  onerror: ((ev: unknown) => void) | null;
}

const NOTICE =
  "Programming environment is a custom IEC 61131-3-style language, NOT the cRIO-9047's native LabVIEW FPGA/RT environment.";

const STOPPED_ABORT =
  'the PLC is stopped: every output is already at its fail-safe state, so there is nothing to abort';

// each bang-bang loop's solenoid, as the backend's SimConfig.bb_globals maps it; an enabled loop owns it (D17)
const LOOP_SOLENOID = { lox: 'S1', fuel: 'S2' } as const;

function tagEntries(): TagEntry[] {
  return DRACO_TAGS.map((t) => ({
    tag: t.name,
    kind: t.kind,
    signal: t.signal,
    units: t.units,
    normal_state: t.normalState,
    description: t.description,
  }));
}

function err(id: string | undefined, code: ErrorCode, message: string, details?: Record<string, unknown>): ServerMsg {
  return details ? { type: 'error', id, code, message, details } : { type: 'error', id, code, message };
}

class MockSim {
  private inputs: Record<string, number> = {};
  private outputs: Record<string, boolean> = {};
  private globals: Record<string, number | boolean | string> = {};
  private forced: Record<string, number | boolean | string> = {};
  private manualOutputs: Record<string, boolean> = {};
  private hmi: HmiState = {
    abort: false,
    bb: {
      // the mock compiles nothing, so it cannot tell which program drives a loop: abort_off stays empty
      lox: { setpoint: 0, deadband: 0, enable: false, state: 'OFF', abort_off: [] },
      fuel: { setpoint: 0, deadband: 0, enable: false, state: 'OFF', abort_off: [] },
    },
    manual_allowed: true,
    active_sequence: null,
  };
  private thresholds: AbortThreshold[] = [];
  private running = false;
  private latched = false;
  private latchScan = 0;
  private tripped: AbortInfo['tripped'] = null;
  private abortDisabled: string[] = [];
  private t = 0;
  private scan = 0;
  private rateHz = 10;
  private timer: ReturnType<typeof setInterval> | null = null;
  private programs: Array<{ name: string; language: string; source: unknown }> = [];
  private emit: (msg: ServerMsg) => void;

  constructor(emit: (msg: ServerMsg) => void) {
    this.emit = emit;
    for (const tag of DRACO_TAGS) {
      if (tag.direction === 'in') this.inputs[tag.name] = 0;
      else this.outputs[tag.name] = tag.normalState === 'NO';
    }
  }

  private event(level: EventLevel, text: string, source: 'hmi' | 'plc' | 'sim' = 'sim') {
    this.emit({ type: 'event', t: this.t, scan: this.scan, level, text, source });
  }

  private snapshotOutputs(): Record<string, boolean> {
    const out = { ...this.outputs, ...this.manualOutputs };
    for (const [name, value] of Object.entries(this.forced)) {
      if (name in out) out[name] = Boolean(value);
    }
    return out;
  }

  private snapshotInputs(): Record<string, number> {
    const out = { ...this.inputs };
    for (const [name, value] of Object.entries(this.forced)) {
      if (name in out) out[name] = Number(value);
    }
    return out;
  }

  private enabled(): Record<string, boolean> {
    return Object.fromEntries(this.programs.map((p) => [p.name, !this.abortDisabled.includes(p.name)]));
  }

  startTicking(rateHz: number) {
    this.rateHz = rateHz;
    if (this.timer) clearInterval(this.timer);
    const dt = 1 / this.rateHz;
    this.timer = setInterval(() => {
      this.t += dt;
      this.scan += 1;
      // no abort chains and no live thresholds here, so control returns on the scan after the
      // latch, as the real server does with no chart loaded
      if (this.latched && this.scan > this.latchScan + 1) this.returnControl();
      this.emit({
        type: 'state',
        t: this.t,
        scan: this.scan,
        scan_hz: this.rateHz,
        paused: false,
        inputs: this.snapshotInputs(),
        outputs: this.snapshotOutputs(),
        plc: {
          running: this.running,
          abort_active: this.latched,
          faults: [],
          halted: [],
          enabled: this.enabled(),
          sfc: {},
          globals: this.globals,
          forced: this.forced,
        },
        hmi: this.hmi,
        abort: { thresholds: this.thresholds, tripped: this.tripped, latched: this.latched, waiting_on: [] },
        nonfinite: [],
      });
    }, Math.max(1000 / this.rateHz, 20));
  }

  private checkWrite(id: string | undefined, values: Record<string, unknown>): ServerMsg | null {
    for (const [name, value] of Object.entries(values)) {
      if (name in this.outputs && this.latched) {
        return err(id, 'abort_active', `${name}: the abort owns every output until control returns`, { name });
      }
      if (name in this.outputs && !this.running) {
        return err(id, 'rejected', `${name}: the PLC is stopped and outputs are held at their safe state`, { name });
      }
      for (const loop of ['lox', 'fuel'] as const) {
        if (LOOP_SOLENOID[loop] !== name) continue;
        const key = `hmi.bb.${loop}.enable`;
        const enabled = key in values ? Boolean(values[key]) : this.hmi.bb[loop].enable;
        if (enabled) {
          return err(id, 'rejected', `${name}: the ${loop} bang-bang loop is enabled and owns it; disable the loop to actuate ${name} by hand`, { name, loop });
        }
      }
      if (name === 'hmi.abort') {
        if (!value) {
          return err(id, 'rejected', 'hmi.abort cannot be written false; an abort ends by itself when the abort sequence completes', { name });
        }
        if (!this.running) return err(id, 'rejected', STOPPED_ABORT);
      }
      if (/^hmi\.bb\.(lox|fuel)\.enable$/.test(name) && value && this.latched) {
        return err(id, 'abort_active', `${name}: bang-bang loops stay off while an abort is latched`, { name });
      }
    }
    return null;
  }

  private refuseWhileLatched(id: string | undefined, what: string): ServerMsg | null {
    return this.latched ? err(id, 'abort_active', `${what} is refused while an abort is latched`, { waiting_on: [] }) : null;
  }

  handle(msg: ClientMsg): ServerMsg | null {
    switch (msg.type) {
      case 'hello':
        return {
          type: 'welcome',
          protocol: 1,
          sim_version: 'mock-dev',
          tags: tagEntries(),
          programs: this.programs as never,
          examples: EXAMPLES,
          notice: NOTICE,
        };
      case 'subscribe':
        this.startTicking(msg.rate_hz ?? 10);
        return { type: 'ack', id: msg.id };
      case 'unsubscribe':
        if (this.timer) clearInterval(this.timer);
        this.timer = null;
        return { type: 'ack', id: msg.id };
      case 'read': {
        const values: Record<string, unknown> = {};
        for (const name of msg.names) {
          if (name in this.inputs) values[name] = this.inputs[name];
          else if (name in this.outputs) values[name] = this.snapshotOutputs()[name];
          else if (name.startsWith('plc.globals.')) values[name] = this.globals[name.slice(12)];
          else if (name === 'abort.latched') values[name] = this.latched;
          else if (name === 'abort.waiting_on') values[name] = [];
          else values[name] = null;
        }
        return { type: 'read_result', id: msg.id, values };
      }
      case 'write': {
        const refusal = this.checkWrite(msg.id, msg.values);
        if (refusal) return refusal;
        for (const [name, value] of Object.entries(msg.values)) {
          if (name === 'hmi.abort') {
            this.latch();
          } else if (name.startsWith('plc.globals.')) {
            this.globals[name.slice(12)] = value;
          } else if (name.startsWith('hmi.bb.lox.')) {
            this.setBb('lox', name.slice(11), value);
          } else if (name.startsWith('hmi.bb.fuel.')) {
            this.setBb('fuel', name.slice(12), value);
          } else if (name in this.outputs) {
            this.manualOutputs[name] = Boolean(value);
            this.event('command', `${name} -> ${value ? 'OPEN' : 'CLOSED'}`, 'hmi');
          } else if (name in this.inputs) {
            this.inputs[name] = Number(value);
          }
        }
        return { type: 'ack', id: msg.id };
      }
      case 'abort':
        if (!this.running) return err(msg.id, 'rejected', STOPPED_ABORT);
        this.latch();
        return { type: 'ack', id: msg.id };
      case 'abort.clear':
        if (this.latched) {
          return err(msg.id, 'rejected', 'an abort ends by itself when the abort sequence completes', { waiting_on: [] });
        }
        return { type: 'ack', id: msg.id };
      case 'abort.config':
        this.thresholds = msg.thresholds;
        return { type: 'ack', id: msg.id };
      case 'program.compile':
        // The mock cannot really compile -- it always reports success.
        return { type: 'compile_result', id: msg.id, ok: true, errors: [], variables: [] };
      case 'program.load':
        if (this.latched) return this.refuseWhileLatched(msg.id, 'program.load');
        this.programs = msg.programs;
        this.abortDisabled = [];
        this.event('info', `loaded ${msg.programs.length} program(s)`, 'plc');
        return {
          type: 'program_list',
          id: msg.id,
          programs: this.programs.map((p) => ({ ...p, compiled_ok: true, running: false } as never)),
        };
      case 'program.list':
        return {
          type: 'program_list',
          id: msg.id,
          programs: this.programs.map(
            (p) => ({ ...p, compiled_ok: true, running: this.running && !this.abortDisabled.includes(p.name) } as never),
          ),
        };
      case 'plc.run':
        this.running = true;
        this.event('command', 'PLC RUN', 'hmi');
        return { type: 'ack', id: msg.id };
      case 'plc.stop': {
        if (this.latched) return this.refuseWhileLatched(msg.id, 'plc.stop');
        this.running = false;
        // D17: leave nothing behind that could move a valve on the next plc.run
        this.manualOutputs = {};
        for (const name of Object.keys(this.forced)) {
          if (name in this.outputs) delete this.forced[name];
        }
        const { lox, fuel } = this.hmi.bb;
        this.hmi = { ...this.hmi, active_sequence: null, bb: { lox: { ...lox, enable: false }, fuel: { ...fuel, enable: false } } };
        this.event('command', 'PLC STOP', 'hmi');
        return { type: 'ack', id: msg.id };
      }
      case 'plc.reset':
        if (this.latched) return this.refuseWhileLatched(msg.id, 'plc.reset');
        this.manualOutputs = {};
        this.tripped = null;
        this.abortDisabled = [];
        this.event('command', 'PLC RESET', 'hmi');
        return { type: 'ack', id: msg.id };
      case 'plc.clear_faults':
        return { type: 'ack', id: msg.id };
      case 'plc.force':
        if (msg.name in this.outputs && this.latched) return this.refuseWhileLatched(msg.id, `forcing ${msg.name}`);
        this.forced[msg.name] = msg.value;
        return { type: 'ack', id: msg.id };
      case 'plc.unforce':
        delete this.forced[msg.name];
        return { type: 'ack', id: msg.id };
      case 'sequence':
        if (this.latched) return this.refuseWhileLatched(msg.id, `sequence ${msg.action}`);
        this.hmi = { ...this.hmi, active_sequence: msg.action === 'start' ? msg.name : null };
        this.event('sequence', `${msg.action} ${msg.name}`, 'hmi');
        return { type: 'ack', id: msg.id };
      case 'sim.reset':
        this.t = 0;
        this.scan = 0;
        this.manualOutputs = {};
        this.latched = false;
        this.tripped = null;
        this.abortDisabled = [];
        this.hmi = { ...this.hmi, manual_allowed: true };
        return { type: 'ack', id: msg.id };
      case 'sim.rate':
      case 'sim.pause':
      case 'sim.resume':
        return { type: 'ack', id: msg.id };
      default:
        return err((msg as { id?: string }).id, 'bad_request', `unhandled message type`);
    }
  }

  private setBb(loop: 'lox' | 'fuel', field: string, value: unknown) {
    const current = this.hmi.bb[loop];
    this.hmi = { ...this.hmi, bb: { ...this.hmi.bb, [loop]: { ...current, [field]: value } } };
    const solenoid = LOOP_SOLENOID[loop];
    if (field === 'enable' && value && solenoid in this.manualOutputs) {
      delete this.manualOutputs[solenoid];
      this.event('warn', `manual command released to the ${loop} bang-bang loop: ${solenoid}`, 'hmi');
    }
  }

  private latch() {
    // a request made while latched is already being served by the running abort
    if (this.latched) return;
    this.latched = true;
    this.latchScan = this.scan;
    this.tripped = { tag: 'hmi.abort', value: true, threshold: null, t: this.t, source: 'manual' };
    this.manualOutputs = {};
    for (const name of Object.keys(this.forced)) {
      if (name in this.outputs) delete this.forced[name];
    }
    // without compiling, every non-SFC program counts as an output writer (D10)
    this.abortDisabled = this.programs.filter((p) => p.language !== 'SFC').map((p) => p.name);
    this.hmi = { ...this.hmi, abort: false, manual_allowed: false, active_sequence: null };
    this.event('abort', 'abort latched: manual abort (hmi.abort)', 'hmi');
  }

  private returnControl() {
    this.latched = false;
    const { lox, fuel } = this.hmi.bb;
    this.hmi = {
      ...this.hmi,
      manual_allowed: true,
      bb: { lox: { ...lox, enable: false }, fuel: { ...fuel, enable: false } },
    };
    this.event('abort', 'abort sequence complete -- stand safe, operator in control', 'plc');
    if (this.abortDisabled.length) {
      this.event('abort', `programs left off until plc.reset re-arms them: ${this.abortDisabled.join(', ')}`, 'plc');
    }
  }
}

export function createMockSocket(): SocketLike & { connect(): void } {
  const socket: SocketLike & { connect(): void } = {
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
    connect() {
      setTimeout(() => this.onopen?.(), 30);
    },
    send(data: string) {
      let parsed: ClientMsg;
      try {
        parsed = JSON.parse(data);
      } catch {
        return;
      }
      const reply = sim.handle(parsed);
      if (reply) {
        // Mimic network latency of ~0 but async, so promises resolve on a microtask/tick.
        setTimeout(() => this.onmessage?.({ data: JSON.stringify(reply) }), 0);
      }
    },
    close() {
      /* no-op: the mock has no real connection to tear down */
    },
  };
  const sim = new MockSim((msg) => socket.onmessage?.({ data: JSON.stringify(msg) }));
  return socket;
}
