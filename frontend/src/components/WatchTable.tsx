import { useState } from 'react';
import type { UseSimResult } from '../protocol/useSim';
import { DRACO_TAGS } from '../protocol/tags.generated';
import { lockoutReason } from '../gc/abortUi';

interface Props {
  sim: UseSimResult;
}

function GlobalRow({ name, value, forced, onWrite, onForce, onUnforce }: {
  name: string;
  value: unknown;
  forced: boolean;
  onWrite: (v: number | boolean | string) => void;
  onForce: () => void;
  onUnforce: () => void;
}) {
  const [draft, setDraft] = useState(String(value));
  return (
    <tr className={forced ? 'forced' : ''}>
      <td>{name}</td>
      <td>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              const num = Number(draft);
              onWrite(draft === 'true' ? true : draft === 'false' ? false : Number.isNaN(num) ? draft : num);
            }
          }}
        />
      </td>
      <td>
        <button onClick={onForce}>force</button>
        {forced && <button onClick={onUnforce}>unforce</button>}
      </td>
    </tr>
  );
}

function AddGlobalRow({ onAdd }: { onAdd: (name: string, value: number | boolean | string) => void }) {
  const [name, setName] = useState('');
  const [value, setValue] = useState('');
  return (
    <tr>
      <td>
        <input placeholder="new global name" value={name} onChange={(e) => setName(e.target.value)} />
      </td>
      <td colSpan={2}>
        <input
          placeholder="value"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && name) {
              const num = Number(value);
              onAdd(name, value === 'true' ? true : value === 'false' ? false : Number.isNaN(num) ? value : num);
              setName('');
              setValue('');
            }
          }}
        />
      </td>
    </tr>
  );
}

export function WatchTable({ sim }: Props) {
  const globals = sim.state?.plc.globals ?? {};
  const forced = sim.state?.plc.forced ?? {};
  const outputForceBlocked = sim.state ? lockoutReason(sim.state, 'forceOutput') : null;

  return (
    <div className="watch-table">
      <h4>Watch — VAR_GLOBAL</h4>
      <table>
        <thead>
          <tr>
            <th>name</th>
            <th>value</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(globals).map(([name, value]) => (
            <GlobalRow
              key={name}
              name={name}
              value={value}
              forced={name in forced}
              onWrite={(v) => void sim.sim.write({ [`plc.globals.${name}`]: v })}
              onForce={() => {
                const v = prompt(`Force value for ${name}`, String(value));
                if (v == null) return;
                const num = Number(v);
                void sim.sim.force(name, v === 'true' ? true : v === 'false' ? false : Number.isNaN(num) ? num : num);
              }}
              onUnforce={() => void sim.sim.unforce(name)}
            />
          ))}
          {Object.keys(globals).length === 0 && (
            <tr>
              <td colSpan={3} className="empty">
                No globals reported yet (load a program with VAR_GLOBAL, or wait for the mock's next state tick).
              </td>
            </tr>
          )}
          <AddGlobalRow onAdd={(name, value) => void sim.sim.write({ [`plc.globals.${name}`]: value })} />
        </tbody>
      </table>
      <h4>Tags</h4>
      <table>
        <thead>
          <tr>
            <th>tag</th>
            <th>dir</th>
            <th>value</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {DRACO_TAGS.map((tag) => {
            const value = tag.direction === 'in' ? sim.state?.inputs[tag.name] : sim.state?.outputs[tag.name];
            const isForced = tag.name in forced;
            return (
              <tr key={tag.name} className={isForced ? 'forced' : ''}>
                <td title={tag.description}>{tag.name}</td>
                <td>{tag.direction}</td>
                <td>{value === undefined ? '—' : String(value)}</td>
                <td>
                  <button
                    disabled={tag.direction === 'out' && outputForceBlocked !== null}
                    title={tag.direction === 'out' ? (outputForceBlocked ?? undefined) : undefined}
                    onClick={() => {
                      const v = prompt(`Force value for ${tag.name}`, String(value ?? (tag.dtype === 'BOOL' ? 'false' : '0')));
                      if (v == null) return;
                      if (tag.dtype === 'BOOL') void sim.sim.force(tag.name, v === 'true');
                      else void sim.sim.force(tag.name, Number(v));
                    }}
                  >
                    force
                  </button>
                  {isForced && <button onClick={() => void sim.sim.unforce(tag.name)}>unforce</button>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
