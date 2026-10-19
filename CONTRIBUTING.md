# Contributing

Use Python 3.11+ and an isolated virtual environment. Install with `python -m pip install -e .`, then run `python -m unittest discover -s tests -v`. Windows is required to exercise DPAPI and dispatch locks; portable tests also run on Ubuntu.

Use synthetic keys, certificate chains, archives and fake printer transports in tests. Do not add tests that connect to a real device, send motion/heat/print commands, read a developer's credentials, or require GitHub secrets. Hardware tests must be explicit, authorized and reported separately from offline CI.

Preserve verified TLS, exact target binding, byte-for-byte upload verification, fresh preflight checks, durable receipts and no automatic resend. Discuss new printer/material modes with evidence before broadening supported scope. Do not add an arbitrary MQTT/G-code command passthrough as a shortcut.

Contributions are under AGPL-3.0-or-later. Retain attribution for adapted code and identify external dependencies. Never commit vendor binaries, credential extraction helpers, signing material, raw private logs or complete user configuration files.
