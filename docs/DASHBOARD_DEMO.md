# OpsBridge dashboard demo

The operations workspace shows which integrations send files, what deliveries are expected, and what happened to the latest file. Use the integration selector and status filter to narrow the delivery queue. Open a delivery to see its expected filename, deadline, current file name, byte count, receipt time, SHA-256 and any recorded error. The workspace updates automatically as changes are committed. **Refresh** remains available for an immediate update.

## Run a synthetic demo

From the repository root in PowerShell with Docker Desktop running Linux containers:

```powershell
docker pull postgres:17
docker pull rabbitmq:4.2-management
docker pull axllent/mailpit:v1.27
docker build -t opsbridge-sftp:intake-check infra/sftp
docker build -t opsbridge-backend:intake-check backend
docker build -t opsbridge-dashboard:demo frontend
.\.venv\Scripts\python.exe scripts/verify_intake_demo.py --show-dashboard --operations --events --notifications
```

The driver starts an isolated local PostgreSQL instance, checks it is `opsbridge_test`, and applies the existing migrations. It creates 37 delivery expectations across five fictional integrations through the API. The OpenSSH SFTP subsystem and real intake worker ingest synthetic financial CSVs with reproducible contents and varying file sizes. They exercise valid files, failed validation, corrected replacements, duplicates and source delivery ID conflicts. The initial duplicate check confirms two accepted packages and a single file and receipt event. Pending and overdue expectations are created through the API without uploads. Computed deadlines use UTC offsets relative to the run so both states remain visible at startup. No dashboard business records are inserted with SQL fixtures.

The dashboard opens on loopback port 8080. Pass `--port 18081` if port 8080 is in use. Keep the PowerShell process open while presenting and press Enter to stop its containers. The demo uses the direct SFTP subsystem and needs no SSH credentials.

Use `demo-admin` and the temporary password you choose at the prompt. Disposable automated runs generate passwords for their synthetic accounts. The script supplies them only to the isolated automation and removes its containers at exit.

1. Start with the KPIs and **Requires attention**. Open a source ID conflict to see what intake did and which file it kept.
2. Select **Northstar Treasury** and filter to **Validation failed**. Open **FX confirmations** to see the recorded error and suggested next action.
3. Switch to **Completed** and open **Custody positions**. Its timeline shows the failed upload, corrected replacement, and successful processing result.
4. Open an overdue **Settlement report** expectation. It retains **Expected** as its delivery status. Its details show the persisted breach, open missing-file incident and recorded SLA event.
5. Select **Demo** and open **Daily**. The duplicate upload left one file and one receipt event.
6. Return to **All integrations** and filter **Activity feed** by event type. Open a delivery from the feed to see its authoritative timeline.

## How to read the dashboard

The KPI cards cover all integrations. **Delivery expectations** counts expectation records. **Received** counts expectations with at least one recorded arrival from a file or a committed or finalized claim linked to the expectation. It includes failed validation and identifiable quarantined arrivals. **Pending** and **Overdue** split expectations with no recorded arrival by whether the UTC deadline has passed. Equality is still pending. **Validation failed** counts current delivery status. **On-time receipt** divides expectations whose earliest recorded arrival was at or before their deadline by expectations with a recorded arrival. It shows unavailable when that denominator is zero.

**Active incidents** counts persisted open and acknowledged incidents by type. The attention list includes those incidents plus current failures or overdue expectations with no corresponding active incident. It orders source ID conflicts, processing failures, validation failures and missing arrivals by priority, then by deadline and stable ID. It shows up to 20 items for the selected integration scope and gives investigation guidance. Calculated overdue items do not create incidents or write `overdue_at`. The configuration flag and the latest recorded arrival are separate signals. Neither measures connectivity or uptime.

The delivery timeline reads the authoritative `DeliveryEvent` rows in ascending timestamp and ID order, in pages. It includes file references, validation codes, replacement links, retry history, reconciliation counts and the recorded operator ID. Duplicate uploads have no new receipt event. Quarantine outcomes without a persisted event are absent from the timeline. Receipt metrics use recorded intake timestamps, which can lag the sender's upload.

**Currently overdue** counts missing arrivals past their deadline at read time. **Recorded SLA breaches** counts expectations with a persisted first-detection timestamp. The latter stays visible when intake resolves the missing-file incident. Details list both open and resolved incidents.

## Run with the Compose intake stack

Prepare the isolated test stack and its process environment using the [intake guide](INTAKE_DEMO.md). In the same Compose project and using the same container database URL, start the dashboard and its API.

```powershell
docker compose --profile dashboard up -d --build dashboard
docker compose --profile operations up -d --build sla-worker processing-worker
```

Open `http://127.0.0.1:8080`. The dashboard proxies its read endpoints to the internal FastAPI service. The API reads directly from PostgreSQL. Sign in with an individually provisioned operator account. The Compose API stays on the container network. Serve the dashboard over HTTPS outside loopback.

Operators and Admins can reprocess eligible files after the automatic retry budget is exhausted. Confirm a new series to queue the action. OpsBridge validates the current file and series and records the authenticated account UUID.

## Event transport and recovery

For Compose provide a dedicated RabbitMQ account via private process variables `RABBITMQ_DEFAULT_USER`, `RABBITMQ_DEFAULT_PASS` and a matching `RABBITMQ_URL` using host `rabbitmq`. Start the events profile within the isolated demo project.

```powershell
docker compose --profile events up -d --build rabbitmq outbox-publisher activity-consumer
```

The AMQP listener stays on the Compose network. The management interface binds to local loopback and the named RabbitMQ volume retains durable queues and messages. The one-node local broker exercises persistence without providing node-level high availability.

**Wire schema v1** is UTF-8 JSON with `schema_version: 1`, canonical UUID `event_id` and `event_type` (the persisted outbox routing classification). AMQP `message_id` and `type` repeat those values. The persistent message carries a reference. The consumer verifies it against PostgreSQL and derives the display type, timestamp, delivery and safe detail fields from the authoritative `DeliveryEvent`.

| Boundary | Recovery behavior |
| --- | --- |
| Business transaction | Event and outbox row commit together. Broker outages leave committed work in PostgreSQL. |
| Outbox publisher | Claims one due row with `FOR UPDATE SKIP LOCKED` and requires a routed publisher confirm. Uncertain or rejected publishes remain retryable with exponential delay capped at 60 seconds. Transient transport retries continue until recovery. An interrupted transaction leaves the row eligible again. A crash after confirmation may publish the same ID again. |
| Activity consumer | Inserts the inbox key and projects in one transaction, then acknowledges. A crash after commit can redeliver the same message. The unique inbox and projection keys preserve idempotent effects. |
| Malformed or failing delivery | Malformed and unknown references go to the DLQ immediately. Projection errors receive at most three handled attempts with a two-second delay before requeue. A quorum delivery limit also caps repeated unacknowledged crashes. DLX transfer uses quorum at-least-once dead lettering. Inspect failure codes and investigate before replaying. |
| Rebuild | Refreshes projection rows from authoritative events in one transaction, serialized against live projection writes. It leaves the inbox, outbox and broker queues intact. Retrying rebuild does not multiply activity rows. |

A rebuild can fill a missing feed entry even when its message is in the DLQ. It does not replay business operations or acknowledge that broker message.

```powershell
docker compose --profile events run --rm --no-deps --entrypoint python outbox-publisher -m backend.app.event_worker rebuild
```

The activity API accepts `integration_id`, `delivery_id` and `event_type` filters. For the next page, send the returned `next_before_at` and `next_before_id` values as `before_at` and `before_id`. Ordering is newest event timestamp first, with the source UUID as the tie-breaker. In the workspace, select **Refresh** to fetch newly projected events.

The disposable end-to-end driver attempts publication with the broker initially unavailable, starts it, terminates workers after confirm and after database commit, and verifies the restart boundaries. It also exercises concurrent claims and consumers, malformed messages, rollback after an injected projection error, retry exhaustion and two rebuilds. The projection-error check adds one separately named `EVENT_RECOVERY` expectation to the 37 workload expectations. Use `--tests --dashboard-test --operations --events` for the complete check.

For development, run the host FastAPI service on port 8000, then run `npm ci` and `npm run dev` from `frontend`. Vite proxies dashboard requests to that API. To run the browser tests in Docker, build `frontend` with `--target browser-tests -t opsbridge-dashboard:browser`, then run that image. Add `--dashboard-test` to the smoke driver to exercise the live dashboard through nginx in Chromium.

The [performance report](PERFORMANCE_REPORT.md) contains the isolated load and fault-regression commands, observed recovery times, and measurement limits.

## Incident notifications

With `--notifications`, the demo opens the Mailpit inbox on loopback port 8025 in addition to the dashboard. Use `--mailpit-port 18083` if that port is in use. In the inbox, inspect **OPENED**, **ESCALATED L1** and **RESOLVED** messages. The body contains the synthetic incident reference. In the dashboard, select **Demo**, filter to **Expected**, and open **Notify browser**. Expand the notification history to see the owners, scheduled deadlines, delivery state and attempts. Enter an optional comment and **Acknowledge incident**. Refresh the incident to inspect the cancellation and operator audit.

The driver creates incidents through SLA detection and uses a controlled clock to verify escalation. It exercises the resolution service with a synthetic resolution reason. Normal intake and processing call the same service. Concurrent dispatchers send real SMTP to Mailpit and the driver checks captured Message-IDs against the database. The browser test uses the real acknowledgement route. The SMTP listener is confined to the Docker network. Mailpit has no forwarding or external relay configured, and the worker accepts only the Mailpit host and synthetic `.test` addresses. [Mailpit Docker configuration](https://mailpit.axllent.org/docs/install/docker/)

For the isolated Compose stack, apply the notification migration with the existing test-database guard, then run `docker compose --profile notifications up -d --build mailpit notification-worker`. Open the authenticated dashboard as an Operator or Admin to acknowledge an incident. The server records the account UUID.

The shipped `backend/app/notification_policies.json` covers synthetic owners. Set `OPSBRIDGE_NOTIFICATION_POLICIES` to a JSON rule array before starting the producers and dashboard API to override it. A missing selector is a wildcard. An omitted event field inherits the best matching broader rule. An empty array disables that event for the rule. Each recipient contains `owner` and `email`. Escalation levels are the ordered entries in `escalations`, each with increasing `after_seconds` and a `recipients` list. Opening snapshots scheduled jobs. Resolution uses the policy at resolution time. Policy changes do not retroactively schedule old incidents or change their durable deadlines.

**Delivery state:** `SENT` means local SMTP acceptance. `FAILED` retains rejection or exhaustion details. A crash with an unknown SMTP outcome consumes one attempt and is recorded in the history. Mailpit can capture a duplicate if SMTP accepted a message immediately before a worker interruption. Acknowledgement and resolution stop future escalation claims. An in-flight send may finish after either action.

## Live operations and monitoring

The **Live** badge indicates that the browser is receiving server-sent invalidation signals. The browser bundles updates into at most one automatic refresh per two seconds. The API sends a heartbeat every ten idle seconds. If the stream closes, never becomes ready or is silent for 25 seconds, **Polling fallback** refreshes the existing API data every 15 seconds. SSE keeps reconnecting and a successful subscription prompts a fresh read. Expand a delivery and leave it open while a second client acknowledges its incident to see the state change without pressing **Refresh**.

In a separately configured and verified isolated Compose test project, add `--profile monitoring` to the usual dashboard, intake, operations, events and notifications profiles:

```powershell
docker compose -p opsbridge-observability-demo --profile dashboard --profile intake --profile operations --profile events --profile notifications --profile monitoring up -d --build
```

Use an isolated project and volumes and a PostgreSQL instance already migrated through `f43c720a19be`. The existing Compose API and workers must point to that instance, with the usual SFTP demo account and broker configuration supplied privately. The monitoring services can also be started by targeting only `prometheus grafana`. Targets for profiles that are off will appear down. The optional host ports are configurable with `PROMETHEUS_PORT` and `GRAFANA_PORT`.

- [Grafana operations dashboard](http://127.0.0.1:3000/d/opsbridge-operations) opens as a local anonymous Viewer. It is preconfigured with the local Prometheus data source.
- [Prometheus targets](http://127.0.0.1:9090/targets) show scrape status. The default scrape interval is 15 seconds. Allow at least two scrapes before interpreting rates.
- The API exposes `/health`, `/ready` and `/metrics` on its internal port 8000. An optional RabbitMQ URL enables an authenticated readiness probe. Worker metrics ports and RabbitMQ's metrics port are internal.

| Metric | Interpretation |
| --- | --- |
| `opsbridge_intake_finalized_total` | Persisted intake claims by final storage location. Accepted includes CSV validation failures and exact duplicate packages. Unknown integrations have no database claim and are counted by the intake worker. |
| `opsbridge_delivery_events_total` | Persisted receipt, CSV failure, source-ID conflict, processing attempt/result and SLA breach counts by event type. |
| `opsbridge_processing_retries_total` | Persisted second and third processing attempts. |
| `opsbridge_incidents_opened_total`, `opsbridge_incidents_resolved_total` | Incident counts by type. |
| `opsbridge_notification_attempts_started_total`, `opsbridge_notification_attempts_total`, `opsbridge_notification_jobs` | Durable attempt starts, terminal attempt outcomes and current job counts by state. |
| `opsbridge_outbox_backlog` | Unpublished rows that are due, scheduled or terminally failed. |
| `rabbitmq_queue_messages_ready`, `rabbitmq_queue_messages_unacked` | Broker backlog for the activity queue and DLQ. `opsbridge_worker_outcomes_total` counts observed projection, duplicate, retry and dead-letter outcomes. |
| `opsbridge_worker_duration_seconds`, `opsbridge_worker_ready` | Operation or scan duration and last observed worker readiness. The Prometheus `up` metric detects a stopped or unreachable worker separately. |
| `opsbridge_api_requests_total`, `opsbridge_api_duration_seconds` | HTTP response counts by route template, method and status class, plus time to response headers. For SSE this measures stream establishment. |
| `opsbridge_database_up`, `opsbridge_broker_up` | Last successful database metrics scrape and authenticated broker readiness result. On a failed database scrape the database-backed series are absent. |

The local profile keeps only seven days of Prometheus history. Durable database aggregates are optimized for the local dataset and should be load-tested before large-volume deployment. A fresh Prometheus instance sees current counts, without per-second history from before it started. Process-local counters and histograms restart with their worker. PostgreSQL notifications are transient and contain no business data. The reconnect read recovers current state rather than replaying missed signals.

## Operations Copilot

The standard synthetic demo runs with the deterministic offline provider. Select **Northstar Treasury**, filter for **Validation failed**, and open **FX confirmations**. Expand **Investigate with Copilot** and choose **Analyze incident**. Read the summary and cited validation records, then compare the separate hypothesis with the proposed local investigation. The **Simulated analysis** badge identifies the offline provider. The existing demo driver sets this mode explicitly regardless of host settings.

Open **Operations Copilot** on the main dashboard and try:

- “Which integrations currently have unresolved incidents?” includes open and acknowledged incidents.
- “Which deliveries breached their SLA?” uses persisted breach timestamps.
- “Summarize today's operational problems.” uses the current UTC day and includes incident openings and recorded failure events.
- “Why did the cash-position delivery fail?” matches the exact delivery type after normalization. If more than one failed delivery matches, use `Why did delivery <UUID> fail?`.
- For an acknowledged incident, **Review before acknowledgement** uses the recorded timestamp as the cutoff. The cutoff is shown separately from the earlier evidence.

The Copilot accepts a narrow English question grammar. It caps overview results at 12 per source and delivery history at 12 events, four files, four activity entries, and six notification jobs with their bounded attempt counts. The full evidence drawer shows the retained records and stable IDs. If a source exceeds its limit or the data cannot establish a cause, the result identifies the gap. The application does not send raw files, read arbitrary paths, run model-generated SQL, reprocess files, acknowledge incidents or send notifications on your behalf.

### Optional real provider

Set `OPSBRIDGE_COPILOT_PROVIDER=openai` and an explicit `OPSBRIDGE_COPILOT_MODEL` supported by the OpenAI Responses API and Structured Outputs. Supply `OPENAI_API_KEY` privately to the API process or API container. Recreate that service after changing its environment. Keep the key out of frontend settings and resolved Compose output. Use `OPSBRIDGE_COPILOT_PROVIDER=disabled` to turn the provider off. The core workflow and disposable demo require no account. [OpenAI Responses API reference](https://developers.openai.com/api/reference/resources/responses/methods/create)

Real-mode requests go to OpenAI with `store: false`. The request includes an operation code, selected operational facts and timestamps, temporary evidence labels, and the eligible investigation paths. It excludes raw questions, business record IDs, filenames, CSV content, arbitrary payload fields, names, descriptions, comments, recipient addresses and secrets. The provider still receives operational metadata. Review applicable provider terms and data policies before enabling it for non-synthetic data.

Requests allow up to 320 question characters and a 2 KiB HTTP body. The API permits four concurrent analyses and 12 calls per minute per process, with at most two provider attempts and an 11-second provider deadline. Provider errors stay visible in real mode. Usage and latency are recorded as aggregate metrics where available. Hypotheses are limited to supported paths and can miss causes outside the evidence. Recommendations require operator review.

## Reconciliation workbench

Build the images listed in [Run a synthetic demo](#run-a-synthetic-demo). Run the disposable demo with independently submitted Fund Accounting and Custodian CSVs:

```powershell
.\.venv\Scripts\python.exe scripts/verify_intake_demo.py --show-dashboard --operations --events --notifications --reconciliation
```

1. Open **Reconciliation workbench** and select **Fund vs Custodian · fully matched** to see a clean run.
2. Open **Fund vs Custodian · exception review**. Review exact and within-tolerance pairs, missing rows on either side, an amount mismatch, duplicates and ambiguous candidates. Filter to **Amount mismatch** and inspect the group for a Copilot investigation with a persisted citation.
3. Open the linked incident and return to the run. The operational incident covers the whole run. Each financial exception stays visible in the workbench.
4. Select **Confirm a new reconciliation run** and queue a rerun. The new run has its own identifier and links to the original. The worker completes queued runs during the interactive demo and in the Compose operations profile.
5. Open **Fund vs Custodian · corrected exports** and follow **View preceding run** to see the original result. The demo submits corrections as independent deliveries with explicitly configured correction input types. This preserves the intake rule that a completed file cannot be replaced in place.

The **operations** profile runs `reconciliation-worker` with read-only access to accepted files. This uses the isolated PostgreSQL target and the existing migration guard. Reconciliation writes require a session and CSRF token. Operators and Admins can queue reruns. Only Admins can create definitions and policy versions. To configure a definition, POST to `/dashboard/reconciliation/definitions` with `name`, `business_date`, `source_a_delivery_id`, and `source_b_delivery_id`. Optional fields are `match_on` (`reference` or `record_id`), decimal strings for `tolerance` and `materiality`, `exception_limit`, `incident_on_missing`, and `incident_on_failure`. An approved corrected definition can also specify `supersedes_run_id` and `confirmed: true`. Each definition automatically queues its first run. The dashboard rerun uses the existing definition and a fresh idempotency key.

The comparison supports up to 20,000 records per file and the normal 10 MiB intake limit. Currency comparison checks the uppercase three-letter format. It performs no conversion or currency registry lookup. Tolerance and materiality are absolute, inclusive thresholds. Positive differences mean source A is larger. The workbench displays counts, classifications, currency and calculated differences. Detailed source identifiers and original amounts stay in the private snapshots. The local JSONB report and offset pagination need volume testing before large-scale back-office use. Bulk resolution and production deployment controls are outside the demo.

Alembic revision `b678d1243fa0` adds the reconciliation schema. Its downgrade preserves the additive incident enum label and refuses to remove tables with recorded definitions and history.

## Operator accounts and roles

For an isolated Compose setup, apply the configured test migrations through `ca78b650af13`. Provision the first Admin from the trusted shell connected to the backend image or the repository virtual environment. Supply the same verified database target and `OPSBRIDGE_EXPECTED_DATABASE=opsbridge_test` to the command. Use the hidden prompt for a password of at least twelve characters. Never put a password on the command line.

```powershell
.\.venv\Scripts\python.exe -m backend.app.provision_operator demo-admin --role ADMIN
```

Sign in at the dashboard. Admins can create and deactivate accounts, change their roles, and edit the notification policy under **Administration**. Password resets use `PATCH /auth/operators/{id}`. Admins can create named reconciliation policy versions through the authenticated definition endpoint. A Viewer can use Copilot and read the dashboard, including the activity stream. An Operator can also acknowledge incidents, reprocess eligible files and queue confirmed reconciliation reruns. The browser and direct API callers use the same role checks.

API callers send the login JSON over HTTPS with `X-OpsBridge-Login: 1` and maintain the returned cookie. Send the `csrf` value from the login or session response in `X-CSRF-Token` on writes. Logout, expired sessions and role changes require signing in again. Server-side audit records identify accounts and targets by UUID. The readiness and metrics paths remain on the internal service port. See [the security architecture](architecture.md#operator-authentication-and-authorization) for the trust boundary and deferred controls.
