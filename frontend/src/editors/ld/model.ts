import { newId } from '../../lib/id';
import type { CoilKind, CompareOp, ContactKind, CounterFb, LdDoc, LeafElement, MathOp, Network, Rung, TimerFb } from './types';

/** Views the document with its optional arrays defaulted for editing convenience.
 *  Never fed back through onChange on its own -- an untouched document still
 *  exports exactly as imported, with no key added that wasn't already there. */
export function withLdDefaults(doc: LdDoc): LdDoc {
  return { ...doc, vars: doc.vars ?? [], rungs: doc.rungs ?? [] };
}

export function defaultContact(kind: ContactKind): LeafElement {
  return { id: newId('el'), type: 'contact', kind, operand: '' };
}
export function defaultCoil(kind: CoilKind): LeafElement {
  return { id: newId('el'), type: 'coil', kind, operand: '' };
}
export function defaultTimer(fb: TimerFb): LeafElement {
  return { id: newId('el'), type: 'timer', fb, pt: 'T#1s' };
}
export function defaultCounter(fb: CounterFb): LeafElement {
  return { id: newId('el'), type: 'counter', fb, pv: 0 };
}
export function defaultCompare(op: CompareOp): LeafElement {
  return { id: newId('el'), type: 'compare', op, a: '', b: '' };
}
export function defaultMove(): LeafElement {
  return { id: newId('el'), type: 'move', src: '', dst: '' };
}
export function defaultMath(op: MathOp): LeafElement {
  return { id: newId('el'), type: 'math', op, a: '', b: '', dst: '' };
}

export function emptySeries(): Network {
  return { id: newId('net'), type: 'series', elements: [] };
}

export function newRung(): Rung {
  return { id: newId('r'), logic: emptySeries() };
}

/** Swap the rung with `id` with its neighbour in direction `dir` (-1 up, +1 down).
 *  A no-op (returns the same array reference) at either boundary or if `id` is unknown. */
export function reorderRung(rungs: Rung[], id: string, dir: -1 | 1): Rung[] {
  const idx = rungs.findIndex((r) => r.id === id);
  const j = idx + dir;
  if (idx < 0 || j < 0 || j >= rungs.length) return rungs;
  const next = [...rungs];
  [next[idx], next[j]] = [next[j], next[idx]];
  return next;
}

/** Replace the node with the given id anywhere in the tree; returns a new tree. */
export function mapNetwork(net: Network, id: string, fn: (n: Network) => Network): Network {
  if (net.id === id) return fn(net);
  if (net.type === 'series') return { ...net, elements: net.elements.map((e) => mapNetwork(e, id, fn)) };
  if (net.type === 'parallel') return { ...net, branches: net.branches.map((b) => mapNetwork(b, id, fn)) };
  return net;
}

export function findNetwork(net: Network, id: string): Network | undefined {
  if (net.id === id) return net;
  if (net.type === 'series') {
    for (const e of net.elements) {
      const found = findNetwork(e, id);
      if (found) return found;
    }
  } else if (net.type === 'parallel') {
    for (const b of net.branches) {
      const found = findNetwork(b, id);
      if (found) return found;
    }
  }
  return undefined;
}

/** Remove the node with the given id. Collapses a parallel down to its remaining
 *  branch when only one is left, mirroring what a ladder editor would do. */
export function removeNetwork(net: Network, id: string): Network {
  if (net.type === 'series') {
    const elements = net.elements.filter((e) => e.id !== id).map((e) => removeNetwork(e, id));
    return { ...net, elements };
  }
  if (net.type === 'parallel') {
    const branches = net.branches.filter((b) => b.id !== id).map((b) => removeNetwork(b, id));
    if (branches.length === 1) return branches[0];
    return { ...net, branches };
  }
  return net;
}

/** Insert `newEl` immediately after the node `targetId`. Falls back to wrapping the
 *  target in a new series (target becomes the first element) if the target's parent
 *  isn't a series -- keeps every insertion representable without corrupting siblings. */
export function insertAfter(net: Network, targetId: string, newEl: Network): Network {
  if (net.id === targetId) {
    return { id: newId('net'), type: 'series', elements: [net, newEl] };
  }
  if (net.type === 'series') {
    const idx = net.elements.findIndex((e) => e.id === targetId);
    if (idx >= 0) {
      const elements = [...net.elements];
      elements.splice(idx + 1, 0, newEl);
      return { ...net, elements };
    }
    return { ...net, elements: net.elements.map((e) => insertAfter(e, targetId, newEl)) };
  }
  if (net.type === 'parallel') {
    return { ...net, branches: net.branches.map((b) => insertAfter(b, targetId, newEl)) };
  }
  return net;
}

export function appendToEnd(net: Network, newEl: Network): Network {
  if (net.type === 'series') return { ...net, elements: [...net.elements, newEl] };
  return { id: newId('net'), type: 'series', elements: [net, newEl] };
}

export function wrapInParallel(net: Network, targetId: string): Network {
  return mapNetwork(net, targetId, (node) => ({
    id: newId('par'),
    type: 'parallel',
    branches: [node, emptySeries()],
  }));
}

function operandName(op: unknown): string | undefined {
  if (typeof op === 'string') return op;
  if (op && typeof op === 'object' && 'var' in (op as Record<string, unknown>)) {
    return (op as { var: string }).var;
  }
  return undefined;
}

export type ValueLookup = (name: string) => boolean | number | undefined;

/** Best-effort energised/value lookup for online colouring. Only names the state
 *  stream actually carries (inputs, outputs, plc.globals) resolve; everything else
 *  (locals, FB instance fields, P/N edge memory) is unknown and stays uncoloured --
 *  the wire protocol does not expose it, so we don't invent it. */
export function elementBoolValue(el: LeafElement, lookup: ValueLookup): boolean | undefined {
  if (el.type === 'contact') {
    const name = operandName(el.operand);
    if (name == null) return undefined;
    const v = lookup(name);
    if (v == null) return undefined;
    if (el.kind === 'NC') return !v;
    if (el.kind === 'NO') return Boolean(v);
    return undefined; // P/N edge state needs previous-scan memory we don't have
  }
  if (el.type === 'coil') {
    const name = operandName(el.operand);
    if (name == null) return undefined;
    const v = lookup(name);
    if (v == null) return undefined;
    return el.kind === 'NEGATED' ? !v : Boolean(v);
  }
  return undefined;
}
