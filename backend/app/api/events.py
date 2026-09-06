"""Single-process WebSocket notification hub.

It deliberately emits only invalidation hints.  REST remains the sole channel
for protected message bodies and authoritative state.
"""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import WebSocket


class EventHub:
    def __init__(self) -> None:
        self._connections: dict[str, set[asyncio.Queue[dict]]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, user_id: str) -> asyncio.Queue[dict]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._connections.setdefault(user_id, set()).add(queue)
        return queue

    async def disconnect(self, user_id: str, queue: asyncio.Queue[dict]) -> None:
        async with self._lock:
            queues = self._connections.get(user_id)
            if queues is None:
                return
            queues.discard(queue)
            if not queues:
                self._connections.pop(user_id, None)

    async def publish(self, user_ids: list[str], event_type: str, data: dict) -> None:
        event = {"event_id": str(uuid4()), "type": event_type, "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"), "data": data}
        slow: list[tuple[str, asyncio.Queue[dict]]] = []
        async with self._lock:
            for user_id in set(user_ids):
                for queue in self._connections.get(user_id, set()).copy():
                    try:
                        queue.put_nowait(event)
                    except asyncio.QueueFull:
                        slow.append((user_id, queue))
            for user_id, queue in slow:
                queues = self._connections.get(user_id)
                if queues:
                    queues.discard(queue)
                    if not queues:
                        self._connections.pop(user_id, None)


event_hub = EventHub()


async def send_event(websocket: WebSocket, event_type: str, data: dict) -> None:
    await websocket.send_json({"event_id": str(uuid4()), "type": event_type, "occurred_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"), "data": data})
