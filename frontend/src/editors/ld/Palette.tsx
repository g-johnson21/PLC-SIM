import { defaultCoil, defaultCompare, defaultContact, defaultCounter, defaultMath, defaultMove, defaultTimer } from './model';
import type { LeafElement } from './types';

interface Props {
  disabled: boolean;
  onInsert: (el: LeafElement) => void;
}

export function Palette({ disabled, onInsert }: Props) {
  return (
    <div className="palette">
      <div className="palette-group">
        <span className="palette-label">contacts</span>
        <button disabled={disabled} onClick={() => onInsert(defaultContact('NO'))}>
          ] [
        </button>
        <button disabled={disabled} onClick={() => onInsert(defaultContact('NC'))}>
          ]/[
        </button>
        <button disabled={disabled} onClick={() => onInsert(defaultContact('P'))}>
          P
        </button>
        <button disabled={disabled} onClick={() => onInsert(defaultContact('N'))}>
          N
        </button>
      </div>
      <div className="palette-group">
        <span className="palette-label">coils</span>
        <button disabled={disabled} onClick={() => onInsert(defaultCoil('COIL'))}>
          ( )
        </button>
        <button disabled={disabled} onClick={() => onInsert(defaultCoil('SET'))}>
          (S)
        </button>
        <button disabled={disabled} onClick={() => onInsert(defaultCoil('RESET'))}>
          (R)
        </button>
        <button disabled={disabled} onClick={() => onInsert(defaultCoil('NEGATED'))}>
          (/)
        </button>
      </div>
      <div className="palette-group">
        <span className="palette-label">timers</span>
        <button disabled={disabled} onClick={() => onInsert(defaultTimer('TON'))}>
          TON
        </button>
        <button disabled={disabled} onClick={() => onInsert(defaultTimer('TOF'))}>
          TOF
        </button>
        <button disabled={disabled} onClick={() => onInsert(defaultTimer('TP'))}>
          TP
        </button>
      </div>
      <div className="palette-group">
        <span className="palette-label">counters</span>
        <button disabled={disabled} onClick={() => onInsert(defaultCounter('CTU'))}>
          CTU
        </button>
        <button disabled={disabled} onClick={() => onInsert(defaultCounter('CTD'))}>
          CTD
        </button>
      </div>
      <div className="palette-group">
        <span className="palette-label">compute</span>
        <button disabled={disabled} onClick={() => onInsert(defaultCompare('GT'))}>
          CMP
        </button>
        <button disabled={disabled} onClick={() => onInsert(defaultMove())}>
          MOVE
        </button>
        <button disabled={disabled} onClick={() => onInsert(defaultMath('ADD'))}>
          MATH
        </button>
      </div>
    </div>
  );
}
