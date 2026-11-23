"""Measure transport and PostgreSQL costs inside one disposable event worker."""

from functools import wraps
from time import perf_counter

from pika.adapters.blocking_connection import BlockingChannel

from backend.app import event_worker
from backend.app.telemetry import OPERATIONS


def instrument(operation, function, *, classify=None):
    @wraps(function)
    def measured(*args, **kwargs):
        started = perf_counter()
        label = operation
        try:
            result = function(*args, **kwargs)
            if classify is not None:
                label = classify(result)
            return result
        finally:
            OPERATIONS.labels(label).observe(perf_counter() - started)

    return measured


def verified_engine(*args, **kwargs):
    engine = original_engine(*args, **kwargs)
    engine.dialect.connect = instrument("physical_db_connect", engine.dialect.connect)
    return engine


original_engine = event_worker.verified_engine

if __name__ == "__main__":
    event_worker.verified_engine = verified_engine
    event_worker.Broker.publish = instrument("broker_confirm", event_worker.Broker.publish)
    event_worker.publish_one = instrument("publish_step", event_worker.publish_one,
                                          classify=lambda worked: "publish_busy" if worked else "publish_idle")
    event_worker.apply_publication = instrument("projection_sql", event_worker.apply_publication)
    BlockingChannel.basic_get = instrument("broker_get", BlockingChannel.basic_get,
                                            classify=lambda result: "broker_get_message" if result[0] else "broker_get_empty")
    raise SystemExit(event_worker.main())
