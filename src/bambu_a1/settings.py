"""Explicit per-installation configuration, separate from the source tree."""

import json
import os
from pathlib import Path
import re


def data_directory():
    override = os.environ.get("BAMBU_A1_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "BambuA1Cli"
    return (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        / "bambu-a1-cli"
    )


DATA = data_directory()
CONFIG = DATA / "config.json"


def validate_config(cfg):
    if cfg.get("format") != 1:
        raise ValueError("Unsupported config format; run init")
    if not isinstance(cfg.get("serial"), str) or not re.fullmatch(
        r"[A-Za-z0-9-]{5,64}", cfg["serial"]
    ):
        raise ValueError(
            "Configure the exact printer serial (letters, numbers and hyphens)"
        )
    if not isinstance(cfg.get("host"), str) or not re.fullmatch(
        r"[A-Za-z0-9.:-]{1,253}", cfg["host"]
    ):
        raise ValueError("Configure a printer IP or hostname, without a scheme or port")
    for field in ("ca_file", "app_ca_file"):
        if not isinstance(cfg.get(field), str) or not Path(cfg[field]).is_absolute():
            raise ValueError("Configure an absolute " + field + " path")
        if not Path(cfg[field]).is_file():
            raise ValueError("Configured CA file does not exist")
    if cfg.get("access_code_env") and not re.fullmatch(
        r"[A-Za-z_][A-Za-z0-9_]*", cfg["access_code_env"]
    ):
        raise ValueError("Invalid access-code environment variable name")
    return cfg


def config():
    if not CONFIG.exists():
        raise ValueError("Configuration missing; run bambu-a1 init --help")
    return validate_config(json.loads(CONFIG.read_text(encoding="utf-8-sig")))


def initialize(
    host,
    serial,
    ca_file,
    app_ca_file=None,
    studio_config=None,
    studio_exe=None,
    profile=None,
    access_code_env="BAMBU_A1_ACCESS_CODE",
):
    cfg = {
        "format": 1,
        "host": host,
        "serial": serial,
        "ca_file": str(Path(ca_file).expanduser().resolve()),
        "app_ca_file": str(Path(app_ca_file or ca_file).expanduser().resolve()),
        "access_code_env": access_code_env,
    }
    for field, value in [
        ("studio_config", studio_config),
        ("studio_exe", studio_exe),
        ("default_profile", profile),
    ]:
        if value:
            cfg[field] = str(Path(value).expanduser().resolve())
    validate_config(cfg)
    DATA.mkdir(parents=True, exist_ok=True)
    with CONFIG.open("x", encoding="utf-8") as stream:
        json.dump(cfg, stream, indent=2)
    return {"state": "configured", "config_file": str(CONFIG), "print_started": False}
