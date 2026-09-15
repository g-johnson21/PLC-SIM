import { useSyncExternalStore } from 'react';
import { workspace } from './store';

export function useWorkspace() {
  return useSyncExternalStore(
    (cb) => workspace.subscribe(cb),
    () => workspace.getState(),
  );
}
