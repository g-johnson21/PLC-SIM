// Workspace: the set of programs the operator is editing, persisted to
// localStorage. Separate from the PLC's own loaded program set (which lives
// server-side and is only touched via sim.load()).
import { createStore } from '../lib/store';
import type { Language } from '../protocol/types';

export interface WorkspaceProgram {
  id: string;
  name: string;
  language: Language;
  source: string | Record<string, unknown>;
  /** Set locally after a successful program.compile; cleared on edit. */
  compileOk: boolean | null;
  compileErrors: import('../protocol/types').CompileErrorEntry[];
}

const STORAGE_KEY = 'draco-ide-workspace-v1';

function blankSource(language: Language): string | Record<string, unknown> {
  if (language === 'ST') {
    return 'PROGRAM new_program\n\nEND_PROGRAM\n';
  }
  if (language === 'LD') {
    return {
      version: 1,
      language: 'LD',
      name: 'new_program',
      vars: [],
      rungs: [{ id: 'r1', logic: { type: 'series', elements: [] } }],
    };
  }
  return {
    version: 1,
    language: 'SFC',
    name: 'new_program',
    autostart: false,
    vars: [],
    steps: [{ name: 'INITIAL', id: 's1', initial: true, actions: [] }],
    transitions: [],
  };
}

function load(): WorkspaceProgram[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as WorkspaceProgram[];
    if (!Array.isArray(parsed)) return [];
    return parsed;
  } catch {
    return [];
  }
}

function persist(programs: WorkspaceProgram[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(programs));
  } catch {
    /* storage full or unavailable: in-memory state still works this session */
  }
}

const store = createStore<WorkspaceProgram[]>(load());

let uidCounter = 0;
function makeId(): string {
  uidCounter += 1;
  return `p${Date.now().toString(36)}${uidCounter}`;
}

export const workspace = {
  getState: () => store.getState(),
  subscribe: (cb: () => void) => store.subscribe(cb),

  create(name: string, language: Language): WorkspaceProgram {
    const program: WorkspaceProgram = {
      id: makeId(),
      name,
      language,
      source: blankSource(language),
      compileOk: null,
      compileErrors: [],
    };
    const next = [...store.getState(), program];
    store.setState(next);
    persist(next);
    return program;
  },

  addExample(example: { name: string; language: Language; source: string | Record<string, unknown> }) {
    const program: WorkspaceProgram = {
      id: makeId(),
      name: example.name,
      language: example.language,
      source: structuredClone(example.source),
      compileOk: null,
      compileErrors: [],
    };
    const next = [...store.getState(), program];
    store.setState(next);
    persist(next);
    return program;
  },

  importFile(name: string, language: Language, source: string | Record<string, unknown>) {
    return this.addExample({ name, language, source });
  },

  update(id: string, patch: Partial<WorkspaceProgram>) {
    const next = store.getState().map((p) => (p.id === id ? { ...p, ...patch } : p));
    store.setState(next);
    persist(next);
  },

  setSource(id: string, source: string | Record<string, unknown>) {
    this.update(id, { source, compileOk: null, compileErrors: [] });
  },

  rename(id: string, name: string) {
    this.update(id, { name });
  },

  remove(id: string) {
    const next = store.getState().filter((p) => p.id !== id);
    store.setState(next);
    persist(next);
  },

  setCompileResult(id: string, ok: boolean, errors: import('../protocol/types').CompileErrorEntry[]) {
    this.update(id, { compileOk: ok, compileErrors: errors });
  },
};

export function fileExtensionFor(language: Language): string {
  if (language === 'ST') return '.st';
  if (language === 'LD') return '.ld.json';
  return '.sfc.json';
}

/** JS numbers don't distinguish 870 from 870.0 -- JSON.stringify always drops the
 *  trailing ".0" that a REAL-typed init literal had on disk. Restore it for the
 *  handful of REAL/LREAL `vars[].init` values so an untouched document exports
 *  byte-for-byte (mod whitespace), not just value-for-value. */
function restoreRealLiteralFormatting(doc: Record<string, unknown>): Record<string, unknown> {
  const clone = structuredClone(doc);
  const vars = clone.vars as Array<Record<string, unknown>> | undefined;
  if (!Array.isArray(vars)) return clone;
  for (const v of vars) {
    if ((v.type === 'REAL' || v.type === 'LREAL') && typeof v.init === 'number' && Number.isInteger(v.init)) {
      v.init = `@@REAL_LITERAL@@${v.init}@@`;
    }
  }
  return clone;
}

export function serializeForExport(program: WorkspaceProgram): string {
  if (program.language === 'ST') return program.source as string;
  const prepared = restoreRealLiteralFormatting(program.source as Record<string, unknown>);
  const text = JSON.stringify(prepared, null, 2).replace(/"@@REAL_LITERAL@@(-?\d+)@@"/g, '$1.0');
  return text + '\n';
}

export function languageFromFilename(filename: string): Language | null {
  if (filename.endsWith('.ld.json')) return 'LD';
  if (filename.endsWith('.sfc.json')) return 'SFC';
  if (filename.endsWith('.st')) return 'ST';
  return null;
}
