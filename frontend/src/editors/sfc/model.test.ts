import { describe, expect, it } from 'vitest';
import {
  addAlternativeBranch,
  addSimultaneousBranch,
  addStepAfter,
  addTransitionBetween,
  deleteStep,
  deleteTransition,
  renameStep,
  setInitialStep,
} from './model';
import type { SfcDoc } from './types';

function baseDoc(): SfcDoc {
  return {
    version: 1,
    language: 'SFC',
    name: 'fixture',
    vars: [],
    steps: [
      { id: 's1', name: 'INIT', initial: true, actions: [] },
      { id: 's2', name: 'RUN', actions: [] },
    ],
    transitions: [{ id: 't1', from: 'INIT', to: 'RUN', condition: 'TRUE' }],
  };
}

describe('SFC model: addStepAfter', () => {
  it('adds a new step and a transition wiring it in after the given step', () => {
    const doc = baseDoc();
    const result = addStepAfter(doc, 's2');
    expect(result.steps).toHaveLength(3);
    const added = result.steps[2];
    expect(added.name).not.toBe('INIT');
    expect(added.name).not.toBe('RUN');
    expect(result.transitions).toHaveLength(2);
    const newTransition = result.transitions[1];
    expect(newTransition.from).toBe('RUN');
    expect(newTransition.to).toBe(added.name);
  });

  it('is a no-op for an unknown step id', () => {
    const doc = baseDoc();
    expect(addStepAfter(doc, 'nope')).toBe(doc);
  });
});

describe('SFC model: addTransitionBetween', () => {
  it('links two existing steps by name', () => {
    const doc = baseDoc();
    const result = addTransitionBetween(doc, 's2', 's1'); // loop back RUN -> INIT
    expect(result.transitions).toHaveLength(2);
    expect(result.transitions[1]).toMatchObject({ from: 'RUN', to: 'INIT' });
  });

  it('is a no-op when either step id is unknown', () => {
    const doc = baseDoc();
    expect(addTransitionBetween(doc, 's1', 'nope')).toBe(doc);
    expect(addTransitionBetween(doc, 'nope', 's1')).toBe(doc);
  });
});

describe('SFC model: addAlternativeBranch', () => {
  it('adds a second, alternative transition out of the same step', () => {
    const doc = baseDoc();
    const result = addAlternativeBranch(doc, 's1');
    expect(result.steps).toHaveLength(3);
    expect(result.transitions).toHaveLength(2);
    expect(result.transitions[0].from).toBe('INIT'); // original transition untouched
    expect(result.transitions[1].from).toBe('INIT'); // new alternative also leaves INIT
    expect(result.transitions[1].to).toBe(result.steps[2].name);
  });
});

describe('SFC model: addSimultaneousBranch', () => {
  it('diverge: adds a new step and extends the transition.to into an array', () => {
    const doc = baseDoc();
    const result = addSimultaneousBranch(doc, 't1', 'diverge');
    const t = result.transitions[0];
    expect(Array.isArray(t.to)).toBe(true);
    expect(t.to).toEqual(['RUN', result.steps[2].name]);
    expect(t.from).toBe('INIT'); // from side untouched
  });

  it('converge: extends the transition.from into an array using an existing step', () => {
    const doc = baseDoc();
    const result = addSimultaneousBranch(doc, 't1', 'converge', 's2'); // RUN also converges into t1
    const t = result.transitions[0];
    expect(t.from).toEqual(['INIT', 'RUN']);
    expect(t.to).toBe('RUN'); // to side untouched
  });

  it('converge without otherStepId is a no-op', () => {
    const doc = baseDoc();
    expect(addSimultaneousBranch(doc, 't1', 'converge')).toBe(doc);
  });
});

describe('SFC model: deleteStep', () => {
  it('removes the step and any transition left with no endpoint on one side', () => {
    const doc = baseDoc();
    const result = deleteStep(doc, 's1'); // INIT is t1's only "from"
    expect(result.steps.map((s) => s.name)).toEqual(['RUN']);
    expect(result.transitions).toHaveLength(0); // t1 had nowhere left to come from
  });

  it('shrinks a multi-endpoint transition instead of dropping it, and collapses a 1-item array to a bare string', () => {
    const doc: SfcDoc = {
      version: 1,
      language: 'SFC',
      name: 'fixture',
      vars: [],
      steps: [
        { id: 'a', name: 'A', initial: true, actions: [] },
        { id: 'b', name: 'B', actions: [] },
        { id: 'c', name: 'C', actions: [] },
      ],
      transitions: [{ id: 't', from: ['A', 'B'], to: 'C', condition: 'TRUE' }],
    };
    const result = deleteStep(doc, 'a');
    expect(result.steps.map((s) => s.name)).toEqual(['B', 'C']);
    expect(result.transitions).toHaveLength(1);
    expect(result.transitions[0].from).toBe('B'); // array collapsed to a plain string
    expect(result.transitions[0].to).toBe('C');
  });

  it('clears abort_step when the abort step itself is deleted', () => {
    const doc = { ...baseDoc(), abort_step: 'RUN' };
    const result = deleteStep(doc, 's2');
    expect(result.abort_step).toBeUndefined();
  });

  it('is a no-op for an unknown step id', () => {
    const doc = baseDoc();
    expect(deleteStep(doc, 'nope')).toBe(doc);
  });
});

describe('SFC model: deleteTransition', () => {
  it('removes exactly the named transition', () => {
    const doc = addAlternativeBranch(baseDoc(), 's1');
    const result = deleteTransition(doc, doc.transitions[1].id);
    expect(result.transitions).toHaveLength(1);
    expect(result.transitions[0].id).toBe(doc.transitions[0].id);
  });
});

describe('SFC model: setInitialStep', () => {
  it('marks exactly one step initial, unmarking any previous one', () => {
    const doc = baseDoc();
    const result = setInitialStep(doc, 's2');
    const initialSteps = result.steps.filter((s) => s.initial);
    expect(initialSteps).toHaveLength(1);
    expect(initialSteps[0].id).toBe('s2');
  });
});

describe('SFC model: renameStep', () => {
  it('renames the step and every from/to reference to it, including array form', () => {
    const doc = addSimultaneousBranch(addAlternativeBranch(baseDoc(), 's1'), 't1', 'diverge');
    const result = renameStep(doc, 's1', 'ARMED');
    expect(result.steps.find((s) => s.id === 's1')?.name).toBe('ARMED');
    for (const t of result.transitions) {
      const froms = Array.isArray(t.from) ? t.from : [t.from];
      expect(froms).not.toContain('INIT');
    }
  });

  it('updates abort_step when it names the renamed step', () => {
    const doc = { ...baseDoc(), abort_step: 'INIT' };
    const result = renameStep(doc, 's1', 'ARMED');
    expect(result.abort_step).toBe('ARMED');
  });

  it('is a no-op for an unknown id or an empty name', () => {
    const doc = baseDoc();
    expect(renameStep(doc, 'nope', 'X')).toBe(doc);
    expect(renameStep(doc, 's1', '')).toBe(doc);
  });
});
