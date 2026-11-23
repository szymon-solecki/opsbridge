# OpsBridge reliability and performance report

## Environment and reproduction

Measurements were collected on one Windows workstation using Docker Desktop Engine 29.9.3, Compose 5.7.0, a Linux VM with 32 logical CPUs and 16,602,288,128 bytes of memory, PostgreSQL 17.12, RabbitMQ `4.2-management`, Mailpit `v1.27`, and containerized Chromium. The Windows harness ran on CPython 3.14.10. The bounded-page backend image in the first load comparison begins `f06d8155e9c8`; its dashboard image ID begins `b8d78691c85a`. Images are built from the working tree. Image tags can change over time. The harness records image IDs and the database version in every JSON result.

From the repository root in PowerShell, build the two application images, the SFTP image and the browser runner. Populate the disposable lab's image cache with the listed dependencies if needed.

```powershell
docker build -t opsbridge-backend:intake-check backend
docker build -t opsbridge-sftp:intake-check infra/sftp
docker build -t opsbridge-dashboard:demo frontend
docker build --target browser-tests -t opsbridge-dashboard:browser frontend
docker pull postgres:17
docker pull rabbitmq:4.2-management
docker pull axllent/mailpit:v1.27
```

```powershell
.\.venv\Scripts\python.exe scripts/performance_lab.py --deliveries 100 --records 20000
.\.venv\Scripts\python.exe scripts/performance_lab.py --deliveries 1000 --records 20000
.\.venv\Scripts\python.exe scripts/verify_intake_demo.py --tests --dashboard-test --operations --events --notifications --reconciliation --faults
```

`--deliveries 10000 --timeout 1800` selects the extended run. `--records` accepts 1,000, 10,000 or 20,000 per reconciliation source. Use `--operators`, `--workers` and `--dispatchers` to vary concurrency. `--workers` sets the replica count for each of intake and processing. The matching microbenchmark always runs at all three sizes. Retain the JSON output to compare samples from repeated runs.

The lab requires a local Docker endpoint. PostgreSQL starts in a private network namespace, and services sharing the namespace use its loopback interface. The performance and fault runs publish no host ports. Both use generated synthetic operators, disposable storage, and a fresh database whose identity is checked with `SELECT current_database()` before applying migrations. Neither uses the development database, local SFTP mappings or `.env`. The fault regression modifies only the disposable PostgreSQL container's host-based authentication rules and restores them even if an assertion fails. The expense of these workloads keeps them outside the default fast test suite.

## Workload and delivery results

Two synthetic vendors publish batches through the OpenSSH SFTP subsystem, dropping 10% invalid one-row CSVs into the mix. Each run adds an exact duplicate upload and two valid files for one 20,000-record-per-source reconciliation. There are two intake workers, two processing workers, two notification dispatchers, one reconciliation worker, one publisher and one consumer. Four independent authenticated operator sessions read through nginx during ingestion. HTTP fixtures are created before timing. End-to-end samples measure from batch release to each delivery's persisted completion or validation failure; these include queue waiting and do not measure single-file upload latency. Convergence includes drained queues, notification delivery and reconciliation.

| Workload | Last terminal result | Throughput | Full convergence | End-to-end p50 / p95 / p99 |
| --- | ---: | ---: | ---: | ---: |
| 100 deliveries, baseline | 6.151 s | 16.26/s | 10.766 s | 3.606 / 6.049 / 6.129 s |
| 1,000 deliveries, baseline | 38.911 s | 25.70/s | 65.845 s | 19.703 / 36.122 / 38.783 s |
| 1,000 deliveries, bounded page | 46.828 s | 21.36/s | 76.004 s | 17.426 / 42.111 / 44.678 s |

The 100-delivery trial had 103 finalized claims and 102 files (92 completed, 10 validation failures). It projected all 391 outbox events and sent 20 notifications. Both 1,000-delivery trials had 1,003 finalized claims and 1,002 files (902 completed, 100 validation failures). Each projected all 3,811 outbox events into 3,811 inbox and activity records and sent 200 notifications. Each trial had one completed reconciliation, zero deadlocks, zero terminal notification or outbox failures, and zero dead-letter messages. The extra upload was finalized without an extra business file.

| Peak sampled count | 100 baseline | 1,000 baseline | 1,000 bounded page |
| --- | ---: | ---: | ---: |
| PostgreSQL connections to `opsbridge_test` | 11 | 13 | 15 |
| PostgreSQL lock waiters | 0 | 1 | 1 |
| Pending outbox rows | 57 | 954 | 1,037 |
| Ready broker messages | 57 | 1,056 | 964 |
| Unacknowledged broker messages | 1 | 1 | 1 |

The observer sampled database and broker counters 13, 86 and 101 times. Docker resource snapshots numbered 6, 24 and 28. Representative maxima after the optimization are below. CPU is Docker's percentage of one logical core; resource use for replicated roles is summed per sample. Memory is Docker-reported container memory in MiB. Peak usage between samples may be higher.

| Role | Peak CPU | Peak memory |
| --- | ---: | ---: |
| PostgreSQL | 255.41% | 108.80 MiB |
| API | 118.08% | 212.60 MiB |
| Intake | 64.38% | 151.52 MiB |
| Processing | 73.33% | 127.67 MiB |
| Reconciliation | 26.24% | 91.91 MiB |
| Notification dispatchers | 16.71% | 147.91 MiB |
| Outbox publisher | 26.39% | 62.36 MiB |
| Activity consumer | 29.23% | 63.12 MiB |
| RabbitMQ | 40.24% | 278.80 MiB |
| nginx | 1.79% | 29.21 MiB |
| Mailpit | 3.00% | 43.57 MiB |

## Reconciliation and authenticated HTTP

The matcher ran with unique reference keys, exact `Decimal` amounts and a one-cent difference on every tenth row. Five timed runs per size and a separate `tracemalloc` run were taken after stopping the load workers. Allocation measurements exclude construction of input fixtures and are Python allocations, not process RSS. With five samples, p95 and p99 equal the maximum. Ambiguous and duplicate groups are covered by regression tests rather than this unique-key microbenchmark.

| Records per source | Matcher p50 / p95 / p99 | Peak traced allocation |
| ---: | ---: | ---: |
| 1,000 | 10.00 / 11.34 / 11.34 ms | 0.97 MiB |
| 10,000 | 93.00 / 103.09 / 103.09 ms | 13.01 MiB |
| 20,000 | 217.88 / 222.44 / 222.44 ms | 26.68 MiB |

| Read | 1,000 baseline p50 / p95 / p99 | 1,000 bounded page p50 / p95 / p99 |
| --- | ---: | ---: |
| Dashboard overview, deliveries and attention, measured as a sequential group | 49.42 / 112.37 / 171.99 ms | 41.87 / 95.57 / 164.01 ms |
| Delivery-scoped incident list | 10.08 / 40.41 / 57.27 ms | 12.75 / 30.88 / 50.10 ms |
| Activity feed | 6.92 / 30.38 / 51.29 ms | 9.25 / 28.09 / 42.33 ms |
| Completed reconciliation, 20 items at offset 100 | 55.75 / 101.84 / 101.84 ms | 18.08 / 19.58 / 20.33 ms |
| Chromium, authenticated navigation to delivery-results rendering | 190.82 / 201.15 / 201.15 ms | 189.81 / 205.12 / 205.12 ms |

The completed reconciliation endpoint had 18 and 20 samples respectively, taken after workload convergence. The changed run had 687 samples per general HTTP read/group and zero HTTP or SSE errors. Seven fresh Chromium contexts reused an established session. The modified run's observed SSE connection received 205 invalidation signals; first signal arrived after 53.72 ms. That combines setup and waiting for a signal, and is not a distribution of commit-to-browser latency.

Previously the page selected and decoded the full persisted report in the API before discarding all but 20 groups. It now selects `limit + 1` display summaries in PostgreSQL, applies the category and offset before transfer, and preserves the original 1-based evidence index. The observed page p95 fell by 81%, without changing results, history or the schema. The PostgreSQL page plan uses the run-identity index and aggregates a bounded result after an ordinal JSON array scan. The measured page query took 6.64 ms. PostgreSQL still traverses the persisted JSON array, so high offsets and filters with few matches can increase work. The matcher remains unchanged. Delivery throughput varied across the two 1,000-delivery runs; no system-wide speedup is attributed to this change.

The sampled activity read used `ix_activity_feed_chronological` (0.032 ms). Due notification and pending outbox reads used their partial indexes (0.033 ms and 0.014 ms), with a small sort. The incident sample used a sequential scan over a small fixture table (0.044 ms). These are representative post-convergence read-only `EXPLAIN ANALYZE` samples. They cannot establish plan stability under large historical tables or peak write contention. The API reuses a default SQLAlchemy queue pool; the workers use short-lived connections and dedicated connections for lock scopes as needed. Connection samples include the observer. No new index or pool setting was justified by these observations. The gap of roughly 27–29 seconds between the last terminal delivery and convergence in the 1,000-delivery runs makes drain throughput the next profiling target. Convergence also includes notification and reconciliation completion, so this is not a measured consumer-only drain time.

## Convergence tail investigation

The lab now captures a time series of PostgreSQL counters and RabbitMQ ready and unacknowledged counts, plus final persisted timestamps for each stage. The outbox creation and activity insertion markers use PostgreSQL transaction-start timestamps. `published_at` follows the broker confirm and precedes the publisher database commit. `processed_at` is set inside the consumer transaction. The publisher and consumer structured logs mark the successful return from commit and, on the consumer path, the ACK call. A queue sample gives an upper bound for broker drain. Observer return and container shutdown are timed separately. Every run still requires the original counts and empty-queue predicate for convergence.

The SQL and AMQP probes run only in the disposable lab. They aggregate worker timings without recording business payloads. The timer around the physical PostgreSQL connection excludes the single identity check before the pool is instrumented. Publisher timing includes checkout, row selection, broker confirmation and transaction completion. Consumer processing includes the PostgreSQL transaction and acknowledgement. The nested projection SQL timer includes lazy checkout and excludes commit. These timers overlap within a worker and must not be summed as independent costs.

The publisher takes one outbox row per transaction and the consumer takes one delivery per AMQP `basic_get`. Both loop without an intentional delay after work and wait about 0.5 seconds on an empty poll. Intake scans incoming packages and waits two seconds between scans. Processing selects up to 100 candidates per cycle, reconciliation up to 25, and both wait two seconds between cycles. Notification dispatch selects up to 100 due jobs and waits one second between cycles. Those polling intervals were held constant for the comparison.

### Matched before and after runs

Each run used 1,000 deliveries, a 20,000-record reconciliation per source, two intake workers, two processing workers, two notification dispatchers and four authenticated operators. Both ran with the same probes, Docker VM, PostgreSQL, RabbitMQ, Mailpit, SFTP and dashboard images. The baseline backend image was `opsbridge-backend:intake-check` (`f06d8155e9c8`) and the updated image was `opsbridge-backend:tail-check` (`3c90146b307b`). The baseline command was the regular 1,000-delivery command above. The comparison used the same arguments and `--backend-image opsbridge-backend:tail-check`. The local aggregate JSON results are `data/performance/tail-before.json` and `data/performance/tail-after.json`. A first attempt was excluded because Docker routed the worker logs to stderr and the initial collector read stdout only.

| Last stage marker, seconds from batch release | Before | After |
| --- | ---: | ---: |
| SFTP vendor commands returned to the host | 1.418 | 1.320 |
| CSV validation success recorded | 33.892 | 32.997 |
| CSV validation failure recorded | 28.792 | 32.626 |
| Intake claim finalized | 33.915 | 33.020 |
| Opening notification marked sent | 29.539 | 33.430 |
| Last processing completion and workload terminal result | 36.571 | 35.719 |
| Reconciliation report committed, stored marker | 36.725 | 36.638 |
| Outbox row created, stored marker | 36.726 | 36.640 |
| RabbitMQ confirmation, stored publication marker | 43.334 | 37.053 |
| Publisher commit returned, log marker | 43.337 | 37.055 |
| Inbox processing marker | 56.221 | 37.502 |
| Activity row insertion marker | 56.219 | 37.501 |
| Final projection committed and ACK call returned, log marker | 56.225 | 37.505 |
| Zero ready and unacknowledged messages observed, original completion | 60.814 | 41.170 |
| Observer returned to host | 66.625 | 48.055 |

The baseline reproduced a 24.243 s gap after the last terminal delivery, compared with 26.934 s and 29.176 s in the earlier runs. At 36.759 s, all claims were finalized and all 200 opening notifications sent. There were still 703 pending outbox rows and only 2,243 committed projections. The reconciliation completed 0.154 s after the last terminal delivery. Publishing completed 6.766 s after that delivery, and the last consumer ACK call followed 12.888 s after publisher completion. The largest remaining step was draining through the consumer and committing activity projections. The final outcome depended on the worker pipeline for 19.654 s and on detecting broker drain for another 4.589 s. After the last ACK call the exported ready count stayed at 63 across samples before switching to zero. After the change it stayed at 175 and then switched to zero. The repeated values after the last ACK show that this metric can lag the worker. The experiment did not time when RabbitMQ internally processed the last ACK, so the corrected comparison uses the worker's ACK-call marker alongside the original observed-zero result.

The observer sleeps 0.6 s between snapshots. Baseline snapshots spent a mean 9 ms on PostgreSQL and 139 ms on the broker query, so that sampling loop alone does not explain the 4.589 s. The extra dashboard samples, thread shutdown and SSE join added 5.811 s between baseline completion detection and host observer return. Browser measurements and idle container shutdown occurred afterwards. Idle shutdown itself took 3.800 s before and 4.130 s after. Neither host teardown nor browser measurements counted toward convergence.

| Measured cost | Before | After |
| --- | ---: | ---: |
| Publisher, busy iteration mean | 11.265 ms | 7.519 ms |
| Publisher, physical database connections after identity check | 3,873 / 8.499 s | 0 |
| Publisher, broker confirmation mean | 3.427 ms | 3.630 ms |
| Consumer, `basic_get` with message mean | 4.332 ms | 4.469 ms |
| Consumer, message handling mean | 10.221 ms | 5.039 ms |
| Consumer, projection SQL and checkout mean | 8.526 ms | 3.399 ms |
| Consumer, physical database connections after identity check | 3,825 / 8.120 s | 0 |
| Peak pending outbox / broker ready | 1,066 / 967 | 911 / 616 |
| Tail using last projection and ACK-call marker | 19.654 s | 1.786 s |
| Tail using original convergence predicate | 24.243 s | 5.451 s |

The baseline opened thousands of fresh physical connections for two serial loops. The worker entry points now reuse one checked connection per publisher or consumer process. The pool has no overflow and checks connection liveness at checkout. Transaction scopes and ordering remain the same: hold the outbox row lock through confirm and commit, then deduplicate and project in one consumer transaction before ACK. No batch sizes, delays or completion conditions changed. Both runs finalized 1,003 claims and 1,002 files, persisted 3,811 outbox, inbox and activity rows, sent all 200 opening notifications, and had zero final outbox or AMQP backlog, DLQ entries, deadlocks or HTTP errors. Future incident escalation timers are outside the existing completion predicate. In this pair the original completion time improved from 60.814 s to 41.170 s (32.3%). Reduced connection setup is measured directly. The timings also include overlapping contention between workers, so the full wall-clock gain cannot be assigned to connection setup alone.

This comparison contains one pair of instrumented runs. RabbitMQ queue counters are sampled, and worker timing spans include scheduling under contention. The remaining consumer transport cost was 17.032 s summed across successful `basic_get` calls for the updated run. Repeated trials and a separate broker-side measurement would help quantify variability and metric lag before changing the consume protocol.

Verification on the updated image passed 223 backend tests, including the new isolated PostgreSQL test that terminates the worker's own idle connection and checks that the next checkout recovers. The disposable fault run passed publisher and consumer interruption, database and broker outage, DLQ and rebuild, and the other existing recovery checks. Chromium passed six live and five simulated-response cases. Backend image build, quiet Compose validation, Python syntax and scoped whitespace checks passed.

## Fault regression results

| Scenario | Verified behavior | Observed recovery |
| --- | --- | --- |
| RabbitMQ unavailable | Business writes and outbox persisted. The publisher scheduled retry. Starting RabbitMQ allowed backlog publication; readiness then recovered. | 4.37–4.50 s from container start to AMQP readiness across two runs. This excludes any publisher retry wait. |
| PostgreSQL connection rejection and session termination | Readiness changed to HTTP 503, then returned 200 after local connection rules were restored. File, event and outbox counts matched before and after. | 0.59–0.61 s to detect unavailability; 0.35 s after restoring access. |
| Processing exits after recording an attempt start | Recovery recorded the interruption, consumed one retry and persisted one completion without another receipt. | 5.65–5.78 s from starting the crash process to completion. |
| Publisher exits after confirm | A committed outbox event was published again. The event ID remained stable. | State verified with an advanced test retry clock; no wall-clock retry latency reported. |
| Consumer exits after database commit and before ACK | RabbitMQ redelivered a real message. The projection retained one inbox row and one activity row. A separate injected transaction failure rolled back both writes. | Verified by persisted state. |
| Notification dispatcher exits after SMTP acceptance | One durable job per recipient remained. The retried job recorded `UNKNOWN` then `SENT`. Mailpit captured two copies with the same Message-ID, consistent with at-least-once delivery. | 5.65–5.77 s from starting the crash process to `SENT`. |
| Duplicate SFTP delivery | Two accepted packages and one persisted file and receipt event. | Verified by durable counts. |
| Concurrent and restarted reconciliation | One worker owned the committed attempt. The interrupted run recovered and a corrected run preserved the previous result. | Verified by attempt history and stored results. |
| Blocked SSE then reconnect | Chromium showed polling fallback while its stream was blocked. After unblocking it showed `Live` and rendered the new committed delivery. | 5.03–5.06 s from unblocking until visible. |
| Poison messages and projection rebuild | Malformed and retry-exhausted messages reached the DLQ. Rebuilding twice from authoritative events preserved unique derived rows. | Verified by broker and database state. |

PostgreSQL injection tests client disconnection and rejected connections. RabbitMQ injection tests the broker absent and then available with committed events waiting. Worker injections exit real child processes at explicit boundaries; they do not approximate transaction outcomes with mocks. Browser injection blocks the streaming request but leaves the normal polling API available. Use these cases to reproduce recovery contracts, and keep distributed failover and longer soak tests separate.

## Regression and limits

The disposable Linux run passed 222 backend tests, including 42 PostgreSQL cases, and six live Chromium cases. The separate network-isolated browser run passed all five simulated-response cases. The production image builds and quiet Compose configuration validation passed. The Windows virtual environment was missing the declared Argon2 dependency during test collection; the containerized suite included it.

The load measurements are single trials of a synthetic mix on one machine. The 10,000-delivery extended run is available but was not executed. There is no capacity or service-level claim for production. The lab exercises OpenSSH's actual SFTP subsystem, local Linux permissions and package publication. It bypasses authenticated SSH setup and network latency. It does not model slow client links, multi-host production failover, power loss, long retention, or process saturation with many concurrent browser streams.
