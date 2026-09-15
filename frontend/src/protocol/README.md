# Protocol client

Implements `docs/protocol.md` v1. One `SimClient` singleton (`client.ts`) owns the
WebSocket (or the dev mock, `mock.ts`) and every other part of the app reads it
through the `useSim()` hook (`useSim.ts`). This is the surface task 8's Control
view is expected to build on — it should need nothing else from this folder.

## `useSim()`

```ts
const { status, welcome, state, events, sim, connectionLabel } = useSim();
```

- `status`: `'connecting' | 'connected' | 'reconnecting' | 'mock'`.
- `connectionLabel`: human-readable text for the same, for the top bar.
- `welcome`: the `welcome` message (tags, examples, notice, protocol/sim version) once received, else `null`.
- `state`: the latest cyclic `state` message, else `null`. Re-renders on every tick at the subscribed rate.
- `events`: array of `event` messages, newest last, capped at 500.
- `sim`: request functions, each returning a `Promise` that resolves with the server's reply or rejects with a `ProtocolError` (`.code`, `.message`, `.details`) on an `error` reply, or a plain `Error` on timeout/disconnect:
  - `compile(name, language, source)`, `load(programs)` (replies `program_list`), `programList()`
  - `run()`, `stop()`, `reset()`, `clearFaults()`
  - `write(values)`, `force(name, value)`, `unforce(name)`
  - `abort()`, `abortClear()` (compatibility only: an abort ends by itself), `abortConfig(thresholds)`
  - `sequenceStart(name)`, `sequenceStop(name)`
  - `read(names)`
  - `simReset(initial?)`, `simRate({scan_hz?, realtime?, speed?})`, `simPause()`, `simResume()`

`sim` is stable (module-level), so it's safe to call from event handlers without
adding it to dependency arrays.

## Files

- `types.ts` — every message shape from the protocol doc.
- `client.ts` — the WebSocket client: hello/subscribe handshake, id-correlated
  request/reply, reconnect with exponential backoff (capped 10s), and the
  mock fallback (`VITE_SIM_MOCK=1`, or no real connection within 2s on the
  first attempt only — later drops trigger normal reconnect, not the mock).
- `mock.ts` — in-process dev transport with the same message shapes. No physics:
  inputs start at 0, outputs at their de-energized normal state, and everything
  else only changes because a client wrote it. Clearly a dev aid, not a stand-in
  for the real scan loop (e.g. it does not execute loaded programs).
- `tags.generated.ts`, `examples.generated.ts` — generated, see `frontend/scripts/`.

## Endpoint

`import.meta.env.VITE_SIM_WS`, default `ws://localhost:8765/ws`. Set
`VITE_SIM_MOCK=1` to force the mock even when a real server is reachable.
