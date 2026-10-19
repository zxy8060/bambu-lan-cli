"""Import operator-provided signing material; never extract vendor secrets."""

import datetime as dt
import json
import os
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from .dpapi import protect
from . import lan
from .signed_lan import app_cert_ids, cert_id

STORE = lan.DATA / "app-credential.dpapi"


def current(cert):
    now = dt.datetime.now(dt.timezone.utc)
    if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
        raise ValueError("Certificate outside validity window")


def chain_for(leaf, candidates):
    anchors = x509.load_pem_x509_certificates(
        Path(lan.config()["app_ca_file"]).read_bytes()
    )
    trusted = {c.fingerprint(hashes.SHA256()) for c in anchors}
    chain, seen = [leaf], set()
    for _ in range(6):
        cert = chain[-1]
        current(cert)
        fp = cert.fingerprint(hashes.SHA256())
        if fp in trusted:
            return chain
        if fp in seen:
            break
        seen.add(fp)
        for parent in [*candidates, *anchors]:
            if cert.issuer != parent.subject:
                continue
            try:
                constraint = parent.extensions.get_extension_for_class(
                    x509.BasicConstraints
                ).value
                if not constraint.ca:
                    continue
                # All preceding intermediate certificates are CAs, leaf is not.
                if (
                    constraint.path_length is not None
                    and len(chain) - 1 > constraint.path_length
                ):
                    continue
                cert.verify_directly_issued_by(parent)
            except (ValueError, x509.ExtensionNotFound):
                continue
            chain.append(parent)
            break
        else:
            break
    raise ValueError(
        "Application certificate chain does not reach the configured root CA"
    )


def validate(leaf, key, candidates, trusted_ids=None):
    current(leaf)
    try:
        if leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise ValueError("Signing identity must be an application leaf, not a CA")
    except x509.ExtensionNotFound:
        pass
    if trusted_ids is not None and cert_id(leaf) not in trusted_ids:
        raise ValueError(
            "Application certificate is not already trusted by this printer"
        )
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size != 2048:
        raise ValueError("Only RSA-2048 application keys are currently supported")
    if (
        not isinstance(leaf.public_key(), rsa.RSAPublicKey)
        or leaf.public_key().public_numbers() != key.public_key().public_numbers()
    ):
        raise ValueError("Application public/private key mismatch")
    chain = chain_for(leaf, candidates)
    challenge = b"Bambu A1 CLI credential validation v1"
    signature = key.sign(challenge, padding.PKCS1v15(), hashes.SHA256())
    leaf.public_key().verify(signature, challenge, padding.PKCS1v15(), hashes.SHA256())
    return chain


def import_files(certificate, private_key, password=None):
    if os.name != "nt":
        raise RuntimeError("Credential import currently requires Windows")
    if STORE.exists():
        raise ValueError(
            "Credential store exists; inspect it before replacing credentials"
        )
    certificates = x509.load_pem_x509_certificates(Path(certificate).read_bytes())
    if not certificates:
        raise ValueError("Supply a PEM certificate chain, application leaf first")
    key = serialization.load_pem_private_key(
        Path(private_key).read_bytes(), password=password
    )
    cfg = lan.config()
    with lan.Connection(cfg) as conn:
        ids = app_cert_ids(conn)
    chain = validate(certificates[0], key, certificates[1:], ids)
    record = {
        "format": 1,
        "target_serial": cfg["serial"],
        "leaf_sha256": chain[0].fingerprint(hashes.SHA256()).hex(),
        "chain": [c.public_bytes(serialization.Encoding.PEM).decode() for c in chain],
        "key": key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode(),
    }
    raw = json.dumps(record, separators=(",", ":")).encode()
    protected = protect(raw, cfg["serial"])
    if protect(protected, cfg["serial"], True) != raw:
        raise RuntimeError("Encrypted credential round-trip failed")
    STORE.parent.mkdir(parents=True, exist_ok=True)
    with STORE.open("xb") as stream:
        stream.write(protected)
    return {
        "state": "credential_imported",
        "certificate_sha256": record["leaf_sha256"],
        "valid_until": chain[0].not_valid_after_utc.isoformat(),
        "protection": "DPAPI CurrentUser",
        "print_started": False,
    }


def load(serial):
    if not STORE.exists():
        raise ValueError(
            "Signing credentials missing; see docs/credentials.md before dispatch"
        )
    data = json.loads(protect(STORE.read_bytes(), serial, True))
    if data.get("format") != 1 or data.get("target_serial") != serial:
        raise ValueError("Credential-store target mismatch")
    chain = [x509.load_pem_x509_certificate(p.encode()) for p in data["chain"]]
    key = serialization.load_pem_private_key(data["key"].encode(), password=None)
    if chain[0].fingerprint(hashes.SHA256()).hex() != data.get("leaf_sha256"):
        raise ValueError("Stored application identity changed")
    validate(chain[0], key, chain[1:])
    return chain[0], key, data
