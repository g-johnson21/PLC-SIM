import { useState } from 'react';
import { useSim } from './protocol/useSim';
import { TopBar, type ViewName } from './components/TopBar';
import { EventLog } from './components/EventLog';
import { ProgramView } from './views/ProgramView';
import { ControlView } from './views/ControlView';

function App() {
  const sim = useSim();
  const [view, setView] = useState<ViewName>('program');

  return (
    <div className="app-shell">
      <TopBar sim={sim} view={view} onViewChange={setView} />
      <main className="app-main">{view === 'program' ? <ProgramView /> : <ControlView sim={sim} />}</main>
      <EventLog events={sim.events} />
    </div>
  );
}

export default App;
