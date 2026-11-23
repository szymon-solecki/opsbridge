"""Launch the Copilot evaluation with a fresh local database and synthetic data."""

from contextlib import ExitStack
import subprocess
import sys

from performance_lab import wait_database
from verify_intake_demo import BACKEND, ROOT, docker, ensure_local_engine, stop_demo_container


def main(args):
    ensure_local_engine()
    with ExitStack() as cleanup:
        # PostgreSQL listens on namespace loopback only. Offline workers have no egress.
        network = "bridge" if "--live" in args and "--help" not in args else "none"
        pg = docker("run", "-d", "--rm", "--pull=never", "--network", network,
                    "-e", "POSTGRES_DB=opsbridge_test", "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
                    "postgres:17", "-c", "listen_addresses=127.0.0.1")
        cleanup.callback(stop_demo_container, pg)
        wait_database(pg)
        isolated = ["--network", f"container:{pg}", "-e", "PYTHON_DOTENV_DISABLED=1",
                    "-e", "OPSBRIDGE_EXPECTED_DATABASE=opsbridge_test",
                    "-e", "DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1/opsbridge_test"]
        docker("run", "--rm", "--pull=never", *isolated,
               "-v", f"{ROOT / 'backend/alembic'}:/app/backend/alembic:ro",
               "-v", f"{ROOT / 'backend/alembic.ini'}:/app/backend/alembic.ini:ro",
               "--entrypoint", "python", BACKEND, "-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head")
        credentials = ["-e", "OPENAI_API_KEY"] if network == "bridge" else []
        command = ["docker", "run", "--rm", "--pull=never", *isolated, *credentials,
                   "-v", f"{ROOT / 'scripts/copilot_eval'}:/app/copilot_eval:ro", "--entrypoint", "python", BACKEND,
                   "-m", "copilot_eval.runner", *args]
        return subprocess.run(command, check=False, timeout=240).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise SystemExit("The disposable evaluation infrastructure failed.") from None
