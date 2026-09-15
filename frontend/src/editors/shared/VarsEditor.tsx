import type { VarDecl } from './types';

interface Props {
  vars: VarDecl[];
  readOnly: boolean;
  onChange: (vars: VarDecl[]) => void;
}

const TYPES = ['BOOL', 'INT', 'DINT', 'REAL', 'TIME', 'STRING', 'TON', 'TOF', 'TP', 'CTU', 'CTD', 'CTUD', 'R_TRIG', 'F_TRIG', 'SR', 'RS'];

export function VarsEditor({ vars, readOnly, onChange }: Props) {
  function update(i: number, patch: Partial<VarDecl>) {
    onChange(vars.map((v, idx) => (idx === i ? { ...v, ...patch } : v)));
  }
  function add() {
    onChange([...vars, { name: `var${vars.length + 1}`, type: 'BOOL', scope: 'VAR' }]);
  }
  function remove(i: number) {
    onChange(vars.filter((_, idx) => idx !== i));
  }

  return (
    <details className="vars-editor" open={vars.length > 0}>
      <summary>Variables ({vars.length})</summary>
      {vars.map((v, i) => (
        <div className="var-row" key={i}>
          <input
            value={v.name}
            disabled={readOnly}
            onChange={(e) => update(i, { name: e.target.value })}
            placeholder="name"
          />
          <select value={v.type} disabled={readOnly} onChange={(e) => update(i, { type: e.target.value })}>
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <select
            value={v.scope ?? 'VAR'}
            disabled={readOnly}
            onChange={(e) => update(i, { scope: e.target.value as VarDecl['scope'] })}
          >
            <option value="VAR">VAR</option>
            <option value="VAR_GLOBAL">VAR_GLOBAL</option>
            <option value="VAR_RETAIN">VAR_RETAIN</option>
          </select>
          <input
            value={v.init != null ? String(v.init) : ''}
            disabled={readOnly}
            placeholder="init"
            onChange={(e) => {
              const t = e.target.value;
              const num = Number(t);
              const init = t === '' ? undefined : t === 'true' ? true : t === 'false' ? false : Number.isNaN(num) ? t : num;
              update(i, { init });
            }}
          />
          <button disabled={readOnly} onClick={() => remove(i)}>
            ✕
          </button>
        </div>
      ))}
      <button disabled={readOnly} onClick={add}>
        + var
      </button>
    </details>
  );
}
