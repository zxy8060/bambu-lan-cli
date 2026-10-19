"""Machine/material routing checks using synthetic profiles and telemetry only."""

import copy
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from bambu_a1 import a1, a1_print, machine, filament, lan, settings


class GeneralizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.profile = self.root / "machine.json"
        self.profile.write_text(
            json.dumps(
                {
                    "printer_model": "Bambu Lab P1S",
                    "nozzle_diameter": ["0.6"],
                    "printable_area": ["0x0", "256x0", "256x256", "0x256"],
                    "printable_height": "256",
                }
            )
        )
        self.cfg = {"machine_profile": str(self.profile), "serial": "OFFLINETEST"}
        self.geometry = machine.target(self.cfg)
        self.job = {
            "machine": self.geometry,
            "nozzle_mm": 0.6,
            "material": "PETG",
            "colors": [],
            "bed_type": "Textured PEI Plate",
            "sha256": "offline",
        }
        self.tray = {"id": "1", "tray_type": "PETG", "tray_color": "000000FF"}
        self.state = {
            "gcode_state": "IDLE",
            "print_error": 0,
            "hms": [],
            "sdcard": True,
            "nozzle_diameter": "0.6",
            "ams_status": 0,
            "nozzle_target_temper": 0,
            "bed_target_temper": 0,
            "ams": {"units": [{"id": "1", "trays": [self.tray]}]},
        }
        self.patches = [
            patch.object(a1, "config", return_value=self.cfg),
            patch.object(a1, "status", return_value={"status": self.state}),
            patch.object(a1, "inspect", return_value=self.job),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def preflight(self):
        return a1.preflight("offline.gcode.3mf", 2, 1)

    def test_materials_are_matched_without_a_pla_whitelist(self):
        for material in ["PLA", "PETG", "ABS", "ASA", "PA", "PC", "PVA", "CUSTOM"]:
            with self.subTest(material=material):
                self.job["material"] = self.tray["tray_type"] = material
                self.assertTrue(self.preflight()["checks_passed"])

    def test_wrong_material_still_blocks(self):
        self.tray["tray_type"] = "PLA"
        self.assertFalse(self.preflight()["checks_passed"])

    def test_target_model_nozzle_and_volume_must_match(self):
        for field, value in [
            ("model", "Bambu Lab X1 Carbon"),
            ("nozzle_mm", 0.4),
            ("bounds_xy_mm", [0, 0, 300, 300]),
            ("height_mm", 300),
        ]:
            with self.subTest(field=field):
                self.job["machine"] = dict(self.geometry, **{field: value})
                self.assertFalse(self.preflight()["checks_passed"])

    def test_no_target_profile_does_not_adopt_job_settings(self):
        self.cfg.clear()
        with self.assertRaisesRegex(ValueError, "configure-machine"):
            self.preflight()
        a1.status.assert_not_called()

    def test_live_nozzle_mismatch_or_missing_blocks(self):
        for value in ["0.4", None, "nan", "bad"]:
            self.state["nozzle_diameter"] = value
            self.assertFalse(self.preflight()["checks_passed"])

    def test_ams_unit_is_not_ignored(self):
        self.assertFalse(a1.preflight("offline", 2, 0)["checks_passed"])
        result = self.preflight()
        self.assertTrue(result["checks_passed"])
        self.assertEqual(result["routing"]["ams_mapping"], [5])

    def test_external_tpu_without_ams(self):
        del self.state["ams"]
        del self.state["ams_status"]
        self.job["material"] = "TPU"
        self.state["vt_tray"] = {"id": "254", "tray_type": "TPU"}
        result = a1.preflight("offline", external=True)
        self.assertTrue(result["checks_passed"])
        self.assertFalse(result["routing"]["use_ams"])
        self.state["vt_tray"]["tray_type"] = "PLA"
        self.assertFalse(a1.preflight("offline", external=True)["checks_passed"])

    def test_external_missing_material_blocks(self):
        self.assertFalse(a1.preflight("offline", external=True)["checks_passed"])

    def test_ht_single_slot_mapping_and_validation(self):
        self.state["ams"]["units"] = [
            {"id": "128", "trays": [{"id": "0", "tray_type": "PETG"}]}
        ]
        result = a1.preflight("offline", 1, 128)
        self.assertTrue(result["checks_passed"])
        self.assertEqual(result["routing"]["ams_mapping"], [128])
        with self.assertRaises(ValueError):
            filament.route(2, 128)

    def test_conflicting_and_invalid_routes_rejected(self):
        for args in [
            dict(slot=1, external=True),
            dict(ams_id=1, external=True),
            dict(slot=0),
            dict(slot=5),
            dict(slot=1, ams_id=-1),
        ]:
            with self.assertRaises(ValueError):
                filament.route(**args)

    def test_cli_passes_external_and_calibration_options(self):
        with patch.object(
            a1_print, "prepare", return_value={"print_started": False}
        ) as prepare:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    a1.main(
                        [
                            "prepare-print",
                            "--file",
                            "offline",
                            "--external",
                            "--bed-image",
                            "bed.jpg",
                            "--flow-calibration",
                        ]
                    ),
                    0,
                )
        prepare.assert_called_once_with(
            "offline",
            None,
            None,
            ams_id=0,
            external=True,
            bed_image="bed.jpg",
            flow_calibration=True,
            vibration_calibration=False,
        )

    def test_cli_rejects_two_filament_sources(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                a1.main(["preflight", "--file", "offline", "--external", "--slot", "2"])
        self.assertEqual(error.exception.code, 2)

    def test_virtual_tray_list_is_sanitized_and_ambiguous_selection_rejected(self):
        raw = {"vt_tray": [{"id": "254", "tray_type": "TPU", "secret": "hidden"}]}
        clean = lan.sanitize(raw)
        self.assertNotIn("secret", json.dumps(clean))
        self.assertEqual(
            filament.selected_tray(clean, filament.route(external=True))["tray_type"],
            "TPU",
        )
        clean["vt_tray"].append({"id": "255", "tray_type": "PLA"})
        self.assertIsNone(filament.selected_tray(clean, filament.route(external=True)))

    def test_finite_geometry_required(self):
        profile = machine.read_profile(self.profile)
        for field, value in [
            ("printable_height", "nan"),
            ("nozzle_diameter", ["inf"]),
            ("printable_area", ["0x0", "1x0", "0x1", "0x0"]),
        ]:
            with self.assertRaises(ValueError):
                machine.from_profile(dict(profile, **{field: value}))

    def test_calibration_is_opt_in_and_h2_uses_integer_flags(self):
        self.assertIs(filament.calibration_flags("Bambu Lab P1S")["flow_cali"], False)
        self.assertIs(
            filament.calibration_flags("Bambu Lab P1S", True)["flow_cali"], True
        )
        flags = filament.calibration_flags("Bambu Lab H2S", True)
        self.assertEqual(flags["flow_cali"], 1)
        self.assertIs(type(flags["flow_cali"]), int)

    def test_supplied_bed_photo_keeps_original_age(self):
        source, dest = self.root / "source.jpg", self.root / "bed.jpg"
        source.write_bytes(b"\xff\xd8synthetic-jpeg\xff\xd9")
        stamp = time.time() - 120
        os.utime(source, (stamp, stamp))
        picture, captured_at = a1_print.capture_bed(dest, source)
        self.assertAlmostEqual(captured_at, stamp, places=3)
        self.assertEqual(dest.read_bytes(), source.read_bytes())
        self.assertEqual(picture["source"], "operator-supplied")
        os.utime(source, (stamp - 200, stamp - 200))
        with self.assertRaises(ValueError):
            a1_print.capture_bed(dest, source)

    def test_non_jpeg_bed_photo_blocks(self):
        source = self.root / "bad.jpg"
        source.write_bytes(b"not a JPEG")
        with self.assertRaises(ValueError):
            a1_print.capture_bed(self.root / "copy.jpg", source)

    def test_small_future_file_timestamp_is_clamped(self):
        source = self.root / "fresh.jpg"
        source.write_bytes(b"\xff\xd8synthetic-jpeg\xff\xd9")
        now = time.time()
        os.utime(source, (now + 0.01, now + 0.01))
        with patch.object(a1_print.time, "time", return_value=now):
            _, captured_at = a1_print.capture_bed(self.root / "copy.jpg", source)
            self.assertEqual(captured_at, now)
            self.assertTrue(
                a1_print.review_is_fresh(
                    {"prepared_at": now, "bed_captured_at": captured_at}
                )
            )

    def test_genuinely_future_file_timestamp_is_rejected(self):
        source = self.root / "future.jpg"
        source.write_bytes(b"\xff\xd8synthetic-jpeg\xff\xd9")
        now = time.time()
        os.utime(source, (now + 10, now + 10))
        with patch.object(a1_print.time, "time", return_value=now):
            with self.assertRaises(ValueError):
                a1_print.capture_bed(self.root / "copy.jpg", source)

    def test_future_rounding_tolerance_does_not_extend_old_photo_limit(self):
        source = self.root / "stale.jpg"
        source.write_bytes(b"\xff\xd8synthetic-jpeg\xff\xd9")
        now = time.time()
        os.utime(source, (now - 300.01, now - 300.01))
        with patch.object(a1_print.time, "time", return_value=now):
            with self.assertRaises(ValueError):
                a1_print.capture_bed(self.root / "copy.jpg", source)

    def test_configure_machine_preserves_other_settings(self):
        cfg = dict(self.cfg, serial="OFFLINETEST", host="192.0.2.10")
        path = self.root / "config.json"
        with (
            patch.object(settings, "config", return_value=cfg),
            patch.object(settings, "CONFIG", path),
        ):
            settings.configure_machine(self.profile)
        saved = json.loads(path.read_text())
        self.assertEqual(saved["serial"], cfg["serial"])
        self.assertEqual(saved["host"], cfg["host"])

    @unittest.skipUnless(os.name == "nt", "Windows credential preparation")
    def test_prepare_petg_binds_machine_route_and_calibration(self):
        result = self.preflight()
        source = self.root / "source.jpg"
        source.write_bytes(b"\xff\xd8synthetic-jpeg\xff\xd9")
        with (
            patch.object(a1_print.a1, "preflight", return_value=copy.deepcopy(result)),
            patch.object(
                a1_print.lan, "config", return_value={"serial": "OFFLINETEST"}
            ),
            patch.object(a1_print.vault, "load"),
            patch.object(a1_print, "JOBS", self.root / "jobs"),
        ):
            prepared = a1_print.prepare("offline", 2, ams_id=1, bed_image=source)
        manifest = json.loads(
            (self.root / "jobs" / prepared["job_id"] / "manifest.json").read_text()
        )
        self.assertEqual(manifest["format"], 2)
        self.assertEqual(manifest["target_machine"], self.geometry)
        self.assertEqual(manifest["routing"]["ams_mapping"], [5])
        self.assertFalse(manifest["calibration"]["flow_cali"])
        self.assertFalse(prepared["print_started"])
