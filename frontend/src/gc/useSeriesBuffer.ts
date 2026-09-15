import { useEffect, useState } from 'react';

export interface Sample {
  t: number;
  value: number;
}

const HARD_CAP = 4000; // backstop regardless of window/rate

/** Bounded ring buffer of (t, value) samples for the strip chart, keyed off the
 * simulator's own clock (state.t) rather than wall time, and trimmed to the
 * trailing `windowSec` of simulated time. Accumulating history across ticks from
 * an external stream is exactly what an effect is for, despite the generic
 * lint warning about setState-in-effect. */
export function useSeriesBuffer(t: number | undefined, value: number | undefined, windowSec: number): Sample[] {
  const [buf, setBuf] = useState<Sample[]>([]);

  useEffect(() => {
    if (t === undefined || value === undefined || Number.isNaN(value)) return;
    setBuf((prev) => {
      if (prev.length > 0 && prev[prev.length - 1].t === t) return prev;
      const cutoff = t - windowSec;
      const next = [...prev, { t, value }].filter((s) => s.t >= cutoff);
      return next.length > HARD_CAP ? next.slice(next.length - HARD_CAP) : next;
    });
  }, [t, value, windowSec]);

  return buf;
}
