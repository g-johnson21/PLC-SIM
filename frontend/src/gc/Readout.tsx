import type { UseSimResult } from '../protocol/useSim';
import { findTag } from './tagHelpers';
import type { ReadoutPos } from './layout';

interface Props {
  sim: UseSimResult;
  pos: ReadoutPos;
}

export function Readout({ sim, pos }: Props) {
  const { tag, x, y } = pos;
  const tagInfo = findTag(sim.welcome?.tags, tag);
  const value = sim.state?.inputs[tag];
  const running = sim.state?.plc.running ?? false;
  const nonfinite = sim.state?.nonfinite.includes(`inputs.${tag}`);

  return (
    <g className={`readout ${running ? '' : 'readout-stopped'}`} transform={`translate(${x - 32},${y - 13})`}>
      <title>{tagInfo?.description || tag}</title>
      <rect width={64} height={26} rx={3} className="readout-box" />
      <text x={4} y={10} className="readout-tag">
        {tag}
      </text>
      <text x={4} y={21} className="readout-value">
        {nonfinite ? 'n/a' : value === undefined ? '—' : value.toFixed(tagInfo?.units === 'degF' ? 0 : 1)}
        {tagInfo?.units && !nonfinite ? ` ${tagInfo.units}` : ''}
      </text>
    </g>
  );
}
