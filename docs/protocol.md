# WebSocket protocol — external GC interface contract (v1, orchestrator draft)

This is the only way anything talks to the simulator backend. The built-in GC panel and the
programming IDE are ordinary clients of it; a future external ground-control system replaces the
panel without backend changes. Task 6 implements it and may ADD messages and fields; it must not
rename or remove anything here. Tasks 7 and 8 build against this document.

The real cRIO-9047 would expose EtherNet/IP (CIP Class 1 adapter). This protocol carries the same
semantics — tag reads, tag writes, cyclic state — as JSON over WebSocket. Wire-format fidelity is a
non-goal.

## Transport
- Endpoint: `ws://<host>:8765/ws`. One JSON object per text frame. UTF-8.
- Every client message: `{"type": "<name>", "id": "<client-chosen string, optional>", ...}`.
  Every direct reply carries the same `id`. Unsolicited server messages have no `id`.
- Server never closes on a bad message; it replies `error`.
- Values: numbers are engineering units from the tag database (psi, degF, lbf), booleans for
  valve/DO tags meaning FUNCTIONAL OPEN (true = open), never the energize bit.
- Time: `t` is simulation seconds since sim start, `scan` is the scan counter. No wall-clock.

## Namespaces for read/write
| Name pattern | Dir | Meaning |
|---|---|---|
| `PT1` … `THRUST` (32 input tags) | read | PLC input image, as delivered by the card simulation |
| `S1` … `PB6`, spares (14 output tags) | read / write* | PLC output image (functional open). *Write = manual valve command, see arbitration |
| `plc.globals.<name>` | read / write | VAR_GLOBAL of loaded programs, e.g. `plc.globals.setpoint` |
| `hmi.abort` | read / write | Manual abort request bit. Write `true` to abort; writing `false` is rejected, because an abort ends by itself. Writing `true` while the PLC is stopped is rejected too, because the outputs are already fail-safe. Reads `false` again once the abort latches |
| `hmi.bb.lox.setpoint`, `hmi.bb.lox.deadband`, `hmi.bb.lox.enable`, same for `hmi.bb.fuel.*` | read / write | Bang-bang operator entries. The scan loop mirrors them into the PLC globals the regulation programs declare (mapping is configured server-side) |
| `abort.thresholds` | read / write via `abort.config` | Auto-abort thresholds |
| `abort.tripped`, `abort.latched`, `abort.waiting_on` | read | Same as `state.abort` (see "Abort lifecycle") |
| `plant.<node>` | read | Plant internals for the HMI (pressures, masses, valve positions, flows); names are whatever `PlantState` exposes |
| `raw.<module>.<index>.<ch>` | read | Card channel view: electrical value, raw code |

## Client → server
```
hello            {"client": "gc-panel"|"ide"|"<name>", "protocol": 1}
subscribe        {"rate_hz": 1..50, "groups": ["inputs","outputs","plc","hmi","plant","raw"]}   # default all but raw, 20 Hz
unsubscribe      {}
read             {"names": ["PT3", "plc.globals.setpoint", ...]}
write            {"values": {"hmi.bb.lox.setpoint": 904, "PB2": true, ...}}      # atomic: all or none; rejected names listed in error
sequence         {"action": "start"|"stop", "name": "hotfire"}
abort            {}                                   # same as write hmi.abort=true; error code=rejected while the PLC is stopped (nothing to abort)
abort.clear      {}                                   # compatibility only: an abort ends by itself. ack when not latched; while latched, error code=rejected with details.waiting_on
abort.config     {"thresholds": [{"tag": "PT0", "op": ">", "value": 0.0, "enabled": false, "label": "chamber overpressure"}, ...]}
program.compile  {"name": "x", "language": "ST"|"LD"|"SFC", "source": "<text>" | {<json doc>}}     # compile only, no load
program.load     {"programs": [{"name", "language", "source", "role"?}, ...]}    # replaces the whole program set; requires plc stopped
                 # role: "regulation"|"sequence"|"monitor"|"other", optional. Omit it and the server infers
                 # one (see "Program roles" below); send it to override the inference.
                 # refused with abort_active while an abort is latched
program.list     {}                                   # -> program_list
plc.run / plc.stop / plc.reset / plc.clear_faults      {}   # plc.stop and plc.reset are refused with abort_active while latched; plc.stop drops an abort request not yet latched; plc.reset re-arms programs an abort switched off
                 # plc.stop puts every valve in its default state and clears manual commands, output forces, sequences,
                 # bang-bang enables and PLC variables, so nothing moves on the next plc.run (D17)
plc.force        {"name": "PT3", "value": 900.0}      # input tag, output tag or variable; plc.unforce {"name"}. Output forces are refused while latched
sim.reset        {"initial": {"bottle_psi": 4000, "lox_ullage_psi": 0, "fuel_ullage_psi": 0, "lox_mass_lbm": 60, "fuel_mass_lbm": 40, "muscle_bus_psi": 100}}   # all optional
                 # allowed while latched: the instructor reset, which clears the latch
sim.rate         {"scan_hz": 10..100, "realtime": true|false, "speed": 1.0}   # speed multiplies realtime pacing; realtime=false runs as fast as possible
sim.pause / sim.resume      {}
```

## Server → client
```
welcome          {"protocol": 1, "sim_version": "...", "tags": [<tag database entries: tag, kind, signal, units, range, normal_state, description>],
                  "programs": [...],   # same entries as program_list, role included
                  "examples": [{"name", "language", "source"}],   # the shipped example programs, for the IDE "load example" menu
                  "notice": "Programming environment is a custom IEC 61131-3-style language, NOT the cRIO-9047's native LabVIEW FPGA/RT environment."}
ack              {"id": ...}                                          # for writes/commands that produce no data
error            {"id": ..., "code": "bad_request"|"unknown_name"|"read_only"|"rejected"|"plc_running"|"abort_active"|"compile_error"|"internal", "message": "...", "details": {...}}
read_result      {"id": ..., "values": {...}}
program_list     {"id": ..., "programs": [{"name", "language", "source", "role", "compiled_ok": true, "running": true}]}
compile_result   {"id": ..., "ok": true|false, "errors": [{"message", "line", "col", "path"}], "variables": [...], "ladder_text": "<ascii, LD only>"}
state            (cyclic, per subscription) {
                   "t": 12.34, "scan": 1234, "scan_hz": 50, "paused": false,
                   "inputs": {"PT1": 4000.0, ...}, "outputs": {"S1": false, ...},
                   "plc": {"running": true, "abort_active": false, "faults": [...], "halted": [...],
                           "sfc": {"hotfire": {"active_steps": [...], "step_times": {...}, "aborted": false, "running": true}},
                           "globals": {...}, "forced": {...}},
                   "hmi": {"abort": false, "bb": {"lox": {"setpoint","deadband","enable","state": "OFF"|"PRESS"|"HOLD","abort_off": []}, "fuel": {...}},
                           "manual_allowed": true, "active_sequence": null|"hotfire"},
                   "abort": {"thresholds": [...], "tripped": null | {"tag","value","threshold","t","source"},
                             "latched": false, "waiting_on": []},   # always sent, whatever the subscribed groups
                   "plant": {...}, "raw": {...},
                   "nonfinite": [] }   # additive, see Server -> "Non-finite values" below
event            {"t": 12.34, "scan": 1234, "level": "info"|"command"|"sequence"|"abort"|"fault"|"warn", "text": "MV-LOX (PB2) -> OPEN", "source": "hmi"|"plc"|"sim"}
```
Event texts should follow the real stand's log style seen in the DAQ CSV `event` column so operators
recognise them: `[command] <alias> (<tag>) -> OPEN|CLOSED`, `[sequence] T+<s> <step>`, `[abort] ...`.

## `state.abort.tripped`
`null` until an abort latches. Once set, `source` says which of the three abort paths fired, and
**the type of `value` and `threshold` follows from it** — a client must not assume a number:

| `source` | `tag` | `value` | `threshold` |
|---|---|---|---|
| `"threshold"` | the input tag that tripped, e.g. `"PT0"` | number — the reading | number — the configured trip value |
| `"manual"` | `"hmi.abort"` | boolean `true` | `null` |
| `"program"` | `"plc.globals.auto_abort_request"` | boolean `true` | `null` |

`t` is always the simulation time of the latch. Render the value with the type in mind
(`typeof value === "number" ? value.toFixed(1) : String(value)`); formatting it as a number
unconditionally throws on the two boolean sources.

`tripped` keeps describing the last abort after control returns, until `plc.reset` or `sim.reset`.
Use `latched` to decide whether an abort is in progress.

## Abort lifecycle
An abort is absolute and ends by itself (`docs/decisions.md` D12; full detail in `docs/runtime.md` §3).

* **Latch.** A trip latches the abort in the same scan. A trip is an enabled threshold row
  tested against the real card reading, never the forced value, or `auto_abort_request`, or
  `hmi.abort`. `state.abort.latched` becomes true and `tripped` is filled in. Manual valve
  commands and output forces are dropped, output-writing programs are disabled, and every
  loaded SFC's abort chain starts.
* **While latched** the abort owns every output (arbitration rule 1). These requests get
  `error code=abort_active`: `write` to an output tag, `write hmi.bb.<loop>.enable=true`,
  `sequence` start or stop, `plc.stop`, `plc.reset`, `program.load`, and `plc.force` on an
  output tag. `abort.clear` gets `code=rejected`. `plc.stop`, `plc.reset` and `abort.clear`
  carry `details.waiting_on`. Setpoint and deadband writes, `plc.globals` writes, input
  forces, `plc.unforce`, `abort.config`, `plc.clear_faults`, `sim.rate`, `sim.pause` and
  `sim.resume` stay accepted. `sim.reset` is accepted and clears the latch.
* **`state.abort.waiting_on`** lists, as human-readable strings, why control has not
  returned: `"<chart> at <step>"` for each unfinished abort chain,
  `"<tag> <op> <value> still tripped"` for each enabled threshold the card reading still
  trips, and `"plc.globals.auto_abort_request still set"`. It is `[]` when not latched.
  Display the strings; do not parse them.
* **Return of control.** On the first scan where `waiting_on` is empty, the latch drops by
  itself. Every chart stops, and both bang-bang enables read OFF, with setpoints kept. The
  disabled programs stay off until `plc.reset` re-arms them. Until then,
  `state.hmi.bb.<loop>.abort_off` names the switched-off programs that drive that loop's
  solenoid, and `write hmi.bb.<loop>.enable=true` for such a loop gets `code=rejected`. Outputs hold where the abort left them. The server
  emits `[abort] abort sequence complete -- stand safe, operator in control`, and
  `hmi.manual_allowed` becomes true.
* **Held latch.** If a threshold is still tripped when the chains finish, the latch holds,
  and an `[abort] abort sequence complete but the latch is held: …` event names it. To
  release a failed sensor, send `abort.config` with that row disabled.

## Program roles
Every loaded program carries a role (`regulation`, `sequence`, `monitor` or `other`). When a
`program.load` entry omits `role` (or sends `null`), the server infers one from the compiled
program:

| Program | Inferred role |
|---|---|
| SFC | `sequence` |
| ST or LD that writes at least one output tag | `regulation` |
| ST or LD that writes no output tag | `monitor` |

"Writes" is the compiler's record of which output tags the program contains a write to, not its
name. `program_list` and `welcome.programs` report the resolved role.

**An explicit `role` overrides the inference, but it may not contradict the code**, and no safety
rule trusts the label on its own:

* A `role` value outside `regulation | sequence | monitor | other` is a malformed request:
  `error code=bad_request`, nothing loaded.
* A valid role that contradicts the code rejects the whole load with `error code=compile_error`,
  whose `details.results` holds one compile-result entry per program; each offending program has
  `ok: false` and an error with `path: "/role"`. The contradictions are: an SFC with any role but
  `sequence`; a non-SFC with `sequence`; a program that writes output tags with `monitor`.
* `other` is allowed for any non-SFC program, but it exempts nothing.
* **When an abort latches, every non-SFC program whose code writes an output tag is disabled,
  whatever its role**, plus any program explicitly labelled `regulation`. Labelling a valve-writing
  loop `other` does not keep it running through an abort. Its output tags go to their fail-safe
  state on the latch scan unless an abort chain writes them (arbitration rule 1). The programs
  stay off after control returns, until `plc.reset`, `sim.reset` or `program.load` re-arms them.
* Manual valve commands are locked out while a chart is running and not parked on a final step —
  decided by the chart itself, not by any label.

## Output arbitration (implemented by the scan loop, task 5; exposed via `hmi.manual_allowed`)
1. Abort active: the abort owns all outputs. Each loaded SFC's abort chain — its `abort_step` and
   every step reachable from it, not the chart as a whole — keeps control of the output tags it
   writes for the whole latch. Every other output tag is driven to its fail-safe state (NC closed,
   NO open) on the latch scan and held there until control returns, whichever program last drove
   it; one `[abort]` event lists the tags that changed. The abort is absolute: output forces are
   cleared at the latch and new ones refused, and every `write` to an output tag or `sequence`
   start is rejected with `abort_active` (see "Abort lifecycle" for the full refusal list).
2. A sequence is running: output writes are rejected with `rejected` ("sequence active"); stop it first.
   Manual commands set before the start stay in force (D16), except on a coil the running chart
   writes, which releases that coil's manual command.
3. Otherwise a write to an output tag sets the manual command for that valve.
   - **Bang-bang solenoids (D17).** A bang-bang loop owns its solenoid (S1 for `lox`, S2 for `fuel`)
     only while enabled. A write to it then gets `rejected` with `details: {name, loop}`; send
     `hmi.bb.<loop>.enable=false` first, or in the same write. Disabling a loop closes its solenoid
     once and hands it to the operator. Enabling a loop releases a manual command on its solenoid.
   - **Other programs** that write a coil during a scan win over the manual command for that scan.
   - **Lifetime.** Manual commands persist until overwritten. An abort latch, `plc.stop`,
     `plc.reset` and `sim.reset` clear them.
4. Auto-abort thresholds are evaluated first in every scan while the PLC runs, regardless of mode,
   against the real card readings rather than forced values.

## Versioning
`protocol` integer in hello/welcome. Additive changes keep 1. Breaking changes bump it and the server
must reject a mismatched hello with `error code=bad_request`.

## Server (task 6 — `draco_sim.protocol`)

### Running it
```
cd backend && python -m draco_sim.protocol.server [options]
```
| Flag | Default | Meaning |
|---|---|---|
| `--host` | `127.0.0.1` | bind address |
| `--port` | `8765` | WebSocket port; endpoint is `ws://<host>:<port>/ws` (any other path gets HTTP 404 at the handshake) |
| `--scan-hz` | `50` | PLC scan rate |
| `--load-examples` | off | load the five programs in `backend/examples` on startup |
| `--speed` | `1.0` | simulated-time multiplier used while pacing to the wall clock |
| `--no-realtime` | off | run scans back-to-back as fast as the host allows, ignoring the wall clock, instead of pacing with `--speed` |
| `--static DIR` | none | also serve a built frontend (`npm run build` output) as plain static files, stdlib-only, so one command can run the whole app |
| `--http-port` | `8080` | port for `--static` |
| `--verbose` | off | log every message type in and out, and the `websockets` library's own connection chatter |

One `Simulator` (docs/runtime.md) backs every client; there is one stand, not one per connection.
`sim.rate` (scan_hz/realtime/speed) reconfigures it for everyone, same as walking up to the real
control room console.

### Concurrency model
Everything — the scan loop and every client's message handling — runs on one asyncio event loop, in
one OS thread. `Simulator.step()` and every protocol handler run to completion before anything else
on the loop gets a turn, so `Simulator` is never touched from two places at once and no lock is
needed anywhere in `draco_sim.protocol`. The scan loop wakes roughly every 1–2 ms to ask
`Pacer.due_scans()` how many scans are due (0 usually, since a scan is 20 ms at 50 Hz) rather than
sleeping for a whole scan period, so an incoming client message is never stuck behind a long sleep.
If the host can't keep up and the pacer starts dropping scans, the server logs one `warning` per
second (not per drop) naming the total dropped so far — the simulated clock falls behind real time
rather than the loop spiralling.

Each connected client gets one outbound queue drained by one writer task, because a websocket
connection tolerates only one `send()` in flight at a time. Two channels feed it:
- direct replies (`ack`/`error`/`welcome`/`read_result`/...) and every broadcast `event` go through
  an unbounded, in-order queue — nothing here is dropped. A client so far behind that this queue
  passes 2000 unsent messages is logged once and disconnected (code 1011); a well-behaved GUI or IDE
  never gets near that.
- cyclic `state` pushes go through a single-slot, latest-value-wins box instead: if a client's
  connection is slower than its subscribed rate, snapshots are silently superseded rather than
  queued, since a stale `state` is worthless once a newer one exists. This is the backpressure
  policy for a slow subscriber; nothing else in the protocol is throttled this way.

### Subscription semantics
`subscribe` starts (or replaces, if already subscribed) a per-client asyncio task that calls
`sim.snapshot(groups)` on its own timer — independent of the scan clock and of every other client —
and pushes the result as `state`. `rate_hz` is clamped to 1–50; omitted `groups` defaults to
everything but `raw`, matching the message table above. `unsubscribe` cancels that task; no more
`state` arrives until `subscribe` is sent again. A `state` sent immediately after `subscribe` and
another sent 1/`rate_hz` seconds later carry two different `scan` values (unless the PLC is stopped
and the sim is paused). `event` messages are unrelated to subscriptions: every connected client
receives every event, in emission order, whether or not it has ever subscribed.

### Behaviour on Simulator errors
Every `SimError` the Simulator raises (`SimRejected`, `SimStateError`; see
`draco_sim.runtime.errors`) already carries a protocol error code, a message and a details dict —
the server reads those three fields straight onto an `error` frame with the request's `id`. Anything
else escaping a handler (a bug, not a modelled refusal) becomes `error code=internal` with the
exception text, is logged server-side with its traceback, and the connection is left open — a client
should never be disconnected by a request it can retry or correct. Malformed JSON, a non-object
top-level value, a missing/unrecognised `type`, or a `hello` with a `protocol` other than `1` all get
`error code=bad_request` the same way, `id` set from the request when one could be parsed out of it
(`null` for JSON that couldn't be parsed at all). A client is not required to send `hello` before
anything else works; `hello` only gates the protocol-version check and fills in `welcome`.

### Disconnect behaviour
Closing a websocket (cleanly or abruptly) cancels that client's subscription task and stops its
writer task; no other client is affected, and the scan loop keeps running regardless of whether
anyone is connected at all. A second client connecting mid-run gets the same `welcome`, the same
event stream from the moment it connects onward (not replayed from before), and its own independent
subscription.

### Non-finite values (`state.nonfinite`)
Wire JSON is strict (`allow_nan=False`) — real JSON has no `NaN`/`Infinity`. A plant global can
legitimately go to `+inf`, `-inf` or `NaN` (a divide-by-zero mid-integration, for instance), and the
server will not invent a substitute value for it. Instead, every `state` message carries an additive
field:
```
"nonfinite": ["plant.some_field", "inputs.PT7", ...]
```
a list of the dotted (and `[index]`-suffixed, for arrays) paths, within that same `state` object,
whose value was replaced with JSON `null` because it was not finite. The list is always present,
empty when nothing needed replacing, so a client can check `state.nonfinite.length` unconditionally
instead of a field that sometimes doesn't exist.

### Logging
Standard `logging`: one `INFO` line per connection open/close, one line per error, `--verbose` also
logs every message type in and out. Anything hitting port 8765 with plain HTTP instead of a WebSocket
handshake — a load balancer's health check, a desktop preview tool's `HEAD /` probe, a bare TCP
connect-and-close — is not an application error; `websockets` itself would otherwise log a full
traceback at `ERROR` for every single one of them. The server collapses that specific failure to one
line naming the peer address and the one-line reason (`unsupported HTTP method; expected GET; got
HEAD`, `connection closed while reading HTTP request line`, ...), no traceback, at `DEBUG` normally
and `INFO` under `--verbose`. A failure *after* a successful WebSocket handshake is unaffected and
keeps its full traceback at `ERROR`, same as any other internal error.
