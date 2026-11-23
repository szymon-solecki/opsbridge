"""Run an isolated SFTP, worker, broker and browser performance workload."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import re
from secrets import token_urlsafe
from threading import Event
from time import perf_counter, sleep

from verify_intake_demo import BACKEND, MOUNT, ROOT, SFTP, docker, ensure_local_engine, stop_demo_container


BROWSER = """
const {chromium} = require('playwright');
(async () => {
  const browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH});
  try {
    const login = await browser.newPage();
    await login.goto('http://127.0.0.1:8080');
    await login.getByLabel('Username', {exact:true}).fill('demo-admin');
    await login.getByLabel('Password', {exact:true}).fill(process.env.OPSBRIDGE_DEMO_PASSWORD);
    await login.getByRole('button', {name:'Sign in',exact:true}).click();
    await login.getByRole('button', {name:'Sign out'}).waitFor();
    const state = await login.context().storageState();
    const elapsed = [];
    for (let i=0; i<7; ++i) {
      const context = await browser.newContext({storageState:state, viewport:{width:1440,height:900}});
      const page = await context.newPage();
      const start = performance.now();
      await page.goto('http://127.0.0.1:8080/deliveries');
      await page.getByRole('region', {name:'Delivery results'}).waitFor();
      elapsed.push(performance.now()-start);
      await context.close();
    }
    console.log(JSON.stringify(elapsed));
  } finally {
    await browser.close();
  }
})().catch(() => { console.error('Chromium performance measurement failed'); process.exitCode=1; });
"""


def wait_database(container):
    for _ in range(45):
        import subprocess
        try:
            actual = docker("exec", container, "psql", "-h", "127.0.0.1", "-U", "postgres", "-d",
                            "opsbridge_test", "-Atc", "SELECT current_database()")
        except subprocess.CalledProcessError:
            sleep(1)
            continue
        if actual == "opsbridge_test":
            return
        raise RuntimeError("Unexpected database")
    raise RuntimeError("Disposable PostgreSQL did not start")


def memory_mib(text):
    amount, unit = next((text[:-len(unit)], factor) for unit, factor in (
        ("GiB", 1024), ("MiB", 1), ("KiB", 1/1024), ("B", 1/2**20),
    ) if text.endswith(unit))
    return float(amount) * unit


def collect_resources(containers, stop, output):
    import subprocess

    while not stop.is_set():
        try:
            raw = docker("stats", "--no-stream", "--format", "{{.ID}}|{{.CPUPerc}}|{{.MemUsage}}", *containers)
        except subprocess.CalledProcessError:
            if stop.is_set():
                return
            raise
        groups = {}
        for line in raw.splitlines():
            identifier, cpu, memory = line.split("|")
            key = next(value for name, value in containers.items() if name.startswith(identifier))
            row = groups.setdefault(key, [0.0, 0.0])
            row[0] += float(cpu.removesuffix("%"))
            row[1] += memory_mib(memory.split(" / ")[0].strip())
        output.append(groups)
        stop.wait(1)


def results_resources(samples):
    from performance_workload import distribution

    return {
        role: {"cpu_percent": distribution([sample[role][0] for sample in samples if role in sample]),
               "memory_mib": distribution([sample[role][1] for sample in samples if role in sample])}
        for role in sorted({role for sample in samples for role in sample})
    }


def event_worker_timings(metrics):
    totals = {}
    for part, operation, value in re.findall(
        r'^opsbridge_worker_duration_seconds_(count|sum)\{operation="([a-z_]+)"\} ([0-9.eE+\-]+)$',
        metrics, re.MULTILINE,
    ):
        totals.setdefault(operation, {})[part] = float(value)
    return {key: {"calls": int(row["count"]), "total_s": round(row["sum"], 3),
                  "mean_ms": round(row["sum"] * 1000 / row["count"], 3)}
            for key, row in totals.items() if row["count"]}


def last_event_log(logs, code, beginning):
    timestamps = []
    for line in logs.splitlines():
        if line.startswith('{'):
            record = json.loads(line)
            if record.get("code") == code:
                timestamps.append(datetime.fromisoformat(record["timestamp"]))
    if not timestamps:
        raise AssertionError(f"Missing worker completion log for {code}")
    return round((max(timestamps) - beginning).total_seconds(), 3)


def run(args):
    from performance_workload import distribution
    import subprocess

    ensure_local_engine()
    with ExitStack() as cleanup:
        containers = {}
        def launch(role, *flags, runtime_env=None):
            key = docker("run", "-d", "--rm", "--pull=never", *flags, runtime_env=runtime_env)
            cleanup.callback(stop_demo_container, key)
            containers[key] = role
            return key

        pg = launch("postgres", "--network=none", "-e", "POSTGRES_DB=opsbridge_test",
                    "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:17", "-c", "listen_addresses=127.0.0.1")
        wait_database(pg)
        namespace = ["--network", f"container:{pg}"]
        worker_env = [*namespace, "-e", "PYTHON_DOTENV_DISABLED=1", "-e",
                      "DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1/opsbridge_test",
                      "-e", "OPSBRIDGE_EXPECTED_DATABASE=opsbridge_test"]
        python = ["--entrypoint", "python", args.backend_image]
        migrations = ["-v", f"{ROOT / 'backend/alembic'}:/app/backend/alembic:ro",
                      "-v", f"{ROOT / 'backend/alembic.ini'}:/app/backend/alembic.ini:ro"]
        docker("run", "--rm", "--pull=never", *worker_env, *migrations, *python, "-m", "alembic",
               "-c", "backend/alembic.ini", "upgrade", "head")
        env = {"OPSBRIDGE_DEMO_PASSWORD": token_urlsafe(24), "OPSBRIDGE_VIEWER_PASSWORD": token_urlsafe(24)}
        docker("run", "--rm", "-i", *worker_env, *python, "-m", "backend.app.provision_operator",
               "demo-admin", "--password-stdin", stdin=env["OPSBRIDGE_DEMO_PASSWORD"] + "\n")
        amqp = "amqp://127.0.0.1:5672/%2F"
        launch("rabbitmq", *namespace, "-e", "RABBITMQ_NODENAME=rabbit@localhost", "--mount",
               f"type=bind,source={ROOT / 'infra/monitoring/rabbitmq-plugins'},target=/etc/rabbitmq/enabled_plugins,readonly",
               "rabbitmq:4.2-management")
        launch("mailpit", *namespace, "axllent/mailpit:v1.27")
        api = launch("api", *worker_env, "-e", "OPSBRIDGE_DEMO_PASSWORD", "-e", "OPSBRIDGE_VIEWER_PASSWORD",
                     "-e", "RABBITMQ_URL=" + amqp, "-e", "OPSBRIDGE_COPILOT_PROVIDER=mock",
                     "--user", "9001:9001", "--group-add", "1999", "-v", MOUNT,
                     "--mount", f"type=bind,source={ROOT / 'scripts/demo_http.py'},target=/app/demo_http.py,readonly",
                     *python, "-m", "uvicorn", "backend.app.main:app", runtime_env=env)
        launch("nginx", *namespace, "-e", "API_UPSTREAM=127.0.0.1:8000", "opsbridge-dashboard:demo")
        for _ in range(45):
            try:
                docker("exec", api, "python", "-c", "import httpx; "
                       "httpx.get('http://127.0.0.1:8000/ready',timeout=8).raise_for_status()")
                break
            except subprocess.CalledProcessError:
                sleep(1)
        else:
            raise AssertionError("The disposable stack did not become ready")
        workload = (ROOT / "scripts/performance_workload.py").read_text(encoding="utf-8")
        base = ["--deliveries", str(args.deliveries), "--operators", str(args.operators),
                "--records", str(args.records)]
        fixture = json.loads(docker("exec", "-i", api, "python", "-", "seed", *base, stdin=workload,
                                    timeout=900))
        docker("exec", "-u", "0", api, "install", "-d", "-m", "0700", "-o", "9001", f"{MOUNT}/_opsbridge")
        for source in fixture["sources"]:
            for directory, mode in (("staging", "2700"), ("incoming", "2770")):
                docker("exec", "-u", "0", api, "install", "-d", "-m", mode, "-o", "65534", "-g", "1999",
                       f"{MOUNT}/{source}/{directory}")
        readiness = ["--volumes-from", api, "--user", "9001:9001", "--group-add", "1999"]
        for _ in range(args.workers):
            launch("intake", *worker_env, *readiness, *python, "-m", "backend.app.intake.worker")
            launch("processing", *worker_env, *readiness, *python, "-m", "backend.app.operations_worker", "processing")
        for _ in range(args.dispatchers):
            launch("notification", *worker_env, "-e", "OPSBRIDGE_MAILPIT_HOST=127.0.0.1",
                   *python, "-m", "backend.app.notification_worker")
        launch("reconciliation", *worker_env, *readiness, *python, "-m", "backend.app.operations_worker", "reconciliation")
        event_workers = {}
        for mode, port, code in (("publish", 9101, "OUTBOX_PUBLISHED"), ("consume", 9102, "PUBLICATION_PROJECTED")):
            container = launch(mode, *worker_env, "-e", "RABBITMQ_URL=" + amqp, "-e", f"OPSBRIDGE_METRICS_PORT={port}",
                               "--mount", f"type=bind,source={ROOT / 'scripts/performance_event_probe.py'},"
                               "target=/app/performance_event_probe.py,readonly",
                               *python, "/app/performance_event_probe.py", mode)
            event_workers[mode] = (container, port, code)

        def upload(side):
            docker("run", "--rm", "--pull=never", "-i", "--network=none", "--volumes-from", api,
                   "-e", f"DEMO_HOME={MOUNT}/{fixture['sources'][side]}", "--user", "65534:65534", "--entrypoint",
                   "python3", SFTP, "-", "vendor", "--side", str(side), *base, stdin=workload, timeout=args.timeout)

        resources = []
        stop = Event()
        with ThreadPoolExecutor(max_workers=4) as pool:
            sampler = pool.submit(collect_resources, containers, stop, resources)
            beginning = datetime.now(timezone.utc)
            try:
                monitor = pool.submit(docker, "exec", "-i", api, "python", "-", "observe", *base,
                                      "--start", beginning.isoformat(), "--fixture", json.dumps(fixture),
                                      "--timeout", str(args.timeout), stdin=workload, timeout=args.timeout + 60)
                for future in (pool.submit(upload, 0), pool.submit(upload, 1)):
                    future.result()
                vendors_returned = datetime.now(timezone.utc)
                performance = json.loads(monitor.result())
                observer_returned = datetime.now(timezone.utc)
            finally:
                stop.set()
            sampler.result()

        performance["timeline_s"].update(
            vendors_returned=round((vendors_returned - beginning).total_seconds(), 3),
            observer_returned=round((observer_returned - beginning).total_seconds(), 3),
        )
        performance["event_worker_timings"] = {}
        for mode, (container, port, code) in event_workers.items():
            metrics = docker("exec", api, "python", "-c", "import urllib.request; "
                             f"print(urllib.request.urlopen('http://127.0.0.1:{port}/metrics', timeout=5).read().decode())")
            performance["event_worker_timings"][mode] = event_worker_timings(metrics)
            # The worker's logging handler writes to stderr through Docker.
            logs = subprocess.run(["docker", "logs", container], encoding="utf-8", errors="replace",
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True, timeout=120).stdout
            performance["timeline_s"][f"{mode}_last_completed_log"] = last_event_log(
                logs, code, beginning)

        post_observation = perf_counter()
        browser = json.loads(docker("run", "--rm", "--pull=never", "-i", *namespace,
                                  "-e", "OPSBRIDGE_DEMO_PASSWORD", "--entrypoint", "node",
                                  "opsbridge-dashboard:browser", "-", stdin=BROWSER, runtime_env=env))
        performance["browser_initial_ms"] = distribution(browser)
        performance["resources"] = results_resources(resources)
        performance["resource_samples"] = len(resources)
        performance["replicas"] = {"intake": args.workers, "processing": args.workers, "notification": args.dispatchers}
        performance["environment"] = {
            "docker": docker("info", "--format", "{{.ServerVersion}} | {{.OperatingSystem}} | {{.NCPU}} CPUs | {{.MemTotal}} bytes"),
            "postgres": docker("exec", pg, "psql", "-h", "127.0.0.1", "-U", "postgres", "-d", "opsbridge_test",
                               "-Atc", "SHOW server_version"),
            "images": {name: docker("image", "inspect", name, "--format", "{{.Id}}") for name in (
                args.backend_image, SFTP, "opsbridge-dashboard:demo", "opsbridge-dashboard:browser", "rabbitmq:4.2-management",
                "axllent/mailpit:v1.27", "postgres:17")},
        }
        # Run in a separate process after sampling, without the workload's worker loops.
        shutdown_started = perf_counter()
        for key, role in containers.items():
            if role not in {"api", "postgres"}:
                stop_demo_container(key)
        performance["post_observation_s"] = {"browser_and_metadata": round(shutdown_started - post_observation, 3),
                                             "idle_container_shutdown": round(perf_counter() - shutdown_started, 3)}
        performance["matching"] = json.loads(docker("exec", "-i", api, "python", "-", "matching", stdin=workload))
        return performance


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--deliveries", type=int, default=100, choices=(100, 1000, 10000))
    parser.add_argument("--records", type=int, default=20000, choices=(1000, 10000, 20000))
    parser.add_argument("--operators", type=int, choices=range(1, 13), default=4)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--dispatchers", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--backend-image", default=BACKEND, help="Local image tag for a controlled comparison")
    args = parser.parse_args()
    if not 60 <= args.timeout <= 3600:
        parser.error("--timeout must be from 60 to 3600 seconds")
    print(json.dumps(run(args), indent=2), flush=True)
