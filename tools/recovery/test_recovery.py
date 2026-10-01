"""Synthetic-only tests. Valid test passwords are randomly generated per run."""
import base64
import json
import os
import secrets
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import recovery_core as r

PASSWORD = secrets.token_urlsafe(32)
ENV = b"DISCORD_TOKEN=DUMMY_NOT_A_REAL_TOKEN\nAI_PROVIDER=codex\n"
AUTH = b'{"dummy_only":true,"token":"DUMMY_AUTH_REVISION_1"}\n'
UPDATED_AUTH = b'{"dummy_only":true,"token":"DUMMY_AUTH_REVISION_2"}\n'


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.package = r.encrypt({".env": ENV, "codex/auth.json": AUTH}, PASSWORD)
        cls.envelope = json.loads(cls.package)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="DUMMY-ONLY-recovery-tests-")
        self.root = Path(self.tmp.name)
        self.env = self.root / "DUMMY-ONLY-env"
        self.auth = self.root / "DUMMY-ONLY-auth"
        self.enc = self.root / "DUMMY-ONLY-backup.encrypted.json"
        self.output = self.root / "restored"
        self.env.write_bytes(ENV)
        self.auth.write_bytes(AUTH)
        self.enc.write_bytes(self.package)

    def tearDown(self):
        self.tmp.cleanup()

    def change(self, **values):
        return r._json({**self.envelope, **values})

    def forged_payload(self, payload):
        header = {k: v for k, v in self.envelope.items() if k != "ciphertext_and_tag"}
        key = r._key(PASSWORD, r._unb64(header["salt"], 16))
        encrypted = AESGCM(key).encrypt(r._unb64(header["nonce"], 12), payload, r._json(header))
        return r._json({**header, "ciphertext_and_tag": r._b64(encrypted)})

    def assert_rejected_without_writes(self, raw=None, password=PASSWORD):
        if raw is not None:
            self.enc.write_bytes(raw)
        before = set(self.root.iterdir())
        with self.assertRaises((r.RecoveryError, OSError)):
            r.restore(self.enc, self.output, password)
        self.assertEqual(set(self.root.iterdir()), before)
        self.assertFalse(self.output.exists())

    def test_roundtrip_and_permissions(self):
        r.restore(self.enc, self.output, PASSWORD)
        self.assertEqual((self.output / ".env").read_bytes(), ENV)
        self.assertEqual((self.output / "codex/auth.json").read_bytes(), AUTH)
        for item, mode in [(self.output, 0o700), (self.output / "codex", 0o700),
                           (self.output / ".env", 0o600), (self.output / "codex/auth.json", 0o600)]:
            self.assertEqual(stat.S_IMODE(item.stat().st_mode), mode)

    def test_updated_backup_restores_new_auth(self):
        target = self.root / "DUMMY-ONLY-new-backup.encrypted.json"
        self.auth.write_bytes(UPDATED_AUTH)
        r.backup(self.env, self.auth, target, PASSWORD)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        updated = json.loads(target.read_bytes())
        self.assertEqual(updated["version"], 2)
        for key in ("salt", "nonce", "backup_id", "ciphertext_and_tag"):
            self.assertNotEqual(updated[key], self.envelope[key])
        r.restore(target, self.output, PASSWORD)
        self.assertEqual((self.output / "codex/auth.json").read_bytes(), UPDATED_AUTH)
        self.assertNotIn(UPDATED_AUTH, target.read_bytes())
        self.assertNotIn(PASSWORD.encode(), target.read_bytes())

    def test_env_only(self):
        target = self.root / "env-only.enc"
        r.backup(self.env, None, target, PASSWORD)
        r.restore(target, self.output, PASSWORD)
        self.assertEqual(set(p.name for p in self.output.iterdir()), {".env"})

    def test_wrong_password(self):
        self.assert_rejected_without_writes(password=PASSWORD + "wrong")

    def test_tampered_ciphertext(self):
        value = bytearray(base64.b64decode(self.envelope["ciphertext_and_tag"]))
        value[len(value) // 2] ^= 1
        self.assert_rejected_without_writes(self.change(ciphertext_and_tag=r._b64(bytes(value))))

    def test_tampered_authenticated_header(self):
        self.assert_rejected_without_writes(self.change(created_at="2026-01-01T00:00:00Z"))

    def test_tampered_nonce(self):
        self.assert_rejected_without_writes(self.change(nonce=r._b64(bytes(12))))

    def test_unsupported_and_expensive_kdf_before_derivation(self):
        with patch.object(r, "Scrypt", side_effect=AssertionError("must not derive")):
            for kdf in ({**r.KDF, "n": 2**30}, {**r.KDF, "p": True}, {**r.KDF, "length": 1}, {}):
                with self.subTest(kdf=kdf):
                    self.assert_rejected_without_writes(self.change(kdf=kdf))

    def test_invalid_versions_and_fields(self):
        for changes in ({"version": 1}, {"version": True}, {"extra": "x"}, {"algorithm": "AES-CBC"}, {"backup_id": "bad"}, {"salt": ""}):
            with self.subTest(changes=changes):
                self.assert_rejected_without_writes(self.change(**changes))

    def test_duplicate_json_keys(self):
        self.assert_rejected_without_writes(self.package.rstrip()[:-1] + b',"version":2}')

    def test_invalid_json_and_encoding(self):
        for raw in (b"", b"{", b"[]", b"null", b"NaN", b"\xff", b"[" * 1200 + b"]" * 1200):
            with self.subTest(raw_length=len(raw)):
                self.assert_rejected_without_writes(raw)

    def test_invalid_base64_and_lengths(self):
        for field, value in (("nonce", "%%%%"), ("salt", r._b64(bytes(17))),
                             ("nonce", r._b64(bytes(11))), ("ciphertext_and_tag", r._b64(bytes(16)))):
            self.assert_rejected_without_writes(self.change(**{field: value}))

    def test_oversize_package(self):
        self.assert_rejected_without_writes(b"x" * (r.MAX_PACKAGE + 1))

    def test_traversal_and_unexpected_payload_names(self):
        for name in ("../outside", "/tmp/outside", "codex/../../outside", "codex/config.toml", "CODEX_HOME/auth.json"):
            with self.subTest(name=name):
                payload = r._json({"payload_version": 1, "files": {".env": r._b64(ENV), name: r._b64(AUTH)}})
                self.assert_rejected_without_writes(self.forged_payload(payload))

    def test_duplicate_inner_keys_and_invalid_payload(self):
        payloads = [b'{"payload_version":1,"files":{".env":"eA==",".env":"eQ=="}}',
                    r._json({"payload_version": True, "files": {".env": r._b64(ENV)}}),
                    r._json({"payload_version": 1, "files": {".env": ""}}),
                    r._json({"payload_version": 1, "files": {"codex/auth.json": r._b64(AUTH)}})]
        for payload in payloads:
            self.assert_rejected_without_writes(self.forged_payload(payload))

    def test_existing_file_and_directory_untouched(self):
        self.output.mkdir()
        marker = self.output / "marker"
        marker.write_bytes(b"KEEP")
        with self.assertRaises(r.RecoveryError):
            r.restore(self.enc, self.output, PASSWORD)
        self.assertEqual(marker.read_bytes(), b"KEEP")
        with self.assertRaises(r.RecoveryError):
            r.backup(self.env, self.auth, self.enc, PASSWORD)
        self.assertEqual(self.enc.read_bytes(), self.package)

    def test_existing_empty_directory_untouched(self):
        self.output.mkdir()
        with self.assertRaises(r.RecoveryError):
            r.restore(self.enc, self.output, PASSWORD)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_destination_created_during_restore_is_not_overwritten(self):
        original = r._rename_new
        def racing(parent, source, target):
            self.output.mkdir()
            original(parent, source, target)
        with patch.object(r, "_rename_new", side_effect=racing), self.assertRaises(r.RecoveryError):
            r.restore(self.enc, self.output, PASSWORD)
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertFalse(any(p.name.startswith(".recovery-") for p in self.root.iterdir()))

    def test_symlink_input_and_ancestor(self):
        alias = self.root / "alias"
        alias.symlink_to(self.enc)
        with self.assertRaises(OSError):
            r.restore(alias, self.output, PASSWORD)
        linked_dir = self.root / "linked"
        linked_dir.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            r.restore(linked_dir / self.enc.name, self.output, PASSWORD)

    def test_symlink_output_and_ancestor(self):
        self.output.symlink_to(self.root / "nonexistent")
        with self.assertRaises(r.RecoveryError):
            r.restore(self.enc, self.output, PASSWORD)
        self.assertTrue(self.output.is_symlink())
        linked = self.root / "linked"
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            r.restore(self.enc, linked / "nested", PASSWORD)

    def test_hardlink_fifo_and_directory_sources(self):
        alias = self.root / "hardlink"
        os.link(self.env, alias)
        with self.assertRaises(r.RecoveryError):
            r.read_bounded(alias, r.LIMITS[".env"])
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        for item in (fifo, self.root):
            with self.assertRaises(r.RecoveryError):
                r.read_bounded(item, 100)

    def test_oversize_and_empty_source(self):
        for data in (b"", b"x" * (r.LIMITS[".env"] + 1)):
            self.env.write_bytes(data)
            with self.assertRaises(r.RecoveryError):
                r.backup(self.env, self.auth, self.root / "new.enc", PASSWORD)
            self.assertFalse((self.root / "new.enc").exists())

    def test_invalid_passwords_and_no_secret_error(self):
        for value in ("short", " " * 20, "x" * 1025, "\0" + "x" * 20):
            with self.assertRaises(r.RecoveryError) as caught:
                r.encrypt({".env": ENV}, value)
            self.assertNotIn(value, str(caught.exception))

    def test_unicode_password(self):
        value = "ダミー専用" + secrets.token_urlsafe(24)
        self.assertEqual(r.decrypt(r.encrypt({".env": ENV}, value), value), {".env": ENV})

    def test_untrusted_output_parent(self):
        parent = self.root / "unsafe"
        parent.mkdir(mode=0o777)
        parent.chmod(0o777)
        with self.assertRaises(r.RecoveryError):
            r.restore(self.enc, parent / "new", PASSWORD)

    def test_parent_traversal_is_rejected(self):
        with self.assertRaises(r.RecoveryError):
            r.restore(self.enc, str(self.root) + "/../outside", PASSWORD)

    def test_failed_write_removes_partial_stage(self):
        original = r._write
        def fail(parent, name, raw):
            original(parent, name, raw)
            if name == "auth.json":
                raise OSError("synthetic disk-full")
        with patch.object(r, "_write", side_effect=fail), self.assertRaises(OSError):
            r.restore(self.enc, self.output, PASSWORD)
        self.assertFalse(self.output.exists())
        self.assertFalse(any(p.name.startswith(".recovery-") for p in self.root.iterdir()))

    def test_failed_backup_write_removes_partial_ciphertext(self):
        target = self.root / "new.enc"
        original = r._write
        def fail(parent, name, raw):
            original(parent, name, raw)
            raise OSError("synthetic disk-full")
        with patch.object(r, "_write", side_effect=fail), self.assertRaises(OSError):
            r.backup(self.env, self.auth, target, PASSWORD)
        self.assertFalse(target.exists())
        self.assertFalse(any(p.name.startswith(".recovery-") for p in self.root.iterdir()))

    def test_failed_codex_open_cleans_empty_directory_and_closes_fds(self):
        original = os.open
        before = len(os.listdir("/proc/self/fd"))
        def fail(path, flags, *args, **kwargs):
            if path == "codex":
                raise OSError("synthetic open failure")
            return original(path, flags, *args, **kwargs)
        with patch.object(r.os, "open", side_effect=fail), self.assertRaises(OSError):
            r.restore(self.enc, self.output, PASSWORD)
        self.assertEqual(len(os.listdir("/proc/self/fd")), before)
        self.assertFalse(any(p.name.startswith(".recovery-") for p in self.root.iterdir()))

    def test_cleanup_error_is_explicit_and_fds_close(self):
        original_write, original_unlink = r._write, os.unlink
        before = len(os.listdir("/proc/self/fd"))
        def fail_write(parent, name, raw):
            original_write(parent, name, raw)
            if name == "auth.json":
                raise OSError("synthetic write failure")
        def fail_unlink(path, *args, **kwargs):
            if path == "auth.json":
                raise OSError("synthetic cleanup failure")
            return original_unlink(path, *args, **kwargs)
        with patch.object(r, "_write", side_effect=fail_write), patch.object(r.os, "unlink", side_effect=fail_unlink):
            with self.assertRaisesRegex(r.RecoveryError, "private .recovery-stage folder may remain"):
                r.restore(self.enc, self.output, PASSWORD)
        self.assertEqual(len(os.listdir("/proc/self/fd")), before)
        self.assertFalse(self.output.exists())

    def test_parent_fsync_after_publication_returns_durability_warning(self):
        original = r.os.fsync
        def fail_parent(fd):
            if os.fstat(fd).st_ino == self.root.stat().st_ino:
                raise OSError("synthetic fsync failure")
            return original(fd)
        with patch.object(r.os, "fsync", side_effect=fail_parent):
            self.assertFalse(r.restore(self.enc, self.output, PASSWORD))
            self.assertFalse(r.backup(self.env, self.auth, self.root / "new.enc", PASSWORD))
        self.assertEqual((self.output / ".env").read_bytes(), ENV)
        self.assertTrue((self.root / "new.enc").is_file())

    def test_staging_remains_private_with_permissive_umask(self):
        before = os.umask(0)
        try:
            r.restore(self.enc, self.output, PASSWORD)
        finally:
            os.umask(before)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.output / ".env").stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main(verbosity=2)
