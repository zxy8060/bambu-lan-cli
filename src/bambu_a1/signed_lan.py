"""Bound A1 transport helpers. No arbitrary-command CLI or plaintext credentials."""

import base64
import json
import time
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from . import lan


def cert_id(cert):
    serial = format(cert.serial_number, "x")
    if len(serial) % 2:
        serial = "0" + serial
    return serial + cert.issuer.rfc4514_string()


def next_message(conn, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        conn.sock.settimeout(max(0.1, deadline - time.monotonic()))
        head, body = lan.receive(conn.sock)
        if head >> 4 != 3:
            continue
        length = int.from_bytes(body[:2], "big")
        topic, offset = body[2 : 2 + length].decode(), 2 + length
        qos = (head >> 1) & 3
        if qos:
            msgid, offset = body[offset : offset + 2], offset + 2
            if qos == 1:
                conn.sock.sendall(lan.packet(0x40, msgid))
        if topic == "device/" + conn.serial + "/report":
            return json.loads(body[offset:])
    raise TimeoutError("No matching A1 report")


def publish(conn, payload):
    # Internal callers only. Bind destination to the TLS-verified configured device.
    conn.sock.sendall(
        lan.packet(0x30, lan.field("device/" + conn.serial + "/request") + payload)
    )


def app_cert_ids(conn):
    seq = str(int(time.time() * 1000))
    publish(
        conn,
        json.dumps(
            {
                "security": {
                    "sequence_id": seq,
                    "command": "app_cert_list",
                    "type": "app",
                }
            }
        ).encode(),
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        sec = next_message(conn, deadline - time.monotonic()).get("security", {})
        if sec.get("command") == "app_cert_list" and str(sec.get("sequence_id")) == seq:
            if not isinstance(sec.get("cert_ids"), list):
                raise RuntimeError("A1 did not return its app trust list")
            return set(sec["cert_ids"])
    raise TimeoutError("No app trust list reply")


def encrypt_field(public_key, text):
    raw = text.encode("utf-8")
    limit = public_key.key_size // 8 - 11
    encrypted = b"".join(
        public_key.encrypt(raw[i : i + limit], padding.PKCS1v15())
        for i in range(0, len(raw), limit)
    )
    return base64.b64encode(encrypted).decode("ascii")


def signed_envelope(inner, cert, key):
    # Serialize once. The exact bytes signed must be those placed on the wire.
    value = json.dumps(
        inner, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    canonical = b'{"print":' + value + b"}"
    signature = key.sign(canonical, padding.PKCS1v15(), hashes.SHA256())
    cert.public_key().verify(signature, canonical, padding.PKCS1v15(), hashes.SHA256())
    header = {
        "sign_ver": "v1.0",
        "sign_alg": "RSA_SHA256",
        "sign_string": base64.b64encode(signature).decode("ascii"),
        "cert_id": cert_id(cert),
        "payload_len": len(canonical),
    }
    return (
        b'{"header":'
        + json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
        + b',"print":'
        + value
        + b"}"
    )
