"""Build and start the isolated OpsBridge portfolio demonstration."""

import argparse
import subprocess
import sys

from verify_intake_demo import BACKEND, ROOT, SFTP, ensure_local_engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reuse-images",
        action="store_true",
        help="Use previously built and pulled images",
    )
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--mailpit-port", type=int, default=8025)
    parser.add_argument("--grafana-port", type=int, default=3000)
    args = parser.parse_args()
    ports = (args.port, args.mailpit_port, args.grafana_port)
    if any(not 1 <= port <= 65535 for port in ports) or len(set(ports)) != len(ports):
        parser.error("Use three distinct ports between 1 and 65535.")
    ensure_local_engine()
    if not args.reuse_images:
        for image in (
            "postgres:17",
            "rabbitmq:4.2-management",
            "axllent/mailpit:v1.27",
            "prom/prometheus:v3.5.0",
            "grafana/grafana:12.4.15",
        ):
            subprocess.run(["docker", "pull", image], cwd=ROOT, check=True)
        for tag, folder in (
            (BACKEND, "backend"),
            (SFTP, "infra/sftp"),
            ("opsbridge-dashboard:demo", "frontend"),
        ):
            subprocess.run(["docker", "build", "-t", tag, folder], cwd=ROOT, check=True)
    command = [
        sys.executable,
        "scripts/verify_intake_demo.py",
        "--show-dashboard",
        "--operations",
        "--events",
        "--notifications",
        "--reconciliation",
        "--monitoring",
        "--port",
        str(args.port),
        "--mailpit-port",
        str(args.mailpit_port),
        "--grafana-port",
        str(args.grafana_port),
    ]
    subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"Portfolio command failed with exit code {exc.returncode}."
        ) from None
