import type { UseSimResult } from '../protocol/useSim';
import { VALVE_POS, READOUT_POS, VIEWBOX } from './layout';
import { ValveSymbol } from './ValveSymbol';
import { Readout } from './Readout';

interface Props {
  sim: UseSimResult;
}

/** Simplified process mimic -- schematic arrangement of `Draco V4.02.pdf`, not a
 * geometric redraw of it. Pipe colours loosely follow the P&ID legend (orange
 * GN2, green pressurant lines, blue LOX run line, red fuel run line, purple
 * purge, grey muscle bus). */
export function ProcessMimic({ sim }: Props) {
  return (
    <svg className="process-mimic" viewBox={VIEWBOX} preserveAspectRatio="xMidYMid meet">
      {/* GN2 bottle bank */}
      <g className="pid-static">
        {[430, 470, 510, 550].map((bx) => (
          <rect key={bx} x={bx} y={15} width={30} height={55} rx={8} className="pid-bottle" />
        ))}
        <text x={490} y={10} textAnchor="middle" className="pid-label">
          GN2 4x6K
        </text>

        {/* GN2 manifold branches */}
        <path d="M490,70 V90 H230 V120" className="pid-pipe pipe-gn2" />
        <path d="M490,90 H750 V120" className="pid-pipe pipe-gn2" />

        {/* LOX pressurant / vent */}
        <path d="M230,120 V190" className="pid-pipe pipe-lox" />
        <path d="M230,150 H140 V190" className="pid-pipe pipe-lox" />
        <path d="M140,190 L140,190" className="pid-pipe pipe-lox" />
        <path d="M230,190 V220" className="pid-pipe pipe-lox" />

        {/* Fuel pressurant / vent */}
        <path d="M750,120 V190" className="pid-pipe pipe-fuel" />
        <path d="M750,150 H840 V190" className="pid-pipe pipe-fuel" />
        <path d="M750,190 V220" className="pid-pipe pipe-fuel" />

        {/* Tanks */}
        <rect x={150} y={220} width={110} height={200} rx={6} className="pid-tank" />
        <text x={205} y={330} textAnchor="middle" className="pid-label pid-label-v">
          LOX TANK
        </text>
        <rect x={740} y={220} width={110} height={200} rx={6} className="pid-tank" />
        <text x={795} y={330} textAnchor="middle" className="pid-label pid-label-v">
          FUEL TANK
        </text>

        {/* LOX Dewar + fill */}
        <rect x={30} y={430} width={70} height={90} rx={6} className="pid-tank pid-dewar" />
        <text x={65} y={478} textAnchor="middle" className="pid-label pid-label-v small">
          LOX DEWAR
        </text>
        <path d="M100,470 H140" className="pid-pipe pipe-lox" />
        <path d="M140,470 H205 V420" className="pid-pipe pipe-lox" />

        {/* LOX run line: tank -> V1 -> PB6 -> PB2 -> engine */}
        <path d="M205,420 V572" className="pid-pipe pipe-lox" />
        <rect x={185} y={505} width={40} height={20} className="pid-venturi" />
        <text x={205} y={519} textAnchor="middle" className="pid-venturi-label">
          V1
        </text>
        <path d="M205,540 H275" className="pid-pipe pipe-purge" />
        <path d="M205,572 V592 H350 V606" className="pid-pipe pipe-lox" />

        {/* Fuel run line: tank -> V2 -> PB4 -> engine */}
        <path d="M795,420 V572" className="pid-pipe pipe-fuel" />
        <rect x={775} y={505} width={40} height={20} className="pid-venturi" />
        <text x={795} y={519} textAnchor="middle" className="pid-venturi-label">
          V2
        </text>
        <path d="M795,540 H725" className="pid-pipe pipe-purge" />
        <path d="M795,572 V592 H650 V606" className="pid-pipe pipe-fuel" />

        {/* Purge manifold + muscle bus */}
        <rect x={440} y={520} width={120} height={40} className="pid-manifold" />
        <text x={500} y={514} textAnchor="middle" className="pid-label small">
          PURGE MANIFOLD
        </text>
        <path d="M500,460 V500" className="pid-pipe pipe-muscle" />
        <text x={500} y={450} textAnchor="middle" className="pid-label small">
          MUSCLE BUS
        </text>

        {/* Engine */}
        <rect x={430} y={575} width={140} height={30} rx={4} className="pid-engine" />
        <path d="M470,605 L530,605 L500,620 Z" className="pid-engine" />
        <text x={500} y={568} textAnchor="middle" className="pid-label small">
          ENGINE
        </text>
      </g>

      {VALVE_POS.map((p) => (
        <ValveSymbol key={p.tag} sim={sim} pos={p} />
      ))}
      {READOUT_POS.map((p) => (
        <Readout key={p.tag} sim={sim} pos={p} />
      ))}
    </svg>
  );
}
