import { useSyncExternalStore } from 'react';
import { simClient, sim, type ConnectionStatus, type SimSnapshot } from './client';

export interface UseSimResult extends SimSnapshot {
  sim: typeof sim;
  connectionLabel: string;
  /** Tear down the dev fallback mock and connect to the real backend. No-op unless
   *  `mockFallback` is set (i.e. this is an automatic fallback, not VITE_SIM_MOCK=1). */
  switchToRealBackend: () => void;
}

const LABELS: Record<ConnectionStatus, string> = {
  connecting: 'connecting…',
  connected: 'connected',
  reconnecting: 'reconnecting…',
  mock: 'mock (dev)',
};

/** Shared hook onto the protocol client. Task 8's Control view consumes exactly this. */
export function useSim(): UseSimResult {
  const snapshot = useSyncExternalStore(
    (cb) => simClient.subscribeSnapshot(cb),
    () => simClient.snapshot,
  );
  return {
    ...snapshot,
    sim,
    connectionLabel: LABELS[snapshot.status],
    switchToRealBackend: () => simClient.switchToRealBackend(),
  };
}
