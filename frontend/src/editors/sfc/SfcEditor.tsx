import { useEffect, useMemo, useState } from 'react';
import type { CompileErrorEntry, SfcState } from '../../protocol/types';
import { nearestIdForPointer } from '../../lib/jsonPointer';
import type { SfcDoc } from './types';
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
import { layoutChart } from './layout';
import { SfcChart } from './SfcChart';
import { StepForm } from './StepForm';
import { TransitionForm } from './TransitionForm';
import { VarsEditor } from '../shared/VarsEditor';

interface Props {
  doc: SfcDoc;
  onChange: (doc: SfcDoc) => void;
  errors: CompileErrorEntry[];
  readOnly: boolean;
  liveState?: SfcState;
}

type Selection = { kind: 'step'; id: string } | { kind: 'transition'; id: string } | null;

export function SfcEditor({ doc, onChange, errors, readOnly, liveState }: Props) {
  const [selection, setSelection] = useState<Selection>(null);

  const { normal, abort } = useMemo(() => layoutChart(doc), [doc]);

  const idToName = useMemo(() => new Map(doc.steps.map((s) => [s.id, s.name])), [doc.steps]);
  const { errorStepNames, errorTransitionIds } = useMemo(() => {
    const stepNames = new Set<string>();
    const transitionIds = new Set<string>();
    for (const e of errors) {
      if (!e.path) continue;
      const id = nearestIdForPointer(doc, e.path);
      if (!id) continue;
      if (idToName.has(id)) stepNames.add(idToName.get(id)!);
      else if (doc.transitions.some((t) => t.id === id)) transitionIds.add(id);
    }
    return { errorStepNames: stepNames, errorTransitionIds: transitionIds };
  }, [errors, doc, idToName]);

  const activeSteps = useMemo(() => new Set(liveState?.active_steps ?? []), [liveState]);
  const stepTimes = liveState?.step_times ?? {};

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (readOnly || !selection) return;
      const target = e.target as HTMLElement | null;
      if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
      if (e.key === 'Delete') {
        e.preventDefault();
        if (selection.kind === 'step' && confirm('Delete this step and its transitions?')) {
          onChange(deleteStep(doc, selection.id));
          setSelection(null);
        } else if (selection.kind === 'transition') {
          onChange(deleteTransition(doc, selection.id));
          setSelection(null);
        }
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [selection, readOnly, doc, onChange]);

  const selectedStep = selection?.kind === 'step' ? doc.steps.find((s) => s.id === selection.id) : undefined;
  const selectedTransition = selection?.kind === 'transition' ? doc.transitions.find((t) => t.id === selection.id) : undefined;

  return (
    <div className="sfc-editor">
      <div className="sfc-main">
        <div className="sfc-toolbar">
          <button disabled={readOnly || selection?.kind !== 'step'} onClick={() => selection && onChange(addStepAfter(doc, selection.id))}>
            + step after
          </button>
          <button
            disabled={readOnly || !(selection?.kind === 'step')}
            onClick={() => selection && onChange(addAlternativeBranch(doc, selection.id))}
          >
            + alternative branch
          </button>
          <button
            disabled={readOnly || !(selection?.kind === 'transition')}
            onClick={() => selection && onChange(addSimultaneousBranch(doc, selection.id, 'diverge'))}
          >
            + simultaneous branch
          </button>
          <label className="field checkbox inline">
            <input
              type="checkbox"
              checked={doc.autostart ?? false}
              disabled={readOnly}
              onChange={(e) => onChange({ ...doc, autostart: e.target.checked })}
            />
            <span>autostart</span>
          </label>
          <input
            className="description-field"
            placeholder="description"
            value={doc.description ?? ''}
            disabled={readOnly}
            onChange={(e) => onChange({ ...doc, description: e.target.value || undefined })}
          />
        </div>
        <div className="sfc-charts" onClick={() => setSelection(null)}>
          <div className="sfc-partition">
            <div className="sfc-partition-title">Normal chain</div>
            <SfcChart
              partition={normal}
              selectedStepId={selection?.kind === 'step' ? selection.id : null}
              selectedTransitionId={selection?.kind === 'transition' ? selection.id : null}
              errorStepNames={errorStepNames}
              errorTransitionIds={errorTransitionIds}
              activeSteps={activeSteps}
              stepTimes={stepTimes}
              onSelectStep={(id) => setSelection({ kind: 'step', id })}
              onSelectTransition={(id) => setSelection({ kind: 'transition', id })}
            />
          </div>
          {abort && (
            <div className="sfc-partition sfc-abort-partition">
              <div className="sfc-partition-title abort">Abort chain ({doc.abort_step})</div>
              <SfcChart
                partition={abort}
                selectedStepId={selection?.kind === 'step' ? selection.id : null}
                selectedTransitionId={selection?.kind === 'transition' ? selection.id : null}
                errorStepNames={errorStepNames}
                errorTransitionIds={errorTransitionIds}
                activeSteps={activeSteps}
                stepTimes={stepTimes}
                onSelectStep={(id) => setSelection({ kind: 'step', id })}
                onSelectTransition={(id) => setSelection({ kind: 'transition', id })}
              />
            </div>
          )}
        </div>
      </div>
      <div className="sfc-side">
        {selectedStep && (
          <StepForm
            step={selectedStep}
            isInitial={Boolean(selectedStep.initial)}
            isAbortStep={doc.abort_step === selectedStep.name}
            readOnly={readOnly}
            onChange={(patch) => {
              let next = doc;
              if (patch.name && patch.name !== selectedStep.name) next = renameStep(next, selectedStep.id, patch.name);
              next = { ...next, steps: next.steps.map((s) => (s.id === selectedStep.id ? { ...s, ...patch, name: s.name } : s)) };
              onChange(next);
            }}
            onSetInitial={() => onChange(setInitialStep(doc, selectedStep.id))}
            onSetAbortStep={() =>
              onChange({ ...doc, abort_step: doc.abort_step === selectedStep.name ? undefined : selectedStep.name })
            }
          />
        )}
        {selectedTransition && (
          <TransitionForm
            transition={selectedTransition}
            readOnly={readOnly}
            onChange={(patch) => onChange({ ...doc, transitions: doc.transitions.map((t) => (t.id === selectedTransition.id ? { ...t, ...patch } : t)) })}
          />
        )}
        {!selectedStep && !selectedTransition && (
          <div className="side-form empty">
            Select a step or transition. Tip: select two steps' transition to link them, or use the toolbar to grow the chart.
          </div>
        )}
        <div className="sfc-link-tool">
          <LinkSteps doc={doc} readOnly={readOnly} onChange={onChange} />
        </div>
        <VarsEditor vars={doc.vars} readOnly={readOnly} onChange={(vars) => onChange({ ...doc, vars })} />
      </div>
    </div>
  );
}

function LinkSteps({ doc, readOnly, onChange }: { doc: SfcDoc; readOnly: boolean; onChange: (d: SfcDoc) => void }) {
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  return (
    <details className="vars-editor">
      <summary>Add transition between steps</summary>
      <div className="var-row">
        <select value={from} disabled={readOnly} onChange={(e) => setFrom(e.target.value)}>
          <option value="">from…</option>
          {doc.steps.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <select value={to} disabled={readOnly} onChange={(e) => setTo(e.target.value)}>
          <option value="">to…</option>
          {doc.steps.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        <button
          disabled={readOnly || !from || !to}
          onClick={() => {
            onChange(addTransitionBetween(doc, from, to));
            setFrom('');
            setTo('');
          }}
        >
          link
        </button>
      </div>
    </details>
  );
}
