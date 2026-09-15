import type { UseSimResult } from '../protocol/useSim';
import { isLatched, waitingOn } from '../gc/abortUi';

const FALLBACK_NOTICE =
  "Programming environment is a custom IEC 61131-3-style language, NOT the cRIO-9047's native LabVIEW FPGA/RT environment.";

export type ViewName = 'program' | 'control';

interface Props {
  sim: UseSimResult;
  view: ViewName;
  onViewChange: (v: ViewName) => void;
}

function plcStatus(sim: UseSimResult): { label: string; className: string } {
  const plc = sim.state?.plc;
  if (!plc) return { label: '—', className: 'status-unknown' };
  if (plc.abort_active) return { label: 'ABORT', className: 'status-abort' };
  if (plc.faults.length > 0) return { label: 'FAULT', className: 'status-fault' };
  return plc.running ? { label: 'RUNNING', className: 'status-running' } : { label: 'STOPPED', className: 'status-stopped' };
}

export function TopBar({ sim, view, onViewChange }: Props) {
  const status = plcStatus(sim);
  const notice = sim.welcome?.notice ?? FALLBACK_NOTICE;
  const abortActive = isLatched(sim.state);
  const waiting = waitingOn(sim.state);

  return (
    <>
      <div className="topbar">
        <div className="topbar-left">
          <span className="app-name">DRACO IDE</span>
          <nav className="tabs">
            <button className={view === 'program' ? 'tab active' : 'tab'} onClick={() => onViewChange('program')}>
              Program
            </button>
            <button className={view === 'control' ? 'tab active' : 'tab'} onClick={() => onViewChange('control')}>
              Control
            </button>
          </nav>
        </div>
        <div className="topbar-right">
          <span className={`plc-status ${status.className}`}>{status.label}</span>
          <span className="sim-clock">
            t={sim.state ? sim.state.t.toFixed(2) : '—'}s scan={sim.state?.scan ?? '—'}
          </span>
          <span className={`conn-indicator conn-${sim.status}`}>{sim.connectionLabel}</span>
        </div>
      </div>
      {abortActive && (
        <div className="abort-banner">
          ABORT LATCHED — control returns when the abort sequence is over{waiting.length > 0 ? `; waiting on ${waiting.join('; ')}` : ''}
        </div>
      )}
      {sim.mockFallback &&
        (sim.mockFallback.backendReachable ? (
          <div className="fallback-banner fallback-reachable">
            <span>Simulator backend is now reachable — you are still on the in-browser mock</span>
            <button onClick={sim.switchToRealBackend}>Switch to real backend</button>
          </div>
        ) : (
          <div className="fallback-banner">
            Backend unreachable at {sim.mockFallback.endpoint} — using the in-browser dev mock
          </div>
        ))}
      <div className="notice-line">{notice}</div>
    </>
  );
}
