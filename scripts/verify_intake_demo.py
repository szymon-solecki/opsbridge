"""Run an isolated Linux SFTP subsystem -> worker -> HTTP smoke test with cached images."""

import argparse
from getpass import getpass
from secrets import token_urlsafe
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import webbrowser


ROOT = Path(__file__).resolve().parents[1]
BACKEND = "opsbridge-backend:intake-check"
SFTP = "opsbridge-sftp:intake-check"
MOUNT = "/srv/opsbridge-sftp"


def docker(*args, stdin=None, runtime_env=None, timeout=120):
    env = None if runtime_env is None else os.environ | runtime_env
    return subprocess.run(["docker", *args], input=stdin, encoding="utf-8", errors="replace", capture_output=True,
                          check=True, timeout=timeout, env=env).stdout.strip()


def stop_demo_container(container):
    try:
        docker("stop", container)
    except subprocess.CalledProcessError as exc:
        if "No such container" not in (exc.stderr or ""):
            raise


def ensure_local_engine():
    context = os.environ.get("DOCKER_CONTEXT")
    endpoint = None if context else os.environ.get("DOCKER_HOST")
    if not endpoint:
        endpoint = docker("context", "inspect", "--format", "{{.Endpoints.docker.Host}}", *([context] if context else []))
    if not endpoint.startswith(("npipe:////./pipe/", "unix:///")):
        raise SystemExit("A local Docker socket or named pipe is required.")


def seed_dashboard(api):
    from uuid import UUID

    scenario = (ROOT / "scripts/dashboard_scenarios.py").read_text(encoding="utf-8")
    integrations = [str(UUID(i)) for i in json.loads(docker("exec", "-i", api, "python", "-", stdin=scenario))]
    for integration in integrations:
        home = f"{MOUNT}/{integration}"
        for directory, mode in (("staging", "2700"), ("incoming", "2770")):
            docker("exec", "-u", "0", api, "install", "-d", "-m", mode, "-o", "65534", "-g", "1999",
                   f"{home}/{directory}")
    for wave in range(2):
        for index, integration in enumerate(integrations):
            docker("run", "--rm", "-i", "--network=none", "--volumes-from", api,
                   "-e", f"DEMO_HOME={MOUNT}/{integration}", "--user", "65534:65534", "--entrypoint",
                   "python3", SFTP, "-", "--wave", str(wave), "--vendor", str(index), stdin=scenario)
        docker("exec", api, "python", "-m", "backend.app.intake.worker", "--once")
    print(docker("exec", "-i", api, "python", "-", stdin="""
import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from backend.app.database import get_engine
from backend.app.models import File, IntakeClaim, Incident
from demo_http import client
api = client()
metrics = api.get('/dashboard/overview').json()['metrics']
assert metrics == dict(total=37, received=29, validation_failed=4, failed=4,
                       pending=4, overdue=4, breached=0, on_time=24), metrics
with Session(get_engine()) as session:
    assert session.scalar(select(func.count()).select_from(File)) == 33
    assert session.scalar(select(func.count()).select_from(IntakeClaim)) == 42
    assert session.scalar(select(func.count()).select_from(Incident).where(
        Incident.incident_type == "SOURCE_DELIVERY_ID_CONFLICT")) == 4
print(metrics)
"""), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tests", action="store_true", help="Also run pytest in the isolated Linux environment")
    parser.add_argument("--dashboard-test", action="store_true", help="Check the dashboard in Chromium")
    parser.add_argument("--dashboard-screenshots", action="store_true",
                        help="Capture the operational screens from the isolated Chromium run")
    parser.add_argument("--delivery-screenshots", action="store_true",
                        help="Capture the delivery workspace from the isolated Chromium run")
    parser.add_argument("--reconciliation-screenshots", action="store_true",
                        help="Capture the reconciliation workspace from the isolated Chromium run")
    parser.add_argument("--experience-screenshots", action="store_true",
                        help="Capture Copilot, Monitoring and Administration from the isolated Chromium run")
    parser.add_argument("--operations", action="store_true", help="Run the SLA and processing workers before presentation")
    parser.add_argument("--reconciliation", action="store_true", help="Exercise the two-source reconciliation workbench")
    parser.add_argument("--faults", action="store_true", help="Exercise additional disposable failure scenarios")
    parser.add_argument("--events", action="store_true", help="Verify RabbitMQ failure paths and project the activity feed")
    parser.add_argument("--notifications", action="store_true", help="Send synthetic incident notifications to Mailpit")
    parser.add_argument("--mailpit-port", type=int, default=8025, help="Loopback Mailpit port for the presentation")
    parser.add_argument("--show-dashboard", action="store_true", help="Open the populated dashboard on port 8080")
    parser.add_argument("--monitoring", action="store_true", help="Start the local portfolio telemetry dashboard")
    parser.add_argument("--grafana-port", type=int, default=3000, help="Loopback Grafana port for the presentation")
    parser.add_argument("--port", type=int, default=8080, help="Loopback port for --show-dashboard")
    args = parser.parse_args()
    if args.dashboard_screenshots and not (args.dashboard_test and args.operations and args.events):
        parser.error("--dashboard-screenshots requires --dashboard-test, --operations and --events")
    if args.delivery_screenshots and not (args.dashboard_test and args.operations):
        parser.error("--delivery-screenshots requires --dashboard-test and --operations")
    if args.reconciliation_screenshots and not (args.dashboard_test and args.reconciliation):
        parser.error("--reconciliation-screenshots requires --dashboard-test and --reconciliation")
    if args.experience_screenshots and not (args.dashboard_test and args.operations and args.events):
        parser.error("--experience-screenshots requires --dashboard-test, --operations and --events")
    if args.faults and not (args.operations and args.events and args.notifications and args.dashboard_test and not args.show_dashboard):
        parser.error("--faults requires the isolated dashboard, operations, events and notifications test options")
    if args.reconciliation and not (args.operations and (args.dashboard_test or args.show_dashboard)):
        parser.error("--reconciliation requires --operations and --dashboard-test or --show-dashboard")
    if args.monitoring and not (args.show_dashboard and args.events):
        parser.error("--monitoring requires --show-dashboard and --events")
    if any(not 1 <= port <= 65535 for port in (args.port, args.mailpit_port, args.grafana_port)):
        parser.error("Ports must be between 1 and 65535")
    ensure_local_engine()
    with ExitStack() as cleanup:
        # A networkless, freshly initialized cluster has no published port or persistent named volume.
        network_args = ["--network=none"]
        if args.show_dashboard:
            # Docker Desktop publishes ports from a bridge. PostgreSQL listens
            # only on loopback within its namespace, and only nginx is published.
            from uuid import uuid4
            network = docker("network", "create", f"opsbridge-demo-{uuid4().hex}")
            cleanup.callback(docker, "network", "rm", network)
            network_args = ["--network", network, "-p", f"127.0.0.1:{args.port}:8080"]
            if args.notifications:
                network_args.extend(["-p", f"127.0.0.1:{args.mailpit_port}:8025"])
            if args.monitoring:
                network_args.extend(["--network-alias", "prometheus"])
        pg = docker("run", "--pull=never", "-d", "--rm", *network_args, "-e",
                    "POSTGRES_HOST_AUTH_METHOD=trust", "-e", "POSTGRES_DB=opsbridge_test",
                    "postgres:17", "-c", "listen_addresses=127.0.0.1")
        cleanup.callback(docker, "stop", pg)
        for _ in range(45):
            try:
                actual = docker("exec", pg, "psql", "-h", "127.0.0.1", "-U", "postgres", "-d",
                                "opsbridge_test", "-Atc", "SELECT current_database()")
            except subprocess.CalledProcessError:
                time.sleep(1)
                continue
            if actual != "opsbridge_test":
                raise RuntimeError("Unexpected database")
            break
        else:
            raise RuntimeError("Test database unavailable")
        local = ["--network", f"container:{pg}", "-e", "PYTHON_DOTENV_DISABLED=1",
                 "-e", "DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1/opsbridge_test",
                 "-e", "OPSBRIDGE_EXPECTED_DATABASE=opsbridge_test"]
        migrations = ["-v", f"{ROOT / 'backend/alembic'}:/app/backend/alembic:ro",
                      "-v", f"{ROOT / 'backend/alembic.ini'}:/app/backend/alembic.ini:ro"]
        docker("run", "--rm", *local, *migrations, "--entrypoint",
               "python", BACKEND, "-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head")
        if args.tests:
            try:
                summary = docker("run", "--rm", *local, *migrations, "-e", "OPSBRIDGE_RUN_INTEGRATION=1",
                                 "-v", f"{ROOT / 'backend/tests'}:/app/backend/tests:ro",
                                 "-v", f"{ROOT / 'pytest.ini'}:/app/pytest.ini:ro", "--entrypoint", "python",
                                 BACKEND, "-m", "pytest", "backend/tests", "-q", "--tb=short", "-p", "no:cacheprovider")
            except subprocess.CalledProcessError as exc:
                print(exc.stdout)
                raise
            print(summary.splitlines()[-1], flush=True)
        demo_password = getpass("Choose a temporary demo-admin password (12+ characters): ") if args.show_dashboard else token_urlsafe(24)
        viewer_password = token_urlsafe(24)
        operator_password = token_urlsafe(24)
        for name, role, password in (
            ("demo-admin", "ADMIN", demo_password), ("demo-viewer", "VIEWER", viewer_password),
            ("demo-operator", "OPERATOR", operator_password),
        ):
            docker("run", "--rm", "-i", *local, "--entrypoint", "python", BACKEND, "-m",
                   "backend.app.provision_operator", name, "--role", role, "--password-stdin", stdin=password + "\n")
        synthetic_credentials = {"OPSBRIDGE_DEMO_PASSWORD": demo_password, "OPSBRIDGE_OPERATOR_PASSWORD": operator_password,
                                 "OPSBRIDGE_VIEWER_PASSWORD": viewer_password}
        api = docker("run", "-d", "--rm", *local, "-e", "OPSBRIDGE_DEMO_PASSWORD",
                     "-e", "OPSBRIDGE_OPERATOR_PASSWORD",
                     "-e", "OPSBRIDGE_COPILOT_PROVIDER=mock",
                     "--mount", f"type=bind,source={ROOT / 'scripts/demo_http.py'},target=/app/demo_http.py,readonly",
                     "-e", f"RABBITMQ_URL={'amqp://127.0.0.1:5672/%2F' if args.events else ''}",
                     "--user", "9001:9001", "--group-add", "1999",
                     "-v", MOUNT, "--entrypoint", "python", BACKEND, "-m", "uvicorn", "backend.app.main:app",
                     runtime_env=synthetic_credentials)
        cleanup.callback(docker, "stop", api)
        created = docker("exec", "-i", api, "python", "-", stdin="""
from demo_http import client
import httpx, time
api = httpx.Client(base_url='http://127.0.0.1:8000')
for _ in range(30):
    try:
        api.get('/health').raise_for_status()
        break
    except httpx.ConnectError:
        time.sleep(0.2)
api = client()
r = api.post('/integrations', json=dict(name='Demo', source_name='synthetic'))
r.raise_for_status()
i = r.json()['id']
r = api.post(f'/integrations/{i}/delivery-expectations', json=dict(delivery_type='DAILY',
    business_date='2026-01-01', expected_pattern='*.csv', deadline_at='2026-01-02T00:00:00Z'))
r.raise_for_status()
print(i)
""")
        from uuid import UUID
        integration = str(UUID(created))
        home = f"{MOUNT}/{integration}"
        docker("exec", "-u", "0", api, "install", "-d", "-m", "0700", "-o", "9001", f"{MOUNT}/_opsbridge")
        for directory, mode in (("staging", "2700"), ("incoming", "2770")):
            docker("exec", "-u", "0", api, "install", "-d", "-m", mode, "-o", "65534", "-g", "1999",
                   f"{home}/{directory}")
        vendor = """import hashlib,json,os,subprocess,tempfile
from pathlib import Path
home=os.environ['DEMO_HOME']
with tempfile.TemporaryDirectory() as folder:
    payload=b'record_id,record_date,amount,currency,reference\\na,2026-01-01,1.00,EUR,test\\n'
    Path(folder,'data.csv').write_bytes(payload)
    Path(folder,'manifest.json').write_text(json.dumps(dict(contract_version=1,business_date='2026-01-01',
        delivery_type='DAILY', source_delivery_id='demo',payload=dict(file_name='data.csv',
        size_bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest()))))
    stage=f'{home}/staging/package'
    batch=f'mkdir {stage}\\nput data.csv {stage}/data.csv\\nput manifest.json {stage}/manifest.json\\nrename {stage} {home}/incoming/package\\n'
    subprocess.run(['sftp','-D','/usr/lib/openssh/sftp-server -u 0007','-b','-','localhost'],
                   cwd=folder,input=batch,text=True,check=True)
"""
        # Direct OpenSSH subsystem mode uses real SFTP requests without needing account maps or keys.
        for _ in range(2):
            docker("run", "--rm", "-i", "--network=none", "--volumes-from", api, "-e", f"DEMO_HOME={home}",
                   "--user", "65534:65534", "--entrypoint", "python3", SFTP, "-", stdin=vendor)
            docker("exec", api, "python", "-m", "backend.app.intake.worker", "--once")
        result = docker("exec", "-i", api, "python", "-", stdin="""
import json
from demo_http import client
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from backend.app.database import get_engine
from backend.app.models import IntakeClaim, File, DeliveryEvent
r = client().get('/delivery-expectations')
r.raise_for_status()
delivery, = r.json()
assert delivery['status'] == 'RECEIVED' and delivery['current_file_id']
with Session(get_engine()) as s:
    assert s.scalar(select(func.count()).select_from(File)) == 1
    assert s.scalar(select(func.count()).select_from(DeliveryEvent).where(DeliveryEvent.event_type=='FileReceived')) == 1
    claims = s.scalars(select(IntakeClaim)).all()
    assert len(claims) == 2
    from backend.app.intake.paths import accepted_package_directory
    for c in claims:
        assert c.status.value == 'FINALIZED' and c.final_location.value == 'ACCEPTED'
        assert (accepted_package_directory(c.integration_id,c.id) / 'data.csv').is_file()
print(json.dumps({'status':delivery['status'],'files':1,'receipt_events':1,'accepted_packages':2}))
""")
        print(json.loads(result))
        if args.dashboard_test or args.show_dashboard:
            seed_dashboard(api)
            if args.operations:
                print(docker("exec", "-i", api, "python", "-", stdin="""
import httpx
import subprocess
import sys
for mode in ('sla', 'processing'):
    command = [sys.executable, '-m', 'backend.app.operations_worker', mode, '--once']
    first = subprocess.Popen(command)
    second = subprocess.run(command)
    assert first.wait(timeout=20) == second.returncode == 0
from demo_http import client
api = client()
summary = api.get('/dashboard/overview').json()
assert summary['metrics']['breached'] == 4
assert summary['counts']['COMPLETED'] == 25
assert summary['incidents_by_type']['MISSING_FILE'] == 4
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from backend.app.database import get_engine
from backend.app.models import DeliveryEvent
with Session(get_engine()) as session:
    for event, expected in [('DeliveryOverdue', 4), ('FileProcessingStarted', 25), ('FileProcessingCompleted', 25)]:
        assert session.scalar(select(func.count()).select_from(DeliveryEvent)
                              .where(DeliveryEvent.event_type == event)) == expected
print('Operations verified: 25 completed files and 4 persisted SLA breaches')
"""), flush=True)
            if args.events:
                scenario = (ROOT / "scripts/event_scenarios.py").read_text(encoding="utf-8")
                print(docker("exec", "-i", api, "python", "-", "outage", stdin=scenario), flush=True)
                docker("exec", api, "python", "-c",
                       "import httpx; r = httpx.get('http://127.0.0.1:8000/ready', timeout=10); "
                       "assert r.status_code == 503 and r.json()['dependencies']['broker'] == 'unavailable'")
                broker_start = time.monotonic()
                rabbit = docker("run", "-d", "--rm", "--pull=never", "--network", f"container:{pg}",
                                "--mount", f"type=bind,source={ROOT / 'infra/monitoring/rabbitmq-plugins'},"
                                "target=/etc/rabbitmq/enabled_plugins,readonly",
                                "-e", "RABBITMQ_NODENAME=rabbit@localhost", "rabbitmq:4.2-management")
                cleanup.callback(stop_demo_container, rabbit)
                docker("exec", "-i", api, "python", "-", stdin="""
import socket
import time
for _ in range(45):
    try:
        with socket.create_connection(('127.0.0.1', 5672), timeout=1):
            break
    except OSError:
        time.sleep(1)
else:
    raise RuntimeError('Disposable RabbitMQ AMQP port did not become ready')
""")
                if args.faults:
                    print(json.dumps({"rabbitmq_start_to_amqp_s": round(time.monotonic() - broker_start, 3)}))
                print(docker("exec", "-i", api, "python", "-", "verify", stdin=scenario), flush=True)
                print(docker("exec", "-i", api, "python", "-", stdin="""
import httpx
import time
from prometheus_client.parser import text_string_to_metric_families

api = httpx.Client(base_url='http://127.0.0.1:8000', timeout=10)
assert api.get('/ready').json()['dependencies'] == {'database': 'ready', 'schema': 'ready', 'broker': 'ready'}
body = api.get('/metrics').text
assert 'opsbridge_database_up 1.0' in body
assert 'opsbridge_intake_finalized_total{location="ACCEPTED"}' in body
assert 'opsbridge_outbox_backlog{state="due"}' in body
for attempt in range(25):
    try:
        response = httpx.get('http://127.0.0.1:15692/metrics/per-object')
        response.raise_for_status()
        break
    except httpx.HTTPError:
        time.sleep(1)
else:
    raise AssertionError('RabbitMQ Prometheus endpoint did not become ready')
metrics = text_string_to_metric_families(response.text)
assert any(sample.labels.get('queue') == 'opsbridge.activity.dead.v1' and
           sample.name == 'rabbitmq_queue_messages_ready'
           for family in metrics for sample in family.samples)
print('Readiness recovered and application and broker metrics were scraped.')
"""), flush=True)
                exporter_script = """
import httpx
import time

for attempt in range(30):
    try:
        metrics = httpx.get('http://127.0.0.1:9100/metrics', timeout=2).text
        if 'opsbridge_worker_ready{worker="outbox-publisher"} 1.0' in metrics:
            break
    except httpx.HTTPError:
        pass
    time.sleep(0.5)
else:
    raise AssertionError('Publisher metrics did not show readiness')
"""
                for _ in range(2):
                    publisher = docker("run", "-d", "--rm", *local, "-e", "OPSBRIDGE_METRICS_PORT=9100",
                                       "-e", "RABBITMQ_URL=amqp://127.0.0.1:5672/%2F", "--entrypoint",
                                       "python", BACKEND, "-m", "backend.app.event_worker", "publish")
                    try:
                        docker("exec", "-i", api, "python", "-", stdin=exporter_script)
                    finally:
                        stop_demo_container(publisher)
                print("Publisher readiness was scraped before and after a worker restart.", flush=True)
            if args.notifications:
                mailpit = docker("run", "-d", "--rm", "--pull=never", "--network", f"container:{pg}",
                                 "axllent/mailpit:v1.27")
                cleanup.callback(stop_demo_container, mailpit)
                scenario = (ROOT / "scripts/notification_scenarios.py").read_text(encoding="utf-8")
                print(docker("exec", "-i", api, "python", "-", stdin=scenario), flush=True)
            if args.reconciliation:
                scenario = (ROOT / "scripts/reconciliation_scenarios.py").read_text(encoding="utf-8")
                sources = json.loads(docker("exec", "-i", api, "python", "-", stdin=scenario))
                for side, source in enumerate(sources):
                    home = f"{MOUNT}/{UUID(source['id'])}"
                    for directory, mode in (("staging", "2700"), ("incoming", "2770")):
                        docker("exec", "-u", "0", api, "install", "-d", "-m", mode, "-o", "65534", "-g", "1999",
                               f"{home}/{directory}")
                    docker("run", "--rm", "-i", "--network=none", "--volumes-from", api,
                           "-e", f"DEMO_HOME={home}", "--user", "65534:65534", "--entrypoint",
                           "python3", SFTP, "-", "--side", str(side), stdin=scenario)
                docker("exec", api, "python", "-m", "backend.app.intake.worker", "--once")
                print(docker("exec", "-i", "-e", "DEMO_RECONCILIATION_SOURCES=" + json.dumps(sources),
                             "-e", f"DEMO_RECONCILIATION_MAILPIT={int(args.notifications)}",
                             api, "python", "-", "--verify", stdin=scenario), flush=True)
                if args.show_dashboard:
                    worker = docker("run", "-d", "--rm", *local, "--volumes-from", f"{api}:ro", "--entrypoint",
                                    "python", BACKEND, "-m", "backend.app.operations_worker", "reconciliation")
                    cleanup.callback(stop_demo_container, worker)
            if args.faults:
                from reliability_scenarios import db_outage

                fault_scenario = (ROOT / "scripts/reliability_scenarios.py").read_text(encoding="utf-8")
                print(json.dumps(db_outage(pg, api, docker)), flush=True)
                fault_integration = str(UUID(docker("exec", "-i", api, "python", "-", "seed", "-", "integration",
                                                    stdin=fault_scenario)))
                fault_home = f"{MOUNT}/{fault_integration}"
                for directory, mode in (("staging", "2700"), ("incoming", "2770")):
                    docker("exec", "-u", "0", api, "install", "-d", "-m", mode, "-o", "65534", "-g", "1999",
                           f"{fault_home}/{directory}")
                processing_ids = {}
                for delivery_type in ("FAULT_PROCESSING", "FAULT_REPROCESS"):
                    processing_ids[delivery_type] = docker("exec", "-i", api, "python", "-", "seed", fault_integration,
                                                          delivery_type, stdin=fault_scenario)
                    docker("run", "--rm", "-i", "--network=none", "--volumes-from", api,
                           "--user", "65534:65534", "--entrypoint", "python3", SFTP, "-", "upload", fault_home,
                           delivery_type, stdin=fault_scenario)
                docker("exec", api, "python", "-m", "backend.app.intake.worker", "--once")
                print(docker("exec", "-i", api, "python", "-", "processing", processing_ids["FAULT_PROCESSING"],
                             stdin=fault_scenario), flush=True)
                reprocessing_id = processing_ids["FAULT_REPROCESS"]
                docker("exec", "-i", api, "python", "-", "prepare-reprocessing", reprocessing_id, stdin=fault_scenario)
                notification_id = docker("exec", "-i", api, "python", "-", "seed", fault_integration, "FAULT_NOTIFICATION",
                                         stdin=fault_scenario)
                print(docker("exec", "-i", api, "python", "-", "notification", notification_id,
                             stdin=fault_scenario), flush=True)
            if args.tests:
                scenario = (ROOT / "scripts/security_scenarios.py").read_text(encoding="utf-8")
                print(docker("exec", "-i", api, "python", "-", stdin=scenario), flush=True)
            dashboard_links = ["-e", f"OPSBRIDGE_GRAFANA_URL=http://127.0.0.1:{args.grafana_port}"] if args.monitoring else []
            frontend = docker("run", "-d", "--rm", "--network", f"container:{pg}",
                              "-e", "API_UPSTREAM=127.0.0.1:8000", *dashboard_links, "opsbridge-dashboard:demo")
            cleanup.callback(docker, "stop", frontend)
            docker("exec", frontend, "sh", "-ec",
                   "for i in 1 2 3 4 5; do wget -q -O /dev/null http://127.0.0.1:8080/ && exit 0; sleep 1; done; exit 1")
            if args.dashboard_test:
                screenshots = []
                if args.dashboard_screenshots:
                    target = ROOT / "data" / "frontend-stage2"
                    target.mkdir(parents=True, exist_ok=True)
                    screenshots = ["--mount", f"type=bind,source={target},target=/screenshots", "-e",
                                   "OPSBRIDGE_BRIEFING_SCREENSHOTS=/screenshots"]
                if args.delivery_screenshots:
                    target = ROOT / "data" / "frontend-stage3"
                    target.mkdir(parents=True, exist_ok=True)
                    screenshots += ["--mount", f"type=bind,source={target},target=/delivery-screenshots", "-e",
                                    "OPSBRIDGE_DELIVERY_SCREENSHOTS=/delivery-screenshots"]
                if args.reconciliation_screenshots:
                    target = ROOT / "data" / "frontend-stage4"
                    target.mkdir(parents=True, exist_ok=True)
                    screenshots += ["--mount", f"type=bind,source={target},target=/reconciliation-screenshots", "-e",
                                    "OPSBRIDGE_RECONCILIATION_SCREENSHOTS=/reconciliation-screenshots"]
                if args.experience_screenshots:
                    target = ROOT / "data" / "frontend-stage5"
                    target.mkdir(parents=True, exist_ok=True)
                    screenshots += ["--mount", f"type=bind,source={target},target=/experience-screenshots", "-e",
                                    "OPSBRIDGE_EXPERIENCE_SCREENSHOTS=/experience-screenshots"]
                try:
                    summary = docker("run", "--rm", "--network", f"container:{pg}", "-e",
                                     "DASHBOARD_URL=http://127.0.0.1:8080",
                                     *screenshots,
                                     "-e", "OPSBRIDGE_DEMO_PASSWORD",
                                     "-e", "OPSBRIDGE_VIEWER_PASSWORD",
                                     "-e", "OPSBRIDGE_OPERATOR_PASSWORD", "-e",
                                     f"DEMO_OPERATIONS={int(args.operations)}", "-e", f"DEMO_EVENTS={int(args.events)}",
                                     "-e", f"DEMO_NOTIFICATIONS={int(args.notifications)}",
                                     "-e", f"DEMO_RECONCILIATION={int(args.reconciliation)}",
                                     "-e", f"DEMO_RELIABILITY={int(args.faults)}",
                                     "opsbridge-dashboard:browser",
                                     "npm", "test", "--", "--grep", "real intake", "--workers=3",
                                     runtime_env=synthetic_credentials)
                except subprocess.CalledProcessError as exc:
                    print(exc.stdout)
                    raise
                print(summary)
                if args.faults:
                    print(docker("exec", "-i", api, "python", "-", "verify-reprocessing", reprocessing_id,
                                 stdin=fault_scenario), flush=True)
            if args.show_dashboard:
                if args.events:
                    for mode in ("publish", "consume"):
                        worker = docker("run", "-d", "--rm", *local, "-e", "RABBITMQ_URL=amqp://127.0.0.1:5672/%2F",
                                        "--entrypoint", "python", BACKEND, "-m", "backend.app.event_worker", mode)
                        cleanup.callback(stop_demo_container, worker)
                if args.notifications:
                    dispatcher = docker("run", "-d", "--rm", *local, "-e", "OPSBRIDGE_MAILPIT_HOST=127.0.0.1",
                                        "--entrypoint", "python", BACKEND, "-m", "backend.app.notification_worker")
                    cleanup.callback(stop_demo_container, dispatcher)
                if args.monitoring:
                    start_portfolio_monitoring(cleanup, pg, api, network, args.grafana_port)
                webbrowser.open(f"http://127.0.0.1:{args.port}")
                if args.notifications:
                    webbrowser.open(f"http://127.0.0.1:{args.mailpit_port}")
                if args.monitoring:
                    webbrowser.open(f"http://127.0.0.1:{args.grafana_port}")
                input("Press Enter to stop the demo. ")


def start_portfolio_monitoring(cleanup, pg, api, network, port):
    monitoring = ROOT / "infra/monitoring"
    prometheus = docker("run", "-d", "--rm", "--pull=never", "--network", f"container:{pg}",
                        "-v", f"{monitoring / 'portfolio-prometheus.yml'}:/etc/prometheus/prometheus.yml:ro",
                        "prom/prometheus:v3.5.0")
    cleanup.callback(stop_demo_container, prometheus)
    grafana = docker("run", "-d", "--rm", "--pull=never", "--network", network, "--network-alias", "grafana",
                     "-p", f"127.0.0.1:{port}:3000", "-e", "GF_AUTH_ANONYMOUS_ENABLED=true",
                     "-e", "GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer", "-e", "GF_AUTH_DISABLE_LOGIN_FORM=true",
                     "-e", "GF_AUTH_BASIC_ENABLED=false", "-e", "GF_USERS_ALLOW_SIGN_UP=false",
                     "-e", "GF_ANALYTICS_REPORTING_ENABLED=false", "-e", "GF_ANALYTICS_CHECK_FOR_UPDATES=false",
                     "-e", "GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES=false",
                     "-v", f"{monitoring / 'grafana/provisioning'}:/etc/grafana/provisioning:ro",
                     "-v", f"{monitoring / 'grafana/dashboards'}:/var/lib/grafana/dashboards:ro",
                     "grafana/grafana:12.4.15")
    cleanup.callback(stop_demo_container, grafana)
    docker("exec", "-i", api, "python", "-", stdin="""
import httpx
from time import sleep
from demo_http import client

operator = client()
try:
    operator.get('/dashboard/overview').raise_for_status()
finally:
    operator.close()
for _ in range(30):
    try:
        targets = httpx.get('http://127.0.0.1:9090/api/v1/targets', timeout=2).json()['data']['activeTargets']
        httpx.get('http://grafana:3000/api/health', timeout=2).raise_for_status()
        dashboards = httpx.get('http://grafana:3000/api/search', timeout=2).json()
        query = httpx.get('http://grafana:3000/api/datasources/proxy/uid/opsbridge-prometheus/api/v1/query',
                          params={'query': 'up'}, timeout=2).json()
        series = query.get('data', {}).get('result', [])
        if (len(targets) == 2 and all(target['health'] == 'up' for target in targets)
                and dashboards and len(series) == 2):
            break
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    sleep(1)
else:
    raise RuntimeError('Portfolio monitoring did not become ready')
""")
    print(f"Grafana and both telemetry targets are ready on http://127.0.0.1:{port}.", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.stderr.reconfigure(errors="backslashreplace")
    try:
        main()
    except subprocess.CalledProcessError as exc:
        for line in (exc.stdout or "").splitlines():
            if line.startswith("FAILED ") or line.startswith("ERROR "):
                print(line.partition(" - ")[0])
        raise SystemExit(f"Demo command failed (exit {exc.returncode}): {(exc.stderr or '')[-1200:]}") from None
