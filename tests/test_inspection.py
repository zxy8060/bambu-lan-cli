import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from bambu_a1.a1 import inspect


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "synthetic.gcode.3mf"
        self.settings = {
            "printer_model": "Bambu Lab A1",
            "nozzle_diameter": ["0.4"],
            "printable_area": ["0x0", "256x0", "256x256", "0x256"],
            "printable_height": "256",
            "filament_type": ["PLA"],
            "curr_bed_type": "Supertack Plate",
        }
        self.metadata = {
            "nozzle_diameter": 0.4,
            "bbox_all": [100, 100, 110, 110],
            "filament_ids": [0],
        }
        self.gcode = b"""; printer_model = Bambu Lab A1
; nozzle_diameter = 0.4
; filament_type = PLA
; curr_bed_type = Supertack Plate
; max_z_height: 5
; total estimated time: 1m
; total filament weight [g] : 1.0
; total layer number: 25
; EXECUTABLE_BLOCK_START
; synthetic fixture: contains no actual printing instructions
; EXECUTABLE_BLOCK_END
"""

    def tearDown(self):
        self.temp.cleanup()

    def write(self, checksum=None, extra_plate=False):
        with zipfile.ZipFile(self.path, "w") as archive:
            archive.writestr(
                "Metadata/project_settings.config", json.dumps(self.settings)
            )
            archive.writestr("Metadata/plate_1.json", json.dumps(self.metadata))
            archive.writestr("Metadata/plate_1.gcode", self.gcode)
            archive.writestr(
                "Metadata/plate_1.gcode.md5",
                checksum or hashlib.md5(self.gcode).hexdigest(),
            )
            if extra_plate:
                archive.writestr("Metadata/plate_2.gcode", self.gcode)

    def test_valid_metadata(self):
        self.write()
        self.assertEqual(inspect(self.path)["layers"], 25)

    def test_checksum_mismatch(self):
        self.write(checksum="0" * 32)
        with self.assertRaises(ValueError):
            inspect(self.path)

    def test_out_of_bounds(self):
        self.metadata["bbox_all"] = [0, 0, 257, 10]
        self.write()
        with self.assertRaises(ValueError):
            inspect(self.path)

    def test_infinite_height(self):
        self.gcode = self.gcode.replace(b"max_z_height: 5", b"max_z_height: inf")
        self.write()
        with self.assertRaises(ValueError):
            inspect(self.path)

    def test_wrong_printer(self):
        self.settings["printer_model"] = "Other printer"
        self.write()
        with self.assertRaises(ValueError):
            inspect(self.path)

    def test_second_plate(self):
        self.write(extra_plate=True)
        with self.assertRaises(ValueError):
            inspect(self.path)

    def change_printer(self, model, nozzle, size, material):
        self.settings.update(
            printer_model=model,
            nozzle_diameter=[str(nozzle)],
            printable_area=["0x0", f"{size}x0", f"{size}x{size}", f"0x{size}"],
            printable_height=str(size),
            filament_type=[material],
        )
        self.metadata["nozzle_diameter"] = nozzle
        self.gcode = self.gcode.replace(b"Bambu Lab A1", model.encode())
        self.gcode = self.gcode.replace(
            b"nozzle_diameter = 0.4", f"nozzle_diameter = {nozzle}".encode()
        )
        self.gcode = self.gcode.replace(
            b"filament_type = PLA", f"filament_type = {material}".encode()
        )

    def test_a1_mini_uses_180_mm_build_volume(self):
        self.change_printer("Bambu Lab A1 mini", 0.6, 180, "PETG")
        self.write()
        result = inspect(self.path)
        self.assertEqual(result["nozzle_mm"], 0.6)
        self.assertEqual(result["machine"]["height_mm"], 180)
        self.assertEqual(result["material"], "PETG")
        self.metadata["bbox_all"] = [170, 100, 181, 110]
        self.write()
        with self.assertRaises(ValueError):
            inspect(self.path)

    def test_p1s_accepts_asa_profile(self):
        self.change_printer("Bambu Lab P1S", 0.8, 256, "ASA")
        self.write()
        self.assertEqual(inspect(self.path)["material"], "ASA")

    def test_dual_nozzle_profile_is_not_silently_treated_as_single(self):
        self.settings["nozzle_diameter"] = ["0.4", "0.4"]
        self.write()
        with self.assertRaisesRegex(ValueError, "single-nozzle"):
            inspect(self.path)

    def test_plate_nozzle_must_match_profile(self):
        self.metadata["nozzle_diameter"] = 0.6
        self.write()
        with self.assertRaisesRegex(ValueError, "Plate nozzle"):
            inspect(self.path)

    def test_empty_material_is_not_accepted(self):
        self.settings["filament_type"] = [""]
        self.write()
        with self.assertRaises(ValueError):
            inspect(self.path)
