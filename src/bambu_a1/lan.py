"""Read-only A1 LAN telemetry and camera, with verified TLS. No control commands."""

import json
import os
import pathlib
import socket
import ssl
import struct
import time
import uuid

from .settings import DATA as DATA, config


def credentials(cfg):
    serial = cfg["serial"]
    value = os.environ.get(cfg.get("access_code_env", "BAMBU_A1_ACCESS_CODE"))
    if value is not None:
        if len(value) != 8 or not value.isascii() or not value.isalnum():
            raise ValueError(
                "The configured access-code environment variable is invalid"
            )
        return serial, value
    if cfg.get("studio_config"):
        text = (
            pathlib.Path(cfg["studio_config"]).read_text(encoding="utf-8-sig").lstrip()
        )
        data, _ = json.JSONDecoder().raw_decode(text)
        for key in ("access_code", "user_access_code"):
            value = data.get(key, {}).get(serial)
            if (
                isinstance(value, str)
                and len(value) == 8
                and value.isascii()
                and value.isalnum()
            ):
                return serial, value
    raise RuntimeError(
        "No access code for the pinned printer; configure a Studio config path or the named environment variable"
    )


def context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(cafile=config()["ca_file"])
    return ctx


def tls_socket(cfg, port):
    raw = socket.create_connection((cfg["host"], port), timeout=6)
    try:
        return context().wrap_socket(raw, server_hostname=cfg["serial"])
    except Exception:
        raw.close()
        raise


def field(value):
    value = value.encode() if isinstance(value, str) else value
    return struct.pack("!H", len(value)) + value


def packet(kind, body):
    count, header = len(body), bytearray([kind])
    while True:
        digit, count = count % 128, count // 128
        header.append(digit | (128 if count else 0))
        if not count:
            return bytes(header) + body


def exact(sock, count):
    out = bytearray()
    while len(out) < count:
        part = sock.recv(count - len(out))
        if not part:
            raise ConnectionError("Printer closed connection")
        out.extend(part)
    return bytes(out)


def receive(sock):
    head, count, multiplier = exact(sock, 1)[0], 0, 1
    for _ in range(4):
        value = exact(sock, 1)[0]
        count += (value & 127) * multiplier
        if not value & 128:
            if count > 2_000_000:
                raise ValueError("Unexpected MQTT packet size")
            return head, exact(sock, count)
        multiplier *= 128
    raise ValueError("Invalid MQTT frame")


def merge(target, update):
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = value


def sanitize(state):
    keys = [
        "gcode_state",
        "gcode_file",
        "subtask_name",
        "mc_percent",
        "mc_remaining_time",
        "layer_num",
        "total_layer_num",
        "nozzle_temper",
        "nozzle_target_temper",
        "bed_temper",
        "bed_target_temper",
        "print_error",
        "nozzle_diameter",
        "nozzle_type",
        "sdcard",
        "mc_print_stage",
        "mc_print_sub_stage",
        "ams_status",
        "hms",
    ]
    safe = {k: state[k] for k in keys if k in state}
    if "fun" in state:
        try:
            safe["mqtt_signature_required"] = bool(
                int(str(state["fun"]), 16) & 0x20000000
            )
        except ValueError:
            safe["mqtt_signature_required"] = None
    if isinstance(state.get("vt_tray"), dict):
        safe["vt_tray"] = {
            k: v
            for k, v in state["vt_tray"].items()
            if k in ["id", "tray_type", "tray_color", "tray_info_idx"]
        }
    if isinstance(state.get("ams"), dict):
        ams = state["ams"]
        safe["ams"] = {
            k: ams[k]
            for k in ["tray_now", "tray_tar", "ams_exist_bits", "tray_exist_bits"]
            if k in ams
        }
        safe["ams"]["units"] = [
            {
                "id": unit.get("id"),
                "trays": [
                    {
                        k: tray[k]
                        for k in [
                            "id",
                            "tray_type",
                            "tray_color",
                            "tray_info_idx",
                            "remain",
                        ]
                        if k in tray
                    }
                    for tray in unit.get("tray", [])
                ],
            }
            for unit in ams.get("ams", [])
        ]
    return safe


class Connection:
    def __init__(self, cfg=None):
        self.cfg = cfg or config()

    def __enter__(self):
        self.serial, code = credentials(self.cfg)
        self.sock = tls_socket(self.cfg, 8883)
        try:
            self.sock.settimeout(10)
            payload = field("MQTT") + b"\x04\xc2\x00\x1e"
            payload += (
                field("a1cli-status-" + uuid.uuid4().hex[:12])
                + field("bblp")
                + field(code)
            )
            self.sock.sendall(packet(0x10, payload))
            head, payload = receive(self.sock)
            if head != 0x20 or payload != b"\x00\x00":
                raise RuntimeError("MQTT authentication failed")
            self.sock.sendall(
                packet(
                    0x82,
                    b"\x00\x01" + field("device/" + self.serial + "/report") + b"\x00",
                )
            )
            return self
        except Exception:
            self.sock.close()
            raise

    def read(self, timeout=8):
        for request in [
            {"pushing": {"sequence_id": "0", "command": "pushall"}},
            {"info": {"sequence_id": "0", "command": "get_version"}},
        ]:
            self.sock.sendall(
                packet(
                    0x30,
                    field("device/" + self.serial + "/request")
                    + json.dumps(request).encode(),
                )
            )
        state, firmware = {}, []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.sock.settimeout(max(0.1, deadline - time.monotonic()))
            try:
                head, body = receive(self.sock)
            except socket.timeout:
                break
            if head >> 4 != 3:
                continue
            topic_length = int.from_bytes(body[:2], "big")
            topic, offset = body[2 : 2 + topic_length].decode(), 2 + topic_length
            qos = (head >> 1) & 3
            if qos:
                msg_id, offset = body[offset : offset + 2], offset + 2
                if qos == 1:
                    self.sock.sendall(packet(0x40, msg_id))
            if topic != "device/" + self.serial + "/report":
                continue
            message = json.loads(body[offset:])
            merge(state, message.get("print", {}))
            if message.get("info", {}).get("module"):
                firmware = [
                    {k: item[k] for k in ["name", "sw_ver", "hw_ver"] if k in item}
                    for item in message["info"]["module"]
                ]
            if {
                "gcode_state",
                "nozzle_temper",
                "ams",
                "sdcard",
                "print_error",
                "fun",
            } <= state.keys() and firmware:
                break
        if "gcode_state" not in state:
            raise RuntimeError("Connected, but no fresh printer status received")
        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "host": self.cfg["host"],
            "tls_verified": True,
            "status": sanitize(state),
            "firmware": firmware,
        }

    def __exit__(self, *args):
        try:
            self.sock.sendall(b"\xe0\x00")
        except OSError:
            pass
        self.sock.close()


def status():
    with Connection() as connection:
        return connection.read()


def camera(destination):
    cfg = config()
    _, code = credentials(cfg)
    with tls_socket(cfg, 6000) as sock:
        sock.settimeout(12)
        sock.sendall(
            struct.pack(
                "<IIII32s32s", 0x40, 0x3000, 0, 0, b"bblp", code.encode("ascii")
            )
        )
        count = struct.unpack("<IIII", exact(sock, 16))[0]
        if not 4 <= count <= 10_000_000:
            raise ValueError("Invalid camera frame size")
        jpeg = exact(sock, count)
    if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
        raise ValueError("Invalid JPEG camera frame")
    destination = pathlib.Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(jpeg)
    return {
        "file": str(destination),
        "bytes": len(jpeg),
        "tls_verified": True,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
