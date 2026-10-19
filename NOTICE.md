# License and provenance

Copyright (C) 2026 zxy8060 and contributors.

This project is licensed under the GNU Affero General Public License, version 3 or (at your option) any later version. See LICENSE. This repository is an independent publication of a local Python workflow; it is not affiliated with or endorsed by Bambu Lab.

The private research prototype consulted ClusterM/open-bamboo-networking and temporarily adapted its AGPL-3.0-or-later offline credential-decoding helper (Copyright (C) 2026 Alexey Cluster and contributors). That helper, its encrypted input blobs, memory-capture code and private credentials are **not distributed in this repository**. The published credential module instead imports operator-provided material. The project uses AGPL-3.0-or-later consistently rather than claiming that all research-derived work can be relicensed permissively.

Protocol sources consulted include:

- ClusterM/open-bamboo-networking: https://github.com/ClusterM/open-bamboo-networking
- Doridian/OpenBambuAPI: https://github.com/Doridian/OpenBambuAPI
- greghesp/ha-bambulab: https://github.com/greghesp/ha-bambulab
- Aptimex/bambu-mqtt-generator: https://github.com/Aptimex/bambu-mqtt-generator
- bambulab/BambuStudio: https://github.com/bambulab/BambuStudio
- synman/bambu-printer-manager: https://github.com/synman/bambu-printer-manager (filament mapping and calibration field interoperability)

These source trees are not vendored. The distribution contains no Bambu Studio or network-plugin binaries, vendor private keys, public CA bundle, copied firmware, complete slicer profiles or user print models. Bambu Studio is an optional separately installed executable. Python's cryptography library is an external dependency under its own license.

The full GNU AGPL text in LICENSE is reproduced unmodified from the license text retained during research. Its introductory project-specific notice has been replaced by this project's notice here; the license terms themselves are unchanged.
