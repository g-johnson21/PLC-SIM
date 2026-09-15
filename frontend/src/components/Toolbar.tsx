import type { UseSimResult } from '../protocol/useSim';
import type { WorkspaceProgram } from '../workspace/store';
import { lockoutReason } from '../gc/abortUi';

interface Props {
  sim: UseSimResult;
  current: WorkspaceProgram | null;
  programs: WorkspaceProgram[];
  onCompile: () => void;
  compiling: boolean;
}

export function Toolbar({ sim, current, programs, onCompile, compiling }: Props) {
  const running = Boolean(sim.state?.plc.running);
  const loadBlocked = sim.state ? lockoutReason(sim.state, 'programLoad') : null;
  const stopBlocked = sim.state ? lockoutReason(sim.state, 'plcStop') : null;
  const resetBlocked = sim.state ? lockoutReason(sim.state, 'plcReset') : null;
  const abortBlocked = lockoutReason(sim.state, 'abort');

  async function loadAll() {
    if (running || loadBlocked) return;
    try {
      await sim.sim.load(programs.map((p) => ({ name: p.name, language: p.language, source: p.source })));
    } catch (e) {
      alert(`Load failed: ${(e as Error).message}`);
    }
  }

  return (
    <div className="toolbar">
      <button onClick={onCompile} disabled={!current || compiling} title="Ctrl/Cmd+S">
        {compiling ? 'Compiling…' : 'Compile'}
      </button>
      <button
        onClick={loadAll}
        disabled={running || loadBlocked !== null || programs.length === 0}
        title={loadBlocked ?? (running ? 'Stop the PLC before loading' : 'Replace the PLC program set')}
      >
        Load to PLC
      </button>
      <span className="toolbar-sep" />
      <button onClick={() => void sim.sim.run()} disabled={running}>
        Run
      </button>
      <button onClick={() => void sim.sim.stop()} disabled={!running || stopBlocked !== null} title={stopBlocked ?? undefined}>
        Stop
      </button>
      <button onClick={() => void sim.sim.reset()} disabled={resetBlocked !== null} title={resetBlocked ?? undefined}>
        Reset
      </button>
      <button onClick={() => void sim.sim.clearFaults()}>Clear faults</button>
      <span className="toolbar-sep" />
      <button className="abort-button" onClick={() => void sim.sim.abort()} disabled={abortBlocked !== null} title={abortBlocked ?? undefined}>
        ABORT
      </button>
    </div>
  );
}
