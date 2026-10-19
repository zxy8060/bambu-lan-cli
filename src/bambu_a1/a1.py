"""A1 Windows CLI: slice, inspect, verified LAN monitoring and signed print dispatch."""

import argparse
import hashlib
import json
import math
import pathlib
import re
import subprocess
import tempfile
import time
import zipfile
from .lan import DATA, config, status, camera


def ensure(condition, message):
    if not condition:
        raise ValueError(message)


def write_json(path, data):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as out:
        json.dump(data, out, ensure_ascii=False, indent=2)


def inspect(path):
    path = pathlib.Path(path).resolve()
    ensure(path.is_file(), "Print file not found")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        ensure(len(names) == len(set(names)), "Duplicate archive entries")
        ensure(
            sum(i.file_size for i in archive.infolist()) < 1_000_000_000,
            "Archive too large for this helper",
        )
        gcodes = [n for n in names if re.fullmatch(r"Metadata/plate_\d+\.gcode", n)]
        ensure(
            gcodes == ["Metadata/plate_1.gcode"],
            "Require exactly one sliced plate, plate_1",
        )
        settings = json.loads(archive.read("Metadata/project_settings.config"))
        metadata = json.loads(archive.read("Metadata/plate_1.json"))
        gcode = archive.read(gcodes[0])
        expected = archive.read(gcodes[0] + ".md5").decode().strip().lower()
        ensure(hashlib.md5(gcode).hexdigest() == expected, "G-code checksum mismatch")
    ensure(
        settings.get("printer_model") == "Bambu Lab A1",
        "File must be sliced for Bambu Lab A1",
    )
    ensure(
        settings.get("nozzle_diameter") == ["0.4"],
        "This helper is verified for a single 0.4 mm nozzle",
    )
    ensure(
        abs(float(metadata.get("nozzle_diameter", 0)) - 0.4) < 0.001,
        "Plate nozzle mismatch",
    )
    ensure(
        settings.get("printable_area") == ["0x0", "256x0", "256x256", "0x256"],
        "Unexpected build plate area",
    )
    ensure(float(settings.get("printable_height", 0)) == 256, "Unexpected build height")
    bbox = metadata.get("bbox_all", [])
    ensure(
        len(bbox) == 4
        and all(
            isinstance(v, (float, int)) and math.isfinite(v) and 0 <= v <= 256
            for v in bbox
        ),
        "Model XY bounds exceed A1 plate or are missing",
    )
    ensure(bbox[0] < bbox[2] and bbox[1] < bbox[3], "Empty or reversed model bounds")
    ensure(
        not metadata.get("is_seq_print", False),
        "This workflow uses by-layer printing; review sequential printing separately",
    )
    materials = settings.get("filament_type", [])
    ensure(
        len(materials) == 1 and metadata.get("filament_ids") == [0],
        "Helper currently supports one material per plate",
    )
    body = gcode.decode("utf-8")

    def value(pattern):
        match = re.search(pattern, body, re.M)
        ensure(match is not None, "Missing G-code metadata: " + pattern)
        return match.group(1).strip()

    ensure(
        "EXECUTABLE_BLOCK_START" in body and "EXECUTABLE_BLOCK_END" in body,
        "Missing executable G-code markers",
    )
    ensure(
        value(r"^; printer_model = (.+)$") == settings["printer_model"],
        "G-code and project model disagree",
    )
    ensure(float(value(r"^; nozzle_diameter = (.+)$")) == 0.4, "G-code nozzle mismatch")
    ensure(
        value(r"^; filament_type = (.+)$") == materials[0], "G-code material mismatch"
    )
    ensure(
        value(r"^; curr_bed_type = (.+)$") == settings.get("curr_bed_type"),
        "G-code plate type mismatch",
    )
    max_z = float(value(r"^; max_z_height: (.+)$"))
    ensure(0 < max_z <= 256, "Model Z exceeds A1 height")
    return {
        "file": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "validated": True,
        "printer": settings["printer_model"],
        "nozzle_mm": 0.4,
        "material": materials[0],
        "colors": settings.get("filament_colour", []),
        "filament_profile": settings.get("filament_settings_id", []),
        "bed_type": settings.get("curr_bed_type"),
        "bbox_xy_mm": bbox,
        "height_mm": max_z,
        "layer_height_mm": settings.get("layer_height"),
        "walls": settings.get("wall_loops"),
        "infill": settings.get("sparse_infill_density"),
        "estimated_time": value(r"total estimated time: ([^\r\n]+)"),
        "filament_grams": float(value(r"^; total filament weight \[g\] : (.+)$")),
        "layers": int(value(r"^; total layer number: (.+)$")),
        "validation_scope": "Archive integrity and slicer metadata; not a full motion simulation",
    }


def preflight(file, slot):
    job, live = inspect(file), status()
    state, failures, warnings = live["status"], [], []

    def check(ok, message):
        if not ok:
            failures.append(message)

    check(
        state.get("gcode_state") in ["IDLE", "FINISH"], "Printer is not confirmed idle"
    )
    check(
        state.get("print_error") == 0,
        "Printer reports an error or error status is missing",
    )
    check(
        "hms" in state and not state["hms"],
        "HMS messages require review or HMS status is missing",
    )
    check(state.get("sdcard") is True, "SD card not confirmed present")
    check(
        str(state.get("nozzle_diameter")) == "0.4",
        "Installed nozzle is not confirmed 0.4 mm",
    )
    check(state.get("ams_status") == 0, "AMS is not confirmed idle")
    check(
        state.get("nozzle_target_temper") == 0 and state.get("bed_target_temper") == 0,
        "Printer currently has heating targets or temperatures are missing",
    )
    check(1 <= slot <= 4, "AMS Lite slot must be 1 through 4")
    tray = next(
        (
            t
            for u in state.get("ams", {}).get("units", [])
            if str(u.get("id")) == "0"
            for t in u.get("trays", [])
            if str(t.get("id")) == str(slot - 1)
        ),
        None,
    )
    check(tray is not None, "Requested AMS slot was not returned")
    if tray:
        check(
            tray.get("tray_type") == job["material"],
            "AMS material differs from the sliced material",
        )
        expected_color = (job["colors"] or [""])[0].lstrip("#").upper()[:6]
        if expected_color and tray.get("tray_color", "").upper()[:6] != expected_color:
            warnings.append(
                "AMS color differs from the sliced project; confirm desired color"
            )
        warnings.append(
            "Remaining spool mass is not reliably measured; check sufficient filament"
        )
    warnings.append(
        "Verify physical build plate matches "
        + str(job["bed_type"])
        + " and bed is clear"
    )
    return {
        "checks_passed": not failures,
        "file": job,
        "ams_slot": slot,
        "ams_zero_based_mapping": [slot - 1],
        "selected_tray": tray,
        "failures": failures,
        "warnings": warnings,
        "live": live,
        "print_started": False,
        "automatic_send_available": (DATA / "app-credential.dpapi").exists(),
        "send_route": "signed_lan_windows",
        "send_scope": "Verified A1/0.4/PLA single plate; prepare + reviewed image + dispatch",
    }


def run_studio(arguments, log):
    exe = pathlib.Path(config()["studio_exe"])
    ensure(exe.is_file(), "Configured Bambu Studio executable is missing")
    with pathlib.Path(log).open("wb") as output:
        process = subprocess.run(
            [str(exe), *map(str, arguments)],
            stdout=output,
            stderr=subprocess.STDOUT,
            timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    ensure(process.returncode == 0, "Bambu Studio CLI failed; inspect " + str(log))


def slice_model(model, output, profile=None, overrides=None):
    model, output = pathlib.Path(model).resolve(), pathlib.Path(output).resolve()
    ensure(
        model.is_file() and model.suffix.lower() == ".stl",
        "Input must be an existing STL in millimeters",
    )
    ensure(not output.exists(), "Refusing to overwrite an existing sliced file")
    settings = json.loads(
        pathlib.Path(profile or config()["default_profile"]).read_text(
            encoding="utf-8-sig"
        )
    )
    ensure(
        settings.get("printer_model") == "Bambu Lab A1"
        and settings.get("nozzle_diameter") == ["0.4"],
        "Profile must target A1 0.4",
    )
    ensure(
        bool(settings.get("machine_start_gcode"))
        and bool(settings.get("machine_end_gcode")),
        "Need a full resolved Studio profile, not a preset with inherits",
    )
    if overrides:
        changes = json.loads(pathlib.Path(overrides).read_text(encoding="utf-8-sig"))
        allowed = {
            "wall_loops",
            "sparse_infill_density",
            "sparse_infill_pattern",
            "layer_height",
            "initial_layer_print_height",
            "top_shell_layers",
            "bottom_shell_layers",
            "enable_support",
            "support_type",
            "brim_type",
            "brim_width",
            "filament_colour",
        }
        ensure(
            set(changes) <= allowed,
            "Overrides may only change documented process/color fields",
        )
        settings.update(changes)
    settings["print_sequence"] = "by layer"
    output.parent.mkdir(parents=True, exist_ok=True)
    scratch_root = DATA / "scratch"
    scratch_root.mkdir(parents=True, exist_ok=True)
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="slice-", dir=scratch_root))
    source, prepared = scratch / "source.3mf", scratch / "prepared.3mf"
    run_studio(["--debug", "2", "--export-3mf", source, model], scratch / "export.log")
    ensure(source.is_file(), "CLI returned but did not export a project")
    with (
        zipfile.ZipFile(source) as old,
        zipfile.ZipFile(prepared, "w", zipfile.ZIP_DEFLATED) as new,
    ):
        ensure(
            "Metadata/project_settings.config" in old.namelist(),
            "Exported project has no settings",
        )
        for item in old.infolist():
            payload = (
                json.dumps(settings, ensure_ascii=False).encode()
                if item.filename == "Metadata/project_settings.config"
                else old.read(item)
            )
            new.writestr(item, payload)
    run_studio(
        [
            "--debug",
            "2",
            "--slice",
            "0",
            "--arrange",
            "1",
            "--export-3mf",
            output,
            prepared,
        ],
        scratch / "slice.log",
    )
    result = inspect(output)
    result["scratch"] = str(scratch)
    write_json(output.with_suffix(output.suffix + ".report.json"), result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    cmd = commands.add_parser(
        "init", help="Create private configuration; no network requests"
    )
    cmd.add_argument("--host", required=True)
    cmd.add_argument("--serial", required=True)
    cmd.add_argument("--ca-file", required=True)
    cmd.add_argument("--app-ca-file")
    cmd.add_argument("--studio-config")
    cmd.add_argument("--studio-exe")
    cmd.add_argument("--profile")
    cmd.add_argument("--access-code-env", default="BAMBU_A1_ACCESS_CODE")
    cmd = commands.add_parser(
        "credential-import",
        help="Import your authorized, already trusted application identity on Windows",
    )
    cmd.add_argument("--certificate", required=True)
    cmd.add_argument("--private-key", required=True)
    cmd.add_argument(
        "--password-prompt",
        action="store_true",
        help="Prompt securely for an encrypted PEM password",
    )
    commands.add_parser("status")
    cmd = commands.add_parser("camera")
    cmd.add_argument("--out", required=True)
    cmd = commands.add_parser("inspect")
    cmd.add_argument("--file", required=True)
    cmd = commands.add_parser("slice")
    cmd.add_argument("--model", required=True)
    cmd.add_argument("--out", required=True)
    cmd.add_argument("--profile")
    cmd.add_argument("--overrides")
    cmd = commands.add_parser("preflight")
    cmd.add_argument("--file", required=True)
    cmd.add_argument("--slot", required=True, type=int)
    cmd.add_argument("--out")
    cmd = commands.add_parser("monitor")
    cmd.add_argument("--seconds", type=int, default=45)
    cmd.add_argument("--interval", type=int, default=10)
    cmd = commands.add_parser("prepare-print")
    cmd.add_argument("--file", required=True)
    cmd.add_argument("--slot", required=True, type=int)
    cmd.add_argument("--label")
    cmd = commands.add_parser("dispatch")
    cmd.add_argument("--job-id", required=True)
    cmd.add_argument("--reviewed-bed-sha256", required=True)
    cmd = commands.add_parser("job-status")
    cmd.add_argument("--job-id", required=True)
    args = parser.parse_args(argv)
    if args.command == "init":
        from .settings import initialize

        result = initialize(
            args.host,
            args.serial,
            args.ca_file,
            args.app_ca_file,
            args.studio_config,
            args.studio_exe,
            args.profile,
            args.access_code_env,
        )
    elif args.command == "credential-import":
        import getpass
        from .app_credentials import import_files

        password = (
            getpass.getpass("PEM password: ").encode() if args.password_prompt else None
        )
        result = import_files(args.certificate, args.private_key, password)
    elif args.command == "status":
        result = status()
    elif args.command == "camera":
        result = camera(args.out)
    elif args.command == "inspect":
        result = inspect(args.file)
    elif args.command == "slice":
        result = slice_model(args.model, args.out, args.profile, args.overrides)
    elif args.command == "preflight":
        result = preflight(args.file, args.slot)
        if args.out:
            write_json(args.out, result)
    elif args.command in {"prepare-print", "dispatch", "job-status"}:
        from . import a1_print

        if args.command == "prepare-print":
            result = a1_print.prepare(args.file, args.slot, args.label)
        elif args.command == "dispatch":
            result = a1_print.dispatch(args.job_id, args.reviewed_bed_sha256)
        else:
            result = a1_print.job_status(args.job_id)
    else:
        ensure(
            1 <= args.seconds <= 50 and 5 <= args.interval <= 30,
            "Monitor uses bounded 1-50 second windows and 5-30 second intervals",
        )
        deadline = time.monotonic() + args.seconds
        while True:
            print(json.dumps(status(), ensure_ascii=False), flush=True)
            remaining = deadline - time.monotonic()
            if remaining < args.interval + 8:
                return
            time.sleep(args.interval)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "preflight" and not result["checks_passed"]:
        return 2
    if args.command in {"prepare-print", "dispatch"} and result.get(
        "state", ""
    ).endswith(("failed", "no_print_sent")):
        return 2
    if args.command == "dispatch" and result.get("print_started") is not True:
        return 3
    return 0


def entrypoint():
    try:
        code = main()
    except Exception as error:
        print(
            json.dumps(
                {
                    "error_type": type(error).__name__,
                    "operation_failed": True,
                    "hint": str(error)
                    if isinstance(error, (ValueError, RuntimeError))
                    else "Check local files, connection, job receipt and live printer before any retry",
                },
                ensure_ascii=False,
            )
        )
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    entrypoint()
