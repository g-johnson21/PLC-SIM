import { newId } from '../../lib/id';
import type { SfcDoc, Step, Transition } from './types';

/** Views the document with its optional arrays defaulted for editing convenience.
 *  Never fed back through onChange on its own -- an untouched document still
 *  exports exactly as imported, with no key added that wasn't already there. */
export function withSfcDefaults(doc: SfcDoc): SfcDoc {
  return { ...doc, vars: doc.vars ?? [], steps: doc.steps ?? [], transitions: doc.transitions ?? [] };
}

export function newStep(name: string): Step {
  return { id: newId('s'), name, actions: [] };
}

export function newTransition(from: string, to: string): Transition {
  return { id: newId('t'), from, to, condition: 'TRUE' };
}

/** Insert a new step after `afterStepId`, wired in with a single transition. */
export function addStepAfter(doc: SfcDoc, afterStepId: string): SfcDoc {
  const after = doc.steps.find((s) => s.id === afterStepId);
  if (!after) return doc;
  const step = newStep(`STEP_${doc.steps.length + 1}`);
  const transition = newTransition(after.name, step.name);
  return { ...doc, steps: [...doc.steps, step], transitions: [...doc.transitions, transition] };
}

export function addTransitionBetween(doc: SfcDoc, fromStepId: string, toStepId: string): SfcDoc {
  const from = doc.steps.find((s) => s.id === fromStepId);
  const to = doc.steps.find((s) => s.id === toStepId);
  if (!from || !to) return doc;
  return { ...doc, transitions: [...doc.transitions, newTransition(from.name, to.name)] };
}

/** Alternative branch: a second transition out of the same step, to a new step. */
export function addAlternativeBranch(doc: SfcDoc, fromStepId: string): SfcDoc {
  const from = doc.steps.find((s) => s.id === fromStepId);
  if (!from) return doc;
  const step = newStep(`ALT_${doc.steps.length + 1}`);
  const transition = newTransition(from.name, step.name);
  return { ...doc, steps: [...doc.steps, step], transitions: [...doc.transitions, transition] };
}

/** Simultaneous branch: extend an existing transition's `to` with a second new step
 *  (simultaneous divergence), or its `from` with a second existing step id (convergence). */
export function addSimultaneousBranch(doc: SfcDoc, transitionId: string, mode: 'diverge' | 'converge', otherStepId?: string): SfcDoc {
  const transition = doc.transitions.find((t) => t.id === transitionId);
  if (!transition) return doc;
  if (mode === 'diverge') {
    const step = newStep(`SIM_${doc.steps.length + 1}`);
    const to = Array.isArray(transition.to) ? [...transition.to, step.name] : [transition.to, step.name];
    return {
      ...doc,
      steps: [...doc.steps, step],
      transitions: doc.transitions.map((t) => (t.id === transitionId ? { ...t, to } : t)),
    };
  }
  if (!otherStepId) return doc;
  const other = doc.steps.find((s) => s.id === otherStepId);
  if (!other) return doc;
  const from = Array.isArray(transition.from) ? [...transition.from, other.name] : [transition.from, other.name];
  return { ...doc, transitions: doc.transitions.map((t) => (t.id === transitionId ? { ...t, from } : t)) };
}

function removeNameFromField(field: string | string[], name: string): string | string[] {
  const arr = Array.isArray(field) ? field : [field];
  const filtered = arr.filter((n) => n !== name);
  return filtered.length <= 1 ? filtered[0] ?? arr[0] : filtered;
}

export function deleteStep(doc: SfcDoc, stepId: string): SfcDoc {
  const step = doc.steps.find((s) => s.id === stepId);
  if (!step) return doc;
  const steps = doc.steps.filter((s) => s.id !== stepId);
  const transitions = doc.transitions
    .filter((t) => {
      const froms = Array.isArray(t.from) ? t.from : [t.from];
      const tos = Array.isArray(t.to) ? t.to : [t.to];
      // drop transitions that would be left with no endpoint on either side
      const fromsLeft = froms.filter((n) => n !== step.name);
      const tosLeft = tos.filter((n) => n !== step.name);
      return fromsLeft.length > 0 && tosLeft.length > 0;
    })
    .map((t) => ({ ...t, from: removeNameFromField(t.from, step.name), to: removeNameFromField(t.to, step.name) }));
  return {
    ...doc,
    steps,
    transitions,
    abort_step: doc.abort_step === step.name ? undefined : doc.abort_step,
  };
}

export function deleteTransition(doc: SfcDoc, transitionId: string): SfcDoc {
  return { ...doc, transitions: doc.transitions.filter((t) => t.id !== transitionId) };
}

export function setInitialStep(doc: SfcDoc, stepId: string): SfcDoc {
  return { ...doc, steps: doc.steps.map((s) => ({ ...s, initial: s.id === stepId })) };
}

export function renameStep(doc: SfcDoc, stepId: string, name: string): SfcDoc {
  const step = doc.steps.find((s) => s.id === stepId);
  if (!step || !name || name === step.name) return doc;
  const oldName = step.name;
  const renameField = (f: string | string[]) => (Array.isArray(f) ? f.map((n) => (n === oldName ? name : n)) : f === oldName ? name : f);
  return {
    ...doc,
    steps: doc.steps.map((s) => (s.id === stepId ? { ...s, name } : s)),
    transitions: doc.transitions.map((t) => ({ ...t, from: renameField(t.from), to: renameField(t.to) })),
    abort_step: doc.abort_step === oldName ? name : doc.abort_step,
  };
}
