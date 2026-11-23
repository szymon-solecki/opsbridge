"""Assertions against the disposable RabbitMQ and verified opsbridge_test demo."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
import subprocess
import sys
from threading import Event
import time

import httpx
import pika
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from backend.app import event_worker
from backend.app.event_worker import consume_one, publish_one, verified_engine
from backend.app.messaging import Broker, DLQ, EXCHANGE, QUEUE, ROUTING_KEY
from backend.app.models import ActivityFeed, DeliveryEvent, InboxEvent, OutboxEvent
from backend.app.services.activity import rebuild_activity


BROKER = "amqp://127.0.0.1:5672/%2F"
API = "http://127.0.0.1:8000"


def await_condition(operation, seconds=15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if result := operation():
            return result
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for a demo condition")


def pending(engine):
    with Session(engine) as session:
        return session.scalar(select(OutboxEvent.event_id).where(
            OutboxEvent.published_at.is_(None), OutboxEvent.failed_at.is_(None),
        ).order_by(OutboxEvent.created_at, OutboxEvent.id).limit(1))


def outage(engine):
    event_id = pending(engine)
    assert event_id is not None
    broker = Broker(BROKER)
    try:
        assert publish_one(engine, broker)
    finally:
        broker.close()
    with Session(engine) as session:
        row = session.scalar(select(OutboxEvent).where(OutboxEvent.event_id == event_id))
        assert row.published_at is None and row.next_attempt_at is not None and row.last_error
    print("Broker unavailable: business events retained and retry scheduled.", flush=True)


def worker_interruption(mode):
    hook = "after_confirm" if mode == "publish" else "after_commit"
    operation = "publish_one" if mode == "publish" else "consume_one"
    code = f"""
import os
from datetime import datetime, timedelta, timezone
from backend.app.event_worker import {operation}, verified_engine
from backend.app.messaging import Broker
engine = verified_engine()
broker = Broker({BROKER!r})
{operation}(engine, broker, {hook}=lambda: os._exit(73){', clock=lambda: datetime.now(timezone.utc) + timedelta(minutes=2)' if mode == 'publish' else ''})
"""
    assert subprocess.run([sys.executable, "-c", code], check=False, timeout=15).returncode == 73


def count(engine, model):
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(model))


def publish_concurrently(engine, broker, horizon):
    ready, release = Event(), Event()

    def hold():
        ready.set()
        assert release.wait(8)

    def first():
        owned = Broker(BROKER)
        try:
            return publish_one(engine, owned, after_confirm=hold, clock=horizon)
        finally:
            owned.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(first)
        try:
            assert ready.wait(8)
            assert publish_one(engine, broker, clock=horizon)
        finally:
            release.set()
        assert result.result(timeout=10)


def drain(engine, limit=250):
    owned = Broker(BROKER)
    try:
        for _ in range(limit):
            if not consume_one(engine, owned):
                return
        raise AssertionError("Activity queue did not drain")
    finally:
        owned.close()


def start(engine):
    horizon = lambda: datetime.now(timezone.utc) + timedelta(minutes=2)
    broker = Broker(BROKER)
    first = pending(engine)
    worker_interruption("publish")
    assert pending(engine) == first
    assert publish_one(engine, broker, clock=horizon)
    assert broker.open().queue_declare(QUEUE, passive=True).method.message_count == 2
    worker_interruption("consume")
    assert count(engine, InboxEvent) == count(engine, ActivityFeed) == 1
    await_condition(lambda: broker.open().queue_declare(QUEUE, passive=True).method.message_count == 2)
    drain(engine)
    assert count(engine, InboxEvent) == count(engine, ActivityFeed) == 1
    print("Publisher restart repeated the event; consumer restart kept one inbox and one activity row.", flush=True)

    publish_concurrently(engine, broker, horizon)
    while publish_one(engine, broker, clock=horizon):
        pass
    with ThreadPoolExecutor(max_workers=2) as pool:
        workers = [pool.submit(drain, engine) for _ in range(2)]
        for worker in workers:
            worker.result(timeout=25)
    assert count(engine, ActivityFeed) == count(engine, InboxEvent) == count(engine, DeliveryEvent)
    assert pending(engine) is None

    channel = broker.open()
    channel.basic_publish(EXCHANGE, ROUTING_KEY, b"malformed",
                          properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
                          mandatory=True)
    assert consume_one(engine, broker)

    # A real publication fails after its PostgreSQL mutations but before commit.
    from demo_http import client

    api = client()
    integration_id = api.get("/integrations").json()[0]["id"]
    created = api.post(f"/integrations/{integration_id}/delivery-expectations", json={
        "delivery_type": "EVENT_RECOVERY", "business_date": "2026-01-01",
        "expected_pattern": "*.csv", "deadline_at": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
    })
    created.raise_for_status()
    delivery_id = created.json()["id"]
    failed_event = pending(engine)
    assert publish_one(engine, broker, clock=horizon)
    old_apply = event_worker.apply_publication
    attempts = []

    def fail_projection(*args):
        assert old_apply(*args)
        attempts.append(1)
        raise OperationalError("Synthetic projection failure", None, RuntimeError())

    event_worker.apply_publication = fail_projection
    try:
        for _ in range(3):
            assert await_condition(lambda: consume_one(engine, broker))
            with Session(engine) as session:
                assert session.get(InboxEvent, failed_event) is None
                assert session.get(ActivityFeed, failed_event) is None
    finally:
        event_worker.apply_publication = old_apply
    assert len(attempts) == 3
    await_condition(lambda: channel.queue_declare(DLQ, passive=True).method.message_count == 2)
    assert channel.queue_declare(QUEUE, passive=True).method.message_count == 0
    print("Malformed and exhausted publications reached the DLQ; partial projection writes rolled back.", flush=True)

    for _ in range(2):
        with Session(engine) as session, session.begin():
            assert rebuild_activity(session) == session.scalar(select(func.count()).select_from(DeliveryEvent))
    assert count(engine, ActivityFeed) == count(engine, DeliveryEvent)
    filtered = api.get("/dashboard/activity", params={"delivery_id": delivery_id, "event_type": "DeliveryExpectationCreated"})
    filtered.raise_for_status()
    assert [row["source_event_id"] for row in filtered.json()["items"]] == [str(failed_event)]
    first_page = api.get("/dashboard/activity", params={"limit": 5}).json()
    second_page = api.get("/dashboard/activity", params={
        "limit": 5, "before_at": first_page["next_before_at"], "before_id": first_page["next_before_id"],
    }).json()
    assert len(second_page["items"]) == 5
    assert not ({row["source_event_id"] for row in first_page["items"]}
                & {row["source_event_id"] for row in second_page["items"]})
    assert api.get("/dashboard/activity", params={"before_at": "2026-01-01T00:00:00Z"}).status_code == 422
    broker.close()
    print("Rebuilt twice from authoritative history; activity filter and cursor verified.", flush=True)


if __name__ == "__main__":
    engine = verified_engine()
    try:
        (outage if sys.argv[1] == "outage" else start)(engine)
    finally:
        engine.dispose()
