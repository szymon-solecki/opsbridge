# OpsBridge development status

## Current handoff — Portfolio README update

The README leads with Overview and a compact walkthrough of delivery investigation, reconciliation exceptions, the corrected-run comparison and simulated Copilot citations. The manifest and publication checks allowlist the five reviewed images. The visual update is prepared for review before publication to GitHub.

## Previous handoff — Portfolio publication candidate

The candidate includes a recruiter-facing README, three reviewed synthetic screenshots, a manifest-enforced CI workflow, and an exact source-only file inventory. Use a fresh snapshot to keep existing Git metadata and internal history local. The license and publication authorization remain owner decisions. Run the workflow and demo against the approved private snapshot before changing its visibility. [Publication checklist](PUBLICATION.md) · [File inventory](PUBLICATION_MANIFEST.txt)

## Previous handoff — Command Center Stage 6

The integrated Command Center was checked across the synthetic delivery, SLA, incident, reconciliation and Copilot journeys. Live browser coverage now includes navigating from reconciliation to the source delivery and replaying an already confirmed manual reprocessing request. The authentication test reproduces the server's intentional four-sign-in concurrency limit. Three browser workers leave room under that limit.

The final isolated run passed 227 backend tests and 11 live Chromium scenarios. The additional verification confirmed that the worker completed the second series with one audited request and all three prior failures retained. The separate Chromium run passed 22 controlled tests. The offline Copilot catalog passed all 15 cases with zero external requests.

The [release report](RELEASE_READINESS.md#command-center-stage-6) records test coverage, audit and financial boundaries, the publication gates and the optional provider review. The [13-minute walkthrough](PORTFOLIO_DEMO.md) gives startup commands and loopback URLs. The portfolio startup was smoke-tested with cached images, a generated synthetic password, and separate loopback ports. A fresh Windows virtual environment needs the pinned dependencies. The existing Windows environment lacks `argon2`, so the database-free backend suite was verified in the pinned Linux image instead.

**Next action** Review and freeze the portfolio candidate, confirm the license and publication scope, then run hosted CI on that exact snapshot. Keep the simulated provider for the demonstration.

## Previous handoff — Command Center Stage 5

The operational experience now includes navigable Copilot citations with technical disclosure and simulated investigations, a Monitoring landing page with observed workspace signals and configured external links, and Admin account and policy views with explicit write review. The policy editor preserves null inheritance and empty-array suppression and retains advanced editing for other document shapes.

Verification recorded 226 passing backend tests on disposable `opsbridge_test`, 22 passing Chromium tests with controlled responses, and 10 passing Chromium scenarios against the isolated stack. The initial five-worker browser run encountered a sign-in failure and passed after capping the isolated runner at three workers, below the API's four-sign-in concurrency limit. The application limit remains in force. TypeScript, Vite and the dashboard image built successfully. Offline Compose validation and the public monitoring configuration smoke test passed. Twelve captures in `data/frontend-stage5/` cover Copilot, Monitoring, operator accounts and notification policies at 1440, 768 and 390 pixels. Visual review led to collapsing suggested questions after analysis so the conclusion remains visible on mobile.

```powershell
$env:PYTHON_DOTENV_DISABLED = '1'
.\.venv\Scripts\python.exe scripts/verify_intake_demo.py --tests --dashboard-test --experience-screenshots --operations --events --notifications --reconciliation --faults
```

**Next action** Complete Stage 6 release verification and portfolio walkthrough updates. Treat real provider activation as a separate privacy, configuration and evaluation decision. See [the redesign plan](FRONTEND_REDESIGN_PLAN.md#stage-5-delivered).

## Previous handoff — Command Center Stage 4

Reconciliation now separates run history from a dedicated run workspace. Execution status and recorded matching outcomes are shown independently. Operators can filter category pages, open evidence by stable report ordinal, compare the immediate predecessor, and follow source or incident links to Delivery Workspace. Source pins identify the versions used in the run while the linked deliveries show their current state. Reruns retain the existing confirmation and permissions. Reconciliation Copilot submissions are available in simulated mode.

Verification recorded 226 backend tests passing on disposable `opsbridge_test`, 19 Chromium tests passing with controlled responses, and nine Chromium scenarios passing against the isolated stack. TypeScript, Vite and Docker builds, offline Compose validation, and whitespace checks passed. Visual review of `data/frontend-stage4/` led to stacked history rows on mobile and more room for comparison headers.

```powershell
$env:PYTHON_DOTENV_DISABLED = '1'
.\.venv\Scripts\python.exe scripts/verify_intake_demo.py --tests --dashboard-test --reconciliation-screenshots --operations --events --notifications --reconciliation --faults
```

**Next action** Implement Stage 5. Improve contextual Copilot evidence navigation, add optional deployment-controlled telemetry links to Monitoring, and refine the existing account and notification policy views without changing RBAC. Exact source rows and record-level alignment between runs require additional backend evidence and are outside the current comparison.

## Previous handoff — Command Center Stage 3

Deliveries now has a queue and a dedicated evidence workspace. The queue preserves server filters, sorting and pagination and adds a page-local search and exact delivery ID lookup. The evidence page separates arrival and SLA history, current file facts, the chronological timeline, incident severity and lifecycle, and eligible operator actions. Notification and escalation evidence and the contextual Copilot remain available within each recorded incident. Direct links restore the incident and loaded history page. Demo renewal uses relative deadlines for reconciliation and event recovery fixtures while retaining their business dates.

Verification recorded 226 passing backend tests on disposable `opsbridge_test`, 17 Chromium tests with controlled API responses, and eight Chromium scenarios against the isolated stack. TypeScript and Vite builds, dashboard and browser image builds, all-profile offline Compose validation, and whitespace checks passed. The synthetic screenshots in `data/frontend-stage3/` cover the queue and detail page at 1440, 768 and 390 pixels, plus the focused incident at 390 pixels. Visual review led to a compact integration picker on mobile and a wait for timeline evidence before capture.

```powershell
$env:PYTHON_DOTENV_DISABLED = '1'
.\.venv\Scripts\python.exe scripts/verify_intake_demo.py --tests --dashboard-test --delivery-screenshots --operations --events --notifications --reconciliation --faults
```

**Next action** Start Stage 4 Reconciliation. Reuse the new delivery and incident evidence links for source investigation. Land the run comparison and exception workflow without reimplementing authoritative delivery history. The [redesign plan](FRONTEND_REDESIGN_PLAN.md#stage-3-delivered) records the API limits.

## Previous handoff — Command Center Stage 2

Overview now presents a shift briefing with current incidents, overdue deliveries, processing status, a denominator-backed on-time receipt rate and a separate historical breach count. It links to five priority items and five projected changes, and compares up to six integrations by active incidents, overdue expectations, validation failures and last recorded arrival.

Action Center groups a bounded server slice by critical, high, detected overdue or missing, then other. The integration filter scopes the API query. The issue-scope filter works within the first 40 returned rows. Evidence links preserve the selected incident and queue URL, and the detail dialog confirms lifecycle, severity and acknowledgement eligibility. Reconciliation runs link from their recorded evidence. No API contract changes were required.

Stage 2 verification recorded 226 passing backend tests on disposable `opsbridge_test`, 15 passing local Chromium tests with controlled responses, and seven passing Chromium scenarios against the real isolated stack. TypeScript and Vite production build, dashboard and browser image builds, all-profile offline Compose validation, and whitespace checks passed. The screenshot run covers 1440, 1920, 2560, 768 and 390 pixels. The visual review moved historical SLA context higher on desktop and tightened the filters and header on mobile. Screenshots are in the ignored `data/frontend-stage2/` directory.

```powershell
$env:PYTHON_DOTENV_DISABLED = '1'
.\.venv\Scripts\python.exe scripts/verify_intake_demo.py --tests --dashboard-test --dashboard-screenshots --operations --events --notifications --reconciliation --faults
```

**Next action** Implement Stage 3 Delivery Workspace. The current investigation flow uses the existing routed detail dialog. Exhaustive queue search, financial impact, explicit lifecycle on each queue row and historical SLA trends are outside the available API data. See [the redesign plan](FRONTEND_REDESIGN_PLAN.md#stage-2-delivered).

## Previous handoff — Command Center Stage 1

The dashboard has a responsive shell, seven stable workspace routes, a compact tablet rail and a keyboard-operated mobile menu. The header exposes operator identity, role and browser live-update state. Delivery and incident links open the existing detail dialog, and reconciliation run links restore the selected run. Delivery filters and pagination live in the URL. Activity moved to `/overview/activity`, policy editing and user management moved to `/administration`, and the standalone Copilot has its own workspace. Monitoring explains the browser connection and points users to deployment telemetry.

Viewer and Operator cannot mount Administration, including by direct URL. Existing server authorization, capability flags and CSRF checks continue to govern actions. Session expiry or logout removes the workspace and preserves the current location for sign-in. The dashboard still uses one shared SSE connection with polling fallback. Backend contracts, schema and event handling remain as before.

The Stage 1 Chromium suite recorded 11 passing browser tests with simulated HTTP responses. The isolated demo runner recorded 226 passing backend tests and six passing live Chromium scenarios using a fresh `opsbridge_test` database, real SFTP and the simulated Copilot. The Vite production build, backend and dashboard images, all-profile offline Compose validation and Git whitespace check passed. The existing performance browser probe now targets the routed delivery results. Screenshots are under the ignored `data/frontend-stage1/` directory.

Run backend regressions through the isolated demo runner, which disables dotenv loading. The initial host pytest collection invoked the application dotenv loader and then stopped on missing local imports before any tests ran. For a future host-only check, set `PYTHON_DOTENV_DISABLED=1` before starting Python.

**Next action** Implement Stage 2 Overview and Action Center. The current screens use a small overview and the existing bounded operator queue. Detailed priority previews, delivery list search, reconciliation comparison and configurable Monitoring links are tracked in [the frontend redesign plan](FRONTEND_REDESIGN_PLAN.md).

## Previous handoff — Portfolio release preparation

Read-only GitHub Actions workflows cover unit, isolated integration and Chromium tests, builds, Compose, Python and TypeScript checks, and dependency audits. The one-command portfolio runner provisions a disposable synthetic scenario and exposes the Operations Center, Mailpit and Grafana on loopback. The backend image uses the verified Python version constraints, and the Grafana image is now on the supported 12.4.15 line.

Local verification passed 226 backend tests, 11 Chromium cases, nine evaluator tests, the 15-case offline evaluation, image builds, Compose, actionlint, Ruff and the portfolio monitoring smoke. Both package advisory checks reported zero known vulnerabilities in the tested versions. The source and publication-path checks reported zero findings in scope. No hosted CI run, public repository, Git publication or live OpenAI call was made. The next gates are reviewing the candidate snapshot, deciding licensing and running hosted CI on the reviewed snapshot. See [release readiness](RELEASE_READINESS.md) and the [portfolio guide](PORTFOLIO_DEMO.md).

## Previous handoff — Copilot evidence remediation

The unchanged offline catalog improved from 11 to 15 cases without findings. The Copilot now reads finalized intake integrity failures, duplicate intake and source-ID conflicts, and the selected reconciliation run's immediate predecessor. Historical evidence uses persisted timestamps and separate citations. The mock independently ranks operational facts, so the retry case shows all three attempts while retaining the original hypothesis citation cap. Neither run reported a citation violation, unsupported hypothesis, unsupported phrase match or provider call.

The final disposable run measured evidence retrieval at 22.411 ms p50 and 43.734 ms p95, compared with 18.747 ms and 34.790 ms in the baseline. Added regressions cover intake outcome separation, acknowledgement cutoffs, predecessor chronology and retry ranking. See the [evaluation comparison](AI_EVALUATION_REPORT.md#remediation-results) for remaining scope limits. Real-provider behavior remains unmeasured.

The isolated verification passed 226 backend tests, nine evaluator tests, and 11 Chromium cases. The existing recovery suite, backend and frontend production builds, Compose validation and whitespace checks also passed.

## Previous handoff — Copilot evaluation

The offline evaluator persisted 15 synthetic cases on disposable PostgreSQL and ran them through the same query resolver, evidence retrieval and selection validation as the application. Both runs completed 15 cases with no errors. Eleven had no rubric finding. Checksum and duplicate delivery need intake claim evidence, the corrected reconciliation does not include parent evidence, and the mock skipped the first failed attempt in one retry timeline. The rubric found no citation, injection marker or unsupported-claim failures in this catalog. This is a simulated-provider baseline.

Nine evaluator tests, 223 backend tests and 11 Chromium cases passed. Backend and frontend production images built, and Compose and whitespace validation passed. Live mode has an explicit opt-in, model choice, request cap and spending reservation. No external model requests were sent. Compare against a real model only after authorizing the model and budget. See the [AI evaluation report](AI_EVALUATION_REPORT.md) for exact setup, measurements, safety checks and evidence gaps.

## Previous handoff — Convergence tail investigation

The instrumented 1,000-delivery comparison separated real event processing from stale queue counters and teardown. Before the change, the last delivery completed at 36.571 s, the final activity projection committed and its ACK call returned at 56.225 s, and RabbitMQ's metrics first showed an empty queue at 60.814 s. Reusing one checked PostgreSQL connection per publisher and consumer process moved those markers to 35.719 s, 37.505 s and 41.170 s. Both runs produced the same 3,811 outbox, inbox and activity records, with no deadlocks, DLQ entries or HTTP errors. The lab preserves the original completion predicate and reports the ACK-call marker separately. See the [measurements and commands](PERFORMANCE_REPORT.md#convergence-tail-investigation).

The updated disposable suite passed 223 backend tests and 11 Chromium cases across live and simulated-response runs. It verified recovery of the pooled connection after terminating the worker's own idle PostgreSQL session, plus the existing broker outage, process interruption, duplicate delivery, DLQ, rebuild, and SSE regressions. The image build, Compose validation and scoped whitespace checks passed. Repeat the instrumented trials before additional tuning. The optional 10,000-delivery run remains unmeasured.

## Previous handoff — Reliability and performance engineering

The disposable Docker lab runs synthetic SFTP, PostgreSQL, RabbitMQ, Mailpit and authenticated dashboard workloads without host exposure. It measured 100 and 1,000 deliveries, two intake and processing workers each, two dispatchers and four concurrent operators. The 1,000-delivery runs each projected all 3,811 events, delivered 200 notifications and recorded no deadlocks or terminal dispatch failures. The matcher handled 20,000 records per source with a measured median of 217.88 ms and 26.68 MiB of traced matching allocations. PostgreSQL now returns only the requested reconciliation result summaries while preserving citation indices. The sampled page p95 fell from 101.84 ms to 19.58 ms. The end-to-end runs do not show an overall throughput improvement.

Disposable fault regression covered broker and database unavailability, processing and SMTP interruption, publisher death after confirm, consumer death before ACK, duplicate SFTP intake, reconciliation races and restart, the DLQ and projection rebuild, and browser SSE catch-up. The Linux backend suite passed 222 tests, including 42 PostgreSQL cases, with seven warnings. Chromium passed six live cases and five simulated-response cases across the two runs. Backend and frontend image builds, quiet Compose configuration for the demo profiles, and scoped whitespace checks passed. The Windows virtual environment lacked the declared Argon2 dependency during separate PostgreSQL test collection; the full Linux suite ran against the isolated `opsbridge_test` database. See the [performance report](PERFORMANCE_REPORT.md) for the workload definitions, commands and fault timings.

The 10,000-delivery extended workload is available for a separate run. These measurements do not establish production capacity.

## Previous handoff — Security and RBAC

OpsBridge uses individual Argon2id accounts and revocable PostgreSQL sessions. The dashboard signs in through same-origin secure cookies and includes a per-session CSRF token on writes. Viewer, Operator and Admin permissions are enforced by the backend. Operator actions use the authenticated account UUID. Account administration, policy changes, login and logout are recorded in an append-only security ledger alongside the existing business audit. Browser SSE checks the active session. Machine workers remain independent of browser sessions.

Migration `ca78b650af13` was applied to disposable PostgreSQL and checked in upgrade and downgrade rendering. The backend suite passed 221 tests, including 41 isolated PostgreSQL cases. Chromium passed five simulated-response cases and five live cases. The live security case checked Viewer and Operator sign-in, rejection of direct forbidden actions, Copilot CSRF enforcement, SSE authorization and logout invalidation. The disposable workload verified authenticated intake views, RabbitMQ projection and recovery, Mailpit, reconciliation and Copilot. API checks exercised account creation and deactivation, role changes, denied privilege escalation, session revocation and notification policy access. Production builds, all-profile Compose validation and scoped whitespace checks passed.

Local authorization has no MFA, per-integration scopes or distributed rate limiter. Use TLS outside loopback and keep monitoring and backend ports on private networks. The next milestone should harden production deployment with least-privilege service identities, stronger operator authentication and security audit monitoring. See [operator accounts and roles](DASHBOARD_DEMO.md#operator-accounts-and-roles).

## Previous handoff — Financial reconciliation

OpsBridge now compares independent Fund Accounting and Custodian deliveries after both are processed. The worker pins accepted file versions, verifies their integrity, and stores a deterministic Decimal comparison with private source snapshots and immutable result history. It records exact and within-tolerance pairs, missing records on either side, amount mismatches, duplicate groups, ambiguous groups, and unsupported records. Exception policies open at most one operational incident per run and reuse the existing notification and event transport.

The workbench shows source links, filtered result groups, numeric differences, linked incidents and run lineage. An explicitly confirmed rerun creates a new audited run. Corrected completed exports arrive as separate configured source deliveries and link to the original run. The read-only Copilot cites run and exception classifications without receiving source rows or amounts.

The backend suite passed 210 tests, including 40 isolated PostgreSQL tests. Chromium passed five simulated-response cases and four live cases. The live workbench case checked the mismatch amount, mobile layout, Copilot, incident navigation and explicit rerun confirmation. The disposable end-to-end workload verified independent SFTP intake, concurrent workers, restart after a durable attempt start, bounded retries, matching classifications, an unchanged original run after correction, a reconciliation notification accepted by Mailpit, RabbitMQ activity projection and Copilot citations. Production builds, Compose validation, offline migration rendering and scoped whitespace checks passed.

The demo uses the local operator guard. The worker supports up to 20,000 records per source. The next milestone should add authenticated operator permissions and exercise the storage and query design at representative peak volumes. See [the workbench demo](DASHBOARD_DEMO.md#reconciliation-workbench).

## Previous handoff — Operations Copilot

Operators can analyze a persisted incident from its detail view or ask a supported question in the dashboard. Evidence comes from bounded, read-only PostgreSQL queries. The response separates recorded facts, hypotheses, suggested investigation steps and evidence gaps. Citations map to record IDs and UTC timestamps. The deterministic provider is the demo default and displays the **Simulated analysis** badge. The opt-in OpenAI adapter ranks observations and eligible hypotheses. The server assembles the wording and validates every selected reference.

The full Linux backend suite passed 206 tests, including 38 against a verified disposable PostgreSQL instance. The new tests checked SQL-level read-only enforcement, evidence filtering, source limits and chronology, unsupported requests, invalid citations, provider timeouts and retry limits. Chromium passed five simulated-response cases and three live cases. The live Copilot case investigated a persisted CSV validation incident and answered an SLA question through nginx. The existing intake, processing, RabbitMQ, notification and live refresh workflows passed in the same disposable run.

Backend and frontend production builds, all-profile Compose configuration and whitespace checks passed. The real adapter was tested with synthetic OpenAI HTTP responses. Live OpenAI authentication and model behavior remain unverified. The English question grammar and hypothesis vocabulary are intentionally bounded. Production deployment needs authenticated access and a privacy review. See [the demo and provider setup](DASHBOARD_DEMO.md#operations-copilot).

**Next action** Evaluate the supported investigation paths against representative synthetic failures and review privacy before enabling a live provider for operator use.

## Previous handoff — Observability and real-time operations

The API and worker entry points emit structured JSON with correlation fields. The API exposes liveness, dependency readiness and Prometheus metrics. Workers expose scrapeable durations, outcomes and readiness. Prometheus and Grafana are available through a loopback-only monitoring profile with a provisioned Operations dashboard.

Migration `f43c720a19be` signals dashboard changes after PostgreSQL commits. Each API process relays invalidation through a shared database listener. The dashboard refreshes automatically after a signal, polls every 15 seconds during a disruption and retains manual refresh.

The full Linux backend suite passed 188 tests, including 36 isolated PostgreSQL tests. The transactional invalidation test verified that rollback emits no signal and multiple writes in one commit emit one signal. Chromium passed four simulated-API cases and two live cases. The live run verified that a delivery created by another client and a separately acknowledged incident update the open dashboard automatically. The simulated browser run verified coalescing, polling fallback and catch-up on reconnect.

The disposable runtime verified readiness loss and recovery during a RabbitMQ outage, the API metrics scrape, native DLQ metrics, and publisher readiness before and after restart. A separately named Compose project verified Grafana provisioning, all ten panels' queries and live PostgreSQL, API, publisher and RabbitMQ metrics through the Grafana data source. Backend and frontend production images, all-profile Compose validation, `promtool check config`, offline upgrade and downgrade rendering, and `git diff --check` passed. Test migrations ran only after PostgreSQL identified itself as the disposable `opsbridge_test` database.

For the local setup, metrics catalog and recovery behavior, see [live operations and monitoring](DASHBOARD_DEMO.md#live-operations-and-monitoring). Persisted counters survive worker restarts. Request and operation metrics reset with their processes. The database aggregate queries and SSE fan-out have not been tested at production volume.

**Next milestone** Define operational thresholds and test alerting for sustained worker outages, growing queues and repeated notification failures.

## Previous handoff — Incident notification and escalation

Incident transactions enqueue notification jobs in PostgreSQL. Configurable policies select synthetic owners and recipients by integration, incident type, severity and event. Scheduled levels, attempt outcomes, cancellations and operator acknowledgements are durable. The worker accepts only the local Mailpit sink and synthetic `.test` recipients. The dashboard exposes the policy, incident state, email state and attempt history separately.

The Linux backend suite passed 182 cases, including 35 PostgreSQL integration cases. Three simulated-API Playwright cases and one live case passed. The isolated demo verified concurrent SMTP dispatch, escalation timing, acknowledgement and resolution cancellation, and real Mailpit captures matched by Message-ID. The Windows dashboard and Mailpit endpoints responded on loopback. Production builds, Compose profile validation and whitespace checks passed.

The acknowledgement route is disabled by default. Its opt-in local demo assigns a fixed server-side actor in a verified `opsbridge_test` instance. SMTP acceptance is not exactly-once delivery. If a worker is interrupted after acceptance, the next dispatcher records the attempt as unknown and may send the same Message-ID again. See [the demo and policy guide](DASHBOARD_DEMO.md#incident-notifications).

## Previous handoff — RabbitMQ activity projection

The `events` Compose profile adds a durable RabbitMQ node, an outbox publisher and an activity consumer from the backend image. The publisher confirms routed v1 references before marking outbox rows published. The consumer resolves each reference against PostgreSQL and commits inbox deduplication with the activity projection. The dashboard shows the filtered, paginated feed alongside the authoritative delivery timeline. An atomic rebuild refreshes the feed from delivery events without replaying business operations.

The Linux backend suite passed 173 tests, including 32 PostgreSQL integration cases. Three simulated-API Playwright cases and one live dashboard case passed. The live demo ran on a disposable PostgreSQL 17 instance verified as `opsbridge_test` and a temporary RabbitMQ 4.2 node. It verified broker unavailability and retry, concurrent publisher claims and consumers, crash after confirmation, crash before acknowledgment, duplicate delivery, rollback of inbox and projection together, three projection attempts before dead lettering, malformed-message dead lettering, and two rebuilds with one projection per event. Production builds, Compose validation and whitespace checks passed.

The local RabbitMQ node demonstrates persistence and at-least-once delivery. It does not exercise a clustered failover or a production authorization policy. See [the event demo and rebuild guide](DASHBOARD_DEMO.md#event-transport-and-recovery).

## Previous handoff — SLA and processing

The local operations profile starts dedicated SLA and processing workers from the backend image. The SLA worker records the first breach with a missing-file incident and a transactional outbox record. Late identifiable arrivals resolve the incident while keeping the breach timestamp. The processing worker verifies the finalized snapshot, records reconciliation counts, and persists each attempt and its outcome. Retryable failures wait five seconds between attempts. Each series allows three attempts in total.

The dashboard distinguishes calculated lateness from recorded SLA breaches, shows open and resolved incidents, and displays attempt history and failure reasons. With local reprocessing enabled, an operator can confirm a new series for a current file whose retryable failures exhausted its budget. The actor is an audit label supplied by the trusted local operator. See [the demo guide](DASHBOARD_DEMO.md).

The Linux backend suite passed 164 tests, including 32 isolated PostgreSQL integration cases. Three simulated-API Playwright cases and one live case passed. The production Vite build, Compose profile validation and whitespace checks passed. The demo ran two instances of each worker against a disposable PostgreSQL 17 cluster verified as `opsbridge_test`. It produced 25 completed files, four persisted SLA breaches, four missing-file incidents and one start and completion event per processed file. The live dashboard responded on Windows loopback port 18082. The integration tests also exercised recovery from interruption, exhaustion, rejection of a stale manual request and completion of a new audited series.

Installation-level SSH verification remains blocked by protected credential inputs. The SFTP subsystem demo verifies transfer and atomic handoff without those inputs. The required provisioned identity, trusted host key and acceptance checks are described in [the intake guide](INTAKE_DEMO.md).

**Next milestone:** RabbitMQ outbox publication and the idempotent activity feed projection.

## Previous handoff — Integration Operations Center

The dashboard now prioritizes actionable incidents and computed exceptions. Delivery details read authoritative events with stable pagination. The overview shows UTC deadline and first-arrival KPIs, and each integration separates configured activity from observed receipts and operational issues.

The expanded demo creates 37 expectations across five fictional integrations. The API and intake worker produce 29 recorded arrivals, four current validation failures, four pending expectations, four overdue expectations and 24 on-time arrivals. The demo exercises repeats, replacements and conflicts through OpenSSH SFTP subsystem uploads. The overdue figures are calculations; scheduled SLA detection remains a separate milestone. See [the demo guide](DASHBOARD_DEMO.md) for definitions and the walkthrough.

The Linux backend suite passed 156 tests, including 30 tests on disposable PostgreSQL. The focused Windows unit run passed 118 tests with three Linux-specific cases skipped. All three Playwright cases passed across simulated and live API runs. The live run covered attention priority, replacement and validation history, and a 390 px viewport. The populated demo also responded from Windows at `127.0.0.1:18081`. The production build, Compose validation and whitespace checks passed.

**Next milestone:** scheduled SLA detection, including a persisted breach and missing-file incident once per expectation, and downstream processing with bounded retries.

## Previous handoff — Operations dashboard

The React dashboard shows integration activity, delivery counts by status, a filterable delivery queue and current file details. The read-only FastAPI routes under `/dashboard` return existing PostgreSQL records. Compose serves the dashboard on loopback through nginx and connects it to an internal API container. See the [dashboard demo](DASHBOARD_DEMO.md) for the synthetic duplicate-upload walkthrough.

- Production TypeScript/Vite build and quiet validation of the dashboard and intake Compose profiles passed.
- The Linux backend suite passed all 156 cases, including 30 PostgreSQL integration cases. The new dashboard assertions inspect the filtered read model and the replacement file. The driver checks the database name before running migrations on its disposable PostgreSQL 17 instance.
- All three Playwright cases passed across the simulated API and live API runs. In the live run Chromium opened the received delivery and inspected the invalid CSV outcome. The initial repeat upload still produced one file and one receipt event while retaining two packages.
- The presentation mode responded from Windows at `127.0.0.1:8080` with one received, one validation-failed and one expected delivery. A disposable bridge carries the published dashboard port. PostgreSQL listens only on loopback inside its shared container namespace.

Downstream processing, SLA monitoring and the RabbitMQ activity projection remain separate milestones.

## Previous handoff — SFTP intake, 2026-11-21

The intake slice runs as a dedicated Compose worker. A vendor publishes a package by renaming it from staging to incoming. The worker discovers and claims the package, snapshots into private storage, validates integrity and CSV, resolves the expectation, and commits its business outcome. The delivery list API exposes the resulting status and current file. The demo and its prerequisites are in [INTAKE_DEMO.md](INTAKE_DEMO.md).

| Verification | Result |
| --- | --- |
| Final Linux regression and smoke driver, `.\.venv\Scripts\python.exe scripts/verify_intake_demo.py --tests` | **156 passed, 7 dependency deprecation warnings**, including 30 PostgreSQL integration cases. Both images built. The SFTP entrypoint passed Bash syntax validation and the intake Compose profile passed quiet config validation. |
| OpenSSH direct subsystem, Linux volume, separate vendor/worker UIDs, real worker CLI and HTTP API | Two uploads produced two finalized accepted packages, one file, one receipt event and an API-visible `RECEIVED` expectation. |
| Transaction and failure paths | PostgreSQL coverage includes CSV failure and corrected replacement, conflict/replay priority over content duplicates, unexpected payload, integrity failure, missing incident resolution, inactive/unknown integration, and resuming a committed claim before final movement. Temporary filesystem tests cover both sides of final rename, partial snapshot restart, links, FIFO, private-copy integrity and strict CSV. |
| Database isolation | Each live verification used a fresh local PostgreSQL 17 container. Identity was checked with `SELECT current_database()` before applying the existing revisions. The development database and real account mappings were outside the test setup. |

**Remaining runtime check:** credentialed SSH login, host-key verification and the provisioned account's chroot in the target installation. The automated demo exercises the OpenSSH SFTP subsystem directly. A credentialed simulator is included for a pre-provisioned demo account. Process interruption is covered at transaction and rename boundaries; a host power-loss drill has not been performed.

**Next implementation milestone:** downstream processing and SLA monitoring, including bounded processing attempts, overdue detection and audited manual retries. The intake slice ends at receipt or permanent validation failure. Publisher, consumer and dashboard work follow in the development plan.

## Historical baseline before intake implementation

The following inventory and checks describe the workspace at takeover.

| Area | Current evidence | Next dependency |
| --- | --- | --- |
| API | FastAPI health endpoint, integration create/list and expectation create/list. The write service commits expectation creation, its delivery event and its outbox row together. Tests exercise the HTTP layer with service overrides. | Live PostgreSQL exercises require the isolated test target. |
| Database | SQLAlchemy models and Alembic revisions for eight operational tables plus intake claims. The initial migration defines append-only and replacement-link triggers. The local revision chain is `a84f2c91d6b0 → c51f9a6e2d84 → d2b17c4e806a`. | The applied revision and database contents were not queried during configuration. |
| SFTP infrastructure | Compose defines PostgreSQL 17 and restricted OpenSSH SFTP, loopback ports, separate networks and persistent volumes. SFTP data and host keys have distinct mounts. | Runtime provisioning, package publication and worker access require a later local runtime check. The older SFTP README mentions a different future backend mount. Use the approved shared root `/srv/opsbridge-sftp` when adding the worker. |
| Intake | Phase 1 provides UUID path builders, two-file package inspection, size caps and strict V1 manifest parsing, including parser-limit errors. The claim schema and its tests exist. | Snapshot copying, integrity verification, claiming/locking, CSV validation, business persistence, final movement and recovery are outstanding. |
| Demo | The API foundation can express an expected synthetic delivery. | Vendor simulator, dedicated worker runtime/image, processing, SLA monitor, RabbitMQ publisher/consumer, dashboard and Playwright scenarios remain roadmap work. |

## Verification during configuration

Commands ran from the repository root on Windows. Database-free Python checks disabled dotenv, cleared the child process connection URL and disabled the integration opt-in.

| Check | Observed result |
| --- | --- |
| `.\.venv\Scripts\python.exe -m pytest backend/tests -m 'not integration' -q` | **109 passed, 29 deselected, 7 warnings** in 0.94 s. The Windows sandbox stalled in asyncio socket-pair creation during TestClient startup. The same regression selection passed outside that restriction. Warnings concern the TestClient HTTP dependency and Alembic path-separator configuration. |
| `.\.venv\Scripts\python.exe -m pytest --collect-only -q -p no:cacheprovider backend/tests/integration` | 29 tests collected across connection, business services, triggers and intake claims. Database execution was outside this configuration task. |
| `.\.venv\Scripts\python.exe -m alembic -c backend/alembic.ini heads` | Single local script head `d2b17c4e806a`. Offline migration SQL is also covered by the regression suite. |
| `.\.venv\Scripts\python.exe -m uvicorn --version` | Uvicorn 0.54.0, CPython 3.14.10. The regression suite exercised the ASGI health endpoint in process. |
| `docker compose version` and `docker compose config -q` | Compose v5.7.0. Configuration validation exited 0 with automatic dotenv loading disabled and synthetic process values for the three required PostgreSQL variables. No containers were started. Windows OpenSSH SFTP client was found on PATH. |

Live service readiness, SFTP authentication, PostgreSQL constraints on a running server and browser behavior were not exercised here. None blocks starting the snapshot milestone. Before a database milestone, confirm access to the isolated local `opsbridge_test` and its applied revision. Any migration requires separate task authorization.

## Working tree at takeover

The inspected HEAD was `817f869` (restricted SFTP ingress). The following work predated the workflow documents and remains in the working tree:

- Four tracked edits in model registration, enums, the integration/expectation model and model metadata tests.
- Eleven untracked implementation/test files: the intake-claim revision and model, its integration and migration tests, four intake package files and three Phase 1 unit test modules.

This increment extends the existing root contributor guidance and adds the plan and this status document. The current milestone handoff is here; the root README's feature list predates the intake-claim revision and Phase 1 helpers.
