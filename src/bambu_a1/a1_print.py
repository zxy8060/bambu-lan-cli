"""Reviewed single-nozzle/material Bambu print workflow, Windows CLI only.

prepare captures current checks and camera without printing. The caller must
actually inspect that image, then dispatch with its SHA256 under the user's
authorization for this exact job. Existing receipts always prevent repeat sends.
"""

import datetime as dt
import hashlib
import json
import os

if os.name == "nt":
    import msvcrt
from contextlib import contextmanager
from pathlib import Path
import socket
import time
import uuid
from cryptography import x509
from . import a1
from . import app_credentials as vault
from .signed_lan import (
    lan,
    app_cert_ids,
    cert_id,
    publish,
    next_message,
    signed_envelope,
    encrypt_field,
)
from .verified_ftps import VerifiedFTPS
from .filament import calibration_flags

JOBS = lan.DATA / "print-jobs"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def matches_remote_job(state, remote):
    # User labels may repeat. Only a matching unique uploaded filename proves
    # that this status belongs to this dispatch; absent filename stays unknown.
    filename = str(state.get("gcode_file") or "").replace("\\", "/").rsplit("/", 1)[-1]
    return bool(remote and filename == remote)


def write(path, value):
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def allocate_sequence():
    # Fixed A1-sized sequence range, serialized across local processes. Do not use
    # Unix timestamps: actual A1 01.08.01.00 rejects those with 84033546.
    require_windows()
    lan.DATA.mkdir(parents=True, exist_ok=True)
    fd = os.open(lan.DATA / "signing-sequence.json", os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+b") as stream:
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            stream.seek(0)
            raw = stream.read()
            number = json.loads(raw)["next"] if raw else 20000
            if not 20000 <= number <= 29999:
                raise RuntimeError(
                    "Verified sequence allocation range exhausted; review before reuse"
                )
            stream.seek(0)
            stream.write(json.dumps({"next": number + 1}).encode())
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
            return str(number)
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def prepare(
    file,
    slot=None,
    label=None,
    *,
    ams_id=0,
    external=False,
    bed_image=None,
    flow_calibration=False,
    vibration_calibration=False,
):
    require_windows()
    check = a1.preflight(file, slot, ams_id, external)
    if not check["checks_passed"]:
        return {"state": "preflight_failed", "preflight": check, "print_started": False}
    cfg = lan.config()
    if cfg["serial"] != check["target_serial"]:
        raise ValueError("Configured printer changed during preparation")
    vault.load(cfg["serial"])
    job_id = uuid.uuid4().hex
    folder = JOBS / job_id
    folder.mkdir(parents=True, exist_ok=False)
    bed = folder / "bed.jpg"
    picture, captured_at = capture_bed(bed, bed_image, cfg)
    task = (label or "Bambu LAN " + Path(file).stem)[:100]
    if not task or any(ord(c) < 32 for c in task):
        raise ValueError("Invalid task label")
    manifest = {
        "format": 2,
        "job_id": job_id,
        "target_serial": cfg["serial"],
        "file": str(Path(file).resolve()),
        "sha256": check["file"]["sha256"],
        "slot": slot,
        "ams_id": ams_id,
        "external": external,
        "routing": check["routing"],
        "target_machine": check["target_machine"],
        "calibration": calibration_flags(
            check["target_machine"]["model"], flow_calibration, vibration_calibration
        ),
        "tray": check["selected_tray"],
        "task_name": task,
        "prepared_at": time.time(),
        "bed_captured_at": captured_at,
        "bed_file": str(bed),
        "bed_sha256": digest(bed.read_bytes()),
        "preflight": check,
    }
    write(folder / "manifest.json", manifest)
    return {
        "state": "prepared_requires_actual_bed_image_review",
        "job_id": job_id,
        "file": check["file"],
        "ams_slot": slot,
        "routing": manifest["routing"],
        "calibration": manifest["calibration"],
        "selected_tray": check["selected_tray"],
        "camera": picture,
        "bed_sha256": manifest["bed_sha256"],
        "print_started": False,
    }


def capture_bed(destination, supplied=None, cfg=None):
    if supplied is None:
        picture = lan.camera(destination, cfg)
        return picture, time.time()
    source = Path(supplied).resolve()
    with source.open("rb") as stream:
        stat = os.fstat(stream.fileno())
        if not 4 <= stat.st_size <= 10_000_000:
            raise ValueError("Bed JPEG must be between 4 bytes and 10 MB")
        if not 0 <= time.time() - stat.st_mtime <= 300:
            raise ValueError("Bed image must be freshly captured within 5 minutes")
        jpeg = stream.read()
    if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
        raise ValueError("Bed image must be a JPEG")
    destination.write_bytes(jpeg)
    return {
        "file": str(destination),
        "bytes": len(jpeg),
        "source": "operator-supplied",
        "capture_time_source": "file mtime",
        "requires_review": "Confirm this is a fresh photo of the configured printer",
    }, stat.st_mtime


def fresh_preflight(manifest):
    check = a1.preflight(
        manifest["file"], manifest["slot"], manifest["ams_id"], manifest["external"]
    )
    if check["checks_passed"] and (
        check["target_machine"] != manifest["target_machine"]
        or check["routing"] != manifest["routing"]
        or check["target_serial"] != manifest["target_serial"]
    ):
        raise ValueError(
            "Target machine or filament routing changed after review; prepare again"
        )
    return check


def review_is_fresh(manifest):
    now = time.time()
    return all(
        0 <= now - manifest[field] <= 300
        for field in ("prepared_at", "bed_captured_at")
    )


def get_job(job_id):
    if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
        raise ValueError("Invalid local job id")
    folder = JOBS / job_id
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("format") not in (1, 2)
        or manifest.get("job_id") != job_id
        or manifest.get("target_serial") != lan.config()["serial"]
    ):
        raise ValueError("Local manifest target/format mismatch")
    return folder, manifest


def ensure_trust(conn, cert, data):
    if cert_id(cert) in app_cert_ids(conn):
        return
    raise RuntimeError(
        "Application identity is no longer trusted; restore it through your authorized provisioning method. No print was sent"
    )


def require_windows():
    if os.name != "nt":
        raise RuntimeError("Preparation and signed dispatch currently require Windows")


@contextmanager
def printer_lock():
    require_windows()
    lan.DATA.mkdir(parents=True, exist_ok=True)
    fd = os.open(lan.DATA / "dispatch.lock", os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+b") as stream:
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def dispatch(job_id, reviewed_bed_sha256):
    with printer_lock():
        return _dispatch(job_id, reviewed_bed_sha256)


def _dispatch(job_id, reviewed_bed_sha256):
    folder, m = get_job(job_id)
    receipt = folder / "receipt.json"
    if receipt.exists():
        raise RuntimeError(
            "Receipt exists: inspect job-status and printer; no automatic resend"
        )
    if m["format"] != 2:
        raise ValueError("Version 0.1 jobs must be prepared again")
    if (
        reviewed_bed_sha256 != m["bed_sha256"]
        or digest(Path(m["bed_file"]).read_bytes()) != reviewed_bed_sha256
    ):
        raise ValueError("Reviewed camera frame does not match the prepared job")
    if not review_is_fresh(m):
        raise ValueError(
            "Preparation is older than 5 minutes; prepare and view a fresh image"
        )
    content = Path(m["file"]).read_bytes()
    if digest(content) != m["sha256"]:
        raise ValueError("Prepared print file changed")
    check = fresh_preflight(m)
    if not check["checks_passed"]:
        return {
            "state": "fresh_preflight_failed",
            "preflight": check,
            "print_started": False,
        }
    for field in ("id", "tray_type", "tray_color", "tray_info_idx"):
        if check["selected_tray"].get(field) != m["tray"].get(field):
            raise ValueError("Selected filament changed after review")
    cfg = lan.config()
    if cfg["serial"] != m["target_serial"]:
        raise ValueError("Configured printer changed after review")
    serial, access = lan.credentials(cfg)
    cert, key, data = vault.load(serial)
    remote = "a1cli_" + job_id + ".gcode.3mf"
    with VerifiedFTPS(cfg) as ftp:
        ftp.connect()
        ftp.login("bblp", access)
        ftp.prot_p()
        ftp.upload_new(remote, content)
        if ftp.readback(remote, len(content)) != content:
            raise ValueError("Uploaded bytes differ from reviewed file")
    check = fresh_preflight(m)
    if not check["checks_passed"] or any(
        check["selected_tray"].get(field) != m["tray"].get(field)
        for field in ("id", "tray_type", "tray_color", "tray_info_idx")
    ):
        return {
            "state": "post_upload_preflight_changed_no_print_sent",
            "preflight": check,
            "print_started": False,
        }
    if not review_is_fresh(m):
        raise ValueError("Bed review expired during upload; no print was sent")
    # No print dispatch has happened yet. Capture and retain a receipt even if
    # connection/provisioning later fails; the operator can inspect the outcome.
    record = {
        "timestamp": dt.datetime.now().astimezone().isoformat(),
        "job_id": job_id,
        "file_sha256": m["sha256"],
        "remote_filename": remote,
        "task_name": m["task_name"],
        "ams_slot": m["slot"],
        "routing": m["routing"],
        "target_machine": m["target_machine"],
        "calibration": m["calibration"],
        "state": "uploaded_not_dispatched",
        "print_started": False,
        "remote_readback_verified": True,
        "no_auto_retry": True,
        "acks": [],
    }
    with receipt.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        with lan.Connection(cfg) as conn:
            ensure_trust(conn, cert, data)
            device = x509.load_der_x509_certificate(
                conn.sock.getpeercert(binary_form=True)
            )
            seq = allocate_sequence()
            inner = {
                "sequence_id": seq,
                "command": "project_file",
                "param": "Metadata/plate_1.gcode",
                "url_enc": encrypt_field(device.public_key(), "ftp://" + remote),
                "file": remote,
                "md5": hashlib.md5(content).hexdigest(),
                "bed_type": "auto",
                "timelapse": False,
                **m["calibration"],
                "use_ams": m["routing"]["use_ams"],
                "ams_mapping": m["routing"]["ams_mapping"],
                "ams_mapping2": m["routing"]["ams_mapping2"],
                "subtask_name": m["task_name"],
                "profile_id": "0",
                "project_id": "0",
                "subtask_id": "0",
                "task_id": "0",
                "plate_idx": 1,
                "job_type": 1,
                "job_id": "0",
            }
            wire = signed_envelope(inner, cert, key)
            record.update(
                state="dispatch_about_to_send",
                sequence_id=seq,
                payload_sha256=digest(wire),
                print_started=None,
            )
            write(receipt, record)
            if not review_is_fresh(m):
                raise ValueError("Bed review expired before publish; no print was sent")
            publish(conn, wire)
            record["state"] = "sent_pending_independent_verification"
            write(receipt, record)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    p = next_message(conn, min(5, deadline - time.monotonic())).get(
                        "print", {}
                    )
                except socket.timeout:
                    continue
                if (
                    p.get("command") == "project_file"
                    and str(p.get("sequence_id")) == seq
                ):
                    record["acks"].append(
                        {
                            k: p[k]
                            for k in (
                                "command",
                                "sequence_id",
                                "result",
                                "reason",
                                "err_code",
                            )
                            if k in p
                        }
                    )
                    write(receipt, record)
                    break
        live = lan.status(cfg)
        state = live["status"]
        record["live"] = live
        matching = matches_remote_job(state, remote)
        record["print_started"] = bool(
            matching and state.get("gcode_state") in {"PREPARE", "RUNNING"}
        )
        record["state"] = (
            "new_job_observed"
            if record["print_started"]
            else "not_yet_observed_do_not_resend"
        )
    except Exception as error:
        record.update(
            state="outcome_requires_inspection_do_not_resend",
            error_type=type(error).__name__,
        )
    write(receipt, record)
    return record


def job_status(job_id):
    folder, m = get_job(job_id)
    cfg = lan.config()
    if cfg["serial"] != m["target_serial"]:
        raise ValueError("Configured printer changed during status read")
    receipt = folder / "receipt.json"
    record = (
        json.loads(receipt.read_text(encoding="utf-8"))
        if receipt.exists()
        else {"state": "prepared_only"}
    )
    live = lan.status(cfg)
    state = live["status"]
    matches = matches_remote_job(state, record.get("remote_filename"))
    result = {
        "job_id": job_id,
        "receipt": record,
        "live": live,
        "matches_job": matches,
        "active": bool(matches and state.get("gcode_state") in {"PREPARE", "RUNNING"}),
    }
    write(folder / "latest-status.json", result)
    return result
