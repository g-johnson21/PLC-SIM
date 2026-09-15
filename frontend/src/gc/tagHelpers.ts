import type { TagEntry } from '../protocol/types';

export function findTag(tags: TagEntry[] | undefined, name: string): TagEntry | undefined {
  return tags?.find((t) => t.tag === name);
}

export function formatValue(value: number | undefined, units: string | null | undefined, digits = 1): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '—';
  return `${value.toFixed(digits)}${units ? ` ${units}` : ''}`;
}

// NC/NO valve aliases from docs/tag-database.md (D1/D3) -- the protocol's welcome.tags
// carries normal_state but not the DAQ log alias, so this is a small static label
// lookup, not a stand-in for anything the backend reports numerically.
export const VALVE_ALIAS: Record<string, string> = {
  S1: 'SV-LOXBB',
  S2: 'SV-FBB',
  PB1: 'SV-LOXV',
  PB3: 'SV-FV',
  PB2: 'MV-LOX',
  PB4: 'MV-F',
  S5: 'SV-FPURGE',
  S4: 'SV-LOXPURGE',
  PB5: 'SV-LOX-FILL',
  S3: 'SV-MBV',
  PB6: 'SV-GOX-PURGE',
};
