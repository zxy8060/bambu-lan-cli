"""Offline safety regression tests for the installed dispatcher. No device writes."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from bambu_a1 import a1_print as p


@unittest.skipUnless(os.name == "nt", "Windows dispatcher and file locks")
class DispatchGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.job = "a" * 32
        self.folder = self.root / "jobs" / self.job
        self.folder.mkdir(parents=True)
        self.model = self.root / "job.gcode.3mf"
        self.model.write_bytes(b"offline synthetic print bytes")
        self.bed = self.folder / "bed.jpg"
        self.bed.write_bytes(b"offline image identity")
        self.manifest = {
            "format": 1,
            "job_id": self.job,
            "target_serial": "offline-A1",
            "file": str(self.model),
            "sha256": hashlib.sha256(self.model.read_bytes()).hexdigest(),
            "bed_file": str(self.bed),
            "bed_sha256": hashlib.sha256(self.bed.read_bytes()).hexdigest(),
            "prepared_at": time.time(),
            "slot": 2,
        }
        self.save()
        self.patches = [
            patch.object(p, "JOBS", self.root / "jobs"),
            patch.object(p.lan, "DATA", self.root),
            patch.object(p.lan, "config", return_value={"serial": "offline-A1"}),
            patch.object(
                p.a1, "preflight", side_effect=AssertionError("Unexpected device read")
            ),
            patch.object(
                p, "publish", side_effect=AssertionError("Unexpected device write")
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def save(self):
        (self.folder / "manifest.json").write_text(json.dumps(self.manifest))

    def dispatch(self):
        return p.dispatch(self.job, self.manifest["bed_sha256"])

    def test_duplicate_receipt_blocks_before_network(self):
        (self.folder / "receipt.json").write_text("{}")
        with self.assertRaises(RuntimeError):
            self.dispatch()

    def test_wrong_device_blocks(self):
        self.manifest["target_serial"] = "another-device"
        self.save()
        with self.assertRaises(ValueError):
            self.dispatch()

    def test_changed_job_blocks(self):
        self.model.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.dispatch()

    def test_changed_camera_frame_blocks(self):
        self.bed.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.dispatch()

    def test_stale_review_blocks(self):
        self.manifest["prepared_at"] -= 301
        self.save()
        with self.assertRaises(ValueError):
            self.dispatch()

    def test_path_traversal_job_id_blocks(self):
        with self.assertRaises(ValueError):
            p.get_job("../manifest")

    def test_sequence_is_persisted_valid_json(self):
        self.assertEqual(p.allocate_sequence(), "20000")
        self.assertEqual(p.allocate_sequence(), "20001")
        self.assertEqual(
            json.loads((self.root / "signing-sequence.json").read_bytes())["next"],
            20002,
        )

    def test_sequence_outside_verified_window_blocks(self):
        (self.root / "signing-sequence.json").write_text('{"next":30000}')
        with self.assertRaises(RuntimeError):
            p.allocate_sequence()

    def test_concurrent_dispatch_lock_blocks(self):
        with p.printer_lock():
            with self.assertRaises(OSError):
                with p.printer_lock():
                    pass

    def test_busy_prepare_has_no_job_or_camera_side_effect(self):
        with (
            patch.object(
                p.a1,
                "preflight",
                return_value={"checks_passed": False, "failures": ["busy"]},
            ),
            patch.object(
                p.lan, "camera", side_effect=AssertionError("Camera should not be used")
            ),
        ):
            result = p.prepare(self.model, 2)
        self.assertEqual(result["state"], "preflight_failed")
        self.assertEqual(len(list((self.root / "jobs").iterdir())), 1)

    def test_same_label_on_old_file_is_not_new_job(self):
        self.assertFalse(
            p.matches_remote_job(
                {"subtask_name": "repeated label", "gcode_file": "old.gcode.3mf"},
                "codex_new.gcode.3mf",
            )
        )

    def test_unique_remote_filename_matches_with_path(self):
        self.assertTrue(
            p.matches_remote_job(
                {"gcode_file": "/sdcard/codex_new.gcode.3mf"}, "codex_new.gcode.3mf"
            )
        )

    def test_missing_filename_does_not_claim_started(self):
        self.assertFalse(
            p.matches_remote_job(
                {"subtask_name": "repeated label"}, "codex_new.gcode.3mf"
            )
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
