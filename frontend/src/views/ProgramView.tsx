import { useEffect, useState } from 'react';
import { useSim } from '../protocol/useSim';
import { useWorkspace } from '../workspace/useWorkspace';
import { workspace } from '../workspace/store';
import { ProgramList } from '../components/ProgramList';
import { Toolbar } from '../components/Toolbar';
import { WatchTable } from '../components/WatchTable';
import { StEditor } from '../editors/st/StEditor';
import { LdEditor } from '../editors/ld/LdEditor';
import { SfcEditor } from '../editors/sfc/SfcEditor';
import { withLdDefaults } from '../editors/ld/model';
import { withSfcDefaults } from '../editors/sfc/model';
import type { LdDoc } from '../editors/ld/types';
import type { SfcDoc } from '../editors/sfc/types';
import type { CompileErrorEntry } from '../protocol/types';

export function ProgramView() {
  const sim = useSim();
  const programs = useWorkspace();
  const [selectedId, setSelectedId] = useState<string | null>(programs[0]?.id ?? null);
  const [compiling, setCompiling] = useState(false);
  const [devFixture, setDevFixture] = useState(false);

  useEffect(() => {
    if (!selectedId && programs.length > 0) setSelectedId(programs[0].id);
    if (selectedId && !programs.some((p) => p.id === selectedId)) setSelectedId(programs[0]?.id ?? null);
  }, [programs, selectedId]);

  const current = programs.find((p) => p.id === selectedId) ?? null;

  async function compile() {
    if (!current) return;
    setDevFixture(false);
    setCompiling(true);
    try {
      const result = await sim.sim.compile(current.name, current.language, current.source);
      workspace.setCompileResult(current.id, result.ok, result.errors);
    } catch (e) {
      workspace.setCompileResult(current.id, false, [{ message: (e as Error).message }]);
    } finally {
      setCompiling(false);
    }
  }

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== 's') return;
      // the ST editor (CodeMirror) already handles Ctrl/Cmd+S itself via onSave;
      // only handle it here for LD/SFC, which have no editor-local keymap.
      const target = e.target as HTMLElement | null;
      if (target?.closest('.cm-editor')) return;
      e.preventDefault();
      void compile();
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current]);

  const liveErrors: CompileErrorEntry[] =
    devFixture && sim.status === 'mock'
      ? [{ message: 'CompileError (dev fixture): unexpected token', line: 14, col: 5 }]
      : current?.compileErrors ?? [];

  const sfcLiveState = current && current.language === 'SFC' ? sim.state?.plc.sfc[current.name] : undefined;

  return (
    <div className="program-view">
      <aside className="program-view-left">
        <ProgramList sim={sim} programs={programs} selectedId={selectedId} onSelect={setSelectedId} />
        <WatchTable sim={sim} />
      </aside>
      <section className="program-view-main">
        {current ? (
          <>
            <Toolbar sim={sim} current={current} programs={programs} onCompile={compile} compiling={compiling} />
            {import.meta.env.DEV && sim.status === 'mock' && current.language === 'ST' && (
              <div className="dev-fixture-bar">
                <button onClick={() => setDevFixture((v) => !v)}>
                  {devFixture ? 'Clear demo error (dev)' : 'Inject demo compile error (dev)'}
                </button>
                <span>dev only — the mock cannot really compile, this exercises the error-rendering path locally</span>
              </div>
            )}
            {liveErrors.length > 0 && (
              <div className="problems-list">
                {liveErrors.map((e, i) => (
                  <div key={i} className="problem-row">
                    {e.line != null ? `${e.line}:${e.col ?? 1}` : e.path ?? ''} — {e.message}
                  </div>
                ))}
              </div>
            )}
            <div className="editor-host">
              {current.language === 'ST' && (
                <StEditor
                  value={current.source as string}
                  onChange={(v) => workspace.setSource(current.id, v)}
                  errors={liveErrors}
                  onSave={compile}
                />
              )}
              {current.language === 'LD' && (
                <LdEditor
                  doc={withLdDefaults(current.source as unknown as LdDoc)}
                  onChange={(doc) => workspace.setSource(current.id, doc as unknown as Record<string, unknown>)}
                  errors={liveErrors}
                  readOnly={false}
                  lookup={(name) => {
                    const v = sim.state?.inputs[name] ?? sim.state?.outputs[name] ?? sim.state?.plc.globals[name];
                    return typeof v === 'number' || typeof v === 'boolean' ? v : undefined;
                  }}
                />
              )}
              {current.language === 'SFC' && (
                <SfcEditor
                  doc={withSfcDefaults(current.source as unknown as SfcDoc)}
                  onChange={(doc) => workspace.setSource(current.id, doc as unknown as Record<string, unknown>)}
                  errors={liveErrors}
                  readOnly={false}
                  liveState={sfcLiveState}
                />
              )}
            </div>
          </>
        ) : (
          <div className="no-program">Create a program or open an example to begin.</div>
        )}
      </section>
    </div>
  );
}
