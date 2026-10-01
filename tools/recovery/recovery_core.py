"""Bounded, local-only encrypted recovery. No networking, logging, or login.

Linux is required for atomic, no-replace directory publication. Passwords are
accepted only in memory, never via arguments or environment variables.
"""
from __future__ import annotations

import base64
import binascii
import ctypes
import datetime as dt
import errno
import json
import os
from pathlib import Path
import re
import stat
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

FORMAT = "discord-translate-recovery"
VERSION = 2
KDF = {"name": "scrypt", "n": 131072, "r": 8, "p": 1, "length": 32}
LIMITS = {".env": 128 * 1024, "codex/auth.json": 1024 * 1024}
MAX_PACKAGE = 3 * 1024 * 1024
MAX_PAYLOAD = 2 * 1024 * 1024
HEADER_KEYS = {"format", "version", "algorithm", "kdf", "salt", "nonce", "created_at", "backup_id"}


class RecoveryError(Exception):
    """Only fixed safe messages may cross the UI boundary."""


def _json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RecoveryError("Invalid backup structure.")
        result[key] = value
    return result


def _parse(raw: bytes, limit: int):
    if type(raw) is not bytes or not 0 < len(raw) <= limit:
        raise RecoveryError("Backup size limit exceeded or empty input.")
    try:
        return json.loads(raw, object_pairs_hook=_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise RecoveryError("Invalid backup structure.") from None


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(value, limit: int) -> bytes:
    if type(value) is not str or len(value) > 4 * ((limit + 2) // 3):
        raise RecoveryError("Invalid encoded data or size limit exceeded.")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error):
        raise RecoveryError("Invalid encoded data or size limit exceeded.") from None
    if len(raw) > limit or _b64(raw) != value:
        raise RecoveryError("Invalid encoded data or size limit exceeded.")
    return raw


def _password(password: str) -> bytes:
    if type(password) is not str or not 16 <= len(password) <= 1024:
        raise RecoveryError("Use a recovery passphrase of 16 to 1024 characters.")
    try:
        raw = password.encode("utf-8")
    except UnicodeError:
        raise RecoveryError("Invalid recovery passphrase.") from None
    if len(raw) > 4096 or password.isspace() or "\x00" in password:
        raise RecoveryError("Invalid recovery passphrase.")
    return raw


def _key(password: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=KDF["n"], r=8, p=1).derive(_password(password))


def _files(files) -> dict[str, bytes]:
    if type(files) is not dict or ".env" not in files or not files.keys() <= LIMITS.keys():
        raise RecoveryError("Only .env and optional dedicated codex/auth.json are allowed.")
    for name, raw in files.items():
        if type(raw) is not bytes or not 0 < len(raw) <= LIMITS[name]:
            raise RecoveryError("A configuration file is empty or exceeds its size limit.")
    return files


def encrypt(files: dict[str, bytes], password: str) -> bytes:
    _files(files)
    _password(password)
    salt, nonce = os.urandom(16), os.urandom(12)
    header = {"format": FORMAT, "version": VERSION, "algorithm": "AES-256-GCM", "kdf": dict(KDF),
              "salt": _b64(salt), "nonce": _b64(nonce),
              "created_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "backup_id": str(uuid.uuid4())}
    payload = _json({"payload_version": 1, "files": {name: _b64(raw) for name, raw in files.items()}})
    ciphertext = AESGCM(_key(password, salt)).encrypt(nonce, payload, _json(header))
    return _json({**header, "ciphertext_and_tag": _b64(ciphertext)}) + b"\n"


def decrypt(raw: bytes, password: str) -> dict[str, bytes]:
    package = _parse(raw, MAX_PACKAGE)
    if type(package) is dict and package.get("format") == FORMAT and type(package.get("version")) is int and package.get("version") == 3:
        from auto_envelope import decrypt_snapshot
        return decrypt_snapshot(raw, password)
    if type(package) is not dict or set(package) != HEADER_KEYS | {"ciphertext_and_tag"}:
        raise RecoveryError("Invalid backup structure.")
    if package["format"] != FORMAT or type(package["version"]) is not int or package["version"] != VERSION:
        raise RecoveryError("Unsupported backup format or version.")
    if package["algorithm"] != "AES-256-GCM" or type(package["kdf"]) is not dict or _json(package["kdf"]) != _json(KDF):
        raise RecoveryError("Unsupported encryption parameters.")
    if type(package["created_at"]) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", package["created_at"]):
        raise RecoveryError("Invalid backup metadata.")
    if type(package["backup_id"]) is not str or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", package["backup_id"]):
        raise RecoveryError("Invalid backup metadata.")
    salt, nonce = _unb64(package["salt"], 16), _unb64(package["nonce"], 12)
    ciphertext = _unb64(package["ciphertext_and_tag"], MAX_PAYLOAD + 16)
    if len(salt) != 16 or len(nonce) != 12 or len(ciphertext) < 17:
        raise RecoveryError("Invalid encryption field length.")
    header = {key: value for key, value in package.items() if key != "ciphertext_and_tag"}
    try:
        payload = AESGCM(_key(password, salt)).decrypt(nonce, ciphertext, _json(header))
    except InvalidTag:
        raise RecoveryError("Wrong recovery passphrase or damaged backup. Nothing was restored.") from None
    data = _parse(payload, MAX_PAYLOAD)
    if type(data) is not dict or set(data) != {"payload_version", "files"} or type(data["payload_version"]) is not int or data["payload_version"] != 1:
        raise RecoveryError("Invalid recovered payload.")
    files = data["files"]
    if type(files) is not dict or ".env" not in files or not files.keys() <= LIMITS.keys():
        raise RecoveryError("Only .env and optional dedicated codex/auth.json are allowed.")
    return _files({name: _unb64(value, LIMITS[name]) for name, value in files.items()})


def _path_parts(path) -> tuple[str, ...]:
    path = os.fspath(path)
    if type(path) is not str or not path or "\x00" in path or ".." in path.split("/"):
        raise RecoveryError("Choose a valid path without parent traversal.")
    return Path(os.path.abspath(path)).parts


def _directory(path) -> int:
    parts = _path_parts(path)
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _parent(path, private=False) -> tuple[int, str]:
    parts = _path_parts(path)
    if len(parts) < 2:
        raise RecoveryError("Choose a named output inside a private directory.")
    fd = _directory(str(Path(*parts[:-1])))
    info = os.fstat(fd)
    if private and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o022):
        os.close(fd)
        raise RecoveryError("Choose an output parent owned by you and not writable by others.")
    return fd, parts[-1]


def read_bounded(path, limit: int) -> bytes:
    parent, name = _parent(path)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_nlink != 1 or not 0 < before.st_size <= limit:
            raise RecoveryError("Choose a regular, single-link file owned by you within the size limit.")
        chunks = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(fd, min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(fd)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise RecoveryError("Source changed while reading. Pause the bot and retry.")
        raw = b"".join(chunks)
        if not 0 < len(raw) <= limit:
            raise RecoveryError("File size limit exceeded or empty file.")
        return raw
    finally:
        os.close(fd)


def _absent(parent: int, name: str):
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise RecoveryError("Destination already exists. Choose a new name; existing data is never overwritten.")


def _rename_new(parent: int, source: str, target: str):
    # rename() replaces an existing empty directory. Linux RENAME_NOREPLACE is
    # essential, including for targets that appear after the initial check.
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        rename = libc.renameat2
    except AttributeError:
        raise RecoveryError("Atomic no-replace rename is unavailable on this system.") from None
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(parent, os.fsencode(source), parent, os.fsencode(target), 1) != 0:
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise RecoveryError("Destination already exists. Choose a new name; existing data is never overwritten.")
        raise OSError(code, "Atomic no-replace rename failed")


def _write(parent: int, name: str, raw: bytes):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
    try:
        # Set modes only on brand-new files, independent of the invoking umask.
        os.fchmod(fd, 0o600)
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("Write failed")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _sync_published(parent: int) -> bool:
    # Publication succeeded already. A subsequent durability failure must not
    # be misreported as "nothing saved".
    try:
        os.fsync(parent)
        return True
    except OSError:
        return False


def backup(env_path, auth_path, output, password: str) -> bool:
    parent, name = _parent(output, private=True)
    temporary = ".recovery-encrypted-" + uuid.uuid4().hex
    try:
        _absent(parent, name)
        _password(password)
        files = {".env": read_bounded(env_path, LIMITS[".env"])}
        if auth_path:
            files["codex/auth.json"] = read_bounded(auth_path, LIMITS["codex/auth.json"])
        encrypted = encrypt(files, password)
        _write(parent, temporary, encrypted)
        _rename_new(parent, temporary, name)
        return _sync_published(parent)
    finally:
        try:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass
        finally:
            os.close(parent)


def restore(backup_path, output_directory, password: str) -> bool:
    parent, name = _parent(output_directory, private=True)
    temporary = ".recovery-stage-" + uuid.uuid4().hex
    stage = None
    codex = None
    made_stage = False
    made_codex = False
    try:
        _absent(parent, name)
        files = decrypt(read_bounded(backup_path, MAX_PACKAGE), password)
        # Nothing is written before authentication AND payload validation.
        os.mkdir(temporary, 0o700, dir_fd=parent)
        made_stage = True
        stage = os.open(temporary, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        os.fchmod(stage, 0o700)
        _write(stage, ".env", files[".env"])
        if "codex/auth.json" in files:
            os.mkdir("codex", 0o700, dir_fd=stage)
            made_codex = True
            codex = os.open("codex", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=stage)
            os.fchmod(codex, 0o700)
            _write(codex, "auth.json", files["codex/auth.json"])
            os.fsync(codex)
        os.fsync(stage)
        _rename_new(parent, temporary, name)
        made_stage = False
        return _sync_published(parent)
    finally:
        cleanup_failed = False
        def clean(operation, *args, **kwargs):
            nonlocal cleanup_failed
            try:
                operation(*args, **kwargs)
            except FileNotFoundError:
                pass
            except OSError:
                cleanup_failed = True
        try:
            if made_stage and stage is not None:
                if codex is not None:
                    clean(os.unlink, "auth.json", dir_fd=codex)
                if made_codex:
                    clean(os.rmdir, "codex", dir_fd=stage)
                clean(os.unlink, ".env", dir_fd=stage)
            if made_stage:
                clean(os.rmdir, temporary, dir_fd=parent)
        finally:
            try:
                if codex is not None:
                    os.close(codex)
            finally:
                try:
                    if stage is not None:
                        os.close(stage)
                finally:
                    os.close(parent)
        if cleanup_failed:
            raise RecoveryError("Restore did not complete; a private .recovery-stage folder may remain. Inspect the output parent locally before retrying.") from None
