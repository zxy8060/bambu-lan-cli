import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from bambu_a1 import app_credentials as vault
from bambu_a1.dpapi import protect
from bambu_a1.signed_lan import cert_id
from test_protocol import certificate


class CredentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.root = certificate(cls.root_key, "offline-root", ca=True)
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.leaf = certificate(cls.key, issuer=cls.root, issuer_key=cls.root_key)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.ca = self.folder / "ca.pem"
        self.ca.write_bytes(self.root.public_bytes(serialization.Encoding.PEM))
        self.config_patch = patch.object(
            vault.lan,
            "config",
            return_value={"app_ca_file": str(self.ca), "serial": "offline-A1"},
        )
        self.config_patch.start()

    def tearDown(self):
        self.config_patch.stop()
        self.temp.cleanup()

    def test_valid_chain_and_trusted_identity(self):
        chain = vault.validate(self.leaf, self.key, [], {cert_id(self.leaf)})
        self.assertEqual(len(chain), 2)

    def test_untrusted_identity(self):
        with self.assertRaises(ValueError):
            vault.validate(self.leaf, self.key, [], set())

    def test_wrong_private_key(self):
        with self.assertRaises(ValueError):
            vault.validate(self.leaf, self.root_key, [])

    def test_ca_cannot_be_application_identity(self):
        with self.assertRaises(ValueError):
            vault.validate(self.root, self.root_key, [])

    @unittest.skipUnless(os.name == "nt", "DPAPI is Windows-only")
    def test_dpapi_round_trip_and_wrong_target(self):
        raw = b"synthetic ephemeral test material"
        encrypted = protect(raw, "offline-A1")
        self.assertNotIn(raw, encrypted)
        self.assertEqual(protect(encrypted, "offline-A1", True), raw)
        with self.assertRaises(RuntimeError):
            protect(encrypted, "different-A1", True)

    @unittest.skipUnless(os.name == "nt", "DPAPI import is Windows-only")
    def test_import_and_load_without_plaintext_store(self):
        chain_file, key_file, store = (
            self.folder / "chain.pem",
            self.folder / "key.pem",
            self.folder / "app.dpapi",
        )
        chain_file.write_bytes(self.leaf.public_bytes(serialization.Encoding.PEM))
        key_bytes = self.key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        key_file.write_bytes(key_bytes)

        class FakeConnection:
            def __init__(self, cfg):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        with (
            patch.object(vault, "STORE", store),
            patch.object(vault.lan, "Connection", FakeConnection),
            patch.object(vault, "app_cert_ids", return_value={cert_id(self.leaf)}),
        ):
            result = vault.import_files(chain_file, key_file)
            self.assertEqual(result["state"], "credential_imported")
            self.assertNotIn(key_bytes, store.read_bytes())
            self.assertEqual(
                vault.load("offline-A1")[1].private_numbers(),
                self.key.private_numbers(),
            )
            with self.assertRaises(ValueError):
                vault.import_files(chain_file, key_file)
