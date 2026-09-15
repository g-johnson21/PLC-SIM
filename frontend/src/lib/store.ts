// Minimal external store for useSyncExternalStore -- avoids pulling in a state
// library for what is just "value + subscribers" in two places (protocol client,
// workspace).
export interface Store<T> {
  getState(): T;
  setState(updater: T | ((state: T) => T)): void;
  subscribe(listener: () => void): () => void;
}

export function createStore<T>(initial: T): Store<T> {
  let state = initial;
  const listeners = new Set<() => void>();
  return {
    getState: () => state,
    setState: (updater) => {
      state = typeof updater === 'function' ? (updater as (s: T) => T)(state) : updater;
      for (const l of listeners) l();
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
