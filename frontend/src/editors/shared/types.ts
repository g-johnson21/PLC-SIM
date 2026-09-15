// Shared between LD and SFC documents (docs/plc-language.md S5.1 / S6.1).
export type Operand = string | number | boolean | { var: string } | { const: number | boolean } | { time: string };

export interface VarDecl {
  name: string;
  type: string;
  scope?: 'VAR' | 'VAR_GLOBAL' | 'VAR_RETAIN';
  init?: number | boolean | string;
  comment?: string;
}

export function operandToText(op: Operand | undefined): string {
  if (op == null) return '';
  if (typeof op === 'string' || typeof op === 'number' || typeof op === 'boolean') return String(op);
  if ('var' in op) return op.var;
  if ('const' in op) return String(op.const);
  if ('time' in op) return op.time;
  return '';
}

export function textToOperand(text: string): Operand {
  const trimmed = text.trim();
  if (/^(TIME|T)#/i.test(trimmed)) return trimmed;
  if (/^-?\d+(\.\d+)?$/.test(trimmed)) return Number(trimmed);
  if (trimmed === 'true' || trimmed === 'false') return trimmed === 'true';
  return trimmed;
}
