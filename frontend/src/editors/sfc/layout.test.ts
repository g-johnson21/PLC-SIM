import { describe, expect, it } from 'vitest';
import { layoutChart } from './layout';
import type { SfcDoc, Step, Transition } from './types';

function step(name: string, initial = false): Step {
  return { id: `id-${name}`, name, initial, actions: [] };
}
function transition(id: string, from: string | string[], to: string | string[]): Transition {
  return { id, from, to, condition: 'TRUE' };
}
function docOf(steps: Step[], transitions: Transition[], abort_step?: string): SfcDoc {
  return { version: 1, language: 'SFC', name: 'fixture', vars: [], steps, transitions, abort_step };
}
function names(partitionSteps: { step: Step }[]): string[] {
  return partitionSteps.map((p) => p.step.name).sort();
}

describe('SFC layout: abort chain separation', () => {
  it('puts abort-reachable steps in `abort` and everything else in `normal`', () => {
    const doc = docOf(
      [step('A', true), step('B'), step('C'), step('X'), step('Y')],
      [transition('t1', 'A', 'B'), transition('t2', 'B', 'C'), transition('t3', 'X', 'Y')],
      'X',
    );
    const { normal, abort } = layoutChart(doc);
    expect(abort).not.toBeNull();
    expect(names(abort!.steps)).toEqual(['X', 'Y']);
    expect(names(normal.steps)).toEqual(['A', 'B', 'C']);
  });

  it('abort is null when the document declares no abort_step', () => {
    const doc = docOf([step('A', true), step('B')], [transition('t1', 'A', 'B')]);
    const { abort } = layoutChart(doc);
    expect(abort).toBeNull();
  });

  it('an abort_step naming an unknown step reaches nothing (abort stays null)', () => {
    const doc = docOf([step('A', true)], [], 'GHOST');
    const { abort } = layoutChart(doc);
    expect(abort).toBeNull();
  });
});

describe('SFC layout: initial step identification', () => {
  it('lays out the initial step at depth 0 regardless of its position in doc.steps', () => {
    // steps deliberately out of chain order -- layout must use the `initial` flag, not array order
    const doc = docOf(
      [step('C'), step('B'), step('A', true)],
      [transition('t1', 'A', 'B'), transition('t2', 'B', 'C')],
    );
    const { normal } = layoutChart(doc);
    const depthOf = (n: string) => normal.steps.find((p) => p.step.name === n)!.depth;
    expect(depthOf('A')).toBe(0);
    expect(depthOf('B')).toBe(1);
    expect(depthOf('C')).toBe(2);
  });

  it('every step still appears even if unreachable from the initial step', () => {
    const doc = docOf([step('A', true), step('ORPHAN')], [], undefined);
    const { normal } = layoutChart(doc);
    expect(names(normal.steps)).toEqual(['A', 'ORPHAN']);
  });
});

describe('SFC layout: simultaneous branches', () => {
  it('gives both sides of a divergence the same depth, and the reconvergence one depth further', () => {
    const doc = docOf(
      [step('A', true), step('B'), step('C'), step('D')],
      [transition('t1', 'A', ['B', 'C']), transition('t2', ['B', 'C'], 'D')],
    );
    const { normal } = layoutChart(doc);
    const depthOf = (n: string) => normal.steps.find((p) => p.step.name === n)!.depth;
    expect(depthOf('A')).toBe(0);
    expect(depthOf('B')).toBe(1);
    expect(depthOf('C')).toBe(1);
    expect(depthOf('D')).toBe(2);
  });
});
