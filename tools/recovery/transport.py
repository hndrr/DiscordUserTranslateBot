"""Fail-closed, ciphertext-only handoff to an externally authenticated Library tool.

No network client, credentials, decryption, or automatic retries exist here.
STATE_ROOT and its outbox must be private, owned, non-symlink directories. The
trusted bridge-state.json alone supplies the Library destination and version.

prepare returns STATE_ROOT/upload-{request_id}/discord-backup.encrypted.json
and persists a pending transaction. Each request directory is owner-only (0700);
its ciphertext is a new single-link file (0600). The stable basename preserves
the human Library filename during replacement.
Pass the returned path, library_file_id, and expected_current_version unchanged
to the Library replace tool. Never remove its optimistic concurrency guard.
confirm consumes an explicitly correlated successful tool response on stdin.
An unsuccessful or ambiguous upload MUST leave pending state in place. There
is deliberately no reset/retry command: first reconcile that exact Library item
and the pending ciphertext with the remote service.

Receipt, state, and pending removal are durable ordered writes, not a multi-file
atomic transaction. An interruption leaves pending state, which blocks prepare.
The protected local caller is trusted to supply the authentic tool response;
this helper cannot cryptographically authenticate a JSON response on stdin.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import fcntl
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
import uuid

import auto_envelope as envelope
import recovery_core as recovery

MAX_METADATA = 16 * 1024
MAX_CONFIRMATION = 1024 * 1024
MAX_SEQUENCE = 2**53 - 1
MAX_STAGED_UPLOADS = 256
UPLOAD_BASENAME = "discord-backup.encrypted.json"
STATE_FILE = "bridge-state.json"
PENDING_FILE = "pending-upload.json"
RECEIPT_FILE = "upload-receipt.json"
LOCK_FILE = ".transport.lock"
STATE_KEYS = {"format", "version", "library_file_id", "library_version",
              "last_uploaded_snapshot_id", "last_uploaded_sequence", "recipient_sha256"}
MANIFEST_KEYS = {"format", "version", "snapshot_id", "sequence", "created_at",
                 "file_name", "size_bytes", "sha256", "recipient_sha256"}
PENDING_KEYS = {"format", "version", "request_id", "library_file_id",
                "expected_current_version", "previous_snapshot_id", "previous_sequence",
                "snapshot_id", "sequence", "created_at", "upload_file_name",
                "size_bytes", "sha256", "recipient_sha256", "prepared_at"}
RECEIPT_KEYS = {"format", "version", "request_id", "library_file_id",
                "library_version", "snapshot_id", "sequence", "created_at",
                "size_bytes", "sha256", "recipient_sha256", "confirmed_at"}
CORRELATION_KEYS = {"request_id", "snapshot_id", "sha256", "library_response"}


class TransportError(recovery.RecoveryError):
    """Fixed safe diagnostic; never include raw input or service responses."""


def _reject(message="Invalid transport metadata; no upload is authorized."):
    raise TransportError(message)


def _integer(value, minimum=1, maximum=MAX_SEQUENCE):
    return type(value) is int and minimum <= value <= maximum


def _digest(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _uuid(value):
    if type(value) is not str:
        return False
    try:
        parsed = uuid.UUID(value)
        return parsed.version == 4 and str(parsed) == value
    except ValueError:
        return False


def _timestamp(value):
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        return False
    try:
        dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        return True
    except ValueError:
        return False


def _now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _library_id(value):
    # Opaque identity, never interpreted as a URL, path, or shell fragment.
    return type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}", value) is not None


def _shape(value, keys, format_name):
    if (type(value) is not dict or set(value) != keys or value["format"] != format_name
            or type(value["version"]) is not int or value["version"] != 1):
        _reject()


def _history(snapshot_id, sequence):
    return (_integer(sequence, 0) and ((sequence == 0 and snapshot_id is None)
                                     or (sequence > 0 and _uuid(snapshot_id))))


def _state(value):
    _shape(value, STATE_KEYS, "discord-autobackup-bridge-state")
    if (not _library_id(value["library_file_id"]) or not _integer(value["library_version"], minimum=0)
            or not _history(value["last_uploaded_snapshot_id"], value["last_uploaded_sequence"])
            or not _digest(value["recipient_sha256"])):
        _reject()
    return value


def _manifest(value):
    _shape(value, MANIFEST_KEYS, "discord-autobackup-manifest")
    if (not _uuid(value["snapshot_id"]) or not _integer(value["sequence"])
            or not _timestamp(value["created_at"])
            or value["file_name"] != "snapshot-" + value["snapshot_id"] + ".encrypted.json"
            or not _integer(value["size_bytes"], maximum=recovery.MAX_PACKAGE)
            or not _digest(value["sha256"]) or not _digest(value["recipient_sha256"])):
        _reject()
    return value


def _pending(value):
    _shape(value, PENDING_KEYS, "discord-autobackup-pending-upload")
    if (not _uuid(value["request_id"]) or not _library_id(value["library_file_id"])
            or not _integer(value["expected_current_version"], minimum=0, maximum=MAX_SEQUENCE - 1)
            or not _history(value["previous_snapshot_id"], value["previous_sequence"])
            or not _uuid(value["snapshot_id"]) or not _integer(value["sequence"])
            or value["sequence"] <= value["previous_sequence"]
            or not _timestamp(value["created_at"]) or not _timestamp(value["prepared_at"])
            or value["upload_file_name"] not in {
                "upload-" + value["request_id"] + "/" + UPLOAD_BASENAME,
                "upload-" + value["request_id"] + ".encrypted.json"}
            or not _integer(value["size_bytes"], maximum=recovery.MAX_PACKAGE)
            or not _digest(value["sha256"]) or not _digest(value["recipient_sha256"])):
        _reject()
    return value


def _receipt(value):
    _shape(value, RECEIPT_KEYS, "discord-autobackup-upload-receipt")
    if (not _uuid(value["request_id"]) or not _library_id(value["library_file_id"])
            or not _integer(value["library_version"], minimum=0)
            or not _uuid(value["snapshot_id"]) or not _integer(value["sequence"])
            or not _timestamp(value["created_at"]) or not _timestamp(value["confirmed_at"])
            or not _integer(value["size_bytes"], maximum=recovery.MAX_PACKAGE)
            or not _digest(value["sha256"]) or not _digest(value["recipient_sha256"])):
        _reject()
    return value


def _private_directory(path):
    fd = recovery._directory(path)
    info = os.fstat(fd)
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        os.close(fd)
        _reject("Transport directories must be owned by you and private.")
    return fd


def _safe_entry(fd, name):
    info = os.stat(name, dir_fd=fd, follow_symlinks=False)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
        _reject("Transport state must use private, owned, single-link regular files.")
    return info


def _exists(fd, name):
    try:
        os.stat(name, dir_fd=fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


@contextmanager
def _locked(state_root):
    parts = recovery._path_parts(state_root)
    root = Path(*parts)
    root_fd = _private_directory(root)
    lock_fd = None
    try:
        lock_fd = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
                          | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=root_fd)
        info = os.fstat(lock_fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
            _reject("Invalid transport lock; no upload is authorized.")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _reject("Another transport job is active; no upload is authorized.")
        # Never unlink the lock: a persistent inode coordinates every job.
        yield root, root_fd
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        os.close(root_fd)


def _read_json(root, fd, name, limit=MAX_METADATA):
    _safe_entry(fd, name)
    return recovery._parse(recovery.read_bounded(root / name, limit), limit)


def _atomic_bytes(fd, name, raw, *, replace=False):
    """Write privately, fsync, publish with dirfd, then fsync the directory."""
    temporary = ".transport-stage-" + uuid.uuid4().hex
    try:
        recovery._write(fd, temporary, raw)
        if replace:
            _safe_entry(fd, name)
            os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        else:
            recovery._rename_new(fd, temporary, name)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


def _atomic_json(fd, name, value, *, replace=False):
    _atomic_bytes(fd, name, recovery._json(value) + b"\n", replace=replace)


def _verify_ciphertext(raw, metadata, pin):
    if (len(raw) != metadata["size_bytes"] or hashlib.sha256(raw).hexdigest() != metadata["sha256"]
            or metadata["recipient_sha256"] != pin):
        _reject("Ciphertext size, digest, or recipient pin mismatch; no upload is authorized.")
    package = envelope.validate_snapshot(raw, expected_recipient_digest=pin)
    if any(package[key] != metadata[key] for key in ("snapshot_id", "sequence", "created_at")):
        _reject("Ciphertext identity does not match its manifest; no upload is authorized.")


def _check_previous_receipt(root, fd, state):
    if state["last_uploaded_snapshot_id"] is None:
        if _exists(fd, RECEIPT_FILE):
            _reject("Local upload history is inconsistent; reconcile the exact Library item.")
        return None
    try:
        receipt = _receipt(_read_json(root, fd, RECEIPT_FILE))
    except FileNotFoundError:
        _reject("Confirmed upload receipt is missing; reconcile the exact Library item.")
    expected = {"library_file_id": state["library_file_id"], "library_version": state["library_version"],
                "snapshot_id": state["last_uploaded_snapshot_id"], "sequence": state["last_uploaded_sequence"],
                "recipient_sha256": state["recipient_sha256"]}
    if any(receipt[key] != value for key, value in expected.items()):
        _reject("Local upload history is inconsistent; reconcile the exact Library item.")
    return receipt


def prepare(state_root):
    """Return a single upload authorization, or a confirmed no-op. Never upload."""
    with _locked(state_root) as (root, fd):
        state = _state(_read_json(root, fd, STATE_FILE))
        # Presence alone blocks, including corrupt/symlink/unknown pending state.
        if _exists(fd, PENDING_FILE):
            _reject("An upload is pending or uncertain; reconcile the exact Library item before continuing.")
        previous_receipt = _check_previous_receipt(root, fd, state)
        outbox = root / "outbox"
        outbox_fd = _private_directory(outbox)
        try:
            manifest = _manifest(_read_json(outbox, outbox_fd, "latest.json"))
            _safe_entry(outbox_fd, manifest["file_name"])
            raw = recovery.read_bounded(outbox / manifest["file_name"], recovery.MAX_PACKAGE)
            _verify_ciphertext(raw, manifest, state["recipient_sha256"])
        finally:
            os.close(outbox_fd)
        if manifest["sequence"] == state["last_uploaded_sequence"]:
            if (manifest["snapshot_id"] != state["last_uploaded_snapshot_id"] or previous_receipt is None
                    or any(manifest[key] != previous_receipt[key]
                           for key in ("sha256", "size_bytes", "created_at"))):
                _reject("Snapshot sequence was reused; reconcile the exact Library item.")
            return {"status": "noop", "snapshot_id": manifest["snapshot_id"],
                    "sequence": manifest["sequence"], "library_version": state["library_version"]}
        if (manifest["sequence"] < state["last_uploaded_sequence"]
                or manifest["snapshot_id"] == state["last_uploaded_snapshot_id"]):
            _reject("Snapshot is stale or reuses a confirmed identity; no upload is authorized.")
        if state["library_version"] >= MAX_SEQUENCE:
            _reject("Library version cannot advance safely; reconcile the exact Library item.")
        # Retention is explicit: stop rather than silently delete old backups.
        retained = sum(name.startswith("upload-") and
                       (name.endswith(".encrypted.json") or _uuid(name[len("upload-"):]))
                       for name in os.listdir(fd))
        if retained >= MAX_STAGED_UPLOADS:
            _reject("Ciphertext staging capacity reached; review retained backups before continuing.")
        request_id = str(uuid.uuid4())
        staged_directory = "upload-" + request_id
        staged_name = staged_directory + "/" + UPLOAD_BASENAME
        pending = {"format": "discord-autobackup-pending-upload", "version": 1,
                   "request_id": request_id, "library_file_id": state["library_file_id"],
                   "expected_current_version": state["library_version"],
                   "previous_snapshot_id": state["last_uploaded_snapshot_id"],
                   "previous_sequence": state["last_uploaded_sequence"],
                   **{key: manifest[key] for key in ("snapshot_id", "sequence", "created_at",
                                                   "size_bytes", "sha256", "recipient_sha256")},
                   "upload_file_name": staged_name, "prepared_at": _now()}
        # Preserve the human Library filename while keeping every upload path
        # unique and immutable. Never reuse or replace a request directory.
        os.mkdir(staged_directory, 0o700, dir_fd=fd)
        staged_fd = os.open(staged_directory, os.O_RDONLY | os.O_DIRECTORY
                            | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
        try:
            os.fchmod(staged_fd, 0o700)
            _atomic_bytes(staged_fd, UPLOAD_BASENAME, raw)
        finally:
            os.close(staged_fd)
        os.fsync(fd)
        # Persist this before exposing upload details. An uncertain publication
        # must never lead to an external call, even if pending was made durable.
        _atomic_json(fd, PENDING_FILE, pending)
        return {"status": "ready", "request_id": request_id,
                "library_file_id": state["library_file_id"],
                "expected_current_version": state["library_version"],
                "file": str(root / staged_name),
                **{key: manifest[key] for key in ("snapshot_id", "sequence", "size_bytes", "sha256")}}


def _successful_library_result(response, expected_size):
    """Accept actual structured replace metadata; discard URLs/xattrs/extra data.

    Full MCP responses must explicitly report isError=false. A caller may pass
    the unchanged structuredContent object instead. No content-text fallback,
    inferred status, batch result, or nested guessed success shape is accepted.
    """
    if type(response) is not dict:
        _reject("Library success was not confirmed; preserve pending state and reconcile remotely.")
    if "structuredContent" in response:
        if (response.get("isError") is not False or response.get("error") is not None
                or response.get("errors") is not None):
            _reject("Library success was not confirmed; preserve pending state and reconcile remotely.")
        response = response["structuredContent"]
    if (type(response) is not dict or response.get("operation") != "replace_library_file"
            or response.get("status") != "succeeded"
            or not _library_id(response.get("library_file_id"))
            or not _integer(response.get("current_version_number"))
            or not _integer(response.get("file_size_bytes"), maximum=recovery.MAX_PACKAGE)
            or response["file_size_bytes"] != expected_size
            or response.get("isError", False) is not False
            or response.get("error") is not None or response.get("errors") is not None):
        _reject("Library success was not confirmed; preserve pending state and reconcile remotely.")
    return response["library_file_id"], response["current_version_number"]


def confirm(state_root, confirmation):
    """Commit one correlated success; input may be parsed JSON or bounded bytes."""
    if type(confirmation) is bytes:
        confirmation = recovery._parse(confirmation, MAX_CONFIRMATION)
    if type(confirmation) is not dict or set(confirmation) != CORRELATION_KEYS:
        _reject("Invalid confirmation; preserve pending state and reconcile remotely.")
    with _locked(state_root) as (root, fd):
        state = _state(_read_json(root, fd, STATE_FILE))
        try:
            pending = _pending(_read_json(root, fd, PENDING_FILE))
        except FileNotFoundError:
            _reject("No pending upload exists; this confirmation is stale.")
        expected_state = {"library_file_id": pending["library_file_id"],
                          "library_version": pending["expected_current_version"],
                          "last_uploaded_snapshot_id": pending["previous_snapshot_id"],
                          "last_uploaded_sequence": pending["previous_sequence"],
                          "recipient_sha256": pending["recipient_sha256"]}
        if any(state[key] != value for key, value in expected_state.items()):
            _reject("Local state changed during upload; preserve pending state and reconcile remotely.")
        for key in ("request_id", "snapshot_id", "sha256"):
            if type(confirmation[key]) is not str or confirmation[key] != pending[key]:
                _reject("Confirmation does not identify the pending snapshot; no receipt was written.")
        target, version = _successful_library_result(confirmation["library_response"], pending["size_bytes"])
        if target != pending["library_file_id"] or version != pending["expected_current_version"] + 1:
            _reject("Library destination or version conflicts with pending upload; reconcile remotely.")
        _check_previous_receipt(root, fd, state)
        if pending["upload_file_name"].endswith("/" + UPLOAD_BASENAME):
            # Check the intermediate directory separately; a relative path must
            # never let an intermediate symlink bypass the no-follow checks.
            staged_fd = _private_directory(root / ("upload-" + pending["request_id"]))
            try:
                _safe_entry(staged_fd, UPLOAD_BASENAME)
                raw = recovery.read_bounded(root / pending["upload_file_name"], recovery.MAX_PACKAGE)
            finally:
                os.close(staged_fd)
        else:
            # Legacy flat pending uploads can still be confirmed safely. They
            # are never generated again, renamed, modified, or deleted here.
            _safe_entry(fd, pending["upload_file_name"])
            raw = recovery.read_bounded(root / pending["upload_file_name"], recovery.MAX_PACKAGE)
        _verify_ciphertext(raw, pending, state["recipient_sha256"])
        receipt = {"format": "discord-autobackup-upload-receipt", "version": 1,
                   "request_id": pending["request_id"], "library_file_id": target,
                   "library_version": version,
                   **{key: pending[key] for key in ("snapshot_id", "sequence", "created_at",
                                                  "size_bytes", "sha256", "recipient_sha256")},
                   "confirmed_at": _now()}
        new_state = {**state, "library_version": version,
                     "last_uploaded_snapshot_id": pending["snapshot_id"],
                     "last_uploaded_sequence": pending["sequence"]}
        _atomic_json(fd, RECEIPT_FILE, receipt, replace=_exists(fd, RECEIPT_FILE))
        _atomic_json(fd, STATE_FILE, new_state, replace=True)
        os.unlink(PENDING_FILE, dir_fd=fd)
        os.fsync(fd)
        # Staged ciphertext is intentionally retained. A separate bounded
        # retention policy may delete confirmed ciphertext after reconciliation.
        return {"status": "confirmed", "library_file_id": target, "library_version": version,
                "snapshot_id": pending["snapshot_id"], "sequence": pending["sequence"],
                "sha256": pending["sha256"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "confirm"))
    parser.add_argument("state_root")
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            result = prepare(args.state_root)
        else:
            raw = sys.stdin.buffer.read(MAX_CONFIRMATION + 1)
            result = confirm(args.state_root, raw)
        print(recovery._json(result).decode("ascii"))
        return 0
    except recovery.RecoveryError as error:
        print(recovery._json({"status": "blocked", "error": str(error)}).decode("ascii"), file=sys.stderr)
        return 2
    except OSError:
        print('{"status":"blocked","error":"Local transport did not complete; preserve pending state and reconcile before retrying."}', file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
