# OpsBridge Integration Operations Command Center

**Status:** Original design specification. The [implementation plan](FRONTEND_REDESIGN_PLAN.md) records what shipped and where the implementation differs.

## Product intent

The **Integration Operations Analyst or Operator** starts a shift by finding the next issue to investigate, checks the evidence, and sees which actions are available. The **Integration Operations Manager** starts with workspace health, overdue deliveries and SLA context before drilling into a problem. These personas describe work patterns. The authenticated Viewer, Operator and Admin roles determine access.

Before the redesign, the React screen placed KPI tiles, attention items, delivery results, reconciliation, activity, Copilot and administration in one document. A delivery opened in a modal and a run link scrolled to a section. The specification proposed stable workspace routes with room for evidence and history. The [portfolio demo](PORTFOLIO_DEMO.md) shows the delivered experience, and the [architecture](architecture.md) describes the underlying workflows.

## Navigation and page hierarchy

| Sidebar label | Proposed route | Purpose and first content | Primary action |
| --- | --- | --- | --- |
| Overview | `/overview` | Shift briefing with integration signals, exception previews and SLA context | Open Action Center |
| Action Center | `/action-center` | Prioritized queue of recorded incidents and detected problems | Open the selected issue and review available actions |
| Deliveries | `/deliveries` | Delivery search, filters and results | Open a delivery |
| Reconciliation | `/reconciliation` | Run history with execution state and exception counts | Open a run and inspect exceptions |
| AI Copilot | `/copilot` | Guided operational questions and read-only evidence | Ask a supported question or investigate a referenced record |
| Monitoring | `/monitoring` | App connection status and access to technical telemetry | Open configured Grafana or Prometheus views |
| Administration | `/administration` | Operator accounts and notification policies | Manage accounts or review and save policy changes |

After sign-in, `/` lands on Overview. Signed-in users retain the same left navigation on detail routes. Use **Deliveries** for `/deliveries/:deliveryId` and **Reconciliation** for `/reconciliation/runs/:runId`. Delivery links can carry an incident ID and a selected tab. Run links can carry an exception index. **Back to queue** restores the prior queue scope and scroll when navigation originated there. Browser Back and Forward work independently. Copyable links carry record IDs and bounded filters. Keep form text, credentials and Copilot questions out of URLs. Admin navigation is visible only to Admins.

The shell displays a page title, optional breadcrumb, sign-in identity and role, refresh control and freshness status. Filters live beside the data they affect. The palette identifies the active product area; status symbols and text identify business state. Global Recent activity belongs to Overview as a preview and a deeper subview, `/overview/activity`, with filters and cursor pagination. Delivery details contain their own authoritative timeline.

## Overview

1. **Now** gives four clear signals above the fold: active incidents, currently overdue deliveries, on-time receipts and completed deliveries. Counts are workspace-wide snapshots. A detail line gives the scope and as-of time when available. Selecting an item goes to the correct destination. Use the Action Center queue preview for current overdue or high-priority work and the status-filtered delivery list for completed deliveries.
2. **Critical and high priority** previews up to five relevant items from the bounded Action Center feed. Show integration, issue, deadline or incident age, and one **Review** link. Say **No critical or high-priority items in this view** when the bounded sample is empty. Keep **View Action Center** visible. Recorded incident totals come from Overview. Avoid presenting the sample as a workspace count.
3. **Integration health** groups configured status, last recorded arrival, active incidents, overdue and failed delivery counts. Use a small preview with **View integration deliveries**. If information is missing, show **No arrival recorded** or **Data unavailable** as appropriate. Configured activity and last arrival describe business operation; reachability belongs to Monitoring. Health uses visible operational signals, with no composite score.
4. **SLA performance** shows on-time receipts as `on_time / received` and a separate **Recorded SLA breaches** count. Label the metric **Across recorded arrivals**, with the numerator and denominator available. Show **Not available** when there is no arrival denominator. Received includes identifiable quarantined arrivals. Historical breaches survive late arrival and resolution. The API supplies neither an SLA time series nor a windowed KPI selector.
5. **Recent changes** shows up to five derived Activity Feed entries with UTC timestamps and destination links. Label it **Recent activity** and expose **View activity**. The projection can lag; the delivery timeline supplies the authoritative incident context. Overview displays previews and summaries only.

## Action Center

Use a two-column workspace at desktop width. The queue lists issues and the selected row opens a preview with evidence and a direct route to the record. On compact screens open the detail route. Use integration filtering and preserve the server ordering by issue rank, deadline and stable key. Offer **All issues**, **Recorded incidents** and **Detected problems**, plus issue type or severity filtering in the loaded slice. Expose the bounded scope in the filter and empty-state copy. A delivery can have several distinct queue items.

| Row field | Display rule |
| --- | --- |
| What happened | Short label from the issue code, recorded reason or safe fallback, delivery name and business date |
| Affected integration | Integration name, with the delivery as a separate link |
| Severity and impact | Recorded severity comes from the incident type mapping; confirm on detail. For detected items use **Attention** and a factual explanation such as **No recorded arrival by deadline**. Display available operational impact, with financial exposure unavailable. |
| Current state | Show **Active incident** for a persisted queue entry until detail confirms **Open** or **Acknowledged**. Show **Detected problem** for a computed row. Show delivery status in its own badge. |
| Time sensitivity | Show relative age with the corresponding UTC deadline, opened time or failure time. Escalation timing is shown only when an actual scheduled job supplies it. |
| Next step | Use the existing recommended action. Translate a recommendation requiring external contact or file inspection into guidance, with actual buttons reserved for available application actions. |

Default action is **Review issue**. An Operator or Admin with the loaded incident in `OPEN` state can choose **Acknowledge incident**, enter an optional comment up to 500 characters, and confirm. Re-read the incident, notification schedule and affected preview on success. Acknowledgement records the operator and time and can cancel queued escalation; an already claimed SMTP attempt may finish. The incident can remain in the active queue as **Acknowledged**. A `409` means state changed; show updated detail and preserve the draft long enough for the operator to read it, without replaying the submission. A computed row cannot be acknowledged. Depending on evidence, link **Open delivery**, **Open reconciliation run**, **Investigate with Copilot** or an eligible **Reprocess file** confirmation. Assignment, manual resolution, escalation on demand, and contacting vendors from OpsBridge are future capabilities.

## Deliveries

**List.** Use a searchable results list with server filters for integration and status and the existing **Newest first** and **Earliest deadline** sorts. The UI search is labeled **Search this page** and matches delivery name/type, business date or current filename among loaded rows. Offer exact record lookup by delivery ID using the detail endpoint. Display integration, delivery and business date together, then delivery status, deadline/SLA signals and current file summary. Show incident or quarantine indicators where the page has evidence, such as a selected Action Center row or loaded detail. Avoid rendering an absent indicator as confirmation that a delivery has no incident. Page through bounded results; search never fetches every page.

**Detail.** Use a full-size page with a breadcrumb, current business status and explicit actions. Order the top context as **Delivery**, **Arrival and SLA**, and **Current file**. Provide **Summary**, **Incidents**, and **Timeline** tabs with the targeted record highlighted when possible. Summary shows deadline, breach timestamp, current file identity, size, receipt, safe errors, hash and replacement pointer. A missing current file alone does not prove no arrival. Incident detail distinguishes lifecycle and notification delivery, including scheduled escalation, acknowledgement attribution and send attempts. Timeline uses chronological delivery events and groups processing events under their recorded series and attempt numbers. Appended history remains visible on recovery and replacement. Provide **Load more events** and a visible loaded-range indicator.

| Delivery state | What it communicates |
| --- | --- |
| `EXPECTED` | An expectation exists; review arrival and SLA evidence separately. |
| `RECEIVED` | The current file was accepted for processing. Earlier attempts remain in history. |
| `VALIDATION_FAILED` | This file permanently failed validation. Use recorded errors to request a corrected upload. |
| `PROCESSING` | Processing is active for the current file. Show the series and attempt when present. |
| `PROCESSING_FAILED` | A processing attempt failed. Show the next eligible retry when supplied. A retryable exhausted series may expose manual reprocessing. |
| `COMPLETED` | Processing completed. Recorded SLA breaches and prior failures remain visible. |

Visualize **Expected delivery → File arrival / validation → Processing → Recorded outcome** as stages supported by the evidence, with branches for validation failure, retry, and replacement. Upcoming and unknown stages are distinct. Use the backend status badge and timestamps as source data; stage styling cannot drive state changes. A source ID conflict in the delivery events gives **Submission quarantined** and the retained file reference. The retained file remains distinct from the rejected submission. The dashboard endpoints provide no complete quarantine inventory or payload download. A focused Copilot response may surface a finalized integrity claim as cited evidence.

**Reprocess file** appears for Operator/Admin when the current file is flagged `can_reprocess`. Explain that this queues a new series for the same file and preserves prior attempts. Confirm against the visible file ID and attempt series. On `202`, show **Reprocessing queued** and wait for server state before showing processing or completion. On `409`, refresh eligibility and ask for fresh confirmation. Permanent validation failures use corrective upload guidance.

## Reconciliation

**Run history** shows newest runs with execution state, source-linked context when loaded, exception group count, creation time and lineage marker. Use stable pagination. Distinguish **Waiting for sources**, **Running**, **Retry scheduled**, **Completed** and **Failed** from result categories. A completed comparison may have material differences. Keep waiting or failed execution distinct from a completed run with zero exceptions.

**Run detail** shows run name, UTC completion time, attempt count, matching key, tolerance, run-level material flag and linked incident. Put exception category counts ahead of successful match counts. Start in the exception summary, with **Amount mismatch** as the first drill-down when a material run has that category. Offer explicit category links for **Amount mismatch**, **Missing in source A**, **Missing in source B**, **Duplicate**, **Ambiguous**, and **Invalid or unsupported**. Each category opens its own bounded server page. Exact and within-tolerance groups remain available under **Matched results** with separate category selection. Preserve the group index across filtering and pagination. Detail includes Source A/B integration, delivery, business date, current delivery state clearly labeled, and the pinned file IDs used in the run.

**Inspect group** opens the stored exception category, currency, A/B row counts, and reported signed difference labeled **Source A − Source B**. Keep original decimal strings and group IDs. A missing value displays **Unavailable** rather than a zero amount. The current contract supplies summaries and pointers; there is no raw source-row drill-through or per-group materiality flag. The run-level material flag may elevate investigation of that run once loaded. Never add across currencies or imply a risk amount. Provide a visible **Investigate exception with Copilot** action using the run and group index.

**Compare with previous run** reads the selected run and its immediate `parent_id` as two separate records, side by side on wide screens and stacked on mobile. Compare execution states, source pairs and pinned files, category totals, material indicators and timestamps. Label **Selected run** and **Previous run**; display absent or unavailable history explicitly. Comparison uses aggregates and evidence links; it offers no row alignment or proof of causal correction. **Queue reconciliation rerun** requires a confirmed terminal run and Operator/Admin permission. Tell the operator it queues a new run from the existing definition and retains the original. Reuse the same request ID if the response was lost. A corrected source setup is a distinct Admin definition workflow; a rerun alone does not take an uploaded correction or update the definition.

## AI Copilot

Offer **Investigate with Copilot** from a recorded incident, a run or an exception. Link to a scoped view with its record heading and a **Back to incident/run** route. Offer **Review before acknowledgement** only for a recorded acknowledgement. The dedicated page presents supported question starters and the bounded question input. Make provider state visible before a request and on the result. Use **Simulated analysis** for the mock provider. Never auto-run an investigation on navigation, refresh or reconnect.

Results read in this order: **Summary**, **Recorded facts** with clickable citations, **Hypotheses**, **Recommended investigation steps**, and **Evidence gaps**. Cite evidence kind, UTC time and stable record ID. Citations link to a supported app destination where context identifies one; otherwise focus and expand the citation without implying there is a record page. Show omitted evidence with the response truncation flag. Treat text and labels as untrusted display data. A recommendation can link to an ordinary view, with any write performed later by a separately authorized operator. API errors include unsupported question, rate limit, timeout, unavailable provider and missing evidence. Keep the user's draft on retryable errors and show returned gaps distinctly from an unavailable response.

## Monitoring and Administration

**Monitoring** explains workspace connection status, last successful refresh and how to open deployment-configured Grafana and Prometheus targets. Mark external links and their scope. State unavailable or unconfigured destinations without hardcoding a local loopback port that differs between deployments. Link to documentation when a URL is absent. Do not infer service availability from `Live`, expose raw backend endpoints through the UI, or imply every worker exporter is present in the portfolio setup. Grafana owns operational metric trends; the product overview owns business attention.

**Administration** uses **Operator accounts** and **Notification policies** tabs. Present account state, role and confirmation for changes that revoke sessions. Preserve the self-demotion and self-deactivation protections. New passwords are masked, kept out of links and cleared after submission. Provide a structured policy summary with controlled editing of the current rule format and a preview before saving. Explain that changes affect future jobs and do not edit existing schedules. Keep account and policy drafts independent of live workspace refresh. The existing policy GET can be read by an authenticated Viewer, while edits require Admin. This navigation decision restricts the Administration UX, without changing the API contract. Publish no account deletion, new incident workflow or audit browser in this redesign.

## Visual design and accessibility

| Token group | Proposed use |
| --- | --- |
| Core surfaces | Canvas `#F4F7FA`, surface `#FFFFFF`, sidebar `#14233A`, sidebar text `#EDF2FA`, primary ink `#15243A`, subdued text `#47566B`, borders `#D9E2EC` |
| Area accents | Overview `#1F5AA8`, Action Center `#92400E`, Deliveries `#0F6B62`, Reconciliation `#563D9F`, AI Copilot `#345CB0`, Monitoring `#316179`, Administration `#46546D`. Use on active navigation, links or tinted heading details. |
| Status tokens | Critical `#9F2035` on `#FFF1F3` with alert icon; high/deadline `#854300` on `#FFF3DD` with clock or warning; informational `#1C4E91` on `#EAF2FF`; complete/healthy `#136149` on `#E5F5ED`; neutral `#46546D` on `#EEF2F7`. Validate actual combinations in implementation. |
| Type | Keep DM Sans Variable and system fallback. Main 28/36 px, section 20/28, body 14/22, supporting 12/18; use tabular numerals for metrics and amounts, and monospace for IDs/hashes. A single visible `h1` per screen. |
| Spacing and form | Scale 4, 8, 12, 16, 24, 32, 48 px. Use 24 px for grouped panels, 12–16 px for spacing within them, and 8 px control radius. Limit visual nesting and reserve shadows for overlays. |
| Layout and breakpoints | Wide at 1200 px and above: 232 px sidebar, 12-column main grid, 24 px gutters, optional 360–420 px detail preview. From 768–1199 px: collapsible navigation rail, eight-column grid, full details when space is limited. Below 768 px: menu drawer and four-column layout, stacking cards and full-page details. |

Use one prominent text action per section. A navigable table row has a clearly named link and visible hover and keyboard focus on the link; secondary buttons have separate hit targets. Buttons perform actions and links change location. Use icon plus text for status and severity. Use a persistent active marker and `aria-current` in navigation. A sticky header and drawer must leave focused controls visible; modal confirmations trap and restore focus. Provide a skip link, useful landmarks, semantic tables, named controls, live announcements for meaningful state transitions, and no announcement for every background poll. Keep text wrap and scoped table scrolling at 320 px, and design interactive targets for 44 px where practical. Meet WCAG 2.2 AA contrast and keyboard expectations; verify focus, reflow, zoom and reduced-motion behavior against the rendered implementation. [W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/)

Use same-shape skeletons on first load, no invented zeros, and local **Try again** actions when one surface fails. Keep last good data with a **May be out of date** message during refresh failures. Distinguish **No records yet**, **No results in this view**, and **Service unavailable**. Preserve filters and selected record on reconnect. Disabled controls explain unmet prerequisites; role-restricted writes are hidden in ordinary navigation and denied if attempted via a direct link or stale screen.

## Operator journeys

| Journey | Starting point and screens | Decisions and available actions | Expected outcome and gap |
| --- | --- | --- | --- |
| Investigate missing delivery | Overview **Currently overdue** → Action Center → a **Settlement report** delivery → Timeline and Incidents | Check the UTC deadline and arrival evidence, then distinguish computed overdue from a recorded missing-file incident. Open Copilot or acknowledge an open persisted incident if authorized. Verify later arrival in history. | Understand whether a delivery arrived and whether an SLA breach remains recorded. Vendor contact and manual closure are outside the application. |
| Investigate a source ID conflict | Action Center **Source delivery ID conflict** → affected **Payment register** delivery → conflict incident and event | Confirm the conflict event, quarantine evidence and retained file ID. Escalate externally or acknowledge the incident. Open the Copilot with that incident pinned. | Identify the retained file and clearly separate the rejected upload. Inspecting or downloading quarantined bytes is unavailable. |
| Review and acknowledge a critical incident | Overview priority preview → Action Center → recorded `CRITICAL` source ID conflict → Incidents | Confirm current `OPEN` state and Operator/Admin access. Read notification jobs, optionally add an acknowledgement comment, then confirm. If `409`, inspect the refreshed state. | Audit shows who acknowledged and when. Queued escalation can be cancelled and the incident stays active where applicable. Assignment and manual resolution are unavailable. |
| Investigate a reconciliation exception | Reconciliation → **Fund vs Custodian · exception review** → **Amount mismatch** → Inspect group | Read source A/B, pinned files, category, row counts and signed currency difference. Open source delivery or analyze the exact group with Copilot. | Capture a stable run/group evidence reference and an investigation step. Source-row drill-through is unavailable. |
| Compare a corrected run | Reconciliation → **Fund vs Custodian · corrected exports** → **Compare with previous run** | Check distinct pins, execution and category totals; open original and corrected evidence separately. Queue a rerun only when the operator wants another execution of the same definition. | Show corrected results and preserve the original. Row-to-row comparison across versions requires a new contract. |

Scenario names are based on the synthetic dashboard and reconciliation fixtures. For acknowledgement and SMTP demonstrations use **Demo → Notify browser**; its missing-file incident has High severity, while a source ID conflict supplies the Critical example. [Portfolio demo](PORTFOLIO_DEMO.md)
