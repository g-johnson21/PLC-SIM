import type { Operand, VarDecl } from '../shared/types';

export type ContactKind = 'NO' | 'NC' | 'P' | 'N';
export type CoilKind = 'COIL' | 'SET' | 'RESET' | 'NEGATED';
export type TimerFb = 'TON' | 'TOF' | 'TP';
export type CounterFb = 'CTU' | 'CTD';
export type CompareOp = 'GT' | 'GE' | 'EQ' | 'NE' | 'LE' | 'LT';
export type MathOp = 'ADD' | 'SUB' | 'MUL' | 'DIV';

interface ElBase {
  id: string;
  comment?: string;
}

export interface ContactEl extends ElBase {
  type: 'contact';
  kind: ContactKind;
  operand: Operand;
}
export interface CoilEl extends ElBase {
  type: 'coil';
  kind: CoilKind;
  operand: Operand;
}
export interface TimerEl extends ElBase {
  type: 'timer';
  fb: TimerFb;
  pt: Operand;
  instance?: string;
  in?: Operand;
  q?: Operand;
  et?: Operand;
}
export interface CounterEl extends ElBase {
  type: 'counter';
  fb: CounterFb;
  pv: Operand;
  instance?: string;
  cu?: Operand;
  cd?: Operand;
  reset?: Operand;
  load?: Operand;
  q?: Operand;
  cv?: Operand;
}
export interface CompareEl extends ElBase {
  type: 'compare';
  op: CompareOp;
  a: Operand;
  b: Operand;
}
export interface MoveEl extends ElBase {
  type: 'move';
  src: Operand;
  dst: Operand;
}
export interface MathEl extends ElBase {
  type: 'math';
  op: MathOp;
  a: Operand;
  b: Operand;
  dst: Operand;
}

export type LeafElement = ContactEl | CoilEl | TimerEl | CounterEl | CompareEl | MoveEl | MathEl;

export interface SeriesNet extends ElBase {
  type: 'series';
  elements: Network[];
}
export interface ParallelNet extends ElBase {
  type: 'parallel';
  branches: Network[];
}
export type Network = SeriesNet | ParallelNet | LeafElement;

export interface Rung {
  id: string;
  comment?: string;
  logic: Network;
}

export interface LdDoc {
  version: number;
  language: 'LD';
  name: string;
  description?: string;
  vars: VarDecl[];
  rungs: Rung[];
}

export function isContainer(net: Network): net is SeriesNet | ParallelNet {
  return net.type === 'series' || net.type === 'parallel';
}
