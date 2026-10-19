"""Machine geometry comes from an operator-selected, resolved Studio profile."""

import json
import math
from pathlib import Path


def finite_number(value):
    if isinstance(value, bool):
        raise ValueError("Expected a finite number")
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise ValueError("Expected a finite number") from None
    if not math.isfinite(number):
        raise ValueError("Expected a finite number")
    return number


def from_profile(profile):
    model = profile.get("printer_model")
    if (
        not isinstance(model, str)
        or not model.startswith("Bambu Lab ")
        or len(model) > 100
    ):
        raise ValueError("Profile must name a Bambu Lab printer model")
    nozzles = profile.get("nozzle_diameter")
    if not isinstance(nozzles, list) or len(nozzles) != 1:
        raise ValueError(
            "Only single-nozzle profiles are supported; dual-nozzle routing is not implemented"
        )
    nozzle = finite_number(nozzles[0])
    if nozzle <= 0:
        raise ValueError("Invalid profile nozzle diameter")
    area = profile.get("printable_area")
    if not isinstance(area, list) or len(area) != 4:
        raise ValueError("A rectangular printable_area with four corners is required")
    try:
        points = [tuple(finite_number(v) for v in point.split("x")) for point in area]
    except (AttributeError, ValueError):
        raise ValueError("Invalid printable_area coordinates") from None
    if any(len(point) != 2 for point in points):
        raise ValueError("Invalid printable_area coordinates")
    xs, ys = sorted({p[0] for p in points}), sorted({p[1] for p in points})
    if len(xs) != 2 or len(ys) != 2 or set(points) != {(x, y) for x in xs for y in ys}:
        raise ValueError("Only rectangular build plates are supported")
    height = finite_number(profile.get("printable_height"))
    if height <= 0:
        raise ValueError("Invalid profile build height")
    return {
        "model": model,
        "nozzle_mm": nozzle,
        "bounds_xy_mm": [xs[0], ys[0], xs[1], ys[1]],
        "height_mm": height,
    }


def read_profile(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def target(cfg):
    # This profile is selected independently of the job being checked. Never
    # silently adopt the job's printer settings as the target machine identity.
    path = cfg.get("machine_profile") or cfg.get("default_profile")
    if not path:
        raise ValueError(
            "Set the target machine with configure-machine --profile before preflight"
        )
    return from_profile(read_profile(path))


def contains(machine, bbox, height):
    if not isinstance(bbox, list) or len(bbox) != 4:
        return False
    x0, y0, x1, y1 = [finite_number(v) for v in bbox]
    left, bottom, right, top = machine["bounds_xy_mm"]
    return (
        left <= x0 < x1 <= right
        and bottom <= y0 < y1 <= top
        and 0 < finite_number(height) <= machine["height_mm"]
    )
