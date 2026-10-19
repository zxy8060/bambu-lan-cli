# Bambu LAN CLI

[简体中文](README.zh-CN.md)

An independent, experimental Python CLI for profile-driven Bambu slicing, LAN monitoring and reviewed signed print dispatch. Model, nozzle diameter and build volume come from a resolved machine profile. There is no PLA-only material restriction. Existing cloud and Handy settings are left unchanged. No desktop automation or WSL is used.

**Signing credentials are not included or extracted by this project.** Signed dispatch requires an authorized RSA application identity that the printer already trusts. Installing this repository alone does not enable signed printing. See [credential requirements](docs/credentials.md).

## Scope

| Feature | Support |
| --- | --- |
| Inspect a sliced `.gcode.3mf` | Single plate, single material, single nozzle, rectangular build volume from profile, by-layer |
| Slice STL | Installed Bambu Studio CLI and a complete resolved profile required |
| LAN status | Verified TLS, pinned printer serial and operator-supplied CA bundle; required telemetry must be present |
| Camera | TLS JPEG transport (A1/P1); fresh operator-supplied JPEG alternative; built-in RTSPS capture not implemented |
| Signed dispatch | Windows, matching machine profile and live nozzle/material, trusted signing identity, compatible firmware |
| Filament source | Explicit AMS unit/slot, AMS HT single slot, or external spool; one material per job |
| Materials | No whitelist: PETG, ABS, ASA, TPU, etc. require an appropriate machine/filament profile and feed path |
| Other operating systems | Offline inspection/tests supported; no portable credential store or signed dispatcher yet |
| Cloud sending / multi-host scheduler | Not implemented |
| Dual-nozzle / multicolor / mixed AMS routing | Not implemented; dual-nozzle profiles and multi-material plates are rejected |

The originating private prototype started a real A1 print on firmware **01.08.01.00**, using Studio **02.08.02.61**, a 0.4 mm nozzle and black PLA from AMS slot 2. The public refactor and generalized paths are validated with offline tests only. Other models/materials are **not hardware-qualified** by this project. A matching profile does not prove that a material is appropriate for the machine, enclosure, nozzle or AMS. This is not an official Bambu Lab SDK or product.

## Install

Python 3.11+ is required. Run these commands in a cloned checkout:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\bambu-lan.exe --help
```

The main entry point is `bambu-lan`. The legacy `bambu-a1` command and `python -m bambu_a1` remain available. The commands below assume the virtual environment is active or its executable directory is on PATH.

## Configure one printer

Runtime files still default to `%LOCALAPPDATA%/BambuA1Cli` on Windows for compatibility. `BAMBU_LAN_HOME` selects another private directory (`BAMBU_A1_HOME` is the fallback alias); set it before starting the CLI. Do not put it inside your checkout. Each directory is bound to one printer. The CLI does not reuse any machine's private prototype state automatically.

Obtain the printer CA bundle from a trusted source and verify its provenance. It is a public certificate bundle, not a private key. This repository intentionally does not distribute vendor binaries, credentials or CA bundles. The [ha-bambulab public CA reference](https://github.com/greghesp/ha-bambulab/blob/main/custom_components/bambu_lab/pybambu/certs/bambu.cert) is one research source; verify it is appropriate for your device. An application CA bundle can be supplied separately with `--app-ca-file`.

```powershell
bambu-lan init --host 192.0.2.10 --serial YOURPRINTERSERIAL --ca-file C:/private/printer-ca.pem --studio-config C:/path/to/BambuStudio.conf --studio-exe 'C:/Program Files/Bambu Studio/bambu-studio.exe' --profile C:/private/machine-full-profile.json
bambu-lan status
bambu-lan camera --out C:/private/bed.jpg
```

Replace the documentation-only IP and all paths. `init` refuses to overwrite existing configuration. `studio-config` is optional: alternatively provide the access code through the environment variable named by `--access-code-env` (default `BAMBU_A1_ACCESS_CODE`), using your secret manager. There is no access-code command-line argument. The Studio reader only selects the access code for the configured serial; it does not read or reuse cloud login tokens.

The full profile can be exported from a correctly configured project: `Metadata/project_settings.config` inside its 3MF. It must contain resolved start/end G-code; an inheritance-only preset is insufficient. No default temperatures or private profiles are bundled.

`init --profile` provides both the slicing default and the independently selected target machine. To select/change the target on an existing installation, use `bambu-lan configure-machine --profile C:/private/machine-full-profile.json`. This changes local configuration only. It does not change printer accessories or the default slicing material. Preflight compares the job's model, nozzle and build volume with that target and the live nozzle diameter. Machine identity comes from the operator's profile; it is not an automatic model discovery claim. TLS separately authenticates the configured device serial. Missing required telemetry blocks sending.

## Inspect and slice

```powershell
bambu-lan inspect --file C:/prints/part.gcode.3mf
bambu-lan slice --model C:/prints/part.stl --out C:/prints/part.gcode.3mf --profile C:/private/machine-full-profile.json
bambu-lan preflight --file C:/prints/part.gcode.3mf --slot 2
```

Slicing preserves model scale/orientation and arranges it centrally. `--overrides` accepts a JSON file containing process/color fields listed in `a1.slice_model`. Inspection validates archive and metadata consistency, checksums and reported bounds; it is **not a G-code motion simulator or a guarantee of safe geometry**.

Choose `--ams-id` using the IDs returned by `status`; `--slot` is 1-based within that unit (default unit 0). Four-slot protocol unit IDs 0–25 and single-slot HT IDs 128–135 are accepted only when the requested tray is reported. This range describes encoding, not the number of units a particular printer can connect. For example:

```powershell
bambu-lan preflight --file C:/prints/petg.gcode.3mf --ams-id 1 --slot 2
bambu-lan preflight --file C:/prints/tpu.gcode.3mf --external
```

The selected AMS or external tray's reported material must exactly match the slice. Configure external-spool material on the printer before using `--external`. There is no PLA temperature fallback: temperatures remain those of the selected slicing profile. The CLI does not determine every material/feed-path compatibility combination; select the appropriate profile and hardware.

## Prepare, review, send once

First complete the [credential setup](docs/credentials.md). Check the physical build plate, filament and bed. Preparation does not send a print:

```powershell
bambu-lan prepare-print --file C:/prints/part.gcode.3mf --slot 2 --label 'Reviewed part'
```

Actually inspect the returned `camera.file`. The hash identifies that image; passing it does not itself perform visual review. Under authorization for this specific job, dispatch within five minutes:

```powershell
bambu-lan dispatch --job-id RETURNED_JOB_ID --reviewed-bed-sha256 REVIEWED_IMAGE_SHA256
bambu-lan job-status --job-id RETURNED_JOB_ID
```

Use `--external` instead of `--slot` for an external spool, or add `--ams-id` for another unit. Flow and vibration calibration default to off; opt in with `--flow-calibration` and `--vibration-calibration` when supported by the machine/material. Bed leveling remains enabled.

For a printer whose camera does not use TLS JPEG (for example X1), capture a fresh JPEG through an available camera path and supply `--bed-image C:/private/fresh-bed.jpg` to `prepare-print`. Actually verify that it shows this printer's current bed. File mtime is used as the capture-time proxy and cannot prove freshness or device identity; it must not be refreshed to reuse an old image. Both preparation and image must remain within five minutes through dispatch. The source's original age is preserved when copied.

Dispatch rechecks the file, target profile, live printer and selected filament; uploads a unique filename through FTPS; reads back identical bytes; records a receipt; and sends one signed request. A changed machine or route requires preparation again. It then independently checks the unique filename and active state. ACK success alone does not prove that the correct job started.

- A receipt blocks a second send, including after timeouts. Never delete it or create another job to bypass an uncertain outcome; inspect live state first.
- The same local runtime directory serializes dispatch and sequence allocation. Locks do not coordinate different computers or different runtime directories. Use one execution host per printer.
- Errors/HMS messages and changed materials are not ignored. Do not weaken checks to force a job through.
- Exit codes: `0` completed CLI operation; `1` exception/configuration failure; `2` failed preflight; `3` dispatch outcome not confirmed. An error after sending does **not** prove that printing did not start.
- `monitor --seconds 45 --interval 10` is bounded polling, not an installed background service.

## Upgrading from 0.1

Install the new `bambu-lan-cli` distribution in a fresh virtual environment (or uninstall `bambu-a1-cli` first, since both distributions share the compatibility package). Existing public-project configuration, DPAPI identity and receipt history remain in the same runtime directory. Configure a target profile if it was previously omitted. Version 0.1 prepared manifests cannot be dispatched by 0.2; inspect existing receipts/status and prepare a fresh reviewed job only when appropriate. Never delete receipt history to force a resend.

## Development

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
```

Tests create ephemeral synthetic keys, certificates, archives and fake transports. They never print, contact a printer, read a developer's credentials or require GitHub secrets. Windows CI exercises DPAPI and locking; Ubuntu CI exercises the portable subset and skips Windows-only tests.

See [protocol notes](docs/protocol.md), [security reporting](SECURITY.md) and [contribution notes](CONTRIBUTING.md). Licensed under **AGPL-3.0-or-later**; attribution and source provenance are in [NOTICE.md](NOTICE.md).
