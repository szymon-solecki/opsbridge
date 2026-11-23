# OpsBridge release readiness

**Decision:** candidate for a private, final human review and a synthetic portfolio demonstration. Confirm the publication inventory, licensing and a hosted CI run before making the repository public. A production deployment remains outside this release.

Use the [publication checklist](PUBLICATION.md) and [exact file inventory](PUBLICATION_MANIFEST.txt) to prepare the public source snapshot.

## Command Center Stage 6

### Architecture and capabilities

OpsBridge is a local financial integration operations demonstrator. OpenSSH SFTP hands packages to a Python intake worker, which snapshots and verifies them before applying PostgreSQL business outcomes. FastAPI reads delivery and incident history for the React Command Center and checks role, session and CSRF on mutations. PostgreSQL is authoritative for delivery events, reconciliation runs, security audit and notification state. A transactional outbox and RabbitMQ project the derived activity feed. Prometheus and Grafana provide telemetry, and Mailpit captures synthetic SMTP locally. [Architecture](architecture.md) · [13-minute walkthrough](PORTFOLIO_DEMO.md)

### Operational acceptance inventory

| Journey | Evidence exercised by the isolated application |
| --- | --- |
| Successful arrival and processing | OpenSSH subsystem upload, stored file, receipt and processing timeline. A repeat upload retains two packages with one business file and one receipt. |
| Missing delivery | The monitor records an SLA breach and opens a missing-file incident. Delivery Workspace displays both facts. |
| CSV validation failure | The file and persistent validation code appear in Delivery Workspace. Copilot cites the same failure and the validation incident. |
| Conflicting source delivery ID | The isolation fixture asserts the stored conflict incidents. Action Center surfaces the conflict, and Delivery Workspace shows the retained file and open incident. |
| Investigation and acknowledgement | A browser opens an incident and local notification history, records an acknowledgement comment, and observes cancelled pending escalation. A separate browser observes acknowledgement made through the API. |
| Authorized manual reprocessing | A finalized file exhausts real attempt transactions under an injected storage fault. The browser requires confirmation, gets `202`, and a stale replay gets `409`. A subsequent worker completes series two, keeps all three prior failures, and leaves one audited operator request. |
| Financial exceptions | The original reconciliation is technically completed with five exception groups. A browser drills down to the recorded `-10.000000 USD` amount mismatch. |
| Corrected results | The corrected run has zero exception groups and points to its immediate predecessor. The UI compares the recorded counts and preserves both runs. |
| Source navigation | The live run opens its linked source delivery. Browser Back restores the same run and comparison. |
| Simulated Copilot | Scoped incident and reconciliation analysis are labeled simulated. Citations open persisted evidence, and supported links open the related workspace. The offline evaluation checks exact citation identities and timestamps separately. |

### Data integrity and security review

| Area | Observed contract and evidence |
| --- | --- |
| Amounts and currency | Reconciliation uses Python `Decimal`, six fractional places, amounts below `10^18` in magnitude, and currency in the match key. Unsupported amount precision or currency shape yields `INVALID`. Report differences are signed decimal strings. The UI preserves those strings and displays currency with each result. Cross-currency aggregation and FX conversion are outside the contract. |
| Evidence history | Runs pin source file IDs and use persisted reports. Reconciliation migration triggers protect terminal run evidence, source pins and definitions. The corrected-run comparison uses the immediate predecessor and aggregate group counts. A drop in counts does not establish the resolution of a particular record. The source link opens the current delivery view while the run retains its historical pin. |
| Delivery, incidents and SLA | Delivery completion and incident lifecycle are shown independently. An accepted late arrival can resolve a missing-file incident while the original SLA breach remains recorded. Acknowledgement records the operator and time, and the incident keeps its own lifecycle. Structured date displays use UTC. Reconciliation business dates are calendar dates. Copilot facts may include exact ISO timestamps from persisted evidence. |
| Authorization and audit | Viewer reads evidence, Operator can acknowledge and request eligible reruns, and Admin controls accounts and policy writes. Backend role checks and CSRF still apply to direct requests. Session expiry and revocation are checked in PostgreSQL. Audit coverage includes sign-ins, account and policy changes, acknowledgements, and manual reprocessing. Admin policy review still ends in a whole-policy PUT. |
| Field and log exposure | The reviewed UI hides technical record identifiers behind disclosures where context does not require them. Admin policy details deliberately show configured recipient addresses. Copilot omits raw uploads and untrusted free text from provider input. Operational logs use correlation identifiers and codes. The checks exercise known synthetic adversarial strings and validation input redaction. A full data-classification or log-retention assessment remains a deployment gate. |

### Release checklist and known limitations

| Priority | Release gate or follow-up |
| --- | --- |
| Blocker — public release | Confirm rights and license, review the complete publication inventory including untracked implementation, and run hosted CI from the exact approved snapshot. The local working tree is the release candidate tested here. |
| Blocker — real data deployment | Set deployment security and availability requirements first. The local demo uses synthetic data, single-node services, local monitoring and smoke-test controls. Production identity, TLS, least-privilege database roles, backup/restore validation and external monitoring access are independent gates. |
| Important | Concurrent notification policy editing uses whole-document replacement without a version check. Review before saving and coordinate editors. A version precondition would require a separate API change. |
| Important | Use the credentialed [SFTP setup](INTAKE_DEMO.md) when demonstrating a network handshake. The launcher verifies the OpenSSH subsystem in direct mode. Grafana's default portfolio view covers API and broker targets, and the monitoring Compose profile includes worker targets. |
| Important | SMTP and broker recovery are at least once. Verify inbox deduplication and audit history separately from repeat delivery to a local mail sink. |
| Important | Keep the simulated Copilot in portfolio mode. External processing requires an explicit privacy, egress, billing and model evaluation decision. |

### UX backlog

- **Backlog:** Present exact Copilot fact timestamps in a more compact human-readable style while preserving full evidence timestamps.
- **Backlog:** Add assistive-technology and zoom coverage beyond the desktop, tablet, mobile and keyboard regressions.

### Working-tree release checks

- [x] Verify PostgreSQL identity before migrations. The full isolated run passed 227 backend tests plus the RabbitMQ, Mailpit and readiness recovery scenarios. The network-disabled backend run passed 182 tests. Its five skipped and 40 deselected tests require the isolated PostgreSQL run.
- [x] Chromium passed 22 controlled tests and all 11 live scenarios. Review covered 11 synthetic views at 1440, 768 and 390 pixels. Contact sheets are in `data/frontend-stage6/`.
- [x] Run the original offline Copilot catalog without external requests. All 15 scenarios completed with zero findings or citation violations.
- [x] Smoke-test the portfolio launcher with cached images, a temporary synthetic Admin session and three separate loopback ports. Verify the dashboard, Mailpit, Grafana and both Prometheus scrape targets.
- [x] Verify the frontend production build, Chromium image, offline all-profile Compose configuration and scoped whitespace.
- [ ] Review, license and freeze the exact publication snapshot. Run hosted CI on that snapshot before publishing.

Reproduce the working-tree regression with cached local images. The harness checks `SELECT current_database()` before migrating its fresh `opsbridge_test` and publishes no service ports in verification mode.

```powershell
$env:PYTHON_DOTENV_DISABLED = '1'
.\.venv\Scripts\python.exe scripts/verify_intake_demo.py --tests --dashboard-test --dashboard-screenshots --delivery-screenshots --reconciliation-screenshots --experience-screenshots --operations --events --notifications --reconciliation --faults
```

The earlier parallel browser failure occurred with five workers. The login route intentionally limits each API process to four in-flight sign-ins and returns HTTP `429` when that limit is exceeded. The deterministic regression holds four requests inside the handler, checks the fifth response, and checks that the next request proceeds after the held requests finish. The original browser failure did not capture the HTTP status. The isolated suite uses three workers to leave headroom without changing authentication or increasing timeouts.

The first Stage 6 live browser run passed all 11 scenarios. Its final database check failed because the harness reused the authentication script instead of the reprocessing fixture. A clean rerun used the explicit fault fixture and verified one audited request, three retained first-series failures, and successful completion of the second series.

### Optional OpenAI adapter readiness

The existing adapter is opt-in using `OPSBRIDGE_COPILOT_PROVIDER=openai`, `OPSBRIDGE_COPILOT_MODEL`, and a server-side `OPENAI_API_KEY`. Missing configuration disables the adapter. The portfolio runner sets `mock` explicitly. The redesigned UI accepts simulated analyses. Live provider activation would need a separate controlled UI and deployment decision. No external requests are required for current verification.

- **Outbound payload.** The adapter posts to `https://api.openai.com/v1/responses` with `store: false`. It sends an operation name, bounded normalized facts and UTC timestamps, temporary evidence references, and allowlisted hypothesis keys and text. Record IDs, user question text, source files, raw financial amounts, staff comments, recipient addresses and credential values are outside the model input. Network access and provider retention still require review. The adapter ignores ambient proxy settings (`trust_env=False`). A live network policy must explicitly allow only approved destinations and deny unnecessary egress. The offline evaluator uses a network-disabled namespace.
- **Failure and cost.** Two attempts maximum with an 11-second total deadline and 350 output tokens per attempt. Timeouts and retryable transport or HTTP failures map to safe error codes. Responses are size-limited and strictly validated. Metrics record provider outcomes, latency and reported tokens. The evaluator estimates cost from supplied prices, and usage can be unknown on failed requests. The estimate is separate from a provider billing cap.
- **Citation validation.** The model returns only evidence and hypothesis selections. The server rejects unknown references, assembles facts and recommendations from local data, and attaches the original record identifiers. The evidence transaction is read-only and neither the UI nor the adapter invokes operational actions.
- **Synthetic evaluation.** Reuse the existing 15 cases as a frozen baseline. Add a separate holdout for counterfactual incidents with missing evidence, adversarial free text, corrected predecessor lineage, same-reference multi-currency differences, and unauthorized mutation requests. Before release, measure citation ID and timestamp correctness, unsupported claims, evidence coverage, user-visible failures, latency, tokens and cost on an approved model. [Evaluation rubric and offline results](AI_EVALUATION_REPORT.md)

## Earlier release preparation verification

| Check | Local evidence |
| --- | --- |
| Application regression | 226 backend tests passed, including 45 isolated PostgreSQL cases. The separate no-network selection passed 181 unit tests. All 11 Chromium tests passed across five simulated and six application cases. The RabbitMQ, Mailpit, reconciliation and recovery checks passed. |
| Portfolio runtime | Disposable smoke validated the Operations Center, Mailpit and Grafana over three loopback ports, and both Prometheus targets through the Grafana datasource. An authenticated rerun completed and appeared in Activity Feed through the running publisher and consumer. The first smoke run caught an HTTP client lifecycle error and the corrected run completed successfully. |
| Copilot verifier | Nine evaluator tests passed and all 15 synthetic offline investigations finished without findings. Zero OpenAI requests. |
| Production image builds | Backend with pinned Python constraints, nginx frontend and the Chromium runner built locally. |
| Development checks | Ruff syntax and undefined-name checks across backend and scripts, default lint and formatting on the release tools, TypeScript, quiet all-profile Compose rendering, and `git diff --check`. |
| GitHub workflow configuration | `actionlint` 1.7.12 validated the workflow. Checkout is pinned by full commit SHA with credential persistence disabled. Jobs have read-only repository permissions. No hosted run was triggered. |
| Python dependency audit | `pip-audit` 2.10.1 reported no known vulnerabilities across 35 audited pins at the time of review. `pip check` passed in the backend image. |
| Frontend dependency audit | `npm audit` reported zero advisories in the checked-in lockfile at the time of review. The lockfile is consumed with `npm ci`. |
| Repository content review | The tracked-only check examined 52 paths. The candidate scan also checked permitted untracked sources. Neither found matching token or key markers or blocked publication paths. Existing `.env.example` is the only tracked environment path. Protected local files and Git history were outside this review. |

The Python constraints capture the tested Linux application's resolved dependency versions. They are version pins without artifact hashes. The image's registry comparison reported only the base image's `pip` tooling behind the latest version, from 26.2.2 to 26.3. The frontend lockfile pins its dependency tree. The npm registry check found a newer major line of Lucide; the existing range holds `lucide-react` at 0.468.0. React, React DOM and DM Sans already matched the applicable lockfile versions reported by the check. The declared backend runtime packages and frontend UI packages have uses in the source. Pytest remains required for the shared test image.

## Security review and risk register

Severity reflects the impact and evidence in this repository. No confirmed critical exposure was found in the permitted review scope.

| Severity | Finding and evidence | Release action |
| --- | --- | --- |
| High | The candidate includes existing modified and untracked implementation files. A fresh checkout of the current Git snapshot cannot reproduce working-tree results before a maintainer reviews and includes the required files. | Review the candidate paths and intended diff, and verify the exact reviewed snapshot on a private hosted runner. |
| High | The original Grafana 12.1.1 tag was outside support and predates security fixes. The reviewed demo binds Grafana to loopback and provisions only a Prometheus datasource. Grafana 12.4.15 now replaces it in Compose and in the portfolio launcher, verified with a fresh instance. | Keep both references on a supported, audited line and keep anonymous Viewer access local. Back up existing Grafana data before upgrading a persistent installation. [Vendor support matrix](https://grafana.com/docs/grafana/latest/upgrade-guide/when-to-upgrade/) · [Grafana advisory and fixed versions](https://grafana.com/security/security-advisories/cve-2026-88858/) |
| High for deployment | The synthetic stack uses one PostgreSQL instance, a one-node RabbitMQ quorum queue, synthetic policies and local monitoring. It provides no multi-node failover, backup restore drill, SSO or MFA. | Limit this release to a loopback demo. Before any deployment, specify least-privilege database roles, HTTPS, external identity, authenticated monitoring and a tested backup/restore plan. |
| Medium | The permitted scan detects known secret shapes and blocked artifacts, but it cannot classify arbitrary personal data or prove an entire repository history is secret-free. Image OS layers were outside the Python and npm advisory checks. | Review publication contents and rights manually, and run an image SBOM and vulnerability scan before any distribution of images. Do not rely on the package scan as a full security assessment. |
| Medium | The launcher exercises an actual OpenSSH SFTP subsystem with synthetic files. It bypasses public-key handshake and network transport in this path. The default Grafana view scrapes API and RabbitMQ only. | Use the credentialed Compose procedure to verify an actual SFTP client and provision the full monitoring profile when presenting worker panels. |
| Medium | Outbox delivery is at least once. SMTP recovery can produce a repeat send. Broker queue metrics can lag; the measured 1,000-delivery results came from paired local trials. | Retain the fault regressions and document the delivery guarantee. Run repeated workload and recovery tests before setting any capacity target. |
| Medium | Docker image tags can move, Python pins lack hashes, and the backend image contains test dependencies. | For distributed artifact releases, pin image digests, produce a hash-locked platform manifest and separate the runtime and test dependency sets. |
| Low | The Copilot passed 15 offline scenarios using simulated selections and bounded evidence. Validation against a real model, billing and privacy acceptance remain outside this milestone. | Keep the simulated badge visible and treat real-provider approval as a separate decision. |
| Low | Python formatting enforcement currently covers the newly introduced release tools. Legacy code receives syntax and undefined-name checks. | Tighten style checks in a reviewed, separate change to avoid unrelated churn. |

The repository ignores local environments, key formats, dumps, local database files and generated test results. The demo's monitoring configuration and synthetic Compose validation variables carry no operational secrets. The source checker reports a location or a path-rule failure without matched values. The review found no real financial fixtures in the inspected publication set; the demo generates CSVs during execution from fictional accounts and scenario data.

## Publication checklist

1. Review the complete candidate manifest, including modified and untracked source files. Confirm that configuration examples, screenshots, fixture data and any repository metadata are approved for public use.
2. Select a license and confirm rights to publish project code, documentation and media. No license was chosen in this milestone.
3. Have the maintainer create the reviewed snapshot in a private review repository after authorizing the Git operations. Run the checked-in workflow on that exact snapshot and review every job result. Enable required checks and available secret scanning for the publication repository.
4. On a clean machine, follow the [developer guide](DEVELOPER_SETUP.md) and [13-minute demo](PORTFOLIO_DEMO.md). Recreate the disposable dataset after one walkthrough. If credentialed SFTP is included in the presentation, run that setup separately with synthetic credentials.
5. Approve the public snapshot after reviewing the remaining risks. Keep deployments and production claims outside the scope of this portfolio release.
