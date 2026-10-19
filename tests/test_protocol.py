"""Synthetic keys and packets only; tests never contact a printer."""

import base64
import datetime as dt
import json
import unittest
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from bambu_a1 import lan
from bambu_a1.signed_lan import signed_envelope, encrypt_field


def certificate(key, name="offline-test", issuer=None, issuer_key=None, ca=False):
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = dt.datetime.now(dt.timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer.subject if issuer else subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(
            x509.BasicConstraints(ca=ca, path_length=1 if ca else None), critical=True
        )
        .sign(issuer_key or key, hashes.SHA256())
    )


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.cert = certificate(cls.key)

    def test_signature_covers_exact_payload_and_detects_tampering(self):
        inner = {
            "sequence_id": "20000",
            "command": "project_file",
            "subtask_name": "离线测试",
        }
        wire = signed_envelope(inner, self.cert, self.key)
        parsed = json.loads(wire)
        value = wire.split(b',"print":', 1)[1][:-1]
        signed = b'{"print":' + value + b"}"
        signature = base64.b64decode(parsed["header"]["sign_string"])
        self.assertEqual(len(signed), parsed["header"]["payload_len"])
        self.key.public_key().verify(
            signature, signed, padding.PKCS1v15(), hashes.SHA256()
        )
        with self.assertRaises(InvalidSignature):
            self.key.public_key().verify(
                signature,
                signed.replace(b"20000", b"20001"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )

    def test_url_encryption_round_trip_across_rsa_blocks(self):
        value = "ftp://" + "x" * 500
        encrypted = base64.b64decode(encrypt_field(self.key.public_key(), value))
        plain = b"".join(
            self.key.decrypt(encrypted[i : i + 256], padding.PKCS1v15())
            for i in range(0, len(encrypted), 256)
        )
        self.assertEqual(plain.decode(), value)

    def test_fragmented_mqtt_packet(self):
        class Fragmented:
            def __init__(self, data):
                self.data = data

            def recv(self, count):
                value, self.data = (
                    self.data[: min(count, 2)],
                    self.data[min(count, 2) :],
                )
                return value

        body = b"x" * 300
        self.assertEqual(lan.receive(Fragmented(lan.packet(0x30, body))), (0x30, body))

    def test_closed_socket_does_not_loop(self):
        class Closed:
            def recv(self, count):
                return b""

        with self.assertRaises(ConnectionError):
            lan.exact(Closed(), 1)

    def test_status_allowlist_excludes_secrets(self):
        result = lan.sanitize(
            {
                "gcode_state": "IDLE",
                "access_code": "synthetic",
                "serial": "test",
                "ams": {
                    "ams": [
                        {
                            "id": "0",
                            "secret": "test",
                            "tray": [{"id": "1", "secret": "test"}],
                        }
                    ]
                },
            }
        )
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("access_code", result)
        self.assertNotIn("serial", result)
