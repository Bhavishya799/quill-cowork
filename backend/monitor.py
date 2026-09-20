"""Background monitor — polls tools on a schedule."""

import asyncio
from typing import Callable, Awaitable, Optional
from datetime import datetime


class Monitor:
    def __init__(self, interval_seconds: int = 300):
        self.interval = interval_seconds
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self._callback: Optional[Callable[[], Awaitable[str]]] = None
        self.last_run: Optional[str] = None
        self.last_result: Optional[str] = None

    def set_callback(self, cb):
        self._callback = cb

    async def _loop(self):
        while self.running:
            try:
                if self._callback:
                    self.last_result = await self._callback()
                    self.last_run = datetime.now().isoformat()
            except Exception as e:
                self.last_result = f"Monitor error: {e}"
            await asyncio.sleep(self.interval)

    def start(self):
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._loop())

    def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            self._task = None


monitor = Monitor(interval_seconds=300)