"""Run the public orchestration with fake network peers, never real devices."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from bambu_a1 import a1_print as p
from bambu_a1.filament import route, calibration_flags
from bambu_a1.signed_lan import cert_id
from test_protocol import certificate


@unittest.skipUnless(os.name == "nt", "Windows dispatcher")
class DispatchFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.cert = certificate(cls.key)
        device_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.device = certificate(device_key, "offline-device").public_bytes(
            serialization.Encoding.DER
        )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.job = "b" * 32
        self.folder = self.root / "jobs" / self.job
        self.folder.mkdir(parents=True)
        self.content = b"opaque synthetic reviewed file"
        model = self.root / "synthetic.gcode.3mf"
        model.write_bytes(self.content)
        bed = self.folder / "bed.jpg"
        bed.write_bytes(b"synthetic reviewed frame")
        self.tray = {
            "id": "1",
            "tray_type": "PLA",
            "tray_color": "000000FF",
            "tray_info_idx": "offline",
        }
        self.manifest = {
            "format": 2,
            "job_id": self.job,
            "target_serial": "offline-A1",
            "file": str(model),
            "sha256": hashlib.sha256(self.content).hexdigest(),
            "slot": 2,
            "ams_id": 0,
            "external": False,
            "routing": route(2),
            "target_machine": {"model": "Bambu Lab A1"},
            "calibration": calibration_flags("Bambu Lab A1"),
            "bed_file": str(bed),
            "bed_sha256": hashlib.sha256(bed.read_bytes()).hexdigest(),
            "prepared_at": time.time(),
            "bed_captured_at": time.time(),
            "tray": self.tray,
            "task_name": "offline flow test",
        }
        (self.folder / "manifest.json").write_text(json.dumps(self.manifest))
        self.check = {
            "checks_passed": True,
            "file": {"material": "PLA"},
            "selected_tray": self.tray,
            "target_machine": self.manifest["target_machine"],
            "routing": self.manifest["routing"],
            "target_serial": self.manifest["target_serial"],
        }
        self.remote = "a1cli_" + self.job + ".gcode.3mf"
        self.live = {
            "status": {
                "gcode_state": "RUNNING",
                "gcode_file": self.remote,
                "subtask_name": "offline flow test",
            }
        }
        self.sent, self.uploaded = [], {}
        case = self

        class FakeFTP:
            def __init__(self, cfg):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def connect(self):
                pass

            def login(self, *args):
                pass

            def prot_p(self):
                pass

            def upload_new(self, remote, data):
                case.uploaded[remote] = data

            def readback(self, remote, size):
                return case.uploaded[remote]

        class FakeSocket:
            def getpeercert(self, binary_form=False):
                return case.device

        class FakeConnection:
            def __init__(self, cfg):
                self.sock = FakeSocket()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        def sent(conn, wire):
            receipt = json.loads((self.folder / "receipt.json").read_text())
            self.assertEqual(receipt["state"], "dispatch_about_to_send")
            self.sent.append(json.loads(wire))

        self.patches = [
            patch.object(p, "JOBS", self.root / "jobs"),
            patch.object(p.lan, "DATA", self.root),
            patch.object(p.lan, "config", return_value={"serial": "offline-A1"}),
            patch.object(p.lan, "credentials", return_value=("offline-A1", "A1B2C3D4")),
            patch.object(p.a1, "preflight", return_value=self.check),
            patch.object(p.vault, "load", return_value=(self.cert, self.key, {})),
            patch.object(p, "VerifiedFTPS", FakeFTP),
            patch.object(p.lan, "Connection", FakeConnection),
            patch.object(p, "app_cert_ids", return_value={cert_id(self.cert)}),
            patch.object(p, "publish", side_effect=sent),
            patch.object(
                p,
                "next_message",
                return_value={
                    "print": {
                        "command": "project_file",
                        "sequence_id": "20000",
                        "result": "success",
                    }
                },
            ),
            patch.object(p.lan, "status", return_value=self.live),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def dispatch(self):
        return p.dispatch(self.job, self.manifest["bed_sha256"])

    def test_single_send_receipt_precedes_publish_and_remote_matches(self):
        result = self.dispatch()
        self.assertTrue(result["print_started"])
        self.assertEqual(len(self.sent), 1)
        request = self.sent[0]["print"]
        self.assertEqual(request["ams_mapping"], [1])
        self.assertEqual(request["file"], self.remote)
        self.assertNotIn("url", request)
        self.assertIn("url_enc", request)
        with self.assertRaises(RuntimeError):
            self.dispatch()
        self.assertEqual(len(self.sent), 1)

    def test_send_error_retains_receipt_and_blocks_retry(self):
        with patch.object(
            p, "publish", side_effect=ConnectionError("synthetic disconnect")
        ):
            result = self.dispatch()
        self.assertEqual(result["state"], "outcome_requires_inspection_do_not_resend")
        self.assertIsNone(result["print_started"])
        with self.assertRaises(RuntimeError):
            self.dispatch()

    def test_post_upload_busy_does_not_publish(self):
        with patch.object(
            p.a1, "preflight", side_effect=[self.check, {"checks_passed": False}]
        ):
            result = self.dispatch()
        self.assertFalse(result["print_started"])
        self.assertEqual(self.sent, [])

    def test_lost_trust_does_not_publish(self):
        with patch.object(p, "app_cert_ids", return_value=set()):
            result = self.dispatch()
        self.assertFalse(result["print_started"])
        self.assertEqual(self.sent, [])

    def test_petg_from_second_ams_is_dispatched(self):
        self.tray["tray_type"] = self.check["file"]["material"] = "PETG"
        self.manifest["ams_id"] = 1
        self.manifest["routing"] = self.check["routing"] = route(2, 1)
        (self.folder / "manifest.json").write_text(json.dumps(self.manifest))
        self.assertTrue(self.dispatch()["print_started"])
        request = self.sent[0]["print"]
        self.assertEqual(request["ams_mapping"], [5])
        self.assertEqual(request["ams_mapping2"], [{"ams_id": 1, "slot_id": 1}])
        self.assertFalse(request["flow_cali"])

    def test_tpu_from_external_spool_is_dispatched(self):
        self.tray["tray_type"] = self.check["file"]["material"] = "TPU"
        self.manifest.update(slot=None, external=True)
        self.manifest["routing"] = self.check["routing"] = route(external=True)
        (self.folder / "manifest.json").write_text(json.dumps(self.manifest))
        self.assertTrue(self.dispatch()["print_started"])
        request = self.sent[0]["print"]
        self.assertFalse(request["use_ams"])
        self.assertEqual(request["ams_mapping"], [-1])
        self.assertEqual(request["ams_mapping2"], [{"ams_id": 255, "slot_id": 0}])

    def test_target_changed_after_preparation_does_not_upload(self):
        self.check["target_machine"] = {"model": "Bambu Lab P1S"}
        with self.assertRaisesRegex(ValueError, "changed after review"):
            self.dispatch()
        self.assertEqual(self.uploaded, {})
        self.assertEqual(self.sent, [])

    def test_other_serial_with_same_model_does_not_upload(self):
        self.check["target_serial"] = "OTHERTEST"
        with self.assertRaisesRegex(ValueError, "changed after review"):
            self.dispatch()
        self.assertEqual(self.uploaded, {})
        self.assertEqual(self.sent, [])

    def test_routing_changed_after_upload_does_not_publish(self):
        changed = dict(self.check, routing=route(3))
        with patch.object(p.a1, "preflight", side_effect=[self.check, changed]):
            with self.assertRaisesRegex(ValueError, "changed after review"):
                self.dispatch()
        self.assertTrue(self.uploaded)
        self.assertEqual(self.sent, [])
