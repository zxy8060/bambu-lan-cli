# Credential setup and migration

This repository provides an **import interface**, not credential issuance or extraction. It contains no shared vendor private keys, encrypted vendor key blobs, plugin binaries, memory scanners, cloud session files or firmware modifications. You must already have authority to use the supplied signing material. The project does not establish that authority for you.

## Three different inputs

1. A printer serial and LAN access code authenticate a connection to your printer. The code comes from your configured Studio file or a named environment variable.
2. A public device CA bundle verifies the TLS chain and serial hostname. The verified device public key encrypts the protected file URL.
3. An application certificate chain and matching RSA-2048 private key sign the print message. A device TLS certificate is **not** this signing identity. An application identity may be shared across devices; local target binding does not make its key device-specific.

## Import on Windows

Provide the certificate chain in PEM format, application leaf first, followed by intermediates. The application CA root comes from `app_ca_file` (defaults to `ca_file`). Provide your existing private key via a local path outside the repository. For encrypted PEM, request an interactive password prompt; there is no password argument.

```powershell
bambu-a1 credential-import --certificate C:/private/app-chain.pem --private-key C:/private/app-key.pem --password-prompt
```

Omit `--password-prompt` only for a key that is already unencrypted. The import verifies validity dates, certificate issuer signatures up to the configured root, CA constraints, key pairing and the target printer's current application trust list. It does not upload certificates or change the printer's trust. An untrusted identity fails.

The resulting `app-credential.dpapi` uses Windows CurrentUser DPAPI and target-bound entropy. The CLI does not export it, overwrite it, log its plaintext or delete your input files. Input key protection remains your responsibility. Runtime data inherits the Windows user's directory ACLs; Unix mode bits are not a replacement for Windows ACLs.

Before every dispatch the stored identity is revalidated and its presence in the printer's trust list is checked. If trust has disappeared, dispatch stops. There is no automatic certificate provisioning, certificate renewal, online CRL downloader or unsigned-print fallback. Use your authorized provisioning method before retrying a job that was never sent; preserve any existing receipt when the outcome is uncertain.

If you do not have an authorized application identity, use the read-only/slicing commands and your existing official client for sending. This project does not document a public credential-issuance service.

## Another machine

Copy source code and nonsensitive templates, then install and configure that machine independently. [DPAPI normally requires the originating Windows user and computer](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata); copying the encrypted file alone is not a migration method. Re-import authorized input material locally and protect it under the new Windows user.

The originating private prototype used a different store format and entropy namespace. Its encrypted state is intentionally not auto-imported. Do not copy an entire private runtime directory into this repository.

Use one active execution host/runtime directory per printer. The dispatch lock and sequence counter are local, not distributed. A remote submission gateway is future work, not part of this release.
