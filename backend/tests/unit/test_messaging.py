from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pika
import pytest
from sqlalchemy.exc import OperationalError

from backend.app.messaging import Broker, EXCHANGE, Publication, ROUTING_KEY
from backend.app import event_worker


def test_publisher_sets_durable_routed_message_and_stable_identity(monkeypatch):
    event = Publication(uuid4(), "DeliveryStatusChanged")
    broker = Broker("amqp://localhost")
    calls = []

    def publish(*args, **kwargs):
        calls.append((args, kwargs))
        raise pika.exceptions.NackError([])

    monkeypatch.setattr(broker, "open", lambda: SimpleNamespace(basic_publish=publish))
    with pytest.raises(pika.exceptions.NackError):
        broker.publish(event)
    (exchange, key, body), options = calls[0]
    assert (exchange, key) == (EXCHANGE, ROUTING_KEY)
    assert options["mandatory"] and options["properties"].delivery_mode == 2
    assert Publication.decode(body, options["properties"]) == event


@pytest.mark.parametrize("value", [b"true", b"2", b'"1"', b"1.0"])
def test_envelope_rejects_other_schema_versions(value):
    event = Publication(uuid4(), "DeliveryStatusChanged")
    properties = SimpleNamespace(content_type="application/json", message_id=str(event.event_id), type=event.event_type)
    with pytest.raises(ValueError):
        Publication.decode(event.encode().replace(b'"schema_version":1', b'"schema_version":' + value), properties)


def test_envelope_rejects_mismatched_message_id():
    event = Publication(uuid4(), "DeliveryStatusChanged")
    properties = SimpleNamespace(content_type="application/json", message_id=str(uuid4()), type=event.event_type)
    with pytest.raises(ValueError):
        Publication.decode(event.encode(), properties)


@pytest.mark.parametrize(("attempt", "retry"), [(0, True), (1, True), (2, False)])
def test_projection_failure_uses_broker_integer_delivery_count(monkeypatch, attempt, retry):
    class BrokerInteger(int):
        pass

    event = Publication(uuid4(), "DeliveryStatusChanged")
    properties = SimpleNamespace(content_type="application/json", message_id=str(event.event_id),
                                 type=event.event_type, headers={"x-delivery-count": BrokerInteger(attempt)})
    channel = MagicMock()
    wait = MagicMock()
    monkeypatch.setattr(event_worker, "Session", MagicMock())
    monkeypatch.setattr(event_worker, "apply_publication", MagicMock(
        side_effect=OperationalError("Synthetic projection failure", None, RuntimeError())
    ))
    event_worker.handle_message(None, channel, SimpleNamespace(delivery_tag=7), properties, event.encode(), wait=wait)
    channel.basic_reject.assert_called_once_with(7, requeue=retry)
    channel.basic_ack.assert_not_called()
    assert wait.call_count == int(retry)
