"""Per-client connection state: one outbound writer task per client, since a
websocket only tolerates one send() in flight at a time. Two channels feed it:

- `reliable_queue` (unbounded, FIFO): direct replies (ack/error/welcome/...) and
  broadcast events. Order matters and nothing here should be silently dropped, so
  a client that stops draining is logged and eventually disconnected rather than
  starved forever.
- `state_slot` (a single-item box): cyclic `state` pushes from that client's own
  subscription. It is fine, and expected, for a slow client to miss intermediate
  snapshots -- the next one supersedes it -- so this is latest-value-wins with no
  queue growth.
"""
from __future__ import annotations

import asyncio
import logging

from websockets.exceptions import ConnectionClosed

from .codec import dumps

log = logging.getLogger("draco_sim.protocol")

# A client stuck behind this many un-drained reliable messages (acks, errors,
# events...) is not coming back; log it once and close rather than leak memory.
RELIABLE_QUEUE_WARN = 2000


class ClientConnection:
    _next_id = 1

    def __init__(self, ws, remote: str) -> None:
        self.ws = ws
        self.remote = remote
        self.id = ClientConnection._next_id
        ClientConnection._next_id += 1
        self.client_name = "unknown"
        self.rate_hz = 20.0
        self.groups: list[str] | None = None
        self.subscribe_task: asyncio.Task | None = None

        self.reliable_queue: asyncio.Queue[str] = asyncio.Queue()
        self.state_slot: asyncio.Queue[str] = asyncio.Queue(maxsize=1)
        self._warned_slow = False
        self._writer_task = asyncio.ensure_future(self._writer())

    async def _writer(self) -> None:
        reliable_get = asyncio.ensure_future(self.reliable_queue.get())
        state_get = asyncio.ensure_future(self.state_slot.get())
        try:
            while True:
                done, _ = await asyncio.wait({reliable_get, state_get},
                                             return_when=asyncio.FIRST_COMPLETED)
                if reliable_get in done:
                    await self.ws.send(reliable_get.result())
                    reliable_get = asyncio.ensure_future(self.reliable_queue.get())
                if state_get in done:
                    await self.ws.send(state_get.result())
                    state_get = asyncio.ensure_future(self.state_slot.get())
        except (asyncio.CancelledError, ConnectionClosed):
            pass
        finally:
            reliable_get.cancel()
            state_get.cancel()

    async def send(self, obj: dict) -> None:
        """A direct reply, or a broadcast event, from async code."""
        self.reliable_queue.put_nowait(dumps(obj))
        self._check_backlog()

    def enqueue_event_text(self, text: str) -> None:
        """Same as send(), but callable synchronously: the EventLog callback runs
        inside sim.step(), on this event loop's thread but with no `await`
        available (docs/runtime.md: callbacks must be cheap, no re-entry)."""
        self.reliable_queue.put_nowait(text)
        self._check_backlog()

    def _check_backlog(self) -> None:
        if self.reliable_queue.qsize() > RELIABLE_QUEUE_WARN and not self._warned_slow:
            self._warned_slow = True
            log.warning("client %d (%s) is not draining messages (%d queued); closing",
                       self.id, self.client_name, self.reliable_queue.qsize())
            asyncio.ensure_future(self.ws.close(code=1011, reason="slow consumer"))

    def push_state(self, obj: dict) -> None:
        """Cyclic state push: latest value wins, never blocks, never grows."""
        text = dumps(obj)
        if self.state_slot.full():
            try:
                self.state_slot.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            self.state_slot.put_nowait(text)
        except asyncio.QueueFull:
            pass

    def restart_subscription(self, pump) -> None:
        self.stop_subscription()
        self.subscribe_task = asyncio.ensure_future(pump(self))

    def stop_subscription(self) -> None:
        if self.subscribe_task is not None:
            self.subscribe_task.cancel()
            self.subscribe_task = None

    def close(self) -> None:
        self.stop_subscription()
        self._writer_task.cancel()
