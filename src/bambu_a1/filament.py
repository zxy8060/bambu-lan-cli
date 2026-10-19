"""Single-material routing; material names are not restricted to PLA."""


def route(slot=None, ams_id=0, external=False):
    if external:
        if slot is not None or ams_id != 0:
            raise ValueError("External spool cannot be combined with an AMS slot/unit")
        return {
            "source": "external",
            "use_ams": False,
            "ams_mapping": [-1],
            "ams_mapping2": [{"ams_id": 255, "slot_id": 0}],
        }
    if type(slot) is not int or type(ams_id) is not int:
        raise ValueError("Choose an AMS slot or --external")
    # Protocol four-slot units use IDs 0..25; AMS HT uses IDs 128..135.
    if 0 <= ams_id <= 25 and 1 <= slot <= 4:
        flat = ams_id * 4 + slot - 1
    elif 128 <= ams_id <= 135 and slot == 1:
        flat = ams_id
    else:
        raise ValueError("Use AMS ID 0..25 / slot 1..4, or AMS HT ID 128..135 / slot 1")
    return {
        "source": "ams",
        "use_ams": True,
        "ams_mapping": [flat],
        "ams_mapping2": [{"ams_id": ams_id, "slot_id": slot - 1}],
    }


def selected_tray(state, routing):
    if not routing["use_ams"]:
        tray = state.get("vt_tray")
        if isinstance(tray, dict):
            return tray
        # Some firmware uses a list even for a single virtual tray. Never pick
        # the first one from a multi-nozzle report without nozzle mapping.
        if isinstance(tray, list) and len(tray) == 1:
            return tray[0]
        return None
    selection = routing["ams_mapping2"][0]
    return next(
        (
            tray
            for unit in state.get("ams", {}).get("units", [])
            if str(unit.get("id")) == str(selection["ams_id"])
            for tray in unit.get("trays", [])
            if str(tray.get("id")) == str(selection["slot_id"])
        ),
        None,
    )


def calibration_flags(model, flow=False, vibration=False):
    # H2-family firmware uses integer flags; older families use booleans.
    convert = int if model.startswith("Bambu Lab H2") else bool
    return {
        "bed_leveling": convert(True),
        "flow_cali": convert(flow),
        "vibration_cali": convert(vibration),
        "layer_inspect": convert(False),
    }
