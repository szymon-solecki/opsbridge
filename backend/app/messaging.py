"""Durable RabbitMQ transport for OpsBridge publications."""

from dataclasses import dataclass
import json
from uuid import UUID

import pika

EXCHANGE = "opsbridge.events.v1"
QUEUE = "opsbridge.activity.v1"
DLX = "opsbridge.dead.v1"
DLQ = "opsbridge.activity.dead.v1"
ROUTING_KEY = "delivery"
MAX_MESSAGE_BYTES = 4096


@dataclass(frozen=True)
class Publication:
    event_id: UUID
    event_type: str

    def encode(self) -> bytes:
        return json.dumps({"schema_version": 1, "event_id": str(self.event_id),
                           "event_type": self.event_type}, separators=(",", ":")).encode("utf-8")

    @classmethod
    def decode(cls, body, properties):
        if len(body) > MAX_MESSAGE_BYTES or properties.content_type != "application/json":
            raise ValueError("Invalid event representation")
        data = json.loads(body.decode("utf-8"))
        if (not isinstance(data, dict) or set(data) != {"schema_version", "event_id", "event_type"}
                or type(data["schema_version"]) is not int or data["schema_version"] != 1
                or not isinstance(data["event_id"], str) or not isinstance(data["event_type"], str)
                or not 1 <= len(data["event_type"]) <= 100):
            raise ValueError("Invalid event schema")
        event_id = UUID(data["event_id"])
        if str(event_id) != data["event_id"] or properties.message_id != str(event_id):
            raise ValueError("Invalid event ID")
        if properties.type != data["event_type"]:
            raise ValueError("Invalid event type")
        return cls(event_id, data["event_type"])


def declare_topology(channel):
    channel.exchange_declare(DLX, "direct", durable=True)
    channel.queue_declare(DLQ, durable=True, arguments={"x-queue-type": "quorum"})
    channel.queue_bind(DLQ, DLX, ROUTING_KEY)
    channel.exchange_declare(EXCHANGE, "direct", durable=True)
    channel.queue_declare(QUEUE, durable=True, arguments={
        "x-queue-type": "quorum", "x-delivery-limit": 3,
        "x-dead-letter-exchange": DLX, "x-dead-letter-routing-key": ROUTING_KEY,
        "x-dead-letter-strategy": "at-least-once", "x-overflow": "reject-publish",
    })
    channel.queue_bind(QUEUE, EXCHANGE, ROUTING_KEY)


class Broker:
    def __init__(self, url):
        self.parameters = pika.URLParameters(url)
        self.parameters.connection_attempts = 1
        self.parameters.socket_timeout = 3
        self.parameters.stack_timeout = 5
        self.parameters.blocked_connection_timeout = 5
        self.parameters.heartbeat = 10
        self.connection = self.channel = None

    def open(self):
        if self.connection is None or self.connection.is_closed:
            self.connection = pika.BlockingConnection(self.parameters)
            self.channel = self.connection.channel()
            declare_topology(self.channel)
            self.channel.confirm_delivery()
            self.channel.basic_qos(prefetch_count=1)
        return self.channel

    def publish(self, event):
        channel = self.open()
        channel.basic_publish(
            EXCHANGE, ROUTING_KEY, event.encode(), mandatory=True,
            properties=pika.BasicProperties(
                content_type="application/json", delivery_mode=2,
                message_id=str(event.event_id), type=event.event_type,
            ),
        )

    def close(self):
        connection, self.connection, self.channel = self.connection, None, None
        if connection is not None and connection.is_open:
            try:
                connection.close()
            except (pika.exceptions.AMQPError, OSError):
                pass

    def service(self, seconds):
        if self.connection is not None and self.connection.is_open:
            self.connection.process_data_events(time_limit=seconds)
            return True
        return False
