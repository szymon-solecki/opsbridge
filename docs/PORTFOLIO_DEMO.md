# OpsBridge portfolio demo

Allow about 13 minutes after startup. The initial image build and download take extra time. Use Docker with Linux containers and Python 3.14, then run the following from the repository root in PowerShell.

```powershell
py -3.14 scripts/run_portfolio.py
```

Choose a temporary password of at least 12 characters at the masked prompt and sign in as `demo-admin`. The launcher provisions synthetic accounts, initializes and migrates a fresh `opsbridge_test`, and submits the synthetic workload through the OpenSSH SFTP subsystem. It uses the subsystem in direct mode, without a network SSH handshake. It uses the simulated Copilot provider and does not load `.env`. Keep the launcher terminal open while presenting.

| Destination | Default URL |
| --- | --- |
| Operations Center | [http://127.0.0.1:8080/overview](http://127.0.0.1:8080/overview) |
| Mailpit | [http://127.0.0.1:8025](http://127.0.0.1:8025) |
| Grafana | [http://127.0.0.1:3000](http://127.0.0.1:3000) |

These listeners are loopback-only. RabbitMQ and Prometheus run inside the disposable stack. The launcher does not publish their web interfaces. If the dashboard signs out, sign in again with the password you set at startup.

| Time | Walkthrough | What to point out |
| --- | --- | --- |
| 0–2 min | Start at **Overview**. Read the operational snapshot and follow **Requires attention** to **Action Center**. Start with a critical **Source delivery ID conflict**, such as **Northstar Treasury → Payment register**. | Introduce the fictional entities. The incoming conflict was quarantined, and the delivery retains its prior current file. A completed delivery can still have an open incident. |
| 2–4 min | Open **Deliveries → Northstar Treasury**. Review **Bank statement** for successful processing, **Settlement report** for a missing delivery, and **Fx confirmations** for a CSV failure. If asked about corrections, open **Custody positions** and show both submissions in the timeline. | A recorded SLA breach is separate from delivery status. A failed file remains in history when a corrected upload succeeds. A repeat **Demo → Daily** upload left one persisted file and one receipt event. |
| 4–6 min | Open **Demo → Notify browser**, expand its incident and notification history, and compare the opening notification in Mailpit. Acknowledge the incident with a synthetic comment. | Acknowledgement records the operator and time. The incident remains acknowledged until its business resolution. A pending escalation can be cancelled, and an already dispatched email remains in history. |
| 6–9 min | Open **Reconciliation → Fund vs Custodian · exception review**. Inspect **Amount mismatch**, select the group and show the signed Source A minus Source B difference in USD. Follow **View source A delivery** and return with Back. Open **Fund vs Custodian · corrected exports** from run history and inspect **Immediate predecessor comparison**. | The first run completed with two matched pairs and five exception groups, including a `-10.000000 USD` difference. Corrected exports show zero exception groups. The comparison is aggregate evidence. The pinned file versions remain associated with their own runs. |
| 9–11 min | In the original run's exception group, choose **Investigate exception with Copilot** and **Analyze exception**. Open a citation. Alternatively, open **AI Copilot** and select **Which deliveries breached their SLA?** | The analysis is simulated and read-only. The cited IDs and timestamps correspond to real records in the synthetic database. Hypotheses are investigation leads. |
| 11–13 min | Open **Monitoring**. Compare the workspace's observed connection and API read with **Grafana → OpsBridge Operations**. Open **Administration → Notification policies**, review recipients and scope, and preview the editor without saving. | Grafana shows live API and RabbitMQ metrics. The default portfolio monitoring scope does not include every worker. Admin controls are separate from incident actions. The [Compose monitoring profile](DASHBOARD_DEMO.md#live-operations-and-monitoring) exposes additional worker panels. |

The manual file reprocessing button requires an eligible exhausted retry series. This is exercised by the isolated fault regression rather than seeded as an ordinary portfolio delivery. The existing reconciliation rerun can be demonstrated separately with an explicit confirmation.

## Repeat the dataset and take screenshots

Press Enter in the launcher terminal to clean up its containers and anonymous data volumes. Start again with `py -3.14 scripts/run_portfolio.py --reuse-images`. This creates a new `opsbridge_test` and repeats the same business scenarios. IDs, timestamps and passwords differ per run. Acknowledgements and other changes made during the previous demo disappear with its database. Leave other Docker projects and volumes alone.

Use `--port`, `--mailpit-port` and `--grafana-port` to choose distinct loopback ports when defaults are occupied. The URLs above assume default ports.

For reproducible screenshots, open the browser at 1440×900 and 100% zoom. Capture the Operations Center with **All integrations** selected, the reconciliation mismatch after opening its detail, and the incident investigation with the **Simulated analysis** badge and citations visible. Take the screenshots after signing in. Crop local browser tabs and exclude password prompts or non-demo information. Keep generated screenshots outside version control until reviewed.
