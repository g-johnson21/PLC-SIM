"""A real protocol server on an ephemeral port (never 8765), driven from the test's own
event loop. The scan loop is not started: tests call `sim.step()` between messages, so
every reply is deterministic. pytest-asyncio is not installed; `async_test` runs each
test coroutine with `asyncio.run`."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import itertools
import json

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from draco_sim.protocol.codec import dumps
from draco_sim.protocol.server import _process_request, handle_client
from draco_sim.runtime import Pacer

from ..runtime.helpers import make_sim

TIMEOUT = 5.0


def async_test(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        asyncio.run(asyncio.wait_for(fn(*args, **kwargs), 30.0))
    return wrapper


class Client:
    def __init__(self, ws) -> None:
        self.ws = ws
        self.welcome: dict | None = None
        self.events: list[dict] = []
        self.states: list[dict] = []
        self._ids = itertools.count(1)

    async def next(self, timeout: float = TIMEOUT) -> dict:
        msg = json.loads(await asyncio.wait_for(self.ws.recv(), timeout))
        if msg.get("type") == "event":
            self.events.append(msg)
        elif msg.get("type") == "state":
            self.states.append(msg)
        return msg

    async def next_of(self, type_: str, timeout: float = TIMEOUT) -> dict:
        while True:
            msg = await self.next(timeout)
            if msg.get("type") == type_:
                return msg

    async def send(self, obj) -> None:
        await self.ws.send(obj if isinstance(obj, str) else json.dumps(obj))

    async def reply(self, mid) -> dict:
        while True:
            msg = await self.next()
            if msg.get("type") not in ("event", "state") and msg.get("id") == mid:
                return msg

    async def request(self, type_: str, **fields) -> dict:
        mid = f"r{next(self._ids)}"
        await self.send({"type": type_, "id": mid, **fields})
        return await self.reply(mid)

    async def ok(self, type_: str, **fields) -> dict:
        reply = await self.request(type_, **fields)
        assert reply["type"] != "error", reply
        return reply

    async def error(self, code: str, type_: str, **fields) -> dict:
        reply = await self.request(type_, **fields)
        assert reply["type"] == "error" and reply["code"] == code, reply
        return reply

    async def drain(self, wait: float = 0.15) -> None:
        with contextlib.suppress(TimeoutError):
            while True:
                await self.next(wait)

    def event_texts(self, level: str | None = None) -> list[str]:
        return [e["text"] for e in self.events if level is None or e["level"] == level]


class Stand:
    def __init__(self, sim) -> None:
        self.sim = sim
        self.pacer = Pacer(sim, realtime=True)
        self.connections: set = set()
        self.port = 0
        # the same fan-out run_server installs
        sim.on_event(self._broadcast)

    def _broadcast(self, event) -> None:
        text = dumps({"type": "event", **event.as_dict()})
        for conn in list(self.connections):
            conn.enqueue_event_text(text)

    def connection(self, client_name: str):
        return next(c for c in self.connections if c.client_name == client_name)

    @contextlib.asynccontextmanager
    async def client(self, name: str = "pytest", hello: bool = True, path: str = "/ws"):
        async with connect(f"ws://127.0.0.1:{self.port}{path}") as ws:
            client = Client(ws)
            if hello:
                client.welcome = await client.ok("hello", client=name, protocol=1)
            yield client


@contextlib.asynccontextmanager
async def stand(sim=None, examples: bool = True):
    stand_ = Stand(sim if sim is not None else make_sim(examples=examples))
    handler = functools.partial(handle_client, sim=stand_.sim, pacer=stand_.pacer,
                                connections=stand_.connections)
    async with serve(handler, "127.0.0.1", 0, process_request=_process_request) as server:
        stand_.port = server.sockets[0].getsockname()[1]
        yield stand_


async def wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            return False
        await asyncio.sleep(0.01)
    return True
