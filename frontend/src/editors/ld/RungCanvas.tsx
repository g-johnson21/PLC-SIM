import type { LeafElement } from './types';
import { layoutRung, colX, ROW } from './layout';
import { operandToText } from '../shared/types';
import { elementBoolValue, type ValueLookup } from './model';

interface Props {
  logic: import('./types').Network;
  selectedId: string | null;
  errorIds: Set<string>;
  onSelect: (id: string) => void;
  lookup?: ValueLookup;
}

function operandLabel(el: LeafElement): string {
  switch (el.type) {
    case 'contact':
    case 'coil':
      return operandToText(el.operand);
    case 'timer':
      return `${el.instance ?? ''} PT=${operandToText(el.pt)}`.trim();
    case 'counter':
      return `${el.instance ?? ''} PV=${operandToText(el.pv)}`.trim();
    case 'compare':
      return `${operandToText(el.a)} ${el.op} ${operandToText(el.b)}`;
    case 'move':
      return `${operandToText(el.src)} -> ${operandToText(el.dst)}`;
    case 'math':
      return `${operandToText(el.a)} ${el.op} ${operandToText(el.b)} -> ${operandToText(el.dst)}`;
    default:
      return '';
  }
}

function ContactSymbol({ el, energized }: { el: Extract<LeafElement, { type: 'contact' }>; energized?: boolean }) {
  const color = energized == null ? '#7d8b98' : energized ? '#5ce07b' : '#4a5763';
  return (
    <g stroke={color} strokeWidth={2} fill="none">
      <line x1={-6} y1={-9} x2={-6} y2={9} />
      <line x1={6} y1={-9} x2={6} y2={9} />
      {el.kind === 'NC' && <line x1={-9} y1={9} x2={9} y2={-9} />}
      {el.kind === 'P' && <text x={0} y={-13} fontSize={9} fill={color} stroke="none" textAnchor="middle">P</text>}
      {el.kind === 'N' && <text x={0} y={-13} fontSize={9} fill={color} stroke="none" textAnchor="middle">N</text>}
    </g>
  );
}

function CoilSymbol({ el, energized }: { el: Extract<LeafElement, { type: 'coil' }>; energized?: boolean }) {
  const color = energized == null ? '#7d8b98' : energized ? '#5ce07b' : '#4a5763';
  const label = el.kind === 'SET' ? 'S' : el.kind === 'RESET' ? 'R' : el.kind === 'NEGATED' ? '/' : '';
  return (
    <g stroke={color} strokeWidth={2} fill="none">
      <circle cx={0} cy={0} r={10} />
      {label && (
        <text x={0} y={4} fontSize={10} fill={color} stroke="none" textAnchor="middle" fontWeight="bold">
          {label}
        </text>
      )}
    </g>
  );
}

function BlockSymbol({ el }: { el: LeafElement }) {
  const title = el.type === 'timer' ? el.fb : el.type === 'counter' ? el.fb : el.type === 'compare' ? el.op : el.type === 'math' ? el.op : 'MOVE';
  return (
    <g>
      <rect x={-48} y={-16} width={96} height={32} rx={3} fill="#152029" stroke="#5a7185" strokeWidth={1.5} />
      <text x={0} y={-3} fontSize={10} fill="#9fd6ff" textAnchor="middle" fontWeight="bold">
        {title}
      </text>
    </g>
  );
}

export function RungCanvas({ logic, selectedId, errorIds, onSelect, lookup }: Props) {
  const layout = layoutRung(logic);
  const railTop = 0;
  const railBottom = layout.height;
  const leftX = colX(0);
  const rightX = colX(layout.cols);

  return (
    <svg width={layout.width} height={layout.height} style={{ display: 'block' }}>
      <line x1={leftX} y1={railTop} x2={leftX} y2={railBottom} stroke="#7d8b98" strokeWidth={3} />
      <line x1={rightX} y1={railTop} x2={rightX} y2={railBottom} stroke="#7d8b98" strokeWidth={3} />
      {layout.wires.map((w, i) => (
        <line key={i} x1={w.x1} y1={w.y1} x2={w.x2} y2={w.y2} stroke="#5a6b7a" strokeWidth={2} />
      ))}
      {layout.boxes.map((box) => {
        const isSelected = box.el.id === selectedId;
        const isError = errorIds.has(box.el.id);
        const energized = lookup ? elementBoolValue(box.el, lookup) : undefined;
        const label = operandLabel(box.el);
        return (
          <g
            key={box.el.id}
            transform={`translate(${box.cx}, ${box.cy})`}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(box.el.id);
            }}
            style={{ cursor: 'pointer' }}
          >
            {(isSelected || isError) && (
              <rect
                x={-58}
                y={-22}
                width={116}
                height={44}
                rx={4}
                fill="none"
                stroke={isError ? '#ff6b6b' : '#4aa3ff'}
                strokeWidth={2}
                strokeDasharray={isError ? '4 2' : undefined}
              />
            )}
            {box.el.type === 'contact' && <ContactSymbol el={box.el} energized={energized as boolean | undefined} />}
            {box.el.type === 'coil' && <CoilSymbol el={box.el} energized={energized as boolean | undefined} />}
            {(box.el.type === 'timer' || box.el.type === 'counter' || box.el.type === 'compare' || box.el.type === 'move' || box.el.type === 'math') && (
              <BlockSymbol el={box.el} />
            )}
            {label && (
              <text x={0} y={ROW / 2 - 6} fontSize={9} fill="#9aa9b6" textAnchor="middle">
                {label.length > 20 ? label.slice(0, 19) + '…' : label}
              </text>
            )}
            {box.el.comment && <title>{box.el.comment}</title>}
          </g>
        );
      })}
    </svg>
  );
}
