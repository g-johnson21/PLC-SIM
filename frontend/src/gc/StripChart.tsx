import type { Sample } from './useSeriesBuffer';

interface Props {
  points: Sample[];
  nowT: number | undefined;
  windowSec: number;
  domain: [number, number];
  setpoint?: number;
  deadband?: number;
  width?: number;
  height?: number;
  unit?: string;
}

/** Hand-rolled SVG strip chart -- last `windowSec` of a feedback pressure, with
 * the bang-bang setpoint +/- deadband drawn as a band. No charting dependency. */
export function StripChart({ points, nowT, windowSec, domain, setpoint, deadband, width = 260, height = 90, unit }: Props) {
  const [lo, hi] = domain;
  const span = hi - lo || 1;
  const t1 = nowT ?? points[points.length - 1]?.t ?? windowSec;
  const t0 = t1 - windowSec;

  const x = (t: number) => ((t - t0) / windowSec) * width;
  const y = (v: number) => height - ((v - lo) / span) * height;

  const path = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${x(p.t).toFixed(1)},${y(p.value).toFixed(1)}`)
    .join(' ');

  const bandTop = setpoint !== undefined && deadband !== undefined ? y(Math.min(hi, setpoint + deadband)) : null;
  const bandBottom = setpoint !== undefined && deadband !== undefined ? y(Math.max(lo, setpoint - deadband)) : null;

  return (
    <svg className="strip-chart" viewBox={`0 0 ${width} ${height}`} width={width} height={height} preserveAspectRatio="none">
      <rect x={0} y={0} width={width} height={height} className="strip-chart-bg" />
      {bandTop !== null && bandBottom !== null && (
        <rect x={0} y={bandTop} width={width} height={Math.max(0, bandBottom - bandTop)} className="strip-chart-band" />
      )}
      {setpoint !== undefined && setpoint >= lo && setpoint <= hi && (
        <line x1={0} x2={width} y1={y(setpoint)} y2={y(setpoint)} className="strip-chart-setpoint" />
      )}
      {points.length > 1 && <path d={path} className="strip-chart-line" />}
      <text x={3} y={11} className="strip-chart-label">
        {hi.toFixed(0)}
        {unit}
      </text>
      <text x={3} y={height - 3} className="strip-chart-label">
        {lo.toFixed(0)}
        {unit}
      </text>
    </svg>
  );
}
