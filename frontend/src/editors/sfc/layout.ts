import { asArray, type SfcDoc, type Step, type Transition } from './types';

export const STEP_W = 132;
export const STEP_H = 46;
export const COL_STRIDE = 168;
export const ROW_STRIDE = 108;
export const MARGIN = 30;

export interface StepPos {
  step: Step;
  col: number;
  depth: number;
}

export interface Partition {
  title: string;
  steps: StepPos[];
  transitions: Transition[];
  width: number;
  height: number;
}

function buildGraph(steps: Step[], transitions: Transition[]) {
  const byName = new Map(steps.map((s) => [s.name, s]));
  const outgoing = new Map<string, Transition[]>();
  for (const t of transitions) {
    for (const from of asArray(t.from)) {
      if (!outgoing.has(from)) outgoing.set(from, []);
      outgoing.get(from)!.push(t);
    }
  }
  return { byName, outgoing };
}

/** Steps reachable from `rootName` by following transitions forward. */
function reachableFrom(rootName: string | undefined, steps: Step[], transitions: Transition[]): Set<string> {
  const seen = new Set<string>();
  if (!rootName || !steps.some((s) => s.name === rootName)) return seen;
  const { outgoing } = buildGraph(steps, transitions);
  const queue = [rootName];
  seen.add(rootName);
  while (queue.length) {
    const name = queue.shift()!;
    for (const t of outgoing.get(name) ?? []) {
      for (const to of asArray(t.to)) {
        if (!seen.has(to)) {
          seen.add(to);
          queue.push(to);
        }
      }
    }
  }
  return seen;
}

function layoutPartition(title: string, steps: Step[], allTransitions: Transition[], rootNames: string[]): Partition {
  const names = new Set(steps.map((s) => s.name));
  const transitions = allTransitions.filter(
    (t) => asArray(t.from).every((n) => names.has(n)) && asArray(t.to).every((n) => names.has(n)),
  );
  const { outgoing } = buildGraph(steps, transitions);

  const col = new Map<string, number>();
  const depth = new Map<string, number>();
  let nextCol = 0;

  function bfsFrom(root: string) {
    if (col.has(root)) return;
    col.set(root, nextCol++);
    depth.set(root, 0);
    const queue = [root];
    while (queue.length) {
      const name = queue.shift()!;
      const d = depth.get(name)!;
      const c = col.get(name)!;
      const outs = outgoing.get(name) ?? [];
      outs.forEach((t, i) => {
        for (const to of asArray(t.to)) {
          if (!depth.has(to)) {
            depth.set(to, d + 1);
            col.set(to, i === 0 ? c : nextCol++);
            queue.push(to);
          }
        }
      });
    }
  }

  for (const r of rootNames) bfsFrom(r);
  // anything unreached (orphan steps, or added but not yet wired) gets its own column
  for (const s of steps) {
    if (!depth.has(s.name)) bfsFrom(s.name);
  }

  const positions: StepPos[] = steps.map((s) => ({ step: s, col: col.get(s.name) ?? 0, depth: depth.get(s.name) ?? 0 }));
  const maxCol = Math.max(0, ...positions.map((p) => p.col));
  const maxDepth = Math.max(0, ...positions.map((p) => p.depth));
  return {
    title,
    steps: positions,
    transitions,
    width: MARGIN * 2 + (maxCol + 1) * COL_STRIDE,
    height: MARGIN * 2 + (maxDepth + 1) * ROW_STRIDE,
  };
}

export function layoutChart(doc: SfcDoc): { normal: Partition; abort: Partition | null } {
  const abortNames = reachableFrom(doc.abort_step, doc.steps, doc.transitions);
  const abortSteps = doc.steps.filter((s) => abortNames.has(s.name));
  const normalSteps = doc.steps.filter((s) => !abortNames.has(s.name));

  const initial = doc.steps.find((s) => s.initial);
  const normalRoots = [initial?.name, ...normalSteps.map((s) => s.name)].filter((n): n is string => Boolean(n));
  const normal = layoutPartition('Normal chain', normalSteps, doc.transitions, normalRoots);

  const abort =
    abortSteps.length > 0
      ? layoutPartition('Abort chain', abortSteps, doc.transitions, [doc.abort_step!, ...abortSteps.map((s) => s.name)])
      : null;

  return { normal, abort };
}
