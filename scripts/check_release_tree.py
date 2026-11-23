"""Check publication paths and permitted source without opening local secret files."""

import argparse
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/PUBLICATION_MANIFEST.txt"
SCREENSHOTS = {
    Path("docs/portfolio/copilot-incident-simulated.png"),
    Path("docs/portfolio/overview.png"),
    Path("docs/portfolio/delivery-incident.png"),
    Path("docs/portfolio/reconciliation-comparison.png"),
    Path("docs/portfolio/reconciliation-exceptions.png"),
}
SCOPES = (
    "backend",
    "frontend",
    "infra",
    "docs",
    "scripts",
    ".github",
    "README.md",
    "compose.yaml",
    ".env.example",
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "pytest.ini",
    "LICENSE",
)
TEXT = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".json",
    ".yml",
    ".yaml",
    ".md",
    ".txt",
    ".sh",
    ".ini",
    ".css",
    ".html",
    ".template",
}
BLOCKED_DIRS = {
    ".secrets",
    "secrets",
    "data",
    "uploads",
    ".venv",
    "node_modules",
    "test-results",
    "playwright-report",
    ".ssh",
    ".aws",
    ".git",
    "coverage",
    "artifacts",
}
BLOCKED_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".ppk",
    ".jks",
    ".keystore",
    ".dump",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".sql",
    ".csv",
    ".bak",
    ".log",
    ".tmp",
    ".trace",
    ".har",
    ".pub",
    ".zip",
    ".tar",
}
PATTERNS = {
    "private key marker": re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    "provider token shape": re.compile(
        r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{28,}|gh[pousr]_[A-Za-z0-9]{30,})\b"
    ),
    "cloud access key shape": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
}


def protected(relative):
    name = relative.name.casefold()
    return (
        any(part.casefold() in BLOCKED_DIRS for part in relative.parts)
        or relative.suffix.casefold() in BLOCKED_SUFFIXES
        or name.startswith(("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", "ssh_host_"))
        or name
        in {
            ".codex_access_probe.tmp",
            "accounts.json",
            "sftp-accounts.json",
            ".netrc",
            ".npmrc",
            ".pypirc",
            "credentials.json",
            "authorized_keys",
        }
        or name.startswith("known_hosts")
        or (name.startswith(".env") and name != ".env.example")
        or name.endswith(
            (
                ".sql.gz",
                ".sql.zst",
                ".pgdump",
                ".dump.gz",
                ".tar.gz",
                ".db-wal",
                ".db-shm",
            )
        )
    )


def git_paths(*args):
    output = subprocess.check_output(["git", "ls-files", "-z", *args], cwd=ROOT)
    return {
        Path(name)
        for name in output.decode("utf-8", errors="surrogateescape").split("\0")
        if name
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-candidates",
        action="store_true",
        help="Also check non-ignored untracked files",
    )
    parser.add_argument(
        "--manifest",
        action="store_true",
        help="Require the exact publication file inventory",
    )
    args = parser.parse_args()
    paths = git_paths("--cached")
    if args.include_candidates:
        paths.update(git_paths("--others", "--exclude-standard"))
    findings = []
    if args.manifest:
        expected = MANIFEST.read_text(encoding="utf-8").splitlines()
        manifest_paths = {Path(name) for name in expected}
        if sorted(set(expected)) != expected or any(
            p.is_absolute() or ".." in p.parts or p.as_posix() == "." or protected(p)
            for p in manifest_paths
        ):
            findings.append("Invalid or protected publication manifest entry")
        for relative in sorted(manifest_paths - paths):
            findings.append(f"Missing publication file: {relative.as_posix()}")
        findings.extend(
            "Unexpected publication path outside the manifest"
            for _ in paths - manifest_paths
        )
    scanned = 0
    for relative in sorted(paths):
        if protected(relative) or (
            relative.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
            and relative not in SCREENSHOTS
        ):
            findings.append(
                "Protected or generated publication path (contents were not opened)"
            )
            continue
        if relative.parts[0] not in SCOPES:
            findings.append("Publication path outside approved source scopes")
            continue
        source = ROOT / relative
        if source.is_symlink() or not source.resolve().is_relative_to(ROOT):
            findings.append(f"{relative}: unsafe source link")
            continue
        if not source.is_file():
            findings.append(
                f"{relative.as_posix()}: publication file absent from working tree"
            )
            continue
        if relative in SCREENSHOTS or relative.name == ".gitkeep":
            continue
        if relative.suffix not in TEXT and relative.name not in {
            ".env.example",
            ".gitattributes",
            ".gitignore",
            ".dockerignore",
            "Dockerfile",
            "LICENSE",
            "sshd_config",
            "rabbitmq-plugins",
        }:
            findings.append(f"{relative.as_posix()}: unsupported publication file type")
            continue
        scanned += 1
        content = source.read_text(encoding="utf-8-sig")
        for reason, pattern in PATTERNS.items():
            for match in pattern.finditer(content):
                # Report only location and rule, never the contents or matching value.
                line = content.count("\n", 0, match.start()) + 1
                findings.append(f"{relative}:{line}: {reason}")
    print(
        f"Checked {len(paths)} paths and scanned {scanned} permitted sources. Findings: {len(findings)}."
    )
    for finding in findings:
        print(finding)
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())
