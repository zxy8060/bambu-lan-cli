# Bambu A1 CLI

[简体中文](README.zh-CN.md)

An independent, experimental Python CLI for inspecting sliced A1 jobs, slicing with an installed Bambu Studio CLI, reading LAN status/camera frames, and dispatching reviewed jobs using an operator-provided signing identity. Existing cloud and Handy settings are left unchanged. No desktop automation or WSL is used.

**Signing credentials are not included or extracted by this project.** Signed dispatch requires an authorized RSA application identity that the printer already trusts. Installing this repository alone does not enable signed printing. See [credential requirements](docs/credentials.md).

## Scope

| Feature | Support |
| --- | --- |
| Inspect a sliced `.gcode.3mf` | Single plate, single material, A1 / 0.4 mm, by-layer |
| Slice STL | Installed Bambu Studio CLI and a complete resolved profile required |
| LAN status / camera | Verified TLS, pinned printer serial and operator-supplied CA bundle |
| Signed dispatch | Windows, PLA, AMS unit 0 slots 1–4, supplied trusted application identity |
| Other operating systems | Offline inspection/tests supported; no portable credential store or signed dispatcher yet |
| Cloud sending / multi-host scheduler | Not implemented |

The originating private prototype started a real A1 print on firmware **01.08.01.00**, using Studio **02.08.02.61**, a 0.4 mm nozzle and black PLA from AMS slot 2. The public refactor is validated with offline tests; it has not been reprinted as a separate hardware qualification. Firmware, credentials and certificate trust can change. This is not an official Bambu Lab SDK or product.

## Install

Python 3.11+ is required. Run these commands in a cloned checkout:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\bambu-a1.exe --help
```

The installed entry point is `bambu-a1`; `python -m bambu_a1` is equivalent. The commands below assume the virtual environment is active or its executable directory is on PATH.

## Configure one printer

Runtime files default to `%LOCALAPPDATA%/BambuA1Cli` on Windows. `BAMBU_A1_HOME` selects another private directory; set it before starting the CLI. Do not put it inside your checkout. Each directory is bound to one printer. The CLI does not reuse any machine's private prototype state automatically.

Obtain the printer CA bundle from a trusted source and verify its provenance. It is a public certificate bundle, not a private key. This repository intentionally does not distribute vendor binaries, credentials or CA bundles. The [ha-bambulab public CA reference](https://github.com/greghesp/ha-bambulab/blob/main/custom_components/bambu_lab/pybambu/certs/bambu.cert) is one research source; verify it is appropriate for your device. An application CA bundle can be supplied separately with `--app-ca-file`.

```powershell
bambu-a1 init --host 192.0.2.10 --serial YOURPRINTERSERIAL --ca-file C:/private/printer-ca.pem --studio-config C:/path/to/BambuStudio.conf --studio-exe 'C:/Program Files/Bambu Studio/bambu-studio.exe' --profile C:/private/a1-full-profile.json
bambu-a1 status
bambu-a1 camera --out C:/private/bed.jpg
```

Replace the documentation-only IP and all paths. `init` refuses to overwrite existing configuration. `studio-config` is optional: alternatively provide the access code through the environment variable named by `--access-code-env` (default `BAMBU_A1_ACCESS_CODE`), using your secret manager. There is no access-code command-line argument. The Studio reader only selects the access code for the configured serial; it does not read or reuse cloud login tokens.

The full profile can be exported from a correctly configured project: `Metadata/project_settings.config` inside its 3MF. It must contain resolved start/end G-code; an inheritance-only preset is insufficient. No default temperatures or private profiles are bundled.

## Inspect and slice

```powershell
bambu-a1 inspect --file C:/prints/part.gcode.3mf
bambu-a1 slice --model C:/prints/part.stl --out C:/prints/part.gcode.3mf --profile C:/private/a1-full-profile.json
bambu-a1 preflight --file C:/prints/part.gcode.3mf --slot 2
```

Slicing preserves model scale/orientation and arranges it centrally. `--overrides` accepts a JSON file containing process/color fields listed in `a1.slice_model`. Inspection validates archive and metadata consistency, checksums and reported bounds; it is **not a G-code motion simulator or a guarantee of safe geometry**.

## Prepare, review, send once

First complete the [credential setup](docs/credentials.md). Check the physical build plate, filament and bed. Preparation does not send a print:

```powershell
bambu-a1 prepare-print --file C:/prints/part.gcode.3mf --slot 2 --label 'Reviewed part'
```

Actually inspect the returned `camera.file`. The hash identifies that image; passing it does not itself perform visual review. Under authorization for this specific job, dispatch within five minutes:

```powershell
bambu-a1 dispatch --job-id RETURNED_JOB_ID --reviewed-bed-sha256 REVIEWED_IMAGE_SHA256
bambu-a1 job-status --job-id RETURNED_JOB_ID
```

Dispatch rechecks the file, printer and AMS; uploads a unique filename through FTPS; reads back identical bytes; records a receipt; and sends one signed request. It then independently checks the unique filename and active state. ACK success alone does not prove that the correct job started.

- A receipt blocks a second send, including after timeouts. Never delete it or create another job to bypass an uncertain outcome; inspect live state first.
- The same local runtime directory serializes dispatch and sequence allocation. Locks do not coordinate different computers or different runtime directories. Use one execution host per printer.
- Errors/HMS messages and changed materials are not ignored. Do not weaken checks to force a job through.
- Exit codes: `0` completed CLI operation; `1` exception/configuration failure; `2` failed preflight; `3` dispatch outcome not confirmed. An error after sending does **not** prove that printing did not start.
- `monitor --seconds 45 --interval 10` is bounded polling, not an installed background service.

## Development

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
```

Tests create ephemeral synthetic keys, certificates, archives and fake transports. They never print, contact a printer, read a developer's credentials or require GitHub secrets. Windows CI exercises DPAPI and locking; Ubuntu CI exercises the portable subset and skips Windows-only tests.

See [protocol notes](docs/protocol.md), [security reporting](SECURITY.md) and [contribution notes](CONTRIBUTING.md). Licensed under **AGPL-3.0-or-later**; attribution and source provenance are in [NOTICE.md](NOTICE.md).
