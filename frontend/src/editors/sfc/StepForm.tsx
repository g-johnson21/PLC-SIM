import type { Action, Step } from './types';
import { newId } from '../../lib/id';

interface Props {
  step: Step;
  isInitial: boolean;
  isAbortStep: boolean;
  readOnly: boolean;
  onChange: (patch: Partial<Step>) => void;
  onSetInitial: () => void;
  onSetAbortStep: () => void;
}

const QUALIFIERS: Action['qualifier'][] = ['N', 'S', 'R', 'P', 'P0', 'D'];

export function StepForm({ step, isInitial, isAbortStep, readOnly, onChange, onSetInitial, onSetAbortStep }: Props) {
  const actions = step.actions ?? [];

  function updateAction(i: number, patch: Partial<Action>) {
    onChange({ actions: actions.map((a, idx) => (idx === i ? { ...a, ...patch } : a)) });
  }
  function addAction() {
    onChange({ actions: [...actions, { id: newId('a'), qualifier: 'N', body: '' }] });
  }
  function removeAction(i: number) {
    onChange({ actions: actions.filter((_, idx) => idx !== i) });
  }

  return (
    <div className="side-form">
      <h4>STEP</h4>
      <label className="field">
        <span>name</span>
        <input value={step.name} disabled={readOnly} onChange={(e) => onChange({ name: e.target.value })} />
      </label>
      <label className="field checkbox">
        <input type="checkbox" checked={isInitial} disabled={readOnly} onChange={onSetInitial} />
        <span>initial step</span>
      </label>
      <label className="field checkbox">
        <input type="checkbox" checked={isAbortStep} disabled={readOnly} onChange={onSetAbortStep} />
        <span>abort chain head</span>
      </label>
      <label className="field">
        <span>comment</span>
        <input value={step.comment ?? ''} disabled={readOnly} onChange={(e) => onChange({ comment: e.target.value || undefined })} />
      </label>
      <div className="actions-editor">
        <div className="actions-header">
          <span>Actions</span>
          <button disabled={readOnly} onClick={addAction}>
            + action
          </button>
        </div>
        {actions.map((a, i) => (
          <div className="action-row" key={a.id ?? i}>
            <div className="action-row-head">
              <select value={a.qualifier ?? 'N'} disabled={readOnly} onChange={(e) => updateAction(i, { qualifier: e.target.value as Action['qualifier'] })}>
                {QUALIFIERS.map((q) => (
                  <option key={q} value={q}>
                    {q}
                  </option>
                ))}
              </select>
              <input
                placeholder="name (for S/R pairing)"
                value={a.name ?? ''}
                disabled={readOnly}
                onChange={(e) => updateAction(i, { name: e.target.value || undefined })}
              />
              {a.qualifier === 'D' && (
                <input
                  placeholder="delay T#..."
                  value={String(a.delay ?? '')}
                  disabled={readOnly}
                  onChange={(e) => updateAction(i, { delay: e.target.value })}
                />
              )}
              <button disabled={readOnly} onClick={() => removeAction(i)}>
                ✕
              </button>
            </div>
            <textarea
              className="action-body"
              rows={2}
              value={a.body ?? ''}
              disabled={readOnly}
              placeholder="ST statement list, e.g. PB2 := TRUE;"
              onChange={(e) => updateAction(i, { body: e.target.value })}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
