import { useRef, useState } from 'react';
import type { UseSimResult } from '../protocol/useSim';
import { fileExtensionFor, languageFromFilename, serializeForExport, workspace, type WorkspaceProgram } from '../workspace/store';
import type { Language } from '../protocol/types';

interface Props {
  sim: UseSimResult;
  programs: WorkspaceProgram[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

function roleFor(sim: UseSimResult, name: string): string | undefined {
  return sim.welcome?.programs.find((p) => p.name === name)?.role;
}

function runtimeBadge(sim: UseSimResult, name: string): { label: string; className: string } | null {
  const plc = sim.state?.plc;
  if (!plc) return null;
  if (plc.faults.some((f) => (f as { program?: string }).program === name)) return { label: 'FAULT', className: 'badge-fault' };
  if (plc.halted.includes(name)) return { label: 'HALTED', className: 'badge-fault' };
  if (name in plc.sfc) return { label: plc.sfc[name].running ? 'RUNNING' : 'IDLE', className: plc.sfc[name].running ? 'badge-running' : 'badge-idle' };
  return null;
}

export function ProgramList({ sim, programs, selectedId, onSelect }: Props) {
  const [showNewMenu, setShowNewMenu] = useState(false);
  const [showExampleMenu, setShowExampleMenu] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  function createNew(language: Language) {
    const name = prompt('Program name', `new_${language.toLowerCase()}`);
    if (!name) return;
    const p = workspace.create(name, language);
    onSelect(p.id);
    setShowNewMenu(false);
  }

  function openExample(name: string) {
    const example = sim.welcome?.examples.find((e) => e.name === name);
    if (!example) return;
    const p = workspace.addExample(example);
    onSelect(p.id);
    setShowExampleMenu(false);
  }

  function importFile(file: File) {
    const language = languageFromFilename(file.name);
    if (!language) {
      alert('Unrecognised extension. Use .st, .ld.json or .sfc.json');
      return;
    }
    file.text().then((text) => {
      const source = language === 'ST' ? text : JSON.parse(text);
      const name = file.name.replace(/\.(st|ld\.json|sfc\.json)$/, '');
      const p = workspace.importFile(name, language, source);
      onSelect(p.id);
    });
  }

  function exportProgram(p: WorkspaceProgram) {
    const text = serializeForExport(p);
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = p.name + fileExtensionFor(p.language);
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="program-list">
      <div className="program-list-actions">
        <div className="dropdown">
          <button onClick={() => setShowNewMenu((s) => !s)}>+ New</button>
          {showNewMenu && (
            <div className="dropdown-menu">
              <button onClick={() => createNew('ST')}>Structured Text</button>
              <button onClick={() => createNew('LD')}>Ladder</button>
              <button onClick={() => createNew('SFC')}>Sequential Function Chart</button>
            </div>
          )}
        </div>
        <div className="dropdown">
          <button onClick={() => setShowExampleMenu((s) => !s)} disabled={!sim.welcome}>
            Open example
          </button>
          {showExampleMenu && (
            <div className="dropdown-menu">
              {(sim.welcome?.examples ?? []).map((e) => (
                <button key={e.name} onClick={() => openExample(e.name)}>
                  {e.name} ({e.language})
                </button>
              ))}
            </div>
          )}
        </div>
        <button onClick={() => fileInputRef.current?.click()}>Import…</button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".st,.json"
          style={{ display: 'none' }}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) importFile(file);
            e.target.value = '';
          }}
        />
      </div>
      <div className="program-rows">
        {programs.map((p) => {
          const badge = runtimeBadge(sim, p.name);
          const role = roleFor(sim, p.name);
          return (
            <div key={p.id} className={`program-row${p.id === selectedId ? ' selected' : ''}`} onClick={() => onSelect(p.id)}>
              <span className={`lang-badge lang-${p.language}`}>{p.language}</span>
              {role && <span className={`role-badge role-${role}`}>{role}</span>}
              <span className="program-name">{p.name}</span>
              {p.compileOk === true && <span className="badge badge-ok">OK</span>}
              {p.compileOk === false && <span className="badge badge-fault">ERR</span>}
              {badge && <span className={`badge ${badge.className}`}>{badge.label}</span>}
              <span className="program-row-actions">
                <button
                  title="rename"
                  onClick={(e) => {
                    e.stopPropagation();
                    const name = prompt('Rename program', p.name);
                    if (name) workspace.rename(p.id, name);
                  }}
                >
                  ✎
                </button>
                <button
                  title="export"
                  onClick={(e) => {
                    e.stopPropagation();
                    exportProgram(p);
                  }}
                >
                  ⭳
                </button>
                <button
                  title="delete"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (confirm(`Delete ${p.name}?`)) workspace.remove(p.id);
                  }}
                >
                  ✕
                </button>
              </span>
            </div>
          );
        })}
        {programs.length === 0 && <div className="program-list-empty">No programs yet — create one or open an example.</div>}
      </div>
    </div>
  );
}
