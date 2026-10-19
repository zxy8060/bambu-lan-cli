import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from bambu_a1 import settings, lan


class ConfigTests(unittest.TestCase):
    def test_init_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            ca = folder / "ca.pem"
            ca.write_text("synthetic path-only fixture")
            with (
                patch.object(settings, "DATA", folder),
                patch.object(settings, "CONFIG", folder / "config.json"),
            ):
                settings.initialize("192.0.2.10", "OFFLINETESTA1", ca)
                self.assertEqual(settings.config()["serial"], "OFFLINETESTA1")
                with self.assertRaises(FileExistsError):
                    settings.initialize("192.0.2.11", "DIFFERENTA1", ca)
                self.assertEqual(settings.config()["host"], "192.0.2.10")

    def test_access_code_from_named_environment(self):
        with patch.dict(os.environ, {"OFFLINE_TEST_ACCESS": "A1B2C3D4"}):
            self.assertEqual(
                lan.credentials(
                    {
                        "serial": "OFFLINETESTA1",
                        "access_code_env": "OFFLINE_TEST_ACCESS",
                    }
                ),
                ("OFFLINETESTA1", "A1B2C3D4"),
            )

    def test_invalid_secret_is_not_echoed(self):
        secret = "synthetic-invalid-secret"
        with patch.dict(os.environ, {"OFFLINE_TEST_ACCESS": secret}):
            with self.assertRaises(ValueError) as error:
                lan.credentials(
                    {
                        "serial": "OFFLINETESTA1",
                        "access_code_env": "OFFLINE_TEST_ACCESS",
                    }
                )
        self.assertNotIn(secret, str(error.exception))
