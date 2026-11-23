#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly SFTP_ROOT=/srv/opsbridge-sftp
readonly HOST_KEYS_DIR=/var/lib/ssh-host-keys
readonly ACCOUNT_FILE=/run/config/sftp-accounts.json
readonly AUTHORIZED_KEYS_DIR=/etc/ssh/authorized_keys
readonly ACCOUNT_CONFIG=/run/sshd/opsbridge-accounts.conf
readonly INTAKE_GROUP=opsbridge-intake
readonly INTAKE_GID=1999
readonly ALLOWED_GROUP=opsbridge-sftp
readonly ALLOWED_GROUP_GID=1998

fail() {
    printf 'SFTP initialization failed: %s\n' "$1" >&2
    exit 1
}

set_random_password_hash() {
    local username="$1"
    local password_secret password_salt password_hash
    password_secret="$(openssl rand -hex 32)"
    password_salt="$(openssl rand -hex 8)"
    password_hash="$(printf '%s\n' "$password_secret" | openssl passwd -6 -salt "$password_salt" -stdin)"
    unset password_secret password_salt
    printf '%s:%s\n' "$username" "$password_hash" | chpasswd --encrypted
    unset password_hash
}

if [[ "$(id -u)" -ne 0 ]]; then
    fail 'the container entrypoint must run as root'
fi

for command_name in getent groupadd useradd usermod chpasswd passwd ssh-keygen sshd mountpoint python3 openssl; do
    command -v "$command_name" >/dev/null 2>&1 || fail "required command is unavailable: $command_name"
done

[[ -f "$ACCOUNT_FILE" && ! -L "$ACCOUNT_FILE" ]] || fail 'the account mapping file is missing or is not a regular file'
mountpoint -q -- "$SFTP_ROOT" || fail 'the SFTP data volume is not mounted at the expected path'
mountpoint -q -- "$HOST_KEYS_DIR" || fail 'the SSH host-key volume is not mounted at the expected path'

# Parse and preflight the entire mapping before making persistent changes.
validated_accounts="$(python3 - "$ACCOUNT_FILE" "$SFTP_ROOT" "$HOST_KEYS_DIR" \
    "$AUTHORIZED_KEYS_DIR" "$ACCOUNT_CONFIG" "$INTAKE_GROUP" "$INTAKE_GID" \
    "$ALLOWED_GROUP" "$ALLOWED_GROUP_GID" <<'PY'
import base64
import binascii
import grp
import json
import os
import pwd
import re
import stat
import subprocess
import sys
import uuid
from pathlib import Path


(
    mapping_path,
    sftp_root,
    host_keys_dir,
    authorized_keys_dir,
    account_config,
    intake_group_name,
    intake_group_id_text,
    access_group_name,
    access_group_id_text,
) = sys.argv[1:]
intake_group_id = int(intake_group_id_text)
access_group_id = int(access_group_id_text)


class DuplicateJSONKey(ValueError):
    pass


def reject_duplicate_json_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateJSONKey(key)
        value[key] = item
    return value


def stop(message):
    raise SystemExit(message)


def optional_group_by_name(name):
    try:
        return grp.getgrnam(name)
    except KeyError:
        return None


def groups_by_id(group_id):
    return [group for group in grp.getgrall() if group.gr_gid == group_id]


def check_reserved_group(name, group_id, *, require_no_members=False):
    by_name = optional_group_by_name(name)
    by_id = groups_by_id(group_id)
    if by_name is None and not by_id:
        return None
    if (
        by_name is None
        or by_name.gr_gid != group_id
        or len(by_id) != 1
        or by_id[0].gr_name != name
    ):
        stop(f"reserved group {name} or GID {group_id} conflicts with existing system state")
    if require_no_members and by_name.gr_mem:
        stop(f"reserved group {name} must not contain SFTP account members")
    return by_name


def check_directory(path, label, *, uid, gids, modes, optional=True):
    path = Path(path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        if optional:
            return None
        stop(f"required directory is missing: {label}")
    if not stat.S_ISDIR(info.st_mode):
        stop(f"{label} is not a real directory")
    if info.st_uid != uid or info.st_gid not in gids or stat.S_IMODE(info.st_mode) not in modes:
        stop(f"{label} has conflicting ownership or permissions")
    return info


def check_chroot_directory(path):
    path = Path(path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_gid != 0:
        stop("integration chroot has conflicting type or ownership")
    if stat.S_IMODE(info.st_mode) not in {0o700, 0o755}:
        stop("integration chroot has conflicting permissions")
    return info


def check_upload_directory(path, label, *, uid, private_gid, shared_gid, modes):
    path = Path(path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(info.st_mode):
        stop(f"{label} is not a real directory")
    if (
        info.st_uid == uid
        and info.st_gid in {private_gid, shared_gid}
        and stat.S_IMODE(info.st_mode) in modes
    ):
        return info
    if info.st_uid == 0 and info.st_gid == 0 and stat.S_IMODE(info.st_mode) == 0o700:
        if next(os.scandir(path), None) is None:
            return info
    stop(f"{label} has conflicting ownership, permissions, or contents")


def check_regular_file(path, label, *, uid, gid, mode):
    path = Path(path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        stop(f"{label} is not a regular file")
    if info.st_uid != uid or info.st_gid != gid or stat.S_IMODE(info.st_mode) != mode:
        stop(f"{label} has conflicting ownership or permissions")
    return info


def key_fingerprint(path):
    result = subprocess.run(
        ["ssh-keygen", "-lf", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stop("the persistent SSH host key cannot be parsed")
    fields = result.stdout.split()
    if len(fields) < 2:
        stop("the persistent SSH host key has an invalid fingerprint result")
    return fields[1]


try:
    records = json.loads(
        Path(mapping_path).read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_json_keys,
    )
except DuplicateJSONKey as error:
    stop(f"account mapping contains duplicate JSON property: {error}")
except (OSError, UnicodeError, json.JSONDecodeError):
    stop("account mapping must be readable UTF-8 JSON with valid syntax")

if not isinstance(records, list) or not records:
    stop("account mapping must be a non-empty JSON array")

required_fields = {"integration_id", "username", "uid", "gid", "authorized_key"}
username_pattern = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
accepted_key_types = {
    "ssh-ed25519",
    "ecdsa-sha2-nistp256",
    "ssh-rsa",
    "sk-ssh-ed25519@openssh.com",
    "sk-ecdsa-sha2-nistp256@openssh.com",
}
reserved_names = {intake_group_name, access_group_name}
normalized_records = []
seen_ids = set()
seen_usernames = set()
seen_uids = set()
seen_gids = set()
seen_public_keys = set()

for position, record in enumerate(records, start=1):
    if not isinstance(record, dict) or set(record) != required_fields:
        stop(f"account record {position} must contain exactly the documented fields")

    integration_id = record["integration_id"]
    username = record["username"]
    uid = record["uid"]
    gid = record["gid"]
    authorized_key = record["authorized_key"]

    if not isinstance(integration_id, str):
        stop(f"account record {position} has an invalid integration_id")
    try:
        normalized_id = str(uuid.UUID(integration_id))
    except (ValueError, AttributeError):
        stop(f"account record {position} has an invalid integration_id")

    if not isinstance(username, str) or not username_pattern.fullmatch(username):
        stop(f"account record {position} has an invalid Linux username")
    if username in reserved_names:
        stop(f"account record {position} uses a reserved Linux group name as its username")
    if (
        type(uid) is not int
        or type(gid) is not int
        or not (10000 <= uid <= 60000)
        or not (10000 <= gid <= 60000)
    ):
        stop(f"account record {position} UID and GID must be integers from 10000 through 60000")
    if uid in {intake_group_id, access_group_id} or gid in {intake_group_id, access_group_id}:
        stop(f"account record {position} conflicts with a reserved group ID")
    if (
        not isinstance(authorized_key, str)
        or not authorized_key.isascii()
        or any(character in authorized_key for character in "\r\n\t")
    ):
        stop(f"account record {position} has an invalid public key")

    key_fields = authorized_key.split()
    if len(key_fields) < 2 or key_fields[0] not in accepted_key_types:
        stop(f"account record {position} has an unsupported public-key format")
    try:
        base64.b64decode(key_fields[1], validate=True)
    except (ValueError, binascii.Error):
        stop(f"account record {position} has an invalid public-key encoding")

    key_check = subprocess.run(
        ["ssh-keygen", "-lf", "/dev/stdin"],
        input=(authorized_key + "\n").encode("ascii"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if key_check.returncode != 0:
        stop(f"account record {position} has a public key ssh-keygen cannot parse")

    key_identity = " ".join(key_fields[:2])
    if (
        normalized_id in seen_ids
        or username in seen_usernames
        or uid in seen_uids
        or gid in seen_gids
        or key_identity in seen_public_keys
    ):
        stop(f"account record {position} duplicates an integration ID, username, UID, GID, or public key")
    seen_ids.add(normalized_id)
    seen_usernames.add(username)
    seen_uids.add(uid)
    seen_gids.add(gid)
    seen_public_keys.add(key_identity)
    normalized_records.append((normalized_id, username, uid, gid, authorized_key))

if not Path("/usr/sbin/nologin").is_file():
    stop("the configured no-login shell is unavailable")

# Verify reserved groups and all mapped account/group identities before mutation.
check_reserved_group(intake_group_name, intake_group_id, require_no_members=True)
check_reserved_group(access_group_name, access_group_id)
if any(user.pw_gid == intake_group_id for user in pwd.getpwall()):
    stop(f"no Linux account may use {intake_group_name} as its primary group")

for group_id in (intake_group_id, access_group_id):
    if any(group.gr_gid == group_id for group in grp.getgrall() if group.gr_name not in reserved_names):
        stop(f"reserved GID {group_id} is assigned to another group")

for position, (integration_id, username, uid, gid, authorized_key) in enumerate(normalized_records, start=1):
    group_by_name = optional_group_by_name(username)
    same_gid_groups = groups_by_id(gid)
    if group_by_name is None and not same_gid_groups:
        pass
    elif (
        group_by_name is None
        or group_by_name.gr_gid != gid
        or len(same_gid_groups) != 1
        or same_gid_groups[0].gr_name != username
        or group_by_name.gr_mem
    ):
        stop(f"account record {position} primary group conflicts with the mapping")

    try:
        user_by_name = pwd.getpwnam(username)
    except KeyError:
        user_by_name = None
    same_uid_users = [user for user in pwd.getpwall() if user.pw_uid == uid]
    if user_by_name is None and not same_uid_users:
        pass
    elif (
        user_by_name is None
        or len(same_uid_users) != 1
        or same_uid_users[0].pw_name != username
        or user_by_name.pw_uid != uid
        or user_by_name.pw_gid != gid
        or user_by_name.pw_dir != "/"
        or user_by_name.pw_shell != "/usr/sbin/nologin"
        or (user_by_name is not None and group_by_name is None)
    ):
        stop(f"account record {position} conflicts with an existing Linux account")
    else:
        try:
            supplementary_groups = set(os.getgrouplist(username, gid))
        except OSError:
            stop(f"account record {position} group membership cannot be verified")
        if not supplementary_groups.issubset({gid, access_group_id}):
            stop(f"account record {position} has unexpected supplementary group membership")
        if intake_group_id in supplementary_groups:
            stop(f"account record {position} must not belong to {intake_group_name}")
        password_status = subprocess.run(
            ["passwd", "-S", username],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        if (
            password_status.returncode != 0
            or len(password_status.stdout.split()) < 2
            or password_status.stdout.split()[1] not in {"P", "L"}
        ):
            stop(f"account record {position} has an ambiguous existing password state")

    integration_root = Path(sftp_root) / integration_id
    root_info = check_chroot_directory(integration_root)
    staging_info = check_upload_directory(
        integration_root / "staging",
        "staging directory",
        uid=uid,
        private_gid=gid,
        shared_gid=intake_group_id,
        modes={0o700, 0o2700},
    )
    incoming_info = check_upload_directory(
        integration_root / "incoming",
        "incoming directory",
        uid=uid,
        private_gid=gid,
        shared_gid=intake_group_id,
        modes={0o700, 0o2770},
    )
    root_device = os.stat(sftp_root).st_dev
    for directory_info in (root_info, staging_info, incoming_info):
        if directory_info is not None and directory_info.st_dev != root_device:
            stop("integration chroot and upload directories must share the SFTP data filesystem")

# Verify volume roots, host keys, and current generated files before replacement.
check_directory("/", "container root", uid=0, gids={0}, modes={0o755}, optional=False)
check_directory("/srv", "SFTP root parent", uid=0, gids={0}, modes={0o755}, optional=False)
check_directory(sftp_root, "SFTP data volume root", uid=0, gids={0}, modes={0o755}, optional=False)
check_directory(host_keys_dir, "SSH host-key volume root", uid=0, gids={0}, modes={0o700}, optional=False)
check_directory(authorized_keys_dir, "authorized-keys directory", uid=0, gids={0}, modes={0o755})
check_directory(Path(account_config).parent, "sshd runtime directory", uid=0, gids={0}, modes={0o755})

authorized_dir = Path(authorized_keys_dir)
if authorized_dir.exists():
    mapped_gids = {username: gid for _, username, _, gid, _ in normalized_records}
    for entry in os.scandir(authorized_dir):
        if not username_pattern.fullmatch(entry.name):
            stop("authorized-keys directory contains an unexpected filename")
        try:
            key_info = os.lstat(entry.path)
        except OSError:
            stop("authorized-key file cannot be inspected")
        if not stat.S_ISREG(key_info.st_mode) or key_info.st_uid != 0:
            stop("authorized-key file has conflicting type or ownership")
        key_mode = stat.S_IMODE(key_info.st_mode)
        mapped_gid = mapped_gids.get(entry.name)
        current_permissions = (
            mapped_gid is not None
            and key_info.st_gid == mapped_gid
            and key_mode == 0o640
        )
        legacy_permissions = key_info.st_gid == 0 and key_mode == 0o600
        stale_account_permissions = False
        if mapped_gid is None and key_mode == 0o640:
            try:
                stale_user = pwd.getpwnam(entry.name)
                stale_group = grp.getgrnam(entry.name)
            except KeyError:
                pass
            else:
                stale_account_permissions = (
                    stale_user.pw_gid == stale_group.gr_gid == key_info.st_gid
                )
        if not (current_permissions or legacy_permissions or stale_account_permissions):
            stop("authorized-key file has conflicting group ownership or permissions")

config_file = Path(account_config)
if config_file.exists() or config_file.is_symlink():
    check_regular_file(config_file, "generated sshd account configuration", uid=0, gid=0, mode=0o600)

host_key = Path(host_keys_dir) / "ssh_host_ed25519_key"
host_public_key = Path(str(host_key) + ".pub")
private_exists = host_key.exists() or host_key.is_symlink()
public_exists = host_public_key.exists() or host_public_key.is_symlink()
if public_exists and not private_exists:
    stop("the persistent SSH host-key pair is incomplete")
if private_exists:
    check_regular_file(host_key, "SSH host private key", uid=0, gid=0, mode=0o600)
    private_fingerprint = key_fingerprint(host_key)
    if public_exists:
        check_regular_file(host_public_key, "SSH host public key", uid=0, gid=0, mode=0o644)
        if key_fingerprint(host_public_key) != private_fingerprint:
            stop("the persistent SSH host-key pair does not match")

for position, (integration_id, username, uid, gid, authorized_key) in enumerate(normalized_records, start=1):
    print("\t".join((integration_id, username, str(uid), str(gid), authorized_key)))
PY
)" || fail 'account mapping or existing account state failed preflight'

[[ -n "$validated_accounts" ]] || fail 'account mapping did not contain any valid accounts'

# All mapping, identity, group, path, and key checks completed above.
install -d -o root -g root -m 0755 "$AUTHORIZED_KEYS_DIR" /run/sshd

readonly HOST_KEY="$HOST_KEYS_DIR/ssh_host_ed25519_key"
readonly HOST_PUBLIC_KEY="$HOST_KEY.pub"
if [[ ! -e "$HOST_KEY" && ! -e "$HOST_PUBLIC_KEY" ]]; then
    ssh-keygen -q -t ed25519 -N '' -C opsbridge-sftp-host -f "$HOST_KEY"
elif [[ -f "$HOST_KEY" && ! -e "$HOST_PUBLIC_KEY" ]]; then
    ssh-keygen -y -f "$HOST_KEY" >"$HOST_PUBLIC_KEY"
else
    [[ -f "$HOST_KEY" && -f "$HOST_PUBLIC_KEY" ]] || fail 'the persistent SSH host-key pair is incomplete'
fi
chmod 0600 "$HOST_KEY"
chmod 0644 "$HOST_PUBLIC_KEY"
chown root:root "$HOST_KEY" "$HOST_PUBLIC_KEY"

if ! getent group "$INTAKE_GROUP" >/dev/null; then
    groupadd --gid "$INTAKE_GID" "$INTAKE_GROUP"
fi
if ! getent group "$ALLOWED_GROUP" >/dev/null; then
    groupadd --gid "$ALLOWED_GROUP_GID" "$ALLOWED_GROUP"
fi

account_config_tmp="$(mktemp /run/sshd/opsbridge-accounts.XXXXXX)"
cleanup() {
    rm -f -- "$account_config_tmp"
}
trap cleanup EXIT
: >"$account_config_tmp"

# Revoke keys for removed mappings without deleting accounts or stored data.
find "$AUTHORIZED_KEYS_DIR" -mindepth 1 -maxdepth 1 -type f -delete

while IFS=$'\t' read -r integration_id username uid gid authorized_key; do
    [[ -n "$integration_id" && -n "$username" && -n "$uid" && -n "$gid" && -n "$authorized_key" ]] || fail 'validated account record is incomplete'

    if ! getent group "$username" >/dev/null; then
        groupadd --gid "$gid" "$username"
    fi

    if ! getent passwd "$username" >/dev/null; then
        useradd --uid "$uid" --gid "$gid" --groups "$ALLOWED_GROUP" \
            --home-dir / --no-create-home --shell /usr/sbin/nologin "$username"
        set_random_password_hash "$username"
    else
        usermod --append --groups "$ALLOWED_GROUP" "$username"
        password_status="$(passwd -S "$username" | awk '{print $2}')"
        if [[ "$password_status" == L ]]; then
            set_random_password_hash "$username"
        fi
    fi

    integration_root="$SFTP_ROOT/$integration_id"
    mkdir -p -- "$integration_root/staging" "$integration_root/incoming"
    chown root:root "$integration_root"
    chmod 0755 "$integration_root"

    chown "$username:$INTAKE_GROUP" "$integration_root/staging" "$integration_root/incoming"
    chmod 2700 "$integration_root/staging"
    chmod 2770 "$integration_root/incoming"

    printf '%s\n' "$authorized_key" >"$AUTHORIZED_KEYS_DIR/$username"
    chown "root:$gid" "$AUTHORIZED_KEYS_DIR/$username"
    chmod 0640 "$AUTHORIZED_KEYS_DIR/$username"

    cat >>"$account_config_tmp" <<EOF
Match User $username
    ChrootDirectory $integration_root
    ForceCommand internal-sftp -u 0007 -P setstat,fsetstat
    PermitTTY no
    AllowAgentForwarding no
    AllowTcpForwarding no
    AllowStreamLocalForwarding no
    X11Forwarding no
    PermitTunnel no

EOF
done <<<"$validated_accounts"

chown root:root "$account_config_tmp"
chmod 0600 "$account_config_tmp"
mv -- "$account_config_tmp" "$ACCOUNT_CONFIG"
trap - EXIT
rm -f -- "$account_config_tmp"

# Root owns the mount and vendors cannot reach this sibling of their chroots.
[[ ! -L "$SFTP_ROOT/_opsbridge" ]] || fail 'invalid private storage root'
install -d -o 9001 -g 1999 -m 0700 -- "$SFTP_ROOT/_opsbridge"

sshd -t -f /etc/ssh/sshd_config || fail 'OpenSSH configuration validation failed'

exec "$@"
