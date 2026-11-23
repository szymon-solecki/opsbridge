# Local development and verification

Use Python 3.14 for the backend and Node 22 for local frontend commands. Docker with Compose v2 and Linux containers is the reference runtime. From the repository root, run `py -3.14 scripts/run_portfolio.py` for the complete synthetic demo. It handles database creation, migrations, demo accounts and seeding. See the [portfolio guide](PORTFOLIO_DEMO.md) for the walkthrough and reset.

## Run verification in disposable containers

Run these PowerShell commands from the repository root. The application driver verifies a fresh `opsbridge_test` and builds the data through the application. It uses the simulated Copilot, local SMTP and no production credentials.

```powershell
docker build -t opsbridge-backend:intake-check backend
docker build -t opsbridge-sftp:intake-check infra/sftp
docker build -t opsbridge-dashboard:demo frontend
docker build --target browser-tests -t opsbridge-dashboard:browser frontend
docker pull postgres:17
docker pull rabbitmq:4.2-management
docker pull axllent/mailpit:v1.27
docker run --rm --network none opsbridge-dashboard:browser npm test -- --workers=1
py -3.14 scripts/verify_intake_demo.py --tests --dashboard-test --operations --events --notifications --reconciliation --faults
py -3.14 scripts/evaluate_copilot.py
```

Quiet Compose validation can run with synthetic process variables in a separate terminal.

```powershell
$env:COMPOSE_DISABLE_ENV_FILE = '1'
$env:POSTGRES_DB = 'opsbridge_test'
$env:POSTGRES_USER = 'synthetic'
$env:POSTGRES_PASSWORD = 'synthetic-compose-only'
docker compose --profile '*' config -q
```

For credentialed SFTP or a longer-lived isolated Compose session, start from the sample configuration and follow the [SFTP demo](INTAKE_DEMO.md) and [dashboard guide](DASHBOARD_DEMO.md). The former documents approved database and volume isolation. The latter covers RabbitMQ, Mailpit, Grafana and audited operator provisioning. Keep local configuration and key files outside version control.

## Host development

Create a fresh virtual environment when switching Python versions. Backend `requirements.txt` uses the pinned Linux-tested `constraints.txt`. The constraints govern application and test dependencies while permitting platform-specific packages where the dependency metadata requires them. Update constraints deliberately and rebuild before accepting a dependency update.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
$env:PYTHON_DOTENV_DISABLED = '1'
$env:OPSBRIDGE_RUN_INTEGRATION = '0'
$env:DATABASE_URL = ''
.\.venv\Scripts\python.exe -m pytest backend/tests -m 'not integration' -q
```

Use `npm ci`, `npm run typecheck` and `npm run build` from `frontend`. Use the container browser runner for reproducible Chromium setup. CI uses Ruff syntax and undefined-name checks across the Python code, with default lint and formatting enforcement on the new release tools. Expensive [load tests](PERFORMANCE_REPORT.md) stay outside the pull-request workflow.
