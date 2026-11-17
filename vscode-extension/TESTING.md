# Native Editor Validation

2026-11-17: rebased onto workspace 0.36.11. The isolated real VS Code 1.146.0
run passed opening, rendering, formatted/raw edits, native Save/Undo, acceptance
of external buffer changes, conflict review, Story and reading view. Fifteen
adapter unit tests pass, including a regression that polling an incoming update
cannot authorize the next stale draft write. The deterministic VSIX was installed
successfully through the real VS Code CLI into an isolated extensions directory.
The tests below describe the original preview baseline, not additional native
Mac/Windows acceptance for this release.

Verified on Linux with VS Code 1.146.0, Node 22 and an isolated profile.
No real documents, publishing repositories, accounts or editor settings changed.

- Native adapter: 14 unit tests passed, including CRLF offsets, queued edits,
  stale-write refusal, save refusal, export payloads and frame-message isolation.
- Native VS Code: slide/document frames rendered; formatted/raw edits reached
  the TextDocument without saving; explicit and native Save worked; keyboard
  Undo retained the other editor's changes; separate changes combined;
  overlapping changes retained both versions and blocked Save pending review.
- Shared workspace: 157 Node tests passed, one optional test skipped.
- Python renderer: 343 tests completed, 30 optional tests skipped, no failures.
- Browser regressions: Cursor-style editing/prompt isolation and standard-host
  save/review/retry checks passed without the native bridge.
- VSIX packaging: 10 allowlisted files, approximately 2.21 MB compressed and
  4.80 MB expanded. Prerequisites and the runtime's extracted cache are separate.

Not yet acceptance-tested: native Mac/Windows, remote extension hosts, real
GitHub/GitLab Share, the native export Save dialog and hot-exit restoration.
This is a separate preview, not a claim that those flows have been verified.

## Repeat

Build the shared workspace, then `node vscode-extension/build.mjs`.
Run `npm test --prefix vscode-extension`. The real-editor test requires
Playwright, Xvfb and a locally installed official VS Code executable:

```sh
VSCODE_EXECUTABLE=/path/to/code python3 vscode-extension/tests/browser.py
```

Use a Python environment containing Playwright and set `MATSUGIT_PANDOC` to
an approved converter if it is not discoverable. The test writes its logs and
synthetic screenshots to the temporary directory printed at startup.
The test bridge, fixtures, logs and screenshots are never included in the VSIX.
