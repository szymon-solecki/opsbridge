# OpsBridge SFTP Server Foundation

This image provides a restricted OpenSSH SFTP endpoint for local development. It does not implement package intake, manifest or CSV validation, database persistence, or background processing.

## Runtime mounts

The Compose service mounts the account map and two separate named volumes.

| Container path | Contents | Access |
|---|---|---|
| `/run/config/sftp-accounts.json` | Static account mapping, including authorized public keys | Read-only bind mount from `SFTP_ACCOUNTS_FILE` |
| `/srv/opsbridge-sftp` | Persistent SFTP data root | Named `sftp_data` volume |
| `/var/lib/ssh-host-keys` | Persistent OpenSSH host private/public key pair | Separate named `sftp_host_keys` volume; never mount into the backend |

Authorized public keys are stored in each mapping record's `authorized_key` property. The server generates `/etc/ssh/authorized_keys/<username>` files owned by `root` and the corresponding SFTP user's private primary group, with mode `0640`. This lets the account read its own public-key file while preventing it from modifying the file or reading files owned by other private groups. The authorized-keys directory remains root-owned and mode `0755`; there is no separate authorized-keys mount. The data volume may later be mounted by the backend at `/srv/opsbridge-sftp`. The host-key volume must remain private to the SFTP container. The entrypoint requires both named volumes to be mounted at their expected paths and preflights their ownership and mode. The backend must never receive the host-key mount.

## Account mapping

Provide a non-empty UTF-8 JSON array. Every object must contain exactly these fields:

```json
[
  {
    "integration_id": "7d444840-9dc0-4f7c-a1f2-1b9b1d6c9f20",
    "username": "vendor_demo",
    "uid": 12001,
    "gid": 12001,
    "authorized_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA opsbridge-demo"
  }
]
```

The public key is synthetic and unusable as a credential. Generate a real client key outside the image and repository. Only its public key belongs in this mapping. Keep the client private key with the simulator/operator, never in the server container.

The entrypoint rejects duplicate JSON object keys and validates the complete mapping before it mutates accounts, groups, directories, or keys. Integration IDs must parse as UUIDs; usernames must match `[a-z_][a-z0-9_-]{0,31}`; UIDs and private GIDs must be unique integers from 10000 through 60000; and public keys must use a supported OpenSSH key type and pass `ssh-keygen` parsing. Duplicate IDs, usernames, UIDs, GIDs, or public keys fail startup.

Each mapped account's primary group is named exactly like its username and uses the mapped private GID. The username and group name both support the full 32-character allowlist. Usernames `opsbridge-intake` and `opsbridge-sftp` are reserved.

The SFTP access group is `opsbridge-sftp` with GID `1998`. The shared backend filesystem group is `opsbridge-intake` with GID `1999`. These fixed identities are preflighted; conflicting names or GIDs stop startup. SFTP accounts are supplementary members of `opsbridge-sftp`, never `opsbridge-intake`. The intake group must have no account members and cannot be a primary group.

Before provisioning, the entrypoint checks all mapped UID/GID and username/group conflicts against the container account databases. An existing mapped account is accepted only when its UID, private primary GID, home, shell, and supplementary groups match the mapping's expected state. A locked password left by an interrupted `useradd` is replaced with a newly generated random hash; password authentication remains disabled. Existing mapped primary groups must match the username/GID and have no supplementary members. Existing directory paths and host keys are checked for expected type, owner, group, and mode. An empty root-owned mode-`0700` upload directory is accepted as an interrupted initialization and normalized; non-empty conflicting state fails closed.

If a mapping entry is removed, the next successful startup removes its authorized key and omits its generated `Match User` block. It does not delete the Linux account, group, chroot directory, or stored package data. Those remain for manual review. Previously uploaded package contents are not recursively re-owned or chmodded; review and migrate old content separately if it needs the new shared-group access.

## Chroot and permissions

Each account is chrooted to `/srv/opsbridge-sftp/<integration-id>`. The data-volume root and each integration chroot remain `root:root` mode `0755`. They are not writable by an SFTP user.

The backend runs as a non-root UID, intended to be `9001`, and receives GID `1999` as a supplemental group. `opsbridge-intake` is created with GID `1999` in the SFTP container. SFTP accounts are not members of that group.

| Directory | Owner | Group | Mode | Backend access |
|---|---|---|---:|---|
| `staging/` | SFTP username | `opsbridge-intake` | `2700` | Cannot list or traverse |
| `incoming/` | SFTP username | `opsbridge-intake` | `2770` | Can list, traverse, read, and claim packages |

The SFTP account owns both directories, so it can create a package under `staging/` and rename it into `incoming/`. Rename is atomic because both directories are on the same filesystem. Rename does not change ownership, group, or modes.

Both upload directories have the setgid bit. A package directory created in `staging/` therefore inherits GID `1999`; its setgid bit is inherited as well. Files and nested directories created under that package inherit GID `1999`. The entrypoint sets the SFTP umask to `0007`, which masks other-user permissions while retaining group access for normal OpenSSH client creation modes: a requested file mode of `0666` becomes `0660`, and a requested directory mode of `0777` becomes `0770` (with setgid inherited for new directories). Confirm actual modes with the supported client before relying on the handoff.

The backend's private `work/`, `accepted/`, and `quarantine/` directories must be siblings of the integration chroots in the shared volume, not children of an SFTP chroot. The group permissions on `incoming/` do not expose these sibling paths to SFTP users because OpenSSH confines each account to its own chroot. Keep the host-key volume separate from this shared data volume.

The server's host key is generated on first start in the separate host-key volume and retained across container recreation. An incomplete or mismatched key pair stops startup rather than replacing an existing identity.

## OpenSSH restrictions

The server uses public-key authentication only, `internal-sftp`, a per-user `ChrootDirectory`, and a forced SFTP command. Password and keyboard-interactive authentication are disabled. Shell access, PTY allocation, agent/TCP/stream-local forwarding, X11 forwarding, and tunnels are disabled.

The generated `internal-sftp` command denies `setstat` and `fsetstat` as well as applying umask `0007`. These requests can change file modes or timestamps after upload, which could remove the backend's group-read access. Normal OpenSSH `mkdir`, `put`, and `rename` operations do not require those requests; attribute-preserving uploads such as `put -p` are intentionally unsupported. Verify the simulator's normal upload and rename sequence in the Compose integration phase.

Atomic rename does not prevent a vendor from changing an already published package. The future intake worker must still claim it and verify a private snapshot against manifest size and SHA-256. The account shell is `/usr/sbin/nologin` as an additional restriction.

The entrypoint validates the OpenSSH configuration with `sshd -t` before starting `sshd` in the foreground. Provisioning errors stop startup before the server listens for connections.

## Limitations and next step

Compose builds this image with `infra/sftp` as its context, publishes host `127.0.0.1:${SFTP_PORT:-2222}` to container port 22, and attaches the service only to the dedicated SFTP network. PostgreSQL remains on Compose's default network, where the future backend can join as before. The Compose service does not use `env_file`; the entrypoint uses fixed in-container paths and receives no environment variables. The host port value is Compose interpolation only.

The future backend service must mount `sftp_data` at `/srv/opsbridge-sftp`, run as a non-root user, and receive supplemental GID `1999`. Do not mount `sftp_host_keys` into the backend. The local SFTP account map and client private key belong under the ignored `.secrets/` directory. Do not place private keys in the Docker build context or tracked files.

Docker Desktop on Windows may implement named-volume permissions differently from a native Linux filesystem. Validate chroot ownership and same-filesystem rename behavior in the actual Docker runtime before relying on it. A bind mount from a Windows host directory is especially likely to have permission semantics that differ from OpenSSH's chroot requirements; prefer Docker-managed named volumes for the chroot and host keys.
