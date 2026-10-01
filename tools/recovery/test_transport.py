"""Local-only synthetic transport tests; no real credential read or Library call."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

import auto_envelope as envelope
import recovery_core as recovery
import transport


class TransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Only a runtime-generated test password and public dummy payloads.
        cls.recipient = envelope.create_recipient(secrets.token_urlsafe(32))
        cls.pin = envelope.recipient_digest(cls.recipient)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="ciphertext-transport-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.outbox = self.root / "outbox"
        self.outbox.mkdir(mode=0o700)
        self.state = {"format": "discord-autobackup-bridge-state", "version": 1,
                      "library_file_id": "libfile_SYNTHETIC_TEST_ONLY", "library_version": 8,
                      "last_uploaded_snapshot_id": None, "last_uploaded_sequence": 0,
                      "recipient_sha256": self.pin}
        self.write_json(self.root / transport.STATE_FILE, self.state)
        self.publish()

    def write_bytes(self, path, raw):
        path.write_bytes(raw)
        path.chmod(0o600)

    def write_json(self, path, value):
        self.write_bytes(path, recovery._json(value) + b"\n")

    def read_json(self, name):
        return json.loads((self.root / name).read_bytes())

    def publish(self, sequence=1):
        self.raw = envelope.encrypt_snapshot({".env": b"DUMMY_ONLY=yes\n"},
                                              self.recipient, self.pin, sequence=sequence)
        package = json.loads(self.raw)
        self.manifest = {"format": "discord-autobackup-manifest", "version": 1,
                         **{key: package[key] for key in ("snapshot_id", "sequence", "created_at")},
                         "file_name": "snapshot-" + package["snapshot_id"] + ".encrypted.json",
                         "size_bytes": len(self.raw), "sha256": hashlib.sha256(self.raw).hexdigest(),
                         "recipient_sha256": self.pin}
        self.write_bytes(self.outbox / self.manifest["file_name"], self.raw)
        self.write_json(self.outbox / "latest.json", self.manifest)

    def response(self, prepared, *, full=True):
        metadata = {"operation": "replace_library_file", "status": "succeeded",
                    "library_file_id": prepared["library_file_id"],
                    "current_version_number": prepared["expected_current_version"] + 1,
                    "file_size_bytes": prepared["size_bytes"],
                    "file_id": "file_SYNTHETIC_ONLY", "file_name": "synthetic.encrypted.json",
                    "path": "/synthetic.encrypted.json", "restored_from_version_number": None,
                    "xattrs": [{"name": "ignored-attribute", "value": "IGNORED_TEST_VALUE"}],
                    "download_url": "https://example.invalid/DO_NOT_PERSIST_SYNTHETIC_SIGNED_URL"}
        return {"request_id": prepared["request_id"], "snapshot_id": prepared["snapshot_id"],
                "sha256": prepared["sha256"],
                "library_response": {"isError": False, "structuredContent": metadata,
                                     "content": [{"type": "text", "text": "ignored"}]} if full else metadata}

    def assert_pending_only(self):
        self.assertTrue((self.root / transport.PENDING_FILE).exists())
        self.assertFalse((self.root / transport.RECEIPT_FILE).exists())
        self.assertEqual(self.read_json(transport.STATE_FILE), self.state)

    def test_real_writer_contract_integrates_with_transport_on_dummy_sources(self):
        import automatic_backup as writer
        source = self.root / "synthetic-sources"
        source.mkdir(mode=0o700)
        self.write_bytes(source / ".env", b"DUMMY_ONLY=writer-contract-test\n")
        self.write_bytes(source / "auth.json", b'{"dummy_only":true,"revision":2}\n')
        self.write_bytes(self.root / "recipient.json", self.recipient)
        self.write_json(self.root / "watcher-config.json", {
            "format": "discord-autobackup-config", "version": 1,
            "env_path": str(source / ".env"), "auth_path": str(source / "auth.json"),
            "recipient_sha256": self.pin})
        manifest, _ = writer.publish_snapshot(self.root)
        self.assertEqual(manifest["sequence"], 2)
        prepared = transport.prepare(self.root)
        self.assertEqual(prepared["sha256"], manifest["sha256"])
        self.assertEqual(prepared["snapshot_id"], manifest["snapshot_id"])
        transport.confirm(self.root, self.response(prepared))
        self.assertEqual(transport.prepare(self.root)["status"], "noop")

    def test_initial_library_version_zero_to_one(self):
        self.state["library_version"] = 0
        self.write_json(self.root / transport.STATE_FILE, self.state)
        prepared = transport.prepare(self.root)
        self.assertEqual(prepared["expected_current_version"], 0)
        confirmed = transport.confirm(self.root, self.response(prepared))
        self.assertEqual(confirmed["library_version"], 1)
        self.assertEqual(transport.prepare(self.root)["status"], "noop")

    def test_created_item_receipt_at_version_zero_can_advance(self):
        self.state.update(library_version=0, last_uploaded_snapshot_id=self.manifest["snapshot_id"],
                          last_uploaded_sequence=self.manifest["sequence"])
        self.write_json(self.root / transport.STATE_FILE, self.state)
        receipt = {"format": "discord-autobackup-upload-receipt", "version": 1,
                   "request_id": str(uuid.uuid4()), "library_file_id": self.state["library_file_id"],
                   "library_version": 0,
                   **{key: self.manifest[key] for key in ("snapshot_id", "sequence", "created_at",
                                                         "size_bytes", "sha256", "recipient_sha256")},
                   "confirmed_at": self.manifest["created_at"]}
        self.write_json(self.root / transport.RECEIPT_FILE, receipt)
        self.assertEqual(transport.prepare(self.root)["status"], "noop")
        self.publish(sequence=2)
        prepared = transport.prepare(self.root)
        self.assertEqual(prepared["expected_current_version"], 0)
        self.assertEqual(transport.confirm(self.root, self.response(prepared))["library_version"], 1)

    def test_legacy_flat_pending_upload_can_still_be_confirmed(self):
        prepared = transport.prepare(self.root)
        pending = self.read_json(transport.PENDING_FILE)
        legacy_name = "upload-" + prepared["request_id"] + ".encrypted.json"
        Path(prepared["file"]).rename(self.root / legacy_name)
        self.write_json(self.root / transport.PENDING_FILE, {**pending, "upload_file_name": legacy_name})
        self.assertEqual(transport.confirm(self.root, self.response(prepared))["status"], "confirmed")
        self.assertEqual((self.root / legacy_name).read_bytes(), self.raw)

    def test_prepare_returns_staged_ciphertext_and_trusted_guard(self):
        prepared = transport.prepare(self.root)
        self.assertEqual(prepared["status"], "ready")
        self.assertEqual(prepared["library_file_id"], self.state["library_file_id"])
        self.assertEqual(prepared["expected_current_version"], 8)
        self.assertEqual(prepared["sha256"], self.manifest["sha256"])
        self.assertEqual(Path(prepared["file"]).parent, self.root / ("upload-" + prepared["request_id"]))
        self.assertEqual(Path(prepared["file"]).name, "discord-backup.encrypted.json")
        self.assertEqual(Path(prepared["file"]).parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.read_json(transport.PENDING_FILE)["upload_file_name"],
                         "upload-" + prepared["request_id"] + "/" + transport.UPLOAD_BASENAME)
        self.assertEqual(Path(prepared["file"]).read_bytes(), self.raw)
        self.assertEqual(Path(prepared["file"]).stat().st_mode & 0o777, 0o600)
        self.assert_pending_only()

    def test_happy_path_receipt_noop_and_newer_snapshot(self):
        prepared = transport.prepare(self.root)
        confirmed = transport.confirm(self.root, recovery._json(self.response(prepared)))
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(confirmed["library_version"], 9)
        self.assertFalse((self.root / transport.PENDING_FILE).exists())
        receipt = self.read_json(transport.RECEIPT_FILE)
        self.assertEqual(set(receipt), transport.RECEIPT_KEYS)
        self.assertEqual(receipt["sha256"], prepared["sha256"])
        # Neither raw service metadata, URL, nor xattrs enters local state.
        for name in (transport.STATE_FILE, transport.RECEIPT_FILE):
            saved = (self.root / name).read_bytes()
            self.assertNotIn(b"DO_NOT_PERSIST", saved)
            self.assertNotIn(b"IGNORED_TEST_VALUE", saved)
        self.assertEqual(transport.prepare(self.root)["status"], "noop")
        self.assertTrue(Path(prepared["file"]).exists())
        self.publish(sequence=4)  # Coalescing skips intermediate snapshots.
        newer = transport.prepare(self.root)
        self.assertEqual(newer["expected_current_version"], 9)
        self.assertEqual(newer["sequence"], 4)
        self.assertEqual(Path(newer["file"]).name, Path(prepared["file"]).name)
        self.assertNotEqual(Path(newer["file"]).parent, Path(prepared["file"]).parent)
        transport.confirm(self.root, self.response(newer, full=False))
        self.assertEqual(self.read_json(transport.STATE_FILE)["library_version"], 10)

    def test_existing_pending_blocks_even_if_corrupt_or_symlink(self):
        transport.prepare(self.root)
        for raw in (b"not JSON", b"{}", b"{}" * 10000):
            with self.subTest(kind=len(raw)):
                self.write_bytes(self.root / transport.PENDING_FILE, raw)
                with self.assertRaisesRegex(transport.TransportError, "pending or uncertain"):
                    transport.prepare(self.root)
        (self.root / transport.PENDING_FILE).unlink()
        (self.root / transport.PENDING_FILE).symlink_to("missing")
        with self.assertRaisesRegex(transport.TransportError, "pending or uncertain"):
            transport.prepare(self.root)

    def test_manifest_cannot_control_destination_or_path(self):
        for modification in ({"library_file_id": "libfile_ATTACKER"},
                             {"file_name": "../bridge-state.json"},
                             {"file_name": str(self.root / "bridge-state.json")},
                             {"file_name": "snapshot-other.encrypted.json"}):
            with self.subTest(modification=modification):
                self.write_json(self.outbox / "latest.json", {**self.manifest, **modification})
                with self.assertRaises(recovery.RecoveryError):
                    transport.prepare(self.root)
                self.assertFalse((self.root / transport.PENDING_FILE).exists())

    def test_manifest_checks_types_bounds_and_fields(self):
        modifications = ({"version": True}, {"sequence": True}, {"sequence": 0},
                         {"sequence": 2**53}, {"size_bytes": True}, {"size_bytes": 0},
                         {"size_bytes": recovery.MAX_PACKAGE + 1}, {"created_at": "2026-02-30T00:00:00Z"},
                         {"snapshot_id": "../auth.json"}, {"recipient_sha256": "0" * 64},
                         {"sha256": "A" * 64}, {"unexpected": 1})
        for modification in modifications:
            with self.subTest(modification=modification):
                self.write_json(self.outbox / "latest.json", {**self.manifest, **modification})
                with self.assertRaises(recovery.RecoveryError):
                    transport.prepare(self.root)

    def test_strict_duplicate_json_rejected(self):
        self.write_bytes(self.outbox / "latest.json", recovery._json(self.manifest)[:-1] + b',"version":1}')
        with self.assertRaises(recovery.RecoveryError):
            transport.prepare(self.root)

    def test_manifest_hash_and_size_mismatch_rejected(self):
        for modification in ({"size_bytes": self.manifest["size_bytes"] + 1}, {"sha256": "0" * 64}):
            with self.subTest(modification=modification):
                self.write_json(self.outbox / "latest.json", {**self.manifest, **modification})
                with self.assertRaisesRegex(transport.TransportError, "digest"):
                    transport.prepare(self.root)

    def test_matching_hash_still_rejects_non_ciphertext(self):
        raw = b'{"DUMMY_ONLY":"synthetic plaintext must never be uploaded"}'
        self.write_bytes(self.outbox / self.manifest["file_name"], raw)
        self.write_json(self.outbox / "latest.json", {**self.manifest, "size_bytes": len(raw),
                                                     "sha256": hashlib.sha256(raw).hexdigest()})
        with self.assertRaises(recovery.RecoveryError):
            transport.prepare(self.root)

    def test_v3_identity_must_match_manifest(self):
        for modification in ({"sequence": 2}, {"created_at": "2020-01-01T00:00:00Z"}):
            with self.subTest(modification=modification):
                self.write_json(self.outbox / "latest.json", {**self.manifest, **modification})
                with self.assertRaisesRegex(transport.TransportError, "identity"):
                    transport.prepare(self.root)

    def test_pinned_recipient_is_validated_inside_ciphertext(self):
        changed = json.loads(self.raw)
        changed["recipient"]["recovery_series_id"] = str(uuid.uuid4())
        changed["recipient"]["recovery"]["recovery_series_id"] = changed["recipient"]["recovery_series_id"]
        raw = recovery._json(changed)
        self.write_bytes(self.outbox / self.manifest["file_name"], raw)
        self.write_json(self.outbox / "latest.json", {**self.manifest, "size_bytes": len(raw),
                                                     "sha256": hashlib.sha256(raw).hexdigest()})
        with self.assertRaisesRegex(recovery.RecoveryError, "recipient"):
            transport.prepare(self.root)

    def test_staging_survives_outbox_advance_and_source_removal(self):
        prepared = transport.prepare(self.root)
        old_raw = self.raw
        (self.outbox / self.manifest["file_name"]).unlink()
        self.publish(sequence=2)
        self.assertEqual(Path(prepared["file"]).read_bytes(), old_raw)
        transport.confirm(self.root, self.response(prepared))
        self.assertEqual(self.read_json(transport.STATE_FILE)["last_uploaded_sequence"], 1)
        newer = transport.prepare(self.root)
        self.assertEqual(newer["sequence"], 2)

    def test_tampered_staging_cannot_be_confirmed(self):
        prepared = transport.prepare(self.root)
        path = Path(prepared["file"])
        self.write_bytes(path, path.read_bytes() + b" ")
        with self.assertRaises(recovery.RecoveryError):
            transport.confirm(self.root, self.response(prepared))
        self.assert_pending_only()

    def test_unknown_failed_wrong_version_or_target_never_writes_receipt(self):
        prepared = transport.prepare(self.root)
        good = self.response(prepared, full=False)
        responses = [{}, {"status": "success"},
                     {**good["library_response"], "status": "failed"},
                     {**good["library_response"], "operation": "create_library_file"},
                     {**good["library_response"], "library_file_id": "libfile_OTHER"},
                     {**good["library_response"], "current_version_number": 8},
                     {**good["library_response"], "current_version_number": 10},
                     {**good["library_response"], "current_version_number": True},
                     {**good["library_response"], "file_size_bytes": prepared["size_bytes"] + 1},
                     {**good["library_response"], "error": "something failed"},
                     {"isError": True, "structuredContent": good["library_response"]},
                     {"isError": False, "structuredContent": good["library_response"], "error": "ambiguous"},
                     {"structuredContent": good["library_response"]},
                     {"isError": False, "content": [{"type": "text", "text": json.dumps(good["library_response"])}]},
                     {"isError": False, "structuredContent": {"structuredContent": good["library_response"]}}]
        for response in responses:
            with self.subTest(response=response):
                with self.assertRaises(recovery.RecoveryError):
                    transport.confirm(self.root, {**good, "library_response": response})
                self.assert_pending_only()

    def test_confirmation_correlation_and_unknown_fields(self):
        prepared = transport.prepare(self.root)
        good = self.response(prepared)
        for changes in ({"request_id": str(uuid.uuid4())}, {"snapshot_id": str(uuid.uuid4())},
                        {"sha256": "0" * 64}, {"sha256": True}, {"extra": "not allowed"}):
            with self.subTest(changes=changes), self.assertRaises(recovery.RecoveryError):
                transport.confirm(self.root, {**good, **changes})
            self.assert_pending_only()

    def test_confirmation_is_one_use_and_stale_response_cannot_confirm_next(self):
        prepared = transport.prepare(self.root)
        old_response = self.response(prepared)
        transport.confirm(self.root, old_response)
        with self.assertRaisesRegex(transport.TransportError, "stale"):
            transport.confirm(self.root, old_response)
        self.publish(sequence=2)
        newer = transport.prepare(self.root)
        with self.assertRaisesRegex(transport.TransportError, "pending snapshot"):
            transport.confirm(self.root, old_response)
        self.assertEqual(self.read_json(transport.PENDING_FILE)["request_id"], newer["request_id"])

    def test_state_change_while_pending_requires_reconciliation(self):
        prepared = transport.prepare(self.root)
        self.write_json(self.root / transport.STATE_FILE, {**self.state, "library_version": 9})
        with self.assertRaisesRegex(transport.TransportError, "state changed"):
            transport.confirm(self.root, self.response(prepared))
        self.assertTrue((self.root / transport.PENDING_FILE).exists())
        self.assertFalse((self.root / transport.RECEIPT_FILE).exists())

    def test_stale_sequence_and_reused_sequence_fail(self):
        self.publish(sequence=3)
        prepared = transport.prepare(self.root)
        transport.confirm(self.root, self.response(prepared))
        self.publish(sequence=2)
        with self.assertRaisesRegex(transport.TransportError, "stale"):
            transport.prepare(self.root)
        self.publish(sequence=3)
        with self.assertRaisesRegex(transport.TransportError, "reused"):
            transport.prepare(self.root)

    def test_same_snapshot_with_modified_ciphertext_is_not_noop(self):
        prepared = transport.prepare(self.root)
        transport.confirm(self.root, self.response(prepared))
        raw = self.raw + b" "
        self.write_bytes(self.outbox / self.manifest["file_name"], raw)
        self.write_json(self.outbox / "latest.json", {**self.manifest, "size_bytes": len(raw),
                                                     "sha256": hashlib.sha256(raw).hexdigest()})
        with self.assertRaisesRegex(transport.TransportError, "reused"):
            transport.prepare(self.root)

    def test_corrupt_and_missing_confirmed_history_block_new_upload(self):
        prepared = transport.prepare(self.root)
        transport.confirm(self.root, self.response(prepared))
        self.publish(sequence=2)
        receipt = self.read_json(transport.RECEIPT_FILE)
        self.write_json(self.root / transport.RECEIPT_FILE, {**receipt, "library_version": 1})
        with self.assertRaisesRegex(transport.TransportError, "inconsistent"):
            transport.prepare(self.root)
        (self.root / transport.RECEIPT_FILE).unlink()
        with self.assertRaisesRegex(transport.TransportError, "missing"):
            transport.prepare(self.root)

    def test_lock_prevents_overlap_and_pending_prevents_second_authorization(self):
        with transport._locked(self.root):
            with self.assertRaisesRegex(transport.TransportError, "active"):
                transport.prepare(self.root)
        barrier = threading.Barrier(2)
        results = []
        def attempt():
            barrier.wait()
            try:
                results.append(transport.prepare(self.root)["status"])
            except recovery.RecoveryError:
                results.append("blocked")
        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertCountEqual(results, ["ready", "blocked"])

    def test_path_symlinks_and_hardlinks_rejected(self):
        source = self.outbox / self.manifest["file_name"]
        target = self.root / "synthetic-copy"
        self.write_bytes(target, self.raw)
        source.unlink()
        source.symlink_to(target)
        with self.assertRaises(recovery.RecoveryError):
            transport.prepare(self.root)
        source.unlink()
        os.link(target, source)
        with self.assertRaises(recovery.RecoveryError):
            transport.prepare(self.root)
        with self.assertRaises(recovery.RecoveryError):
            transport.prepare(self.root / "outbox" / "..")

    def test_private_directory_and_state_permissions(self):
        self.outbox.chmod(0o755)
        with self.assertRaisesRegex(transport.TransportError, "private"):
            transport.prepare(self.root)
        self.outbox.chmod(0o700)
        (self.root / transport.STATE_FILE).chmod(0o644)
        with self.assertRaisesRegex(transport.TransportError, "private"):
            transport.prepare(self.root)

    def test_invalid_state_types_and_unknown_destination_metadata(self):
        for changes in ({"library_version": True}, {"library_version": -1},
                        {"last_uploaded_sequence": 1}, {"recipient_sha256": "not a hash"},
                        {"library_file_id": "https://example.invalid/path"}, {"extra": 1}):
            with self.subTest(changes=changes):
                self.write_json(self.root / transport.STATE_FILE, {**self.state, **changes})
                with self.assertRaises(recovery.RecoveryError):
                    transport.prepare(self.root)

    def test_confirm_bounds_duplicate_keys_and_empty_input(self):
        prepared = transport.prepare(self.root)
        good = recovery._json(self.response(prepared))
        for raw in (b"", b"x" * (transport.MAX_CONFIRMATION + 1),
                    good[:-1] + b',"request_id":"duplicate"}'):
            with self.subTest(length=len(raw)), self.assertRaises(recovery.RecoveryError):
                transport.confirm(self.root, raw)
            self.assert_pending_only()

    def test_pending_publication_failure_never_returns_authorization(self):
        original = transport._atomic_json
        def fail_pending(fd, name, value, **kwargs):
            if name == transport.PENDING_FILE:
                raise OSError("synthetic fault")
            return original(fd, name, value, **kwargs)
        with patch.object(transport, "_atomic_json", side_effect=fail_pending):
            with self.assertRaises(OSError):
                transport.prepare(self.root)
        self.assertFalse((self.root / transport.PENDING_FILE).exists())
        self.assertEqual(self.read_json(transport.STATE_FILE), self.state)

    def test_staging_capacity_stops_without_deleting_existing_backups(self):
        retained = self.root / ("upload-" + str(uuid.uuid4()) + ".encrypted.json")
        self.write_bytes(retained, self.raw)
        with patch.object(transport, "MAX_STAGED_UPLOADS", 1):
            with self.assertRaisesRegex(transport.TransportError, "capacity"):
                transport.prepare(self.root)
        self.assertEqual(retained.read_bytes(), self.raw)
        self.assertFalse((self.root / transport.PENDING_FILE).exists())
        self.assertEqual(self.read_json(transport.STATE_FILE), self.state)

    def test_retention_counts_new_directories_and_preserves_legacy_flat_files(self):
        legacy = self.root / ("upload-" + str(uuid.uuid4()) + ".encrypted.json")
        self.write_bytes(legacy, self.raw)
        retained_directory = self.root / ("upload-" + str(uuid.uuid4()))
        retained_directory.mkdir(mode=0o700)
        self.write_bytes(retained_directory / transport.UPLOAD_BASENAME, self.raw)
        with patch.object(transport, "MAX_STAGED_UPLOADS", 2):
            with self.assertRaisesRegex(transport.TransportError, "capacity"):
                transport.prepare(self.root)
        self.assertEqual(legacy.read_bytes(), self.raw)
        self.assertEqual((retained_directory / transport.UPLOAD_BASENAME).read_bytes(), self.raw)
        self.assertFalse((self.root / transport.PENDING_FILE).exists())

    def test_staged_directory_symlink_and_unsafe_permissions_block_confirmation(self):
        prepared = transport.prepare(self.root)
        directory = Path(prepared["file"]).parent
        directory.chmod(0o755)
        with self.assertRaisesRegex(transport.TransportError, "private"):
            transport.confirm(self.root, self.response(prepared))
        directory.chmod(0o700)
        moved = self.root / "synthetic-moved-stage"
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(OSError):
            transport.confirm(self.root, self.response(prepared))
        self.assert_pending_only()

    def test_pending_path_cannot_escape_its_request_directory(self):
        prepared = transport.prepare(self.root)
        pending = self.read_json(transport.PENDING_FILE)
        for name in ("../" + transport.UPLOAD_BASENAME,
                     "upload-" + str(uuid.uuid4()) + "/" + transport.UPLOAD_BASENAME,
                     "upload-" + prepared["request_id"] + "/../" + transport.UPLOAD_BASENAME):
            self.write_json(self.root / transport.PENDING_FILE, {**pending, "upload_file_name": name})
            with self.assertRaises(recovery.RecoveryError):
                transport.confirm(self.root, self.response(prepared))
            self.assert_pending_only()

    def test_commit_interruption_preserves_pending_and_blocks_upload(self):
        prepared = transport.prepare(self.root)
        original = transport._atomic_json
        def fail_state(fd, name, value, **kwargs):
            if name == transport.STATE_FILE:
                raise OSError("synthetic fault after confirmed receipt")
            return original(fd, name, value, **kwargs)
        with patch.object(transport, "_atomic_json", side_effect=fail_state):
            with self.assertRaises(OSError):
                transport.confirm(self.root, self.response(prepared))
        self.assertTrue((self.root / transport.PENDING_FILE).exists())
        self.assertTrue((self.root / transport.RECEIPT_FILE).exists())
        self.assertEqual(self.read_json(transport.STATE_FILE), self.state)
        with self.assertRaisesRegex(transport.TransportError, "pending or uncertain"):
            transport.prepare(self.root)
        with self.assertRaisesRegex(transport.TransportError, "inconsistent"):
            transport.confirm(self.root, self.response(prepared))

    def test_cli_json_stdin_stdout_and_safe_errors(self):
        command = [sys.executable, str(Path(transport.__file__)), "prepare", str(self.root)]
        result = subprocess.run(command, check=True, capture_output=True)
        prepared = json.loads(result.stdout)
        result = subprocess.run([*command[:2], "confirm", str(self.root)],
                                input=recovery._json(self.response(prepared)), capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout)["status"], "confirmed")
        result = subprocess.run(command, check=True, capture_output=True)
        self.assertEqual(json.loads(result.stdout)["status"], "noop")
        result = subprocess.run([*command[:2], "confirm", str(self.root)],
                                input=b"SYNTHETIC_SECRET_DO_NOT_ECHO", capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(b"SYNTHETIC_SECRET", result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stderr)["status"], "blocked")


if __name__ == "__main__":
    unittest.main(verbosity=2)
