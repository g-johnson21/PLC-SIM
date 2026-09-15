import { useState } from 'react';
import type { UseSimResult } from '../protocol/useSim';
import { ProtocolError } from '../protocol/client';
import { findTag, VALVE_ALIAS } from './tagHelpers';
import type { ValvePos } from './layout';
import { lockoutReason } from './abortUi';

interface Props {
  sim: UseSimResult;
  pos: ValvePos;
}

export function ValveSymbol({ sim, pos }: Props) {
  const { tag, x, y } = pos;
  const tagInfo = findTag(sim.welcome?.tags, tag);
  const alias = VALVE_ALIAS[tag];
  const open = sim.state?.outputs[tag];
  const blockedReason = lockoutReason(sim.state, 'valve', undefined, tag);
  const manualAllowed = blockedReason === null;
  const [toast, setToast] = useState<string | null>(null);

  function flash(text: string) {
    setToast(text);
    setTimeout(() => setToast((cur) => (cur === text ? null : cur)), 4000);
  }

  async function onClick() {
    if (blockedReason) {
      flash(blockedReason);
      return;
    }
    if (open === undefined) return;
    try {
      await sim.sim.write({ [tag]: !open });
    } catch (e) {
      if (e instanceof ProtocolError) flash(`${e.code} — ${e.message}`);
      else flash((e as Error).message);
    }
  }

  const stateClass = open === undefined ? 'valve-unknown' : open ? 'valve-open' : 'valve-closed';

  return (
    <g className={`valve-symbol ${stateClass} ${manualAllowed ? '' : 'valve-locked'}`} transform={`translate(${x - 34},${y - 17})`} onClick={onClick}>
      <rect width={68} height={34} rx={4} className="valve-box" />
      <text x={34} y={14} textAnchor="middle" className="valve-tag">
        {tag}
        {tagInfo?.normal_state && <tspan className="valve-normal"> ({tagInfo.normal_state})</tspan>}
      </text>
      <text x={34} y={26} textAnchor="middle" className="valve-alias">
        {alias ?? ''}
      </text>
      <text x={34} y={-4} textAnchor="middle" className="valve-fstate">
        {open === undefined ? '?' : open ? 'OPEN' : 'CLOSED'}
      </text>
      {toast && (
        <foreignObject x={-30} y={40} width={190} height={56}>
          <div className="valve-toast">{toast}</div>
        </foreignObject>
      )}
    </g>
  );
}
