# OpsBridge frontend redesign plan

**Status:** Stages 1–5 implemented. Stage 6 verifies the integrated working-tree candidate and prepares the portfolio walkthrough. [Product and UX specification](PRODUCT_UX_SPEC.md)

## Stage 6 release verification

The existing workspaces were exercised against the disposable application at 1440, 768 and 390 pixels. The release suite adds live checks for the authorized reprocessing confirmation and replay boundary, and for navigation from reconciliation to a pinned source delivery's current workspace. The login regression covers the four-request server concurrency ceiling and subsequent slot release. Production navigation, authorization and financial behavior remain as implemented in Stages 1–5.

The [release report](RELEASE_READINESS.md#command-center-stage-6) captures the operating limits, priority gates and real-provider review. Use the [13-minute walkthrough](PORTFOLIO_DEMO.md) for the synthetic demonstration. A release snapshot needs licensing, an approved file inventory and hosted CI before public publication.

## Stage 5 delivered

- **AI Copilot** leads with an operational conclusion, separates facts, hypotheses and next steps, and opens focused evidence cards from citations. Stable record links use the existing delivery, incident, integration and reconciliation routes. Incident rows carry their owning delivery ID in the browser response. Other evidence without a supported route retains its timestamp and expandable identifier. The workspace accepts simulated investigations and preserves contextual entry points.
- **Monitoring** shows the browser update channel, the last successful overview read, delivery processing counts and the latest projected activity. Service readiness, outbox and broker backlog remain in the monitoring stack. Set the public dashboard-container variables `OPSBRIDGE_GRAFANA_URL` and `OPSBRIDGE_PROMETHEUS_URL` for browser links. Use absolute HTTP(S) destinations without embedded credentials. The portfolio runner passes its configured Grafana address. Prometheus remains internal to that runner.
- **Administration** provides URL-backed account and policy views. Role and activation changes require a separate confirmation. The structured editor preserves inherited, disabled and explicit recipients and escalations. It previews the full replacement policy before applying it. The advanced editor preserves fields outside the structured form. Existing Admin authorization, CSRF and audit checks apply to the same writes. The API supplies a whole-policy replacement without a version precondition.

Use `--experience-screenshots` with the isolated regression runner. Copilot, Monitoring, operator accounts and notification policies are captured at 1440, 768 and 390 pixels under `data/frontend-stage5/`.

The existing provider boundary and citation-backed UI are ready for a provider review. Live external use remains a separate decision that requires privacy and egress review, live provider evaluation against synthetic evidence, and operator approval for enabling external analysis.

## Stage 4 delivered

- **Run history** separates execution status from financial outcome, shows matched pairs and exception group counts, and uses bounded URL-backed pages. The list API supplies aggregate counts. Run-level materiality is shown in the evidence workspace.
- **Run evidence** starts with the highest-priority populated exception category. Result category, page and group index are URL-backed. A direct group link can retrieve one row by its ordinal in the unfiltered report. Amount differences and tolerances use the decimal text returned by the API without numeric conversion.
- **Immediate predecessor comparison** shows execution states, pinned file versions, aggregate result counts and integer deltas per category. The reports provide no record-level lineage or currency-wide total. The fewer-exceptions finding applies only to recorded group totals.
- **Source investigation** distinguishes the historical file pin from the delivery's current status. The source links open Stage 3 evidence. The existing API exposes pinned IDs and row counts. Historical file bytes and individual financial source rows are outside this workspace.
- **Operator actions** keep existing permission checks, CSRF and confirmation. A retry after an uncertain rerun response reuses the same request ID. The reconciliation Copilot enables submissions in simulated mode. Opening a run or group does not start analysis.

Use `--reconciliation-screenshots` with the isolated verification runner. Images of history and run evidence at 1440, 768 and 390 pixels, and comparisons at 1440 and 390 pixels, are stored under `data/frontend-stage4/`.

## Stage 3 delivered

- **Delivery queue** keeps integration, status, sorting and page in the URL. The server returns a 21-row look-ahead for 20 visible rows. The page-local search matches delivery type, business date and current filename. Exact UUID lookup opens the existing detail route. Row signals come from recorded failures or breaches. Successful deliveries stay visible in the same results.
- **Delivery evidence** lives on a dedicated page at `/deliveries/:id` and `/deliveries/:id/incidents/:incidentId`. The summary shows the recorded deadline, current-file receipt, SLA history and the active incident count within the loaded scope. The current file and chronological timeline sit beside incident investigation on wide screens. Jump links connect the continuous evidence sections, and identifiers and hashes open in disclosures.
- **Operator actions** retain the existing server role, CSRF and eligibility checks. Reprocessing requires confirmation for the current file and attempt series and refreshes eligibility on a conflict. Acknowledgement refreshes recorded incident status and notifications. Incident links focus the matching record when it is loaded. The original workspace and filters are available through browser history and the return link.
- **Evidence limits** The API supplies the current file and chronological event pages. A missing current file does not establish whether any submission arrived. SLA outcome describes the recorded breach flag. Incident history uses newest-first pages, up to 100 records per request, with explicit controls for older evidence. There is no exact incident lookup on this API. Queue rows do not claim incident or quarantine status without corresponding evidence.
- **Synthetic demo** Reconciliation expectations and the event-recovery example now use deadlines relative to demo startup. The existing synthetic business dates preserve package matching. Long-horizon performance tests remain separate. Demo views show ordinary processing, missing deliveries, CSV failures and source-ID conflicts using the same APIs as the workspace.

Use `--delivery-screenshots` with the isolated regression runner to capture the queue and evidence pages at 1440, 768 and 390 pixels, plus a focused mobile incident. Artifacts are stored under `data/frontend-stage3/`.

For the delivery demo, select **Northstar Treasury** in the queue. Open **Bank statement** for ordinary processing, **Settlement report** for a missing file, **Fx confirmations** for a validation failure, and **Custody positions** for a corrected upload with retained history. Open **Payment register** to show a completed delivery with an open source-ID conflict. Follow the incident from Action Center to demonstrate the same evidence through a second entry point.

## Stage 2 delivered

- **Overview** is a shift briefing. The workspace snapshot separates active incidents and overdue expectations from the recorded SLA breach count. The on-time rate uses recorded arrivals and shows its denominator. Processing figures come from current delivery statuses. Five priority items, up to six integration rows, and five projected activity entries link to the existing evidence routes.
- **Action Center** groups the first 40 server-ranked items into critical incidents, high-priority incidents, detected overdue or missing deliveries, and other issues. Items keep server rank, deadline, and key order within each group. The 41st result only signals truncation. Integration scope is server-filtered. Recorded, detected, and reconciliation scopes filter the loaded slice. Both filters persist in the URL.
- **Investigation** uses the existing routed evidence dialog. Active is the only incident lifecycle fact supplied by the queue. Open, acknowledged, and resolved states come from detail. Recorded severity is derived from the existing incident-type policy and confirmed on detail. Computed items receive an attention label. Acknowledgement remains available in detail only for eligible roles and open recorded incidents. Reconciliation incidents link to the incident first because the queue response has no run ID. The evidence dialog supplies the run link when available.
- **Data limits** The API supplies snapshots and a projected activity feed. The briefing reports factual counts and latest arrivals. The integration bars compare active incident counts within the displayed integrations. Global severity ordering beyond the returned slice, SLA trends, financial impact, and exhaustive search would require other data.

Screenshots from the isolated synthetic demo are written to `data/frontend-stage2/`. Use `--dashboard-screenshots` with the isolated regression runner to capture both routes at 1440, 1920, 2560, 768 and 390 pixels.

## Stage 1 delivered

| Browser route | Shell view and retained behavior |
| --- | --- |
| `/overview` | Workspace metrics, active incident breakdown and links to the queue, deliveries and activity. `/` opens Overview. |
| `/overview/activity` | Existing activity timeline with event-type filter and cursor paging. |
| `/action-center` | Existing ranked queue with integration filter, links to recorded incidents and the read-only notification policy reference. |
| `/deliveries` | Existing delivery results and integration controls. Integration, status, sort and page are in the URL. |
| `/deliveries/:deliveryId` and `/deliveries/:deliveryId/incidents/:incidentId` | URL-backed delivery dialog with current file, timeline, incidents, notifications, contextual Copilot and supported actions. The incident link focuses the record when it is present in the loaded history. |
| `/reconciliation` and `/reconciliation/runs/:runId` | Existing run history, category results, sources, Copilot and rerun. A run link accepts `?exception=:index` to scope the Copilot when opened. |
| `/copilot` | Standalone question workspace and provider label. Incident and reconciliation investigations also remain available in context. |
| `/monitoring` | Browser connection explanation and a pointer to deployment telemetry. Configurable links and detailed telemetry are deferred. |
| `/administration` | Existing account and policy tools for Admin. Lower roles receive a permission state on direct access. |

The shell uses the browser History API and the existing nginx SPA fallback. It adds no router dependency or new server contracts. A desktop sidebar, a compact tablet rail and a keyboard-operable mobile menu share the same navigation. The session gate wraps the workspace and keeps the current URL when a session expires. One existing SSE stream drives the live indicator and refresh behavior.

Stage 1 established route and focus behavior with the original delivery dialog and operator queue. Stage 2 added the shift briefing, and Stage 3 introduced the dedicated delivery evidence page. URL-backed reconciliation list filters and predecessor comparison remain later work. Existing server authorization and eligibility rules remain authoritative.

The Playwright shell suite covers desktop links and history, deep-link reloads, role guards, session expiry and mobile keyboard navigation. The existing dashboard regression suite follows the new routes. Set `OPSBRIDGE_SCREENSHOTS_DIR` when running Playwright to capture deterministic desktop and mobile examples from the synthetic fixture.

To open the redesigned shell with real synthetic data, run the portfolio launcher from the repository root in PowerShell. This example uses alternate loopback ports so it can coexist with a demo on the defaults.

```powershell
.\.venv\Scripts\python.exe scripts/run_portfolio.py --port 18481 --mailpit-port 18425 --grafana-port 18400
```

Open [the local workspace](http://127.0.0.1:18481/overview), sign in as `demo-admin` using the temporary password entered at the masked launcher prompt, and keep that terminal open. Start on Overview, then use Action Center for incident triage, Deliveries for file details, Reconciliation for comparisons, and AI Copilot for simulated investigations.

## Current implementation and proposed boundaries

| Existing source | Capability to retain | Proposed placement |
| --- | --- | --- |
| `frontend/src/main.tsx` and `styles.css` | KPI calculations, integration/status filters, stable ordering, bounded attention preview, file inspection, confirmations, incidents, notifications, timeline, activity cursor | App shell and dedicated Overview, Action Center, Deliveries and Activity views |
| `frontend/src/Reconciliation.tsx` | Run history, bounded category results, source pointers, prior-run drilldown and idempotent rerun request | Reconciliation list, run detail, exception focus and comparison views |
| `frontend/src/Copilot.tsx` | Guided questions, scoped investigations, provider badge and cited evidence | Standalone Copilot and reusable contextual investigation view |
| `frontend/src/session.tsx` | Session bootstrap, cookie auth, CSRF, sign-in/out, privilege-sensitive account and policy tools | Session provider, sign-in and Administration |
| `frontend/src/liveUpdates.ts` | One invalidation stream, coalescing, fallback polling and expired-session handling | One mounted workspace refresh coordinator |
| `frontend/nginx.conf.template` | SPA `try_files` fallback and scoped same-origin `/api` proxy | Existing proxy and clean client routes. Keep the allowlist and API rewrites. |

Keep React, TypeScript, Vite, the existing icon and typography dependencies, and the same origin. Introduce one route layer under the app shell. Confirm any new client-router dependency in the implementation review. No backend endpoint, database schema or security changes belong in this plan. Use `/overview`, `/action-center`, `/deliveries`, `/reconciliation`, `/copilot`, `/monitoring` and `/administration` as the navigation contract. Add stable details under `/deliveries/:deliveryId` and `/reconciliation/runs/:runId` plus `/overview/activity`. Encode data filters, page, tabs and selected record IDs in validated route state. Restore relevant list context on Back. Preserve deep links through sign-in only for internal known routes. Link directly to a reconciliation exception or an incident within its delivery where the identifiers are available.

## Existing API and data mapping

The paths below are backend routes. Browser calls use the existing `/api` nginx prefix. `/api/auth/*` and `/api/dashboard/*` are the browser routes used by the design.

| Screen or operation | Existing API | Contract and UI limits |
| --- | --- | --- |
| Overview and integration context | `GET /dashboard/overview` | Global `counts`, `metrics`, `incidents_by_type`, `activity`, `integrations`, `as_of`, and `reprocessing_enabled`. `counts.COMPLETED` is a workspace count, separate from `received`. Activity data is per integration and can lack an arrival or count fields. `/overview` has no time window or integration filter. Full integration or activity data loads only on demand where separate reads are available. |
| Action preview and queue | `GET /dashboard/attention` | `integration_id`, `limit` up to 100, no cursor or offset. Request 41 and order the first 40 into the documented urgency groups while preserving server rank, deadline and stable key within them. Overview previews up to five. `recorded_incident` distinguishes persisted and detected rows. The returned key is an incident ID for recorded rows. Queue results supply delivery status, reason and action, and omit exact incident lifecycle, financial impact, run ID, notifications and aggregate filtered total. |
| Delivery results | `GET /dashboard/deliveries` | Server filters `integration_id`, `status`, sorts `newest`/`deadline`, `offset`, `limit` up to 100; use limit 21 to render 20 and infer next page. Text search is visibly limited to current page. Exact ID lookup uses the detail endpoint. No server text/date/quarantine/incident search or reliable global match total. A scoped queue or detail may supply incident/quarantine indicators. |
| Delivery and evidence | `GET /dashboard/deliveries/{id}`, `GET /dashboard/deliveries/{id}/incidents`, `GET /dashboard/deliveries/{id}/events` | Detail includes the current file only. Incident/history lists use `offset` and limits up to 100; use look-ahead for bounded pages. Incidents are newest first and include severity, lifecycle, acknowledgement permission and audit, linked reconciliation ID, and notification attempts. Events are chronological with an ID tie-breaker. Use approved details already returned, including retained file ID for conflicts and processing attempts. A targeted incident may require more than one page; offer Load more without unbounded queries, and explain when the target is outside the loaded window. |
| Existing delivery actions | `POST /dashboard/incidents/{id}/acknowledge`, `POST /dashboard/deliveries/{id}/reprocess` | Acknowledge an open persisted incident; optional `comment` max 500. Reprocess with `{file_id, attempt_series, confirmed: true}` and current server eligibility. Confirm first, show queued after `202`, refresh on `409`, and retain authoritative history. No offline or automatic write replay. |
| Recent changes and activity history | `GET /dashboard/activity` | `integration_id`, `delivery_id`, `event_type`, `limit` and paired `before_at`/`before_id` cursor. Use returned next cursor pair and stable IDs. Overview requests limit five; the activity subview owns filters and Load more. The feed is derived and may lag. |
| Reconciliation history | `GET /dashboard/reconciliation` | `limit` max 50, `offset` max 10,000, `has_more`, and `rerun_enabled`. No server-side search/filter or run-level material flag on list. Group counts can be computed from returned `counts`; absent report means results unavailable. |
| Reconciliation run and comparison | `GET /dashboard/reconciliation/runs/{id}` | Optional single `category`; `limit` max 50 and `offset` max 40,000. Use separate category views and stable group indices. Source A/B metadata includes current delivery status and pinned file identifiers. A previous run is fetched separately from `parent_id`, once per comparison, with a small result page and summary counts. There is no difference ranking API, combined exceptions-only result query, row-level materiality, raw source record or cross-run group pairing. |
| Reconciliation writes | `POST /dashboard/reconciliation/runs/{id}/rerun`, `POST /dashboard/reconciliation/definitions` | Rerun is Operator/Admin, terminal run, explicit `confirmed: true`, `request_id` UUID kept across uncertain submission retries, and `202` returns new `run_id`. Admin definition creation, including `supersedes_run_id`, exists via API and is documented. Creating a new definition UI or corrected-source upload workflow is outside the redesign scope. |
| Copilot | `GET /dashboard/copilot/status`, `POST /dashboard/copilot/investigate` | Use either a valid question, a scoped incident ID, or run ID with optional exception index, following request exclusivity. Questions max 320 chars; before-acknowledgement text is used only with a valid incident ID. Render summary refs, observations, hypotheses, evidence and gaps without reinterpretation; expose truncated state and safe errors. Context navigation never submits the POST automatically. |
| Session and Administration | `POST /auth/login`, `GET /auth/session`, `POST /auth/logout`; `GET/POST /auth/operators`, `PATCH /auth/operators/{id}`; `GET/PUT /dashboard/notification-policies` | Continue the same login header, secure session cookie and in-memory CSRF. Accounts endpoint capped at 200 with no pagination. Policy GET is authenticated; policy PUT and account endpoints are Admin. Account role/active changes can revoke sessions. Retain existing Admin controls and server validation. Password reset via PATCH exists at API level, outside the existing browser workflow. |
| Monitoring and live delivery | `GET /dashboard/stream`; independently configured Grafana/Prometheus links | Stream carries invalidation signals and heartbeats, with no list contents. Backend `/health`, `/ready` and `/metrics` are outside the browser proxy. Monitoring uses the existing connection and freshness signals plus configured links; no new live health polling endpoint. Portfolio can expose fewer scrape targets than Compose. |

The general `/integrations` and `/delivery-expectations` APIs exist and support authenticated reads and Admin creation. Direct browser routes for them are outside the current nginx allowlist. Use `/dashboard/overview` and `/dashboard/deliveries` instead of exposing them as part of this redesign.

## RBAC matrix

| Capability | Viewer | Operator | Admin |
| --- | --- | --- | --- |
| Overview, Action Center, delivery and run evidence, activity, technical links | Read | Read | Read |
| Copilot investigations | Read-only analysis | Read-only analysis | Read-only analysis |
| Acknowledge an open recorded incident | No | Yes | Yes |
| Queue eligible file reprocessing or confirmed reconciliation rerun | No | Yes | Yes |
| Open Administration, create accounts, edit roles/activation and notification policies | No | No | Yes |
| Read policy API outside Administration | Yes | Yes | Yes |
| Create integrations, expectations and reconciliation definitions via existing API | No | No | Yes, the corresponding UI is outside this plan |

Honor session role and server capability fields. Backend authorization is authoritative. Do not request Admin data for lower roles. A protected route loads a permission state without mounting Admin queries. Show action-local `403` errors, clear protected state on session expiration, and preserve safe navigation context. The manager persona does not imply administrative privileges. Local Grafana access has its own deployment boundary.

## Reusable components and state

| Component | Responsibilities |
| --- | --- |
| `AppShell`, `Sidebar`, `PageHeader`, `Breadcrumbs`, `ConnectionStatus` | Route hierarchy, role-sensitive navigation, manual refresh, last good data time, focus routing |
| `MetricCard`, `IntegrationHealthCard`, `StatusBadge`, `SeverityBadge`, `SlaIndicator` | Shared states with per-domain labels. Use text, icon and conservative semantic colors. Use the proposed tokens in the [product specification](PRODUCT_UX_SPEC.md#visual-design-and-accessibility). |
| `FilterBar`, `ResultTable`, `ResultCardList`, `PageControls`, `CursorLoadMore` | Bounded API paging, accessible links, loaded-range and search-scope copy, independent responsive layouts |
| `IssuePreview`, `EvidenceTimeline`, `FileSummary`, `IncidentCard`, `NotificationHistory` | Separate delivery, incident and notification state. Show authoritative timeline events, bounded evidence and recorded UTC times. |
| `ActionConfirmation`, `SectionState`, `InlineNotice` | Eligibility and confirm, pending/success/retry, local errors, role and conflict handling, predictable focus. Keep acknowledgement and rerun drafts through refresh. |
| `ReconciliationSourceCard`, `CategoryPicker`, `ExceptionEvidence`, `RunComparison` | Pinned source context, counts first, category results and genuine predecessor comparison. Distinguish amount strings and unavailable values. |
| `InvestigationContext`, `ProviderBadge`, `FactList`, `CitationList`, `EvidenceGaps` | Scoped, read-only Copilot, plain-text evidence, resilient keyboard navigation, stable source IDs and timestamps |

Keep one session-aware SSE stream. Preserve the current coalescing window (two seconds) and 15-second polling fallback, and re-read after reconnect. Refresh mounted views and shared summary data only. Abort stale requests on scope changes and avoid overwriting drafts or selection. Initial loaded data and refreshing are separate states. Fetch preview, summary and recent activity independently so one failure does not blank Overview. Delivery/incident tab change fetches its own data. Use the existing request layer for CSRF and accepted `401` handling. Preserve secure auth and avoid new storage for session secrets, notes, payloads, or prompts.

## Implementation sequence and verification

| Stage | Scope and dependencies | Acceptance gate |
| --- | --- | --- |
| 1. Shell and route map | After UX approval, add app shell, tokens, auth policy and stable routes behind the existing entry. Use existing views while extracting them. | All seven navigation paths work; refresh keeps deep links, Back restores filters, mobile navigation is keyboard accessible and viewers cannot mount Admin queries. |
| 2. Overview and Action Center | Delivered the shift briefing, bounded priority preview, scoped, grouped queue, and projected activity preview. Reused the routed incident detail for investigation and acknowledgement. | Current overdue and recorded breaches differ visibly. Computed issues have no acknowledgement action. Recorded open incidents can be acknowledged with eligible roles and show audit outcome on refresh. |
| 3. Delivery workspace | Depend on shell and shared status/evidence components. Build list/filter/search scope, directly routed detail, file and incident summaries, timeline and reprocess confirmation. | Scope is explicit, unknown arrival/quarantine fields remain unknown, history is preserved across retry/replacement, and reprocessing respects current eligibility and handles `409`. |
| 4. Reconciliation | Reuse routed source details and evidence components. Move history and exception data into workspace, add immediate-predecessor comparison and preserve reruns. | Material flag is run-level; summary counts and decimal amounts remain exact; category paging keeps group citations stable; confirmed reruns create a new ID and retain the previous result. |
| 5. Copilot, Monitoring and Administration | Reuse scoped IDs and role gates. Expose contextual Copilot, optional infrastructure links, and existing account/policy tools outside Overview. | Offline mode is visibly simulated, citations and gaps are navigable, no analysis is launched automatically and no operational mutation originates in Copilot. Admin controls remain permission-safe. Missing monitoring destinations have explicit fallback. |
| 6. Release verification | After all workspaces render, verify navigation, accessibility, demo data and build on existing CI. Update portfolio and dashboard guides to the actual new routes. | Existing unit, PostgreSQL and browser regressions plus the new journey suite pass against disposable synthetic data. Production build and Compose validation pass. Publish no user-facing claims beyond verified scope. |

### Playwright acceptance scenarios

Use mocked HTTP for deterministic edge cases and the existing isolated portfolio regression for real RBAC, PostgreSQL evidence and events. Avoid assertions on mutable timestamps, counts from other scenarios or hardcoded fixture UUIDs. Find examples by synthetic integration, delivery type and run name. Keep the existing no-egress simulated Copilot coverage.

| Scenario | Required assertions |
| --- | --- |
| Missing delivery | Direct link from Overview to Action Center; show computed overdue separately from a persisted incident; `EXPECTED` and recorded SLA breach can coexist. Simulate or seed a late arrival, then assert the missing incident resolves while the recorded breach remains. |
| Source delivery ID conflict | Open the conflict and verify the Critical text/icon, quarantined submission evidence, retained file ID and no privileged action for a computed or Viewer row. Copilot pins the same incident. |
| Critical acknowledgement | Viewer lacks the write control and a direct POST is denied. Operator confirms with an optional note; acknowledgement state/time appears, queued escalation updates, history stays visible. Simulate a concurrent `409` and verify refresh without an automatic second POST. |
| Delivery workbench and safe reprocessing | Verify server filters and bounded paging, page-local search label, exact-ID lookup and deep links. Verify permanent validation failure has no reprocess action. Queue eligible retry from a fixture and keep earlier attempts and replacement history. A refreshed stale target asks for a fresh confirmation. |
| Reconciliation exception | Open the mixed run and default into exception summaries. Scope the amount mismatch category, compare pinned Source A/B references and exact decimal/currency, and pass only the selected index to Copilot. Preserve stable result index after paging. |
| Corrected run and rerun | Open corrected run and the immediate predecessor; verify different identities and preserved results. Check both direct comparison reload and mobile layout. Confirm rerun once; a retry of an uncertain response uses the original request ID. |
| Contextual Copilot | Verify provider banner and supported starters, keyboard citation expansion, gap and truncation displays, and timeout/429 recovery. The context link never sends a request automatically. |
| Responsive, accessibility and live states | At 320 px and desktop, verify no horizontal body overflow, usable links and visible focus. Check drawer close and focus return, session expiration, one stream, fallback polling, reconnect catch-up, and manual refresh without losing filters, scroll or drafts. Simulate a partial data error and verify independent recovery. |
| Admin and Monitoring | Confirm account and policy management is absent on lower roles, privileged deep links are safely denied, and writes keep audit behavior. Verify Monitoring shows configured links or a clear unavailable state, and does not equate connection to uptime. |

Manually verify keyboard-only navigation, text and non-text contrast, 200% zoom, reduced motion, screen-reader page titles, status names and confirmation focus. Automated browser coverage is necessary for regression, with additional manual accessibility review before releasing the implementation.

## Risks, boundaries and dependencies

| Risk or decision | Design response |
| --- | --- |
| Attention is a bounded ranked slice with incomplete row status | Make the limit visible, apply integration filtering server-side and present row detail before mutation. Complete incident search, ranking by business impact, assignments and manual resolution require new contracts and approval. |
| Search, SLA windows and quarantine inventory exceed available data | Use page-local search, exact ID lookup, snapshot SLA metrics and evidence-driven quarantine badges. Future global search, date windows, advanced exports and quarantine inventory are separately scoped product work. |
| A projection or live stream can be delayed | Keep authoritative delivery history distinct from the Activity Feed. Show freshness separately from broker, integration or service health. |
| Reconciliation cannot compare raw records across versions | Fetch only immediate predecessor aggregates and stable record links. Materiality and differing pins provide investigation context without claiming row alignment. |
| Portal links vary with demo versus Compose ports | Keep infrastructure links optional and deployment-controlled. Validate allowed HTTP(S) destinations and provide documentation fallback. No new browser API route to internal metrics. |
| Routing and accessibility changes can disrupt current workflows | Incremental route extraction, desktop/mobile and keyboard gates per stage, preserve role guards and confirmations, and retain a simple front-end rollback to the prior entry when validating the candidate build. |
| Large lists and multiple background requests | Avoid per-row status joins in the browser, never prefetch every page, keep the reconciliation page limit and independently report unavailable panels. |

Phase 1 verification is a contract and documentation review. The build, browser scenarios and visual validation above are implementation gates. No application test execution is required to validate this documentation-only change.
