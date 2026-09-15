import type { LeafElement } from './types';
import { operandToText, textToOperand } from '../shared/types';

interface Props {
  element: LeafElement | null;
  onChange: (patch: Partial<LeafElement>) => void;
}

function OperandField({ label, value, onChange }: { label: string; value: unknown; onChange: (v: unknown) => void }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input
        value={operandToText(value as never)}
        onChange={(e) => onChange(textToOperand(e.target.value))}
        placeholder="name, number, TRUE/FALSE, T#1s500ms"
      />
    </label>
  );
}

export function ElementForm({ element, onChange }: Props) {
  if (!element) {
    return <div className="side-form empty">Select an element to edit its operands.</div>;
  }
  const patch = (p: Record<string, unknown>) => onChange(p as Partial<LeafElement>);

  return (
    <div className="side-form">
      <h4>{element.type.toUpperCase()}</h4>
      {element.type === 'contact' && (
        <>
          <label className="field">
            <span>kind</span>
            <select value={element.kind} onChange={(e) => patch({ kind: e.target.value })}>
              <option value="NO">NO</option>
              <option value="NC">NC</option>
              <option value="P">P (rising edge)</option>
              <option value="N">N (falling edge)</option>
            </select>
          </label>
          <OperandField label="operand (BOOL)" value={element.operand} onChange={(v) => patch({ operand: v })} />
        </>
      )}
      {element.type === 'coil' && (
        <>
          <label className="field">
            <span>kind</span>
            <select value={element.kind} onChange={(e) => patch({ kind: e.target.value })}>
              <option value="COIL">COIL</option>
              <option value="SET">SET</option>
              <option value="RESET">RESET</option>
              <option value="NEGATED">NEGATED</option>
            </select>
          </label>
          <OperandField label="operand (writable BOOL)" value={element.operand} onChange={(v) => patch({ operand: v })} />
        </>
      )}
      {element.type === 'timer' && (
        <>
          <label className="field">
            <span>fb</span>
            <select value={element.fb} onChange={(e) => patch({ fb: e.target.value })}>
              <option value="TON">TON</option>
              <option value="TOF">TOF</option>
              <option value="TP">TP</option>
            </select>
          </label>
          <OperandField label="pt (TIME)" value={element.pt} onChange={(v) => patch({ pt: v })} />
          <label className="field">
            <span>instance</span>
            <input value={element.instance ?? ''} onChange={(e) => patch({ instance: e.target.value || undefined })} />
          </label>
          <OperandField label="in (optional)" value={element.in} onChange={(v) => patch({ in: v })} />
        </>
      )}
      {element.type === 'counter' && (
        <>
          <label className="field">
            <span>fb</span>
            <select value={element.fb} onChange={(e) => patch({ fb: e.target.value })}>
              <option value="CTU">CTU</option>
              <option value="CTD">CTD</option>
            </select>
          </label>
          <OperandField label="pv (INT)" value={element.pv} onChange={(v) => patch({ pv: v })} />
          <label className="field">
            <span>instance</span>
            <input value={element.instance ?? ''} onChange={(e) => patch({ instance: e.target.value || undefined })} />
          </label>
          {element.fb === 'CTU' ? (
            <OperandField label="cu (optional)" value={element.cu} onChange={(v) => patch({ cu: v })} />
          ) : (
            <OperandField label="cd (optional)" value={element.cd} onChange={(v) => patch({ cd: v })} />
          )}
        </>
      )}
      {element.type === 'compare' && (
        <>
          <label className="field">
            <span>op</span>
            <select value={element.op} onChange={(e) => patch({ op: e.target.value })}>
              {['GT', 'GE', 'EQ', 'NE', 'LE', 'LT'].map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </label>
          <OperandField label="a" value={element.a} onChange={(v) => patch({ a: v })} />
          <OperandField label="b" value={element.b} onChange={(v) => patch({ b: v })} />
        </>
      )}
      {element.type === 'move' && (
        <>
          <OperandField label="src" value={element.src} onChange={(v) => patch({ src: v })} />
          <OperandField label="dst (writable)" value={element.dst} onChange={(v) => patch({ dst: v })} />
        </>
      )}
      {element.type === 'math' && (
        <>
          <label className="field">
            <span>op</span>
            <select value={element.op} onChange={(e) => patch({ op: e.target.value })}>
              {['ADD', 'SUB', 'MUL', 'DIV'].map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </label>
          <OperandField label="a" value={element.a} onChange={(v) => patch({ a: v })} />
          <OperandField label="b" value={element.b} onChange={(v) => patch({ b: v })} />
          <OperandField label="dst (writable)" value={element.dst} onChange={(v) => patch({ dst: v })} />
        </>
      )}
      <label className="field">
        <span>comment</span>
        <input value={element.comment ?? ''} onChange={(e) => patch({ comment: e.target.value || undefined })} />
      </label>
    </div>
  );
}
