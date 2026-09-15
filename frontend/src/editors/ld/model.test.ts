import { describe, expect, it } from 'vitest';
import {
  appendToEnd,
  defaultCoil,
  defaultContact,
  emptySeries,
  insertAfter,
  reorderRung,
  removeNetwork,
  wrapInParallel,
} from './model';
import type { Network, Rung } from './types';

function series(id: string, elements: Network[]): Network {
  return { id, type: 'series', elements };
}
function contact(id: string, operand = ''): Network {
  return { id, type: 'contact', kind: 'NO', operand };
}
function coil(id: string, operand = 'S1'): Network {
  return { id, type: 'coil', kind: 'COIL', operand };
}

/** Every id in the tree, for uniqueness/stability checks -- schema-valid LD
 *  documents must give every element a stable id (see docs/plc-language.md 5.4). */
function collectIds(net: Network): string[] {
  if (net.type === 'series') return [net.id, ...net.elements.flatMap(collectIds)];
  if (net.type === 'parallel') return [net.id, ...net.branches.flatMap(collectIds)];
  return [net.id];
}

describe('LD model: insertAfter', () => {
  it('inserts a new leaf immediately after the target within a series', () => {
    const net = series('r', [contact('a'), contact('b')]);
    const result = insertAfter(net, 'a', contact('new'));
    expect(result.type).toBe('series');
    if (result.type !== 'series') throw new Error('unreachable');
    expect(result.elements.map((e) => e.id)).toEqual(['a', 'new', 'b']);
    // untouched siblings keep their identity
    expect(result.elements[0]).toEqual(contact('a'));
    expect(result.elements[2]).toEqual(contact('b'));
  });

  it('wraps a non-series target (e.g. a lone root leaf) into a new series', () => {
    const root = contact('only');
    const result = insertAfter(root, 'only', coil('new-coil'));
    expect(result.type).toBe('series');
    if (result.type !== 'series') throw new Error('unreachable');
    expect(result.elements).toEqual([contact('only'), coil('new-coil')]);
    expect(result.id).not.toBe('only');
    expect(result.id).not.toBe('new-coil');
  });

  it('only touches the branch that contains the target inside a parallel', () => {
    const untouchedBranch = series('branchB', [contact('b1')]);
    const net: Network = {
      id: 'par',
      type: 'parallel',
      branches: [series('branchA', [contact('a1')]), untouchedBranch],
    };
    const result = insertAfter(net, 'a1', contact('a2'));
    expect(result.type).toBe('parallel');
    if (result.type !== 'parallel') throw new Error('unreachable');
    expect(collectIds(result.branches[0])).toEqual(['branchA', 'a1', 'a2']);
    expect(result.branches[1]).toEqual(untouchedBranch); // untouched branch: same content
  });

  it('ids stay unique after insertion', () => {
    const net = series('r', [contact('a'), contact('b')]);
    const result = insertAfter(net, 'a', contact('c'));
    const ids = collectIds(result);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe('LD model: removeNetwork', () => {
  it('removes a leaf from a series without disturbing order', () => {
    const net = series('r', [contact('a'), contact('b'), contact('c')]);
    const result = removeNetwork(net, 'b');
    expect(result.type).toBe('series');
    if (result.type !== 'series') throw new Error('unreachable');
    expect(result.elements.map((e) => e.id)).toEqual(['a', 'c']);
  });

  it('collapses a parallel to its remaining branch when one is removed', () => {
    const keep = series('keep', [contact('k1')]);
    const net: Network = { id: 'par', type: 'parallel', branches: [keep, series('drop', [contact('d1')])] };
    const result = removeNetwork(net, 'drop');
    // per model.ts: a 2-branch parallel collapses to the single remaining branch, not a 1-branch parallel
    expect(result).toEqual(keep);
    expect(result.type).not.toBe('parallel');
  });

  it('removing an element leaves every remaining id unique', () => {
    const net = series('r', [contact('a'), contact('b'), contact('c')]);
    const result = removeNetwork(net, 'b');
    const ids = collectIds(result);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).not.toContain('b');
  });
});

describe('LD model: wrapInParallel', () => {
  it('wraps the target in a 2-branch parallel: original node plus a fresh empty series', () => {
    const net = series('r', [contact('a'), coil('b')]);
    const result = wrapInParallel(net, 'a');
    expect(result.type).toBe('series');
    if (result.type !== 'series') throw new Error('unreachable');
    const wrapped = result.elements[0];
    expect(wrapped.type).toBe('parallel');
    if (wrapped.type !== 'parallel') throw new Error('unreachable');
    expect(wrapped.branches).toHaveLength(2);
    expect(wrapped.branches[0]).toEqual(contact('a')); // original element unchanged
    expect(wrapped.branches[1].type).toBe('series');
    if (wrapped.branches[1].type === 'series') expect(wrapped.branches[1].elements).toEqual([]);
    // the new parallel's own id and the new empty branch's id must not collide with anything existing
    const ids = collectIds(result);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('is schema-valid: the resulting parallel always has exactly two Network branches', () => {
    const net = contact('solo');
    const result = wrapInParallel(net, 'solo');
    expect(result.type).toBe('parallel');
    if (result.type !== 'parallel') throw new Error('unreachable');
    expect(result.branches).toHaveLength(2);
    expect(result.branches.every((b) => typeof b.id === 'string' && b.id.length > 0)).toBe(true);
  });
});

describe('LD model: appendToEnd / emptySeries', () => {
  it('appends to an existing series', () => {
    const net = series('r', [contact('a')]);
    const result = appendToEnd(net, contact('b'));
    expect(result.type).toBe('series');
    if (result.type === 'series') expect(result.elements.map((e) => e.id)).toEqual(['a', 'b']);
  });

  it('emptySeries starts with no elements and a stable id', () => {
    const e = emptySeries();
    expect(e).toEqual({ id: e.id, type: 'series', elements: [] });
    expect(e.id.length).toBeGreaterThan(0);
  });
});

describe('LD model: reorderRung', () => {
  const rungs: Rung[] = [
    { id: 'r1', logic: emptySeries() },
    { id: 'r2', logic: emptySeries() },
    { id: 'r3', logic: emptySeries() },
  ];

  it('swaps a rung with the next one', () => {
    const result = reorderRung(rungs, 'r1', 1);
    expect(result.map((r) => r.id)).toEqual(['r2', 'r1', 'r3']);
  });

  it('swaps a rung with the previous one', () => {
    const result = reorderRung(rungs, 'r2', -1);
    expect(result.map((r) => r.id)).toEqual(['r2', 'r1', 'r3']);
  });

  it('is a no-op (same array reference) at the top boundary', () => {
    expect(reorderRung(rungs, 'r1', -1)).toBe(rungs);
  });

  it('is a no-op (same array reference) at the bottom boundary', () => {
    expect(reorderRung(rungs, 'r3', 1)).toBe(rungs);
  });

  it('is a no-op for an unknown id', () => {
    expect(reorderRung(rungs, 'nope', 1)).toBe(rungs);
  });

  it('preserves every rung by reference (only order changes)', () => {
    const result = reorderRung(rungs, 'r1', 1);
    for (const r of rungs) expect(result).toContain(r);
  });
});

describe('LD model: id generation', () => {
  it('never repeats an id across successive default-element calls', () => {
    const ids = new Set<string>();
    for (let i = 0; i < 50; i += 1) {
      ids.add(defaultContact('NO').id);
      ids.add(defaultCoil('COIL').id);
    }
    expect(ids.size).toBe(100);
  });
});
