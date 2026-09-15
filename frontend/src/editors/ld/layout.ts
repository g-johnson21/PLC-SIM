import type { LeafElement, Network } from './types';

export const COL = 132;
export const ROW = 56;
export const RAIL_X = 20;
export const PAD_TOP = 14;
export const RIGHT_MARGIN = 20;

export interface Wire {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}
export interface Box {
  el: LeafElement;
  col: number;
  row: number;
  cx: number;
  cy: number;
}
export interface RungLayout {
  cols: number;
  rows: number;
  width: number;
  height: number;
  wires: Wire[];
  boxes: Box[];
}

export function colX(c: number): number {
  return RAIL_X + c * COL;
}
export function rowY(r: number): number {
  return PAD_TOP + r * ROW + ROW / 2;
}

export function measure(net: Network): { rows: number; cols: number } {
  if (net.type === 'series') {
    if (net.elements.length === 0) return { rows: 1, cols: 1 };
    let cols = 0;
    let rows = 1;
    for (const e of net.elements) {
      const m = measure(e);
      cols += m.cols;
      rows = Math.max(rows, m.rows);
    }
    return { rows, cols: Math.max(cols, 1) };
  }
  if (net.type === 'parallel') {
    if (net.branches.length === 0) return { rows: 1, cols: 1 };
    let rows = 0;
    let cols = 0;
    for (const b of net.branches) {
      const m = measure(b);
      rows += m.rows;
      cols = Math.max(cols, m.cols);
    }
    return { rows: Math.max(rows, 1), cols: Math.max(cols, 1) };
  }
  return { rows: 1, cols: 1 };
}

function place(net: Network, rowOffset: number, colOffset: number, wires: Wire[], boxes: Box[]) {
  if (net.type === 'series') {
    if (net.elements.length === 0) {
      wires.push({ x1: colX(colOffset), y1: rowY(rowOffset), x2: colX(colOffset + 1), y2: rowY(rowOffset) });
      return;
    }
    let col = colOffset;
    for (const e of net.elements) {
      const m = measure(e);
      place(e, rowOffset, col, wires, boxes);
      col += m.cols;
    }
    return;
  }
  if (net.type === 'parallel') {
    const maxCols = measure(net).cols;
    let row = rowOffset;
    for (const b of net.branches) {
      const m = measure(b);
      place(b, row, colOffset, wires, boxes);
      if (m.cols < maxCols) {
        wires.push({ x1: colX(colOffset + m.cols), y1: rowY(row), x2: colX(colOffset + maxCols), y2: rowY(row) });
      }
      row += m.rows;
    }
    const yTop = rowY(rowOffset);
    const yBot = rowY(row - 1);
    wires.push({ x1: colX(colOffset), y1: yTop, x2: colX(colOffset), y2: yBot });
    wires.push({ x1: colX(colOffset + maxCols), y1: yTop, x2: colX(colOffset + maxCols), y2: yBot });
    return;
  }
  // leaf
  wires.push({ x1: colX(colOffset), y1: rowY(rowOffset), x2: colX(colOffset + 1), y2: rowY(rowOffset) });
  boxes.push({ el: net, col: colOffset, row: rowOffset, cx: colX(colOffset) + COL / 2, cy: rowY(rowOffset) });
}

export function layoutRung(logic: Network): RungLayout {
  const { rows, cols } = measure(logic);
  const wires: Wire[] = [];
  const boxes: Box[] = [];
  place(logic, 0, 0, wires, boxes);
  return {
    cols,
    rows,
    width: RAIL_X + cols * COL + RIGHT_MARGIN,
    height: PAD_TOP * 2 + rows * ROW,
    wires,
    boxes,
  };
}
