"""Fan out committed PostgreSQL invalidations through one listener per API process."""

import asyncio
from threading import Event, Thread

import psycopg
from sqlalchemy.engine import make_url

from backend.app.config import get_database_url
from backend.app.telemetry import report

CHANNEL = "opsbridge_dashboard"


class DashboardSignal:
    def __init__(self):
        self.online = False
        self.subscribers = set()
        self.pending = None
        self.thread = None
        self.stop = Event()

    def start(self):
        if self.thread is None:
            loop = asyncio.get_running_loop()
            self.thread = Thread(target=self.listen, args=(loop,), daemon=True)
            self.thread.start()

    async def close(self):
        self.stop.set()
        if self.pending is not None:
            self.pending.cancel()
        if self.thread is not None:
            await asyncio.to_thread(self.thread.join, 4)

    def broadcast(self):
        self.pending = None
        for subscriber in self.subscribers:
            subscriber.set()

    def connected(self, online):
        self.online = online
        self.broadcast()

    def invalidate(self, loop):
        if self.pending is None:
            self.pending = loop.call_later(0.35, self.broadcast)

    def listen(self, loop):
        def notify(callback, *args):
            if not self.stop.is_set():
                loop.call_soon_threadsafe(callback, *args)

        while not self.stop.is_set():
            try:
                url = make_url(get_database_url()).set(drivername="postgresql")
                with psycopg.connect(url.render_as_string(hide_password=False), autocommit=True,
                                     connect_timeout=3, application_name="opsbridge-dashboard-listener") as connection:
                    connection.execute(f"LISTEN {CHANNEL}")
                    notify(self.connected, True)
                    while not self.stop.is_set():
                        for _notification in connection.notifies(timeout=1, stop_after=1):
                            notify(self.invalidate, loop)
            except (psycopg.Error, OSError, ValueError, RuntimeError):
                notify(self.connected, False)
                report("DASHBOARD_LISTENER_UNAVAILABLE")
                self.stop.wait(2)

    async def stream(self):
        self.start()
        changed = asyncio.Event()
        self.subscribers.add(changed)
        try:
            yield "retry: 3000\n\n"
            if not self.online:
                try:
                    await asyncio.wait_for(changed.wait(), 4)
                except TimeoutError:
                    pass
            while self.online:
                changed.clear()
                yield "event: invalidate\ndata: {}\n\n"
                while self.online and not changed.is_set():
                    try:
                        await asyncio.wait_for(changed.wait(), 10)
                    except TimeoutError:
                        yield "event: heartbeat\ndata: {}\n\n"
            yield "event: unavailable\ndata: {}\n\n"
        finally:
            self.subscribers.remove(changed)
