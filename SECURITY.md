# Security reporting

Do not attach access codes, application private keys, DPAPI stores, complete Studio configuration files, cloud sessions, raw process captures or unredacted runtime directories to issues or pull requests. Private runtime data belongs outside the checkout.

Use GitHub private vulnerability reporting if it is enabled for this repository. Otherwise open a minimal issue asking for a private contact channel without including exploit details or secrets. Ordinary reproducible bugs can use synthetic data in a public issue.

Credential material is supplied by the operator; this project does not extract or distribute vendor signing keys. TLS verification has no insecure toggle. A single execution host and runtime directory must own dispatch for each printer; local file locks do not provide distributed scheduling.

The tool checks file metadata and observed printer state. It does not physically clear the bed, prove structural load capacity, simulate all G-code motion, or provide continuous supervision. Sending requires authorization for the reviewed job and an actual bed/filament check. Unknown outcomes are never automatically resent.
