import { describe, expect, it } from 'vitest';
import { historyInit, historyPush, historyRedo, historyUndo } from './history';

describe('history', () => {
  it('initialises with empty past/future', () => {
    const h = historyInit('a');
    expect(h).toEqual({ past: [], present: 'a', future: [] });
  });

  it('push records the previous present and clears future', () => {
    let h = historyInit('a');
    h = historyPush(h, 'b');
    expect(h).toEqual({ past: ['a'], present: 'b', future: [] });
    h = historyPush(h, 'c');
    expect(h).toEqual({ past: ['a', 'b'], present: 'c', future: [] });
  });

  it('undo moves present back and stashes it in future', () => {
    let h = historyInit('a');
    h = historyPush(h, 'b');
    h = historyPush(h, 'c');
    h = historyUndo(h);
    expect(h).toEqual({ past: ['a'], present: 'b', future: ['c'] });
    h = historyUndo(h);
    expect(h).toEqual({ past: [], present: 'a', future: ['b', 'c'] });
  });

  it('undo at the start of history is a no-op (same reference)', () => {
    const h = historyInit('a');
    expect(historyUndo(h)).toBe(h);
  });

  it('redo replays a future value and is the exact inverse of undo', () => {
    let h = historyInit('a');
    h = historyPush(h, 'b');
    h = historyPush(h, 'c');
    const afterEdits = h;
    h = historyUndo(h);
    h = historyUndo(h);
    h = historyRedo(h);
    h = historyRedo(h);
    expect(h).toEqual(afterEdits);
  });

  it('redo with no future is a no-op (same reference)', () => {
    const h = historyInit('a');
    expect(historyRedo(h)).toBe(h);
  });

  it('a push after undo discards the redo branch', () => {
    let h = historyInit('a');
    h = historyPush(h, 'b');
    h = historyUndo(h); // present back to 'a', future ['b']
    h = historyPush(h, 'z');
    expect(h).toEqual({ past: ['a'], present: 'z', future: [] });
    expect(historyRedo(h)).toBe(h); // 'b' is gone, nothing to redo
  });
});
