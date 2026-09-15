// Simplified schematic layout for the process mimic, following the arrangement
// of `Draco V4.02.pdf` (GN2 bottles top, LOX train left, fuel train right,
// purge/muscle bus centre, engine bottom). Coordinates are hand-placed for a
// 1000x620 viewBox -- this is a simplification of the P&ID, not a redraw of it.

export const VIEWBOX = '0 0 1000 620';

export interface ValvePos {
  tag: string;
  x: number;
  y: number;
}

export const VALVE_POS: ValvePos[] = [
  { tag: 'S1', x: 230, y: 120 },
  { tag: 'PB1', x: 140, y: 190 },
  { tag: 'S2', x: 750, y: 120 },
  { tag: 'PB3', x: 840, y: 190 },
  { tag: 'PB5', x: 140, y: 470 },
  { tag: 'PB6', x: 205, y: 540 },
  { tag: 'PB2', x: 205, y: 572 },
  { tag: 'PB4', x: 795, y: 572 },
  { tag: 'S4', x: 275, y: 540 },
  { tag: 'S5', x: 725, y: 540 },
  { tag: 'S3', x: 500, y: 460 },
];

export interface ReadoutPos {
  tag: string;
  x: number;
  y: number;
}

export const READOUT_POS: ReadoutPos[] = [
  // LOX GN2 branch
  { tag: 'PT1', x: 300, y: 90 },
  { tag: 'PT2', x: 230, y: 160 },
  { tag: 'PT3', x: 270, y: 100 },
  { tag: 'TC7', x: 195, y: 100 },
  // LOX tank
  { tag: 'TC2', x: 130, y: 240 },
  { tag: 'TC1', x: 130, y: 400 },
  { tag: 'LC4', x: 205, y: 428 },
  // LOX run line
  { tag: 'PT4', x: 205, y: 490 },
  { tag: 'PT21', x: 165, y: 515 },
  { tag: 'PT22', x: 245, y: 515 },
  { tag: 'TC3', x: 165, y: 500 },
  { tag: 'TC4', x: 245, y: 500 },
  { tag: 'PT5', x: 350, y: 592 },
  { tag: 'TC5', x: 350, y: 606 },
  // Fuel GN2 branch
  { tag: 'PT11', x: 690, y: 90 },
  { tag: 'PT12', x: 750, y: 160 },
  { tag: 'PT13', x: 728, y: 100 },
  { tag: 'TC6', x: 800, y: 100 },
  // Fuel tank
  { tag: 'LC_FUEL', x: 795, y: 428 },
  // Fuel run line
  { tag: 'PT14', x: 795, y: 490 },
  { tag: 'PT23', x: 755, y: 515 },
  { tag: 'PT24', x: 835, y: 515 },
  { tag: 'PT15', x: 650, y: 592 },
  // Purge / muscle bus
  { tag: 'PT31', x: 500, y: 430 },
  { tag: 'PT32', x: 500, y: 500 },
  { tag: 'PT33', x: 500, y: 545 },
  // Engine
  { tag: 'PT0', x: 460, y: 592 },
  { tag: 'TC8', x: 460, y: 606 },
  { tag: 'LC1', x: 555, y: 592 },
  { tag: 'LC2', x: 555, y: 606 },
  { tag: 'LC3', x: 610, y: 592 },
  { tag: 'THRUST', x: 610, y: 606 },
];
