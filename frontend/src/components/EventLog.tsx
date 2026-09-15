import { useState } from 'react';
import type { EventMsg } from '../protocol/types';

interface Props {
  events: EventMsg[];
}

const LEVEL_CLASS: Record<EventMsg['level'], string> = {
  info: 'evt-info',
  command: 'evt-command',
  sequence: 'evt-sequence',
  abort: 'evt-abort',
  fault: 'evt-fault',
  warn: 'evt-warn',
};

export function EventLog({ events }: Props) {
  const [open, setOpen] = useState(true);
  return (
    <div className={`event-log ${open ? 'open' : 'collapsed'}`}>
      <button className="event-log-toggle" onClick={() => setOpen((o) => !o)}>
        {open ? '▾' : '▸'} Event log ({events.length})
      </button>
      {open && (
        <div className="event-log-body">
          {events.length === 0 && <div className="event-log-empty">No events yet.</div>}
          {events.map((e, i) => (
            <div key={i} className={`event-row ${LEVEL_CLASS[e.level]}`}>
              <span className="event-time">t={e.t.toFixed(2)}</span>
              <span className="event-level">{e.level}</span>
              <span className="event-source">{e.source}</span>
              <span className="event-text">{e.text}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
