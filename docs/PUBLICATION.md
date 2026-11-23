# Portfolio publication checklist

This is a source-only candidate for the synthetic, loopback portfolio demo. The [publication manifest](PUBLICATION_MANIFEST.txt) is the complete allowlist for the prepared snapshot. Every path outside it is excluded. The only environment example in the candidate is the placeholder-only `.env.example`.

## Candidate contents

- Application source, schema migrations, tests, build definitions, sample policies, demo and verification tooling, and project documentation.
- Three reviewed screenshots from disposable browser runs under `docs/portfolio/`. They show fictional integrations, scenario-specific counts and amounts, and the synthetic `demo-admin` identity. The copies are rendered PNGs without browser chrome or textual image metadata.
- A read-only GitHub Actions workflow for source inventory, dependency audits, builds and isolated tests. Integration tests verify a fresh `opsbridge_test` before migration. The offline Copilot evaluator and the live browser application use the simulated provider. The workflow does not deploy or publish artifacts.

Exclude existing Git metadata and history, runtime environments and credentials, SSH and SFTP account material, databases and dumps, logs, local volumes, installed packages, caches, browser traces, generated reports and all screenshots outside the three approved paths. Keep those materials local. Docker state is outside the source snapshot.

## Release gates

1. Confirm rights to publish the original code, documentation and screenshots. The portfolio owner approved [MIT](../LICENSE) for the original OpsBridge code, copyright 2026 Szymon Solecki. The manifest includes the license. [OSI MIT license](https://opensource.org/license/mit)
2. Verify the manifest and export only its paths into a **new** source directory. Use a GitHub noreply commit address if the public history should omit a personal address. Keep the existing repository, refs and object store local. Avoid copying `.git`, mirroring refs or transferring branches from the current repository. [GitHub commit email settings](https://docs.github.com/en/account-and-profile/how-tos/email-preferences/setting-your-commit-email-address)
3. Inspect the exported snapshot and run its workflow in a new **private** GitHub repository after Git authorization. Do a fresh-clone startup with `py -3.14 scripts/run_portfolio.py` on Windows. Confirm the documented loopback URLs, sign-in procedure, simulated Copilot and screenshot rendering. Review all CI jobs.
4. Enable available GitHub secret scanning and push protection. Change visibility only after the inventory, license, CI and demo checks are approved. The source demo does not certify production readiness.

From the current repository root, the following command checks the candidate without Git writes. In the clean publication checkout, omit `--include-candidates` to check the committed snapshot.

```powershell
.\.venv\Scripts\python.exe scripts/check_release_tree.py --include-candidates --manifest
```

After the release gates are approved, copy the verified candidate to a new sibling directory. This exports only the manifest paths and fails if the destination already exists.

```powershell
$ErrorActionPreference = 'Stop'
.\.venv\Scripts\python.exe scripts/check_release_tree.py --include-candidates --manifest
if ($LASTEXITCODE -ne 0) { throw 'Publication inventory check failed.' }
$candidate = (New-Item -ItemType Directory -Path '..\OpsBridge-public').FullName
foreach ($path in Get-Content -LiteralPath 'docs/PUBLICATION_MANIFEST.txt') {
    $target = Join-Path $candidate $path
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Copy-Item -LiteralPath $path -Destination $target
}
```

## Third-party software

The source snapshot references third-party dependencies and base images. It excludes `node_modules`, installed Python dependencies and Docker image archives. Dependencies retain their upstream licenses. Direct frontend packages declare MIT (React and React DOM), ISC (Lucide) and the SIL Open Font License 1.1 (DM Sans). Separate infrastructure and library terms include RabbitMQ MPL 2.0, Grafana AGPL 3.0, and Psycopg LGPL 3.0. Review and preserve applicable notices before distributing built assets or images. [RabbitMQ](https://www.rabbitmq.com/) · [Grafana licensing](https://github.com/grafana/grafana/blob/main/LICENSING.md) · [Psycopg license](https://github.com/psycopg/psycopg/blob/master/LICENSE.txt)
