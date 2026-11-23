# SFTP intake demonstration

## Repeatable local smoke demo

From the project root in PowerShell, with a running local Docker Desktop Linux engine and the existing Python environment:

```powershell
docker pull postgres:17
docker build -t opsbridge-sftp:intake-check infra/sftp
docker build -t opsbridge-backend:intake-check backend
.\.venv\Scripts\python.exe scripts/verify_intake_demo.py --tests
```

The smoke driver creates a fresh PostgreSQL 17 container with no network interfaces other than loopback. It verifies `current_database()` is `opsbridge_test` before migration. The API and worker share its network namespace. The vendor uses OpenSSH direct subsystem mode on an anonymous data volume, under a different UID from the worker. This exercises the SFTP protocol, staging and rename, Linux group permissions, discovery and the real worker CLI without an SSH identity. The driver creates an integration and expectation over HTTP, publishes the same delivery twice, reads the result over HTTP, checks durable records and final files, and stops its own containers. Success prints `RECEIVED`, one file, one receipt event and two accepted packages.

## Credentialed localhost demonstration

The operator supplies an already provisioned synthetic vendor account, its integration UUID, an SSH agent identity and a trusted host-key entry for the demo host/port. Keep the mapping, client key and host-key volume private. Use a separate Compose project and paired test database/data volume for the demo. Never point a worker using a development ingress volume at a different database.

Use privately supplied **process** variables for Compose's PostgreSQL account, SFTP mapping path, `DATABASE_URL` (host URL on port 55432) and `INTAKE_DATABASE_URL` (container URL on host `postgres`, port 5432). Both URLs must name the same isolated `opsbridge_test` database. Use a dedicated project name and unused ports.

```powershell
$env:COMPOSE_PROJECT_NAME = 'opsbridge-intake-demo'
$env:COMPOSE_DISABLE_ENV_FILE = '1'
$env:PYTHON_DOTENV_DISABLED = '1'
$env:POSTGRES_DB = 'opsbridge_test'
$env:OPSBRIDGE_EXPECTED_DATABASE = 'opsbridge_test'
$env:POSTGRES_PORT = '55432'
$env:SFTP_PORT = '2223'
docker compose up -d --wait postgres sftp
```

When a migration of this isolated target is authorized, the existing Alembic environment compares the actual database name with the expectation before running revision operations. Then start the worker and host API using the prepared environment:

```powershell
.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini upgrade head
docker compose --profile intake up -d --build intake-worker
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Run the simulator in a second process with the same test settings and privately supplied demo integration UUID and username. It uses the system SFTP client with strict host-key checking. It creates the synthetic integration if absent, creates a unique expectation, prints its UUID and uploads a generated CSV and manifest. Verify the matching expectation's status and current file:

```powershell
.\.venv\Scripts\python.exe -m backend.app.intake.vendor_demo $env:DEMO_INTEGRATION_ID $env:DEMO_SFTP_USER --port 2223
Invoke-RestMethod "http://127.0.0.1:8000/delivery-expectations?integration_id=$env:DEMO_INTEGRATION_ID" | ConvertTo-Json
```

Use the API response format reported by the existing list endpoint. A successful receipt has `status=RECEIVED` and a populated `current_file_id`.

## Runtime and recovery

The dedicated process handles one claim at a time. A transaction advisory lock serializes candidate acquisition. A dedicated PostgreSQL connection holds the claim lock across short state transactions and filesystem work. The business transaction locks the expectation, checks source-ID conflicts before content duplicates, and commits the applicable file, expectation, incident, event, outbox and claim together. CSV parsing occurs before that transaction. For integrity failures an identifiable arrival still resolves the missing-file incident.

The worker scans the incoming directories, private work directories, and unfinished database claims. A `COMMITTED` claim only completes final movement and records `FINALIZED`. Final directories have the layout `_opsbridge/{accepted,quarantine}/<integration>/<claim>/package`. A quarantined claim also has a reason file. For snapshotted deliveries the private snapshot is the authoritative stored package. The original source is retained separately as untrusted evidence. A structurally unsafe package is retained by renaming the original entry inside the private quarantine without traversing it. Restrict access to that raw evidence. Unknown integrations use filesystem quarantine and a structured log. V1 retains final directories indefinitely.

The database outcome and filesystem rename are separate operations. Operational failures leave work recoverable; investigate `CLAIM_RETRY` or `WORKER_STOPPED` by claim/integration ID. A committed claim whose final bytes are missing requires investigation. Do not manufacture a replacement package or repeat its business transaction.

## Installation verification boundary

The isolated automated demo exercises real OpenSSH SFTP subsystem requests, staging, atomic publication and worker access to the resulting package. Credentialed SSH verification is blocked in sessions where private keys and account mappings are protected from access. A credentialed acceptance run needs an isolated, pre-provisioned vendor account, a private SSH agent identity already loaded by its owner, and a trusted host-key entry for the local test endpoint. Use the credentialed demonstration above after those inputs are authorized. Confirm strict host-key checking, successful SFTP login, rejected shell and PTY, and that the vendor cannot enter another integration directory or the worker's private storage. Verify package visibility only after the staging-to-incoming rename and verify the worker can inspect the published package. Retain command outcomes without recording credential material or mapping contents.
