import { asArray, type Transition } from './types';
import { COL_STRIDE, MARGIN, ROW_STRIDE, STEP_H, STEP_W, type Partition, type StepPos } from './layout';

interface Props {
  partition: Partition;
  selectedStepId: string | null;
  selectedTransitionId: string | null;
  errorStepNames: Set<string>;
  errorTransitionIds: Set<string>;
  activeSteps: Set<string>;
  stepTimes: Record<string, number>;
  onSelectStep: (id: string) => void;
  onSelectTransition: (id: string) => void;
}

function cx(p: StepPos): number {
  return MARGIN + p.col * COL_STRIDE + STEP_W / 2;
}
function topY(p: StepPos): number {
  return MARGIN + p.depth * ROW_STRIDE;
}
function bottomY(p: StepPos): number {
  return topY(p) + STEP_H;
}

export function SfcChart({
  partition,
  selectedStepId,
  selectedTransitionId,
  errorStepNames,
  errorTransitionIds,
  activeSteps,
  stepTimes,
  onSelectStep,
  onSelectTransition,
}: Props) {
  const byName = new Map(partition.steps.map((p) => [p.step.name, p]));

  return (
    <svg width={partition.width} height={partition.height} style={{ display: 'block' }}>
      {partition.transitions.map((t) => (
        <TransitionMark
          key={t.id}
          t={t}
          byName={byName}
          selected={t.id === selectedTransitionId}
          error={errorTransitionIds.has(t.id)}
          onSelect={() => onSelectTransition(t.id)}
        />
      ))}
      {partition.steps.map((p) => {
        const isActive = activeSteps.has(p.step.name);
        const isSelected = p.step.id === selectedStepId;
        const isError = errorStepNames.has(p.step.name);
        const x = MARGIN + p.col * COL_STRIDE;
        const y = topY(p);
        return (
          <g
            key={p.step.id}
            transform={`translate(${x}, ${y})`}
            onClick={(e) => {
              e.stopPropagation();
              onSelectStep(p.step.id);
            }}
            style={{ cursor: 'pointer' }}
          >
            <rect
              width={STEP_W}
              height={STEP_H}
              rx={3}
              fill={isActive ? '#1d4a2e' : '#15202b'}
              stroke={isError ? '#ff6b6b' : isSelected ? '#4aa3ff' : isActive ? '#5ce07b' : '#5a7185'}
              strokeWidth={isSelected || isError ? 2.5 : 1.5}
            />
            {p.step.initial && (
              <rect x={4} y={4} width={STEP_W - 8} height={STEP_H - 8} rx={2} fill="none" stroke="#5a7185" strokeWidth={1} />
            )}
            <text x={STEP_W / 2} y={STEP_H / 2 - 2} textAnchor="middle" fontSize={12} fill="#e2ecf3" fontWeight={600}>
              {p.step.name}
            </text>
            {isActive && (
              <text x={STEP_W / 2} y={STEP_H / 2 + 14} textAnchor="middle" fontSize={9} fill="#8fe0a6">
                T={stepTimes[p.step.name]?.toFixed(2) ?? '0.00'}s
              </text>
            )}
            {p.step.comment && <title>{p.step.comment}</title>}
          </g>
        );
      })}
    </svg>
  );
}

function TransitionMark({
  t,
  byName,
  selected,
  error,
  onSelect,
}: {
  t: Transition;
  byName: Map<string, StepPos>;
  selected: boolean;
  error: boolean;
  onSelect: () => void;
}) {
  const froms = asArray(t.from).map((n) => byName.get(n)).filter((p): p is StepPos => Boolean(p));
  const tos = asArray(t.to).map((n) => byName.get(n)).filter((p): p is StepPos => Boolean(p));
  if (froms.length === 0 || tos.length === 0) return null;
  const maxFromBottom = Math.max(...froms.map(bottomY));
  const barY = maxFromBottom + 28;
  const xs = [...froms.map(cx), ...tos.map(cx)];
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const simultaneous = froms.length > 1 || tos.length > 1;
  const color = error ? '#ff6b6b' : selected ? '#4aa3ff' : '#8aa0b0';

  return (
    <g onClick={(e) => { e.stopPropagation(); onSelect(); }} style={{ cursor: 'pointer' }}>
      {froms.map((p) => (
        <line key={`f${p.step.id}`} x1={cx(p)} y1={bottomY(p)} x2={cx(p)} y2={barY} stroke={color} strokeWidth={1.5} />
      ))}
      {tos.map((p) => (
        <line key={`to${p.step.id}`} x1={cx(p)} y1={barY} x2={cx(p)} y2={topY(p)} stroke={color} strokeWidth={1.5} />
      ))}
      <line x1={minX - 14} y1={barY} x2={maxX + 14} y2={barY} stroke={color} strokeWidth={selected || error ? 3 : 2} />
      {simultaneous && (
        <line x1={minX - 14} y1={barY + 4} x2={maxX + 14} y2={barY + 4} stroke={color} strokeWidth={2} />
      )}
      <text x={maxX + 20} y={barY + 4} fontSize={10} fill={color}>
        {t.condition.length > 24 ? t.condition.slice(0, 23) + '…' : t.condition}
      </text>
      {t.comment && <title>{t.comment}</title>}
    </g>
  );
}
