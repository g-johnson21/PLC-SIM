import type { VarDecl } from '../shared/types';

export type ActionQualifier = 'N' | 'S' | 'R' | 'P' | 'P0' | 'D';

export interface Action {
  id?: string;
  comment?: string;
  qualifier?: ActionQualifier;
  body?: string;
  name?: string;
  delay?: string | number;
}

export interface Step {
  name: string;
  id: string;
  comment?: string;
  initial?: boolean;
  actions?: Action[];
}

export interface Transition {
  id: string;
  comment?: string;
  from: string | string[];
  to: string | string[];
  condition: string;
}

export interface SfcDoc {
  version: number;
  language: 'SFC';
  name: string;
  description?: string;
  autostart?: boolean;
  abort_step?: string;
  vars: VarDecl[];
  steps: Step[];
  transitions: Transition[];
}

export function asArray(v: string | string[]): string[] {
  return Array.isArray(v) ? v : [v];
}
