# OpsBridge MVP development plan

The first demo follows one synthetic delivery from expectation creation through SFTP upload to an observable outcome. A repeat upload demonstrates deduplication. An invalid CSV followed by a corrected upload demonstrates incident resolution and retained history. Deliver and test the backend path before adding asynchronous projection and the dashboard.

The recruiter demo includes intake, persistent SLA monitoring, deterministic file reconciliation, confirmed RabbitMQ publication and the operations dashboard. The dashboard reads attempt history and authoritative delivery events from PostgreSQL alongside a rebuildable activity feed.

## Milestones in dependency order

| Milestone | Deliverable | Acceptance evidence |
| --- | --- | --- |
| 1. Private snapshot and integrity verification | Extend the existing intake package with a bounded copy of a claimed source into a private sibling snapshot under `_opsbridge/work/<integration-id>/<claim-id>/`. Verify the copied manifest against the actual payload byte count and SHA-256. | Temporary-filesystem tests cover valid and zero-byte payloads, mismatch, growth or substitution during copying, symlinks, unexpected entries, short reads, interrupted copies and retry. Enforce 64 KiB manifest, 10 MiB payload and combined cap while reading. A partial copy is never consumed. The source survives failures. Include real filesystem checks on Linux for Linux-specific behavior. |
| 2. Durable acquisition | Add discovery, atomic incoming-to-work rename and recovery from the deterministic work path. Hold a short candidate lock, then acquire the claim session lock on a dedicated connection before creating or resuming the claim. Bound concurrency and release locks on shutdown. | Two workers racing yield one owner. Recovery covers rename before the claim row exists and interruption during snapshotting. Exercise actual lock behavior on the authorized isolated PostgreSQL target. |
| 3. Identity, CSV and business persistence | Resolve an expectation by integration, business date and delivery type. Apply the approved technical CSV contract and outcomes. Serialize competing writes with a short transaction-scoped identity lock after parsing. Commit applicable file, expectation, incident, event, outbox and claim changes together. | Test header-only, zero-byte, malformed CSV, absent payload, mismatch, inactive integrations, exact duplicate, source-ID conflict, valid replacement and unexpected distinct payload. Force rollback and replay on the isolated database. |
| 4. Finalization and first runnable demo | Run the worker as a dedicated process from the backend image. Add the synthetic vendor client, restricted OpenSSH handoff and final storage. Mount `sftp_data` at `/srv/opsbridge-sftp` in both containers. Use staging-to-incoming rename on the same filesystem. | Demonstrate upload, duplicate, CSV failure and corrected delivery through the real transport. Restart between PostgreSQL commit and filesystem movement. Verify one business outcome and complete retained packages. Verify the worker's non-root access on Linux. |
| 5. Processing and SLA | Implement the approved bounded processing series, audited manual reprocessing, overdue detection and missing-file incident lifecycle. | A synthetic late arrival resolves the missing incident while preserving the original overdue timestamp. Retry and reprocessing tests preserve attempt history. |
| 6. RabbitMQ and activity projection | Publish from the transactional outbox and project relevant operational events into the feed. Commit inbox deduplication with consumer effects. | Repeated broker delivery yields one feed entry. Demonstrate bounded retry, DLQ handling and rebuilding the feed from authoritative events. |
| 7. Operator dashboard and repeatable demo | Add React/TypeScript views and the API reads needed to show deliveries, SLA conditions, incidents and activity. | A Playwright scenario follows the synthetic delivery and replacement through the dashboard. Repeat it against isolated demo data and capture the actual results in the handoff. |
| 8. Observability and real-time operations | Add correlated JSON logs, dependency readiness, Prometheus/Grafana and transaction-driven dashboard refresh. | Verify committed versus rolled-back invalidations, automatic browser recovery, isolated live delivery and incident changes, broker readiness recovery, monitoring provisioning, and dashboard queries. |
| 9. Operations Copilot | Investigate incidents and answer supported operations questions using bounded PostgreSQL evidence. Add an offline provider and an opt-in model adapter with validated references. | Verify read-only PostgreSQL enforcement, evidence ordering and limits, malicious persisted content and fabricated citations, provider timeouts and retries, and a live incident investigation in Chromium. |
| 10. Financial reconciliation | Compare two independently ingested sources, retain immutable results, surface run-level incidents, and support audited reruns and Copilot evidence. | Verify exact decimal boundaries and ambiguous groups, concurrent workers and interruption recovery, corrected-source lineage, and live dashboard navigation. |
| 11. Security and RBAC | Add individual operator accounts, revocable browser sessions, backend authorization, and append-only security audit. | Exercise failed and successful login, role denial on direct API calls, CSRF, operator attribution, revocation, authenticated SSE and worker compatibility on isolated services. |
| 12. Reliability and performance engineering | Run repeatable isolated delivery and reconciliation workloads, verify recovery at durable boundaries, and tune measured bottlenecks. | Exercise transport outages and process deaths with synthetic data, record latency and resource samples, and compare bounded reconciliation pagination against the previous implementation. See the [performance report](PERFORMANCE_REPORT.md). |
| 13. Copilot evaluation | Evaluate persisted synthetic scenarios, evidence coverage, provider boundaries and optional authorized live usage. | Repeat 15 offline cases on disposable PostgreSQL, test cost and privacy controls without egress, and document retrieval and ranking gaps separately. See the [AI evaluation report](AI_EVALUATION_REPORT.md). |
| 14. Portfolio release preparation | Make local verification and the synthetic demonstration reproducible, and prepare the GitHub publication review. | Validate workflow syntax, run local regression and audits, demonstrate all three portfolio views and document the remaining gates in the [release readiness review](RELEASE_READINESS.md). |

## Intake decisions used for acceptance

- A rename acquires ownership. Process only the private copy. The vendor chroot excludes `_opsbridge`. Keep the host-key volume private to SFTP.
- `SNAPSHOTTED` means a completed filesystem copy. `VALIDATED` additionally requires a valid manifest, matching expectation and verified payload size/hash. CSV validity is evaluated separately.
- A valid manifest identifying an expectation plus a physically present payload resolves active `MISSING_FILE` idempotently, including for inactive integrations and quarantined outcomes. Keep it active for missing payloads or unidentified expectations.
- Valid receipt, CSV failure and exact duplicates go to accepted storage. A CSV failure creates a permanently failed file and validation incident. An eligible replacement is a new file linked to its failed predecessor. Resolve predecessor validation incidents after successful replacement validation.
- Check source ID conflicts before hash deduplication. A conflict keeps the current file and uses the stable conflict key for the incident, event and outbox decision. An exact duplicate creates no new file, receipt event or business outbox entry. Unexpected distinct contents can replace only the current validation-failed file, with a fresh source ID when supplied.
- A size/hash mismatch goes directly from `SNAPSHOTTED` to `COMMITTED` with a stable error and quarantine reason. Commit any missing-incident resolution with that decision. The existing file-level validation incident requires a file, and this outcome creates none. Quarantine inactive integrations without changing historical delivery outcomes. Unknown integrations use filesystem-only quarantine, a reason record and an operational log.
- `COMMITTED` is the boundary after which recovery only completes final movement and finalization. Keep accepted and quarantined packages indefinitely. Clean temporary work only after confirmed `FINALIZED` and verified final storage.

## Operational workers

- The SLA worker uses UTC, locks candidate expectations and rechecks recorded physical arrival after taking the same row lock as intake. It records the first detected breach, one active missing-file incident and one authoritative event with its outbox record in one transaction. A later identifiable arrival resolves the incident and preserves the breach timestamp.
- The processing worker uses only finalized accepted snapshots. It verifies the saved filename, byte count and SHA-256, then reconciles the CSV by counting negative, positive and zero amounts. An advisory lock spans the durable attempt start, read-only reconciliation and outcome transaction. Each transition writes an authoritative event with an outbox record.
- An interrupted attempt counts against the current series. The worker records it as interrupted on recovery. Interrupted work and unavailable storage can retry after five seconds, up to three attempts in total. Invalid snapshot bytes and CSV validation failures do not retry automatically. A terminal processing failure opens an incident. A successful later attempt resolves it.
- The authorized reprocessing action queues a new series only for the current finalized file after three retryable attempts. It validates the file ID, series and confirmation, then records the operator account UUID and time. The existing file and previous events remain available. The authorization boundary is documented in the dashboard guide.

## Local command reference for the implementing agent

The `notifications` profile starts the PostgreSQL-backed notification dispatcher and the local Mailpit sink. Incident creation and resolution enqueue notification work in their own transaction. The dashboard provides acknowledgement and notification history. See the dashboard demo for the synthetic policy, escalation and retry verification.

The `events` Compose profile runs RabbitMQ, an outbox publisher and an activity consumer. The database remains authoritative. The dashboard guide specifies the versioned envelope, at-least-once delivery, retries, dead-letter handling and rebuild procedure. The verification driver exercises failures against disposable containers.

Use PowerShell from the repository root and run each group in its own process. Check the exit code after each command. The status document records which commands have actually been exercised.

**Database-free regression** uses the local virtual environment and prevents dotenv loading. Clear an inherited connection URL in this child shell.

```powershell
$env:PYTHON_DOTENV_DISABLED = '1'
$env:OPSBRIDGE_RUN_INTEGRATION = '0'
$env:DATABASE_URL = ''
.\.venv\Scripts\python.exe -m pytest backend/tests -m 'not integration' -q
```

For a focused intake run use the same environment and select `backend/tests/unit/test_intake_paths.py`, `backend/tests/unit/test_intake_package.py` and `backend/tests/unit/test_intake_manifest.py`. Integration discovery is available offline with `.\.venv\Scripts\python.exe -m pytest --collect-only -q backend/tests/integration`. Inspect the revision graph with `.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini heads`.

**PostgreSQL integration tests** require an authorized local isolated instance already provisioned at the required revision. Supply its verified connection via private process environment before Python starts. Test guards validate the explicit URL database name; the operator/agent must also establish that the endpoint is the intended local instance. Keep credentials out of arguments and logs.

```powershell
$env:PYTHON_DOTENV_DISABLED = '1'
$env:OPSBRIDGE_RUN_INTEGRATION = '1'
.\.venv\Scripts\python.exe -m pytest backend/tests/integration -m integration -q
```

**Local runtime** requires privately provisioned local service configuration and an existing authorized SFTP account map. Use the following entry points for a runtime milestone. Starting PostgreSQL on a new volume can initialize a database.

```powershell
docker compose up -d postgres
docker compose up -d --build sftp
docker compose ps postgres sftp
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

For a host-run API, use `GET /health` for liveness and `GET /ready` for dependency readiness on port 8000. PostgreSQL binds to loopback port 5432. SFTP binds to loopback port 2222 by default and has its own Compose network. See [the monitoring profile and synthetic scenario](DASHBOARD_DEMO.md#live-operations-and-monitoring).
