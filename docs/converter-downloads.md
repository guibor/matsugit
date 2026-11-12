# Pinned converter download

`matsugit setup-editor` reuses an existing compatible, locally approved Pandoc.
Only when none is available does that explicitly requested command download
Pandoc **3.13**. Plugin startup and normal preview do not install dependencies.

The five exact asset names and SHA-256 hashes are constants in
`matsugit/converter.py`. There is no `releases/latest` request, remote checksum
lookup, version override or fallback to a different download. The whole archive
must match its packaged hash before extraction or execution. Extraction selects
the exact platform binary path; its version must also match before installation.
The system Pandoc is not modified.

## Pin provenance

These pins were reviewed on 2026-11-12 against the immutable official
[Pandoc 3.13 release](https://github.com/jgm/pandoc/releases/tag/3.13).
All five archives were downloaded separately and their SHA-256 hashes computed
locally, matching the release metadata. Linux x64/ARM64, macOS Intel/ARM64 and
Windows x64 are covered. The package, not a response from the download server,
is the installer trust anchor. This is not an independent reproducible-build
attestation or a claim that all upstream code has been security audited.

To change the pins, review a specific upstream release, hash every supported
archive, inspect its binary path, update the constants and platform tests, and
ship a reviewed package release. Never refresh pins automatically during setup.
The download contacts `github.com` and its HTTPS release-asset CDN; only the
asset request is sent, not document content. A configured network proxy can
also participate. An unavailable or changed asset fails closed.
