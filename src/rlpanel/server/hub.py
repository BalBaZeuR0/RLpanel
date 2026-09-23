"""WebSocket yayını. `publish` herhangi bir thread'den çağrılabilir."""
from __future__ import annotations

import asyncio
import json

from fastapi import WebSocket, WebSocketDisconnect


class Hub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    async def serve(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            self._clients.discard(websocket)

    async def broadcast(self, event: dict) -> None:
        text = json.dumps(event, ensure_ascii=False, default=str)
        for websocket in list(self._clients):
            try:
                await websocket.send_text(text)
            except Exception:
                self._clients.discard(websocket)

    def publish(self, event: dict) -> None:
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is loop:
            loop.create_task(self.broadcast(event))
        else:
            asyncio.run_coroutine_threadsafe(self.broadcast(event), loop)
