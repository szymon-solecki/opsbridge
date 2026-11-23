"""Synthetic workload code run only inside the disposable performance lab."""

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread
from time import monotonic, perf_counter, sleep
import tracemalloc

DAY = date(2026, 1, 1)


def distribution(samples):
    values = sorted(samples)
    if not values:
        return {"samples": 0}
    return {"samples": len(values), **{
        name: round(values[(len(values) * pct + 99) // 100 - 1], 3)
        for name, pct in (("p50", 50), ("p95", 95), ("p99", 99), ("max", 100))
    }}


def now():
    return datetime.now(timezone.utc)


def matching_microbenchmark():
    from backend.app.services.matching import match

    results = {}
    for size in (1000, 10000, 20000):
        def record(index, difference):
            return (str(index), DAY, Decimal(index) + difference, "USD", "reference-" + str(index))

        left = [record(index, Decimal("0")) for index in range(size)]
        right = [record(index, Decimal("0.01") if index % 10 == 0 else Decimal("0")) for index in range(size)]
        kwargs = {"business_date": DAY, "match_on": "reference", "tolerance": Decimal("0.01")}
        times = []
        for _ in range(5):
            start = perf_counter()
            _, _, counts, _ = match(left, right, **kwargs)
            times.append((perf_counter() - start) * 1000)
            assert counts["EXACT"] + counts["WITHIN_TOLERANCE"] == size
        tracemalloc.start()
        match(left, right, **kwargs)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        results[size] = {"latency_ms": distribution(times), "peak_traced_mib": round(peak / 2**20, 3)}
    return results


def checked(response):
    response.raise_for_status()
    return response.json()


def seed(args):
    from demo_http import client

    api = client()
    for index in range(args.operators):
        checked(api.post("/auth/operators", json={
            "username": f"load-viewer-{index}", "role": "VIEWER",
            "password": os.environ["OPSBRIDGE_VIEWER_PASSWORD"],
        }))
    sources = []
    for side in range(2):
        integration = checked(api.post("/integrations", json={
            "name": f"Synthetic performance side {side}", "source_name": "Synthetic SFTP workload",
        }))["id"]
        sources.append(integration)
    def create_expectation(side, kind):
        return checked(api.post(f"/integrations/{sources[side]}/delivery-expectations", json={
            "business_date": str(DAY), "delivery_type": kind,
            "deadline_at": "2099-01-01T00:00:00Z", "expected_pattern": "data.csv",
        }))["id"]

    incident_delivery = None
    for index in range(args.deliveries):
        delivery = create_expectation(index % 2, f"LOAD_{index:05}")
        if index == 0:
            incident_delivery = delivery
    pair = [create_expectation(side, "LOAD_RECON") for side in range(2)]
    run = checked(api.post("/dashboard/reconciliation/definitions", json={
        "name": "Performance reconciliation", "business_date": str(DAY), "source_a_delivery_id": pair[0],
        "source_b_delivery_id": pair[1], "tolerance": "0.01", "match_on": "reference",
    }))["run_id"]
    return {"sources": sources, "incident_delivery": incident_delivery, "run": run}


def csv_payload(index, size=1, side=0):
    rows = ["record_id,record_date,amount,currency,reference"]
    for row in range(size):
        amount = "invalid" if index is not None and index % 10 == 0 else (
            f"{row}.01" if index is None and side == 1 and row % 10 == 0 else str(row))
        rows.append(f"id-{row},{DAY},{amount},USD,reference-{row}")
    return ("\n".join(rows) + "\n").encode()


def vendor(args):
    home = Path(os.environ["DEMO_HOME"])
    packages = [(f"p{index}", f"LOAD_{index:05}", f"load-{index}", index)
                for index in range(args.side, args.deliveries, 2)]
    if args.side == 1:
        # Repeat a valid package with the same business identity and exact bytes.
        packages.append(("duplicate", "LOAD_00001", "load-1", 1))
    packages.append(("reconciliation", "LOAD_RECON", f"recon-{args.side}", None))
    for start in range(0, len(packages), 50):
        with TemporaryDirectory() as local:
            commands = []
            for token, kind, source, index in packages[start:start + 50]:
                folder = Path(local) / token
                folder.mkdir()
                data = csv_payload(index, args.records if index is None else 1, args.side)
                (folder / "data.csv").write_bytes(data)
                (folder / "manifest.json").write_text(json.dumps({
                    "contract_version": 1, "business_date": str(DAY), "delivery_type": kind, "source_delivery_id": source,
                    "payload": {"file_name": "data.csv", "size_bytes": len(data), "sha256": sha256(data).hexdigest()},
                }), encoding="utf-8")
                stage = home / "staging" / token
                commands += [f"mkdir {stage}", f"put {token}/data.csv {stage}/data.csv",
                             f"put {token}/manifest.json {stage}/manifest.json", f"rename {stage} {home}/incoming/{token}"]
            subprocess.run(["sftp", "-D", "/usr/lib/openssh/sftp-server -u 0007", "-b", "-", "localhost"],
                           cwd=local, input="\n".join(commands) + "\n", text=True, check=True,
                           stdout=subprocess.DEVNULL)


STATS = """
SELECT
  (SELECT count(*) FROM intake_claims WHERE status='FINALIZED') final_claims,
  (SELECT count(*) FROM files) files,
  (SELECT count(*) FROM delivery_expectations WHERE status='COMPLETED') completed,
  (SELECT count(*) FROM delivery_expectations WHERE status='VALIDATION_FAILED') invalid,
  (SELECT count(*) FROM outbox_events WHERE published_at IS NULL AND failed_at IS NULL) outbox_pending,
  (SELECT count(*) FROM outbox_events WHERE failed_at IS NOT NULL) outbox_failed,
  (SELECT count(*) FROM outbox_events) outbox_count,
  (SELECT count(*) FROM inbox_events) inbox_count,
  (SELECT count(*) FROM activity_feed) activity_count,
  (SELECT count(*) FROM notification_jobs WHERE event='OPENED' AND status='SENT') sent,
  (SELECT count(*) FROM notification_jobs WHERE event='OPENED' AND status='FAILED') notification_failed,
  (SELECT count(*) FROM notification_jobs WHERE event='OPENED') opened,
  (SELECT count(*) FROM reconciliation_runs WHERE status='COMPLETED') reconciled,
  (SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()) connections,
  (SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock') lock_waiters,
  (SELECT deadlocks FROM pg_stat_database WHERE datname=current_database()) deadlocks
"""


STAGE_MARKERS = """
SELECT
  (SELECT max(finalized_at) FROM intake_claims) intake_finalized,
  (SELECT max(occurred_at) FROM delivery_events WHERE event_type='FileReceived') validation_succeeded,
  (SELECT max(occurred_at) FROM delivery_events WHERE event_type='FileValidationFailed') validation_failed,
  (SELECT max(occurred_at) FROM delivery_events WHERE event_type='FileProcessingCompleted') processing_completed,
  (SELECT max(finished_at) FROM reconciliation_runs WHERE status='COMPLETED') reconciliation_completed,
  (SELECT max(created_at) FROM outbox_events) outbox_created,
  (SELECT max(published_at) FROM outbox_events) outbox_confirmed,
  (SELECT max(processed_at) FROM inbox_events) inbox_processed,
  (SELECT max(created_at) FROM activity_feed) activity_inserted,
  (SELECT max(finished_at) FROM notification_jobs WHERE event='OPENED' AND status='SENT') notification_sent
"""


def observe(args):
    from demo_http import client
    import httpx
    from prometheus_client.parser import text_string_to_metric_families
    from sqlalchemy import text
    from backend.app.event_worker import verified_engine
    from backend.app.messaging import DLQ, QUEUE

    params = json.loads(args.fixture)
    stop = Event()
    ready = Event()
    lock = Lock()
    times = defaultdict(list)
    errors = defaultdict(int)
    samples = []
    failures = (args.deliveries + 9) // 10
    beginning = datetime.fromisoformat(args.start)

    endpoints = {
        "dashboard_group": ["/dashboard/overview", "/dashboard/deliveries?limit=21", "/dashboard/attention?limit=21"],
        "incidents": [f"/dashboard/deliveries/{params['incident_delivery']}/incidents?limit=20"],
        "activity": ["/dashboard/activity?limit=10"],
        "reconciliation_page": [f"/dashboard/reconciliation/runs/{params['run']}?offset=100&limit=20"],
    }

    def request(api, name, paths):
        start = perf_counter()
        failed = False
        try:
            for path in paths:
                response = api.get("http://127.0.0.1:8080/api" + path)
                failed |= response.status_code != 200
        except httpx.TransportError:
            failed = True
        finally:
            elapsed = (perf_counter() - start) * 1000
            with lock:
                errors[name] += int(failed)
                times[name].append(elapsed)

    def operator(api):
        try:
            while not stop.is_set():
                for name, paths in endpoints.items():
                    label = name + "_ready" if name == "reconciliation_page" and ready.is_set() else name
                    request(api, label, paths)
                stop.wait(0.35)
        finally:
            api.close()

    def sse(api):
        try:
            while not stop.is_set():
                start = perf_counter()
                try:
                    with api.stream("GET", "http://127.0.0.1:8080/api/dashboard/stream", timeout=12) as response:
                        response.raise_for_status()
                        first = True
                        for line in response.iter_lines():
                            if line == "event: invalidate":
                                times["sse_invalidation"].append((perf_counter() - start) * 1000 if first else 0)
                                first = False
                            if stop.is_set():
                                return
                except httpx.HTTPError:
                    if not stop.is_set():
                        errors["sse"] += 1
                        stop.wait(0.5)
        finally:
            api.close()

    def broker_metrics():
        response = httpx.get("http://127.0.0.1:15692/metrics/per-object", timeout=2)
        response.raise_for_status()
        return {
            (sample.name, sample.labels.get("queue")): int(sample.value)
            for family in text_string_to_metric_families(response.text) for sample in family.samples
            if sample.labels.get("queue") in {QUEUE, DLQ}
            and sample.name in {"rabbitmq_queue_messages_ready", "rabbitmq_queue_messages_unacked"}
        }

    started = monotonic()
    engine = verified_engine()
    # Provision separate sessions serially before releasing concurrent clients.
    operators = [client(username=f"load-viewer-{index}", variable="OPSBRIDGE_VIEWER_PASSWORD")
                 for index in range(args.operators)]
    stream = Thread(target=sse, args=(client(username="load-viewer-0", variable="OPSBRIDGE_VIEWER_PASSWORD"),),
                    daemon=True)
    stream.start()
    try:
        with ThreadPoolExecutor(max_workers=args.operators) as pool:
            futures = [pool.submit(operator, api) for api in operators]
            try:
                while monotonic() - started < args.timeout:
                    poll_started = now()
                    with engine.connect() as connection:
                        state = dict(connection.execute(text(STATS)).mappings().one())
                    db_sampled = now()
                    q = broker_metrics()
                    state.update(queue_ready=q.get(("rabbitmq_queue_messages_ready", QUEUE), 0),
                                 queue_unacked=q.get(("rabbitmq_queue_messages_unacked", QUEUE), 0),
                                 dlq=q.get(("rabbitmq_queue_messages_ready", DLQ), 0))
                    sampled = now()
                    samples.append(state | {"at_s": round((sampled - beginning).total_seconds(), 3),
                                            "db_sample_ms": round((db_sampled - poll_started).total_seconds() * 1000, 3),
                                            "broker_sample_ms": round((sampled - db_sampled).total_seconds() * 1000, 3)})
                    if (state["final_claims"] == args.deliveries + 3 and state["completed"] + state["invalid"] == args.deliveries + 2
                            and state["reconciled"] == 1 and state["outbox_pending"] == 0
                            and state["outbox_count"] == state["inbox_count"] == state["activity_count"]
                            and state["sent"] == state["opened"] == failures * 2
                            and not any(state[key] for key in ("queue_ready", "queue_unacked", "dlq"))):
                        converged = (sampled - beginning).total_seconds()
                        ready.set()
                        sleep(2)
                        break
                    if any(future.done() for future in futures):
                        next(future for future in futures if future.done()).result()
                        raise AssertionError("Load client exited early")
                    sleep(0.6)
                else:
                    raise TimeoutError(f"Workload did not converge. Last counters: {samples[-1] if samples else {}}")
                assert state["files"] == args.deliveries + 2
                assert state["invalid"] == failures
                assert state["outbox_failed"] == state["notification_failed"] == state["deadlocks"] == 0
            finally:
                stop.set()
        operators_done = now()
        stream.join(timeout=12)
        stream_done = now()

        with engine.connect() as connection:
            markers = connection.execute(text(STAGE_MARKERS)).mappings().one()
            rows = connection.execute(text("""
                SELECT e.occurred_at FROM delivery_events e JOIN delivery_expectations d
                ON d.id=e.delivery_expectation_id
                WHERE d.delivery_type ~ '^LOAD_[0-9]+$'
                AND e.event_type IN ('FileProcessingCompleted','FileValidationFailed')
            """)).scalars().all()
            assert len(rows) == args.deliveries
            elapsed = (max(rows) - beginning).total_seconds()
        return {
            "deliveries": args.deliveries, "operators": args.operators, "reconciliation_records": args.records,
            "pipeline_s": round(elapsed, 3), "convergence_s": round(converged, 3),
            "deliveries_per_s": round(args.deliveries / elapsed, 3),
            "delivery_e2e_ms": distribution([(value - beginning).total_seconds() * 1000 for value in rows]),
            "http_ms": {name: distribution(values) for name, values in times.items() if name != "sse_invalidation"},
            "http_errors": dict(errors),
            "sse": {"invalidations": len(times["sse_invalidation"]),
                    "first_signal_ms": distribution([value for value in times["sse_invalidation"] if value > 0])},
            "peaks": {key: max(sample[key] for sample in samples) for key in (
                "connections", "lock_waiters", "queue_ready", "queue_unacked", "outbox_pending", "dlq")},
            "final": state, "samples": len(samples),
            "timeline_s": {key: round((stamp - beginning).total_seconds(), 3) for key, stamp in markers.items()}
            | {"completion_detected": round(converged, 3),
               "operators_stopped": round((operators_done - beginning).total_seconds(), 3),
               "sse_join_returned": round((stream_done - beginning).total_seconds(), 3)},
            "queue_timeline": samples,
            "plans": query_plans(engine, params),
        }
    finally:
        engine.dispose()


def query_plans(engine, fixture):
    from sqlalchemy import text
    from backend.app.api.routers.reconciliation import RESULT_PAGE_SQL

    queries = {
        "activity": "SELECT * FROM activity_feed ORDER BY occurred_at DESC, source_event_id DESC LIMIT 11",
        "incidents": "SELECT * FROM incidents WHERE delivery_expectation_id=:delivery ORDER BY opened_at DESC,id DESC LIMIT 21",
        "outbox": """SELECT id FROM outbox_events WHERE published_at IS NULL AND failed_at IS NULL
                     AND (next_attempt_at <= now() OR next_attempt_at IS NULL)
                     ORDER BY created_at,id LIMIT 1""",
        "notification": """SELECT id FROM notification_jobs WHERE status IN ('PENDING','SENDING')
                          AND next_attempt_at <= now() ORDER BY next_attempt_at,id LIMIT 100""",
        "reconciliation": "SELECT report FROM reconciliation_runs WHERE id=:run",
        "reconciliation_page": "SELECT (" + RESULT_PAGE_SQL + ") FROM reconciliation_runs WHERE id=:run",
    }
    result = {}
    with engine.connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        for name, sql in queries.items():
            plan = connection.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql),
                                      {"delivery": fixture["incident_delivery"], "run": fixture["run"],
                                       "category": None, "fetch": 21, "offset": 100}).scalar_one()[0]
            def nodes(node):
                return [node.get("Index Name", node["Node Type"])] + [
                    value for child in node.get("Plans", []) for value in nodes(child)
                ]
            result[name] = {"execution_ms": plan["Execution Time"], "nodes": nodes(plan["Plan"]),
                            "shared_hits": plan["Plan"].get("Shared Hit Blocks", 0)}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("seed", "vendor", "observe", "matching"))
    parser.add_argument("--deliveries", type=int)
    parser.add_argument("--records", type=int)
    parser.add_argument("--operators", type=int)
    parser.add_argument("--side", type=int)
    parser.add_argument("--start")
    parser.add_argument("--fixture")
    parser.add_argument("--timeout", type=int)
    args = parser.parse_args()
    functions = {"seed": lambda: seed(args), "vendor": lambda: vendor(args),
                 "observe": lambda: observe(args), "matching": matching_microbenchmark}
    print(json.dumps(functions[args.mode]()))


if __name__ == "__main__":
    main()
