// Data-driven: reads every *.ld.json / *.sfc.json in backend/examples at test time,
// so it stays correct as those files change (e.g. hotfire.sfc.json is being replaced
// with the real procedure) without needing any changes here.
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { serializeForExport, type WorkspaceProgram } from './store';
import type { VarDecl } from '../editors/shared/types';

const here = dirname(fileURLToPath(import.meta.url));
const examplesDir = join(here, '..', '..', '..', 'backend', 'examples');

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** Find the literal text of `"init": <...>` inside the var object named `varName`,
 *  spanning multiple lines so it works on both compact source and pretty-printed export. */
function extractInitLiteral(text: string, varName: string): string | null {
  const re = new RegExp(`"name":\\s*"${escapeRegExp(varName)}"[\\s\\S]*?"init":\\s*(-?\\d+(?:\\.\\d+)?)`);
  const m = text.match(re);
  return m ? m[1] : null;
}

const files = readdirSync(examplesDir).filter((f) => f.endsWith('.ld.json') || f.endsWith('.sfc.json'));

describe('backend/examples JSON round-trip', () => {
  it('found at least one .ld.json and one .sfc.json to exercise (sanity check on the test path)', () => {
    expect(files.some((f) => f.endsWith('.ld.json'))).toBe(true);
    expect(files.some((f) => f.endsWith('.sfc.json'))).toBe(true);
  });

  describe.each(files)('%s', (file) => {
    const rawText = readFileSync(join(examplesDir, file), 'utf-8');
    const orig = JSON.parse(rawText) as Record<string, unknown>;
    const language: 'LD' | 'SFC' = file.endsWith('.ld.json') ? 'LD' : 'SFC';
    const program: WorkspaceProgram = {
      id: 'roundtrip-fixture',
      name: String(orig.name),
      language,
      source: orig,
      compileOk: null,
      compileErrors: [],
    };

    it('imports then exports back to a structurally identical document', () => {
      const exportedText = serializeForExport(program);
      const reimported = JSON.parse(exportedText);
      expect(reimported).toEqual(orig);
    });

    it('restores the exact REAL/LREAL .0 literal formatting for whole-number var inits', () => {
      const exportedText = serializeForExport(program);
      const vars = (orig.vars as VarDecl[] | undefined) ?? [];
      const wholeNumberReals = vars.filter(
        (v) => (v.type === 'REAL' || v.type === 'LREAL') && typeof v.init === 'number' && Number.isInteger(v.init),
      );
      for (const v of wholeNumberReals) {
        const originalLiteral = extractInitLiteral(rawText, v.name);
        const exportedLiteral = extractInitLiteral(exportedText, v.name);
        expect(originalLiteral).not.toBeNull(); // the source really does spell it e.g. "870.0"
        expect(exportedLiteral).toBe(originalLiteral);
      }
    });
  });
});
