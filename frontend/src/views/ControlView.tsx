import type { UseSimResult } from '../protocol/useSim';
import { StatusStrip } from '../gc/StatusStrip';
import { AbortPanel } from '../gc/AbortPanel';
import { ProcessMimic } from '../gc/ProcessMimic';
import { BangBangPanel } from '../gc/BangBangPanel';
import { SequencePanel } from '../gc/SequencePanel';
import { ThresholdsPanel } from '../gc/ThresholdsPanel';
import { PlcSimPanel } from '../gc/PlcSimPanel';

interface Props {
  sim: UseSimResult;
}

/** GC (ground-control) panel: task 8. A reference client of docs/protocol.md,
 * talking to the backend only through useSim() -- see protocol/README.md. */
export function ControlView({ sim }: Props) {
  return (
    <div className="gc-view">
      <div className="gc-top-row">
        <StatusStrip sim={sim} />
        <AbortPanel sim={sim} />
      </div>
      <div className="gc-body">
        <aside className="gc-col gc-col-left">
          <BangBangPanel sim={sim} loop="lox" />
          <BangBangPanel sim={sim} loop="fuel" />
        </aside>
        <section className="gc-col gc-col-center">
          <ProcessMimic sim={sim} />
        </section>
        <aside className="gc-col gc-col-right">
          <SequencePanel sim={sim} />
          <ThresholdsPanel sim={sim} />
          <PlcSimPanel sim={sim} />
        </aside>
      </div>
    </div>
  );
}
