// Wire types for docs/protocol.md (v1). Field names are the contract -- keep them
// exactly as the doc specifies even where a different shape would be more idiomatic.

export type Language = 'ST' | 'LD' | 'SFC';

export interface ProgramSource {
  name: string;
  language: Language;
  source: string | Record<string, unknown>;
}

export interface TagEntry {
  tag: string;
  kind: string;
  signal?: string | null;
  units?: string | null;
  range?: [number, number] | null;
  normal_state?: string | null;
  description?: string | null;
}

// ---- client -> server ------------------------------------------------------

export interface HelloMsg {
  type: 'hello';
  id?: string;
  client: string;
  protocol: number;
}

export interface SubscribeMsg {
  type: 'subscribe';
  id?: string;
  rate_hz: number;
  groups?: SimGroup[];
}

export type SimGroup = 'inputs' | 'outputs' | 'plc' | 'hmi' | 'plant' | 'raw';

export interface UnsubscribeMsg {
  type: 'unsubscribe';
  id?: string;
}

export interface ReadMsg {
  type: 'read';
  id?: string;
  names: string[];
}

export interface WriteMsg {
  type: 'write';
  id?: string;
  values: Record<string, number | boolean | string>;
}

export interface SequenceMsg {
  type: 'sequence';
  id?: string;
  action: 'start' | 'stop';
  name: string;
}

export interface AbortMsg {
  type: 'abort';
  id?: string;
}

export interface AbortClearMsg {
  type: 'abort.clear';
  id?: string;
}

export interface AbortThreshold {
  tag: string;
  op: '>' | '<' | '>=' | '<=' | '=' | '!=';
  value: number;
  enabled: boolean;
  label: string;
}

export interface AbortConfigMsg {
  type: 'abort.config';
  id?: string;
  thresholds: AbortThreshold[];
}

export interface ProgramCompileMsg {
  type: 'program.compile';
  id?: string;
  name: string;
  language: Language;
  source: string | Record<string, unknown>;
}

export interface ProgramLoadMsg {
  type: 'program.load';
  id?: string;
  programs: ProgramSource[];
}

export interface ProgramListMsg {
  type: 'program.list';
  id?: string;
}

export interface PlcCommandMsg {
  type: 'plc.run' | 'plc.stop' | 'plc.reset' | 'plc.clear_faults';
  id?: string;
}

export interface PlcForceMsg {
  type: 'plc.force';
  id?: string;
  name: string;
  value: number | boolean;
}

export interface PlcUnforceMsg {
  type: 'plc.unforce';
  id?: string;
  name: string;
}

export interface SimResetMsg {
  type: 'sim.reset';
  id?: string;
  initial?: Record<string, number>;
}

export interface SimRateMsg {
  type: 'sim.rate';
  id?: string;
  scan_hz?: number;
  realtime?: boolean;
  speed?: number;
}

export interface SimPauseResumeMsg {
  type: 'sim.pause' | 'sim.resume';
  id?: string;
}

export type ClientMsg =
  | HelloMsg
  | SubscribeMsg
  | UnsubscribeMsg
  | ReadMsg
  | WriteMsg
  | SequenceMsg
  | AbortMsg
  | AbortClearMsg
  | AbortConfigMsg
  | ProgramCompileMsg
  | ProgramLoadMsg
  | ProgramListMsg
  | PlcCommandMsg
  | PlcForceMsg
  | PlcUnforceMsg
  | SimResetMsg
  | SimRateMsg
  | SimPauseResumeMsg;

// ---- server -> client -------------------------------------------------------

/** welcome.programs entries -- like ProgramSource, plus the optional server-assigned role. */
export interface ProgramSummary extends ProgramSource {
  role?: ProgramRole;
}

export interface WelcomeMsg {
  type: 'welcome';
  protocol: number;
  sim_version: string;
  tags: TagEntry[];
  programs: ProgramSummary[];
  examples: ProgramSource[];
  notice: string;
}

export type ErrorCode =
  | 'bad_request'
  | 'unknown_name'
  | 'read_only'
  | 'rejected'
  | 'plc_running'
  | 'abort_active'
  | 'compile_error'
  | 'internal';

export interface AckMsg {
  type: 'ack';
  id?: string;
}

export interface ErrorMsg {
  type: 'error';
  id?: string;
  code: ErrorCode;
  message: string;
  details?: Record<string, unknown>;
}

export interface ReadResultMsg {
  type: 'read_result';
  id?: string;
  values: Record<string, unknown>;
}

/** regulation | sequence | monitor | other -- server-assigned, optional (backend addition in progress). */
export type ProgramRole = 'regulation' | 'sequence' | 'monitor' | 'other';

export interface ProgramListResultMsg {
  type: 'program_list';
  id?: string;
  programs: Array<{
    name: string;
    language: Language;
    source: string | Record<string, unknown>;
    compiled_ok: boolean;
    running: boolean;
    role?: ProgramRole;
  }>;
}

export interface CompileErrorEntry {
  message: string;
  line?: number | null;
  col?: number | null;
  path?: string | null;
}

export interface CompileResultMsg {
  type: 'compile_result';
  id?: string;
  ok: boolean;
  errors: CompileErrorEntry[];
  variables?: string[];
  ladder_text?: string;
}

export interface AbortInfo {
  thresholds: AbortThreshold[];
  // value/threshold are numeric for a threshold trip but the manual (hmi.abort) and
  // program (auto_abort_request) sources report value: true, threshold: null instead.
  tripped: null | {
    tag: string;
    value: number | boolean;
    threshold: number | null;
    t: number;
    source?: 'threshold' | 'program' | 'manual';
    label?: string;
    op?: string;
  };
  latched: boolean;
  /** Human-readable reasons control has not returned yet; display, never parse. */
  waiting_on: string[];
}

export interface SfcState {
  active_steps: string[];
  step_times: Record<string, number>;
  aborted: boolean;
  running: boolean;
  stored_actions?: string[];
}

export interface PlcState {
  running: boolean;
  abort_active: boolean;
  faults: Array<Record<string, unknown>>;
  halted: string[];
  enabled?: Record<string, boolean>;
  sfc: Record<string, SfcState>;
  globals: Record<string, number | boolean | string>;
  forced: Record<string, number | boolean | string>;
}

export interface BbLoopState {
  setpoint: number;
  deadband: number;
  enable: boolean;
  state: 'OFF' | 'PRESS' | 'HOLD';
  /** Programs driving this loop that an abort switched off; plc.reset re-arms them. */
  abort_off?: string[];
}

export interface HmiState {
  abort: boolean;
  bb: { lox: BbLoopState; fuel: BbLoopState };
  manual_allowed: boolean;
  active_sequence: string | null;
  manual?: Record<string, boolean>;
}

export interface StateMsg {
  type: 'state';
  t: number;
  scan: number;
  scan_hz: number;
  paused: boolean;
  inputs: Record<string, number>;
  outputs: Record<string, boolean>;
  plc: PlcState;
  hmi: HmiState;
  abort: AbortInfo;
  plant?: Record<string, unknown>;
  raw?: Record<string, unknown>;
  // Additive per docs/protocol.md: dotted paths within this same state object whose
  // value was replaced with null because it was not JSON-finite. Always present.
  nonfinite: string[];
}

export type EventLevel = 'info' | 'command' | 'sequence' | 'abort' | 'fault' | 'warn';

export interface EventMsg {
  type: 'event';
  t: number;
  scan: number;
  level: EventLevel;
  text: string;
  source: 'hmi' | 'plc' | 'sim';
}

export type ServerMsg =
  | WelcomeMsg
  | AckMsg
  | ErrorMsg
  | ReadResultMsg
  | ProgramListResultMsg
  | CompileResultMsg
  | StateMsg
  | EventMsg;
