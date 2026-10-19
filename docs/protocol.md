# Protocol scope and evidence

The signed transport originates from a private A1 prototype. Version 0.2 removes the fixed model, nozzle, bed-size and PLA assumptions; this is not a promise of compatibility with every firmware or printer model.

1. TLS connections validate the operator-supplied CA chain and configured serial hostname. MQTT uses port 8883; implicit FTPS uses port 990; JPEG camera frames use TLS port 6000.
2. A reviewed sliced file is uploaded under a unique `a1cli_<job-id>.gcode.3mf` filename, then read back and compared byte for byte. Existing remote filenames are not overwritten.
3. The `ftp://` URL is RSA PKCS#1 v1.5 encrypted with the verified printer TLS public key, then Base64 encoded into `url_enc`.
4. The exact compact `{"print":...}` bytes are signed with the supplied application RSA key using PKCS#1 v1.5 / SHA-256. The same serialized inner bytes are placed on the wire. The header identifies the application certificate and signed byte length.
5. A receipt is created before the print publish. Publish is attempted once. Independent status must report the unique uploaded filename and PREPARE/RUNNING to confirm startup.

## Observed differences

- The original official networking DLL returned `-26 / BAMBU_NETWORK_SIGNED_ERROR` when hosted by an independent Windows executable. That SDK error is separate from this standalone signed protocol implementation.
- An unsigned request was rejected with `84033543` on the tested A1.
- The tested firmware rejected epoch-sized sequence numbers with `84033546`, while comparable five-digit requests succeeded. The public allocator conservatively uses 20000–29999, persists the next value and stops at exhaustion. This is not a proven protocol maximum, nor evidence that every value has been tested.
- The originating print test reached RUNNING and actual layer progress on A1 firmware 01.08.01.00, Studio 02.08.02.61, nozzle 0.4 mm, PLA from AMS slot 2. Those versions describe the evidence, not an official supported-version matrix.

The public refactor uses synthetic cryptographic, archive and dispatch tests. No private printer identifiers, photos, production receipts or credential captures are published as fixtures. No hardware print is started by CI.

## Generalized routing

The target machine profile is selected independently of each job. Its canonical model/nozzle/build-volume data must match the slice, and live nozzle/material telemetry must agree. Prepared jobs retain the target, routing, calibration flags and image capture time; changing the target or route invalidates preparation. Protocol/status differences that lack an adapter fail preflight rather than silently assuming A1 defaults.

Four-slot units use `unit * 4 + slot` for the legacy mapping; HT units use their unit ID with slot zero. Single-nozzle external jobs use `use_ams=false`, a flat `[-1]` mapping, and unit 255 / slot 0 in `ams_mapping2`. Multi-nozzle and mixed-AMS routing are outside this implementation. See [Studio's mapping implementation](https://github.com/bambulab/BambuStudio/blob/master/src/slic3r/GUI/DeviceCore/DevMapping.cpp) and [the external-spool interoperability report](https://github.com/synman/bambu-printer-manager/issues/55).

Flow/vibration calibration are opt-in. H2 profile names select integer calibration fields; older-family fields remain boolean. This encoding is based on [bambu-printer-manager's implementation](https://github.com/synman/bambu-printer-manager/blob/devel/src/bpm/bambuprinter.py); H2 hardware and its required status schema have not been validated here.

The built-in image adapter remains TLS JPEG. X1/P2S use a different camera transport, described in the [camera protocol reference](https://github.com/Doridian/OpenBambuAPI/blob/main/video.md). A supplied JPEG is an explicit fallback for review, not an RTSPS adapter or proof of physical bed state. Its original mtime and preparation time both expire after five minutes. Changing mtime cannot establish genuine image freshness.

## References

- [Bambu Studio command-line usage](https://github.com/bambulab/BambuStudio/wiki/Command-Line-Usage)
- [Official SDK error handling](https://github.com/bambulab/BambuStudio/blob/v02.08.02.61/src/slic3r/GUI/Jobs/PrintJob.cpp#L858)
- [Open Bamboo Networking: credentials](https://github.com/ClusterM/open-bamboo-networking/blob/master/research/10.02-secrets.md), [signing](https://github.com/ClusterM/open-bamboo-networking/blob/master/research/10.04-mqtt-signing.md), [field encryption](https://github.com/ClusterM/open-bamboo-networking/blob/master/research/10.03-mqtt-field-encryption.md)
- [OpenBambuAPI camera protocol](https://github.com/Doridian/OpenBambuAPI/blob/main/video.md)
- [Aptimex MQTT signing reference](https://github.com/Aptimex/bambu-mqtt-generator/blob/main/bambu_mqtt_generator/sign_mqtt.py)

References document protocol research. No code license grants access to someone else's printer or a vendor's cloud infrastructure.
