import { asArray, type Transition } from './types';

interface Props {
  transition: Transition;
  readOnly: boolean;
  onChange: (patch: Partial<Transition>) => void;
}

export function TransitionForm({ transition, readOnly, onChange }: Props) {
  return (
    <div className="side-form">
      <h4>TRANSITION</h4>
      <label className="field">
        <span>from</span>
        <input
          value={asArray(transition.from).join(', ')}
          disabled={readOnly}
          onChange={(e) => {
            const parts = e.target.value.split(',').map((s) => s.trim()).filter(Boolean);
            onChange({ from: parts.length <= 1 ? parts[0] ?? '' : parts });
          }}
        />
      </label>
      <label className="field">
        <span>to</span>
        <input
          value={asArray(transition.to).join(', ')}
          disabled={readOnly}
          onChange={(e) => {
            const parts = e.target.value.split(',').map((s) => s.trim()).filter(Boolean);
            onChange({ to: parts.length <= 1 ? parts[0] ?? '' : parts });
          }}
        />
      </label>
      <label className="field">
        <span>condition (ST boolean expr)</span>
        <input value={transition.condition} disabled={readOnly} onChange={(e) => onChange({ condition: e.target.value })} />
      </label>
      <label className="field">
        <span>comment</span>
        <input value={transition.comment ?? ''} disabled={readOnly} onChange={(e) => onChange({ comment: e.target.value || undefined })} />
      </label>
    </div>
  );
}
