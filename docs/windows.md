# Native Windows compatibility preview

Windows support is opt-in until the real Codex and Cursor desktop flows have
been checked on Windows. The web UI and renderer are shared, not a Windows fork.
The existing Mac/Linux launchers, configuration locations and save protocol are
unchanged. Do not interpret Linux tests with mocked Windows branches as native
desktop acceptance.

Use Windows 11 x64 with approved Python 3.10+ (`python` on PATH), Node 22+, Git,
Quarto's native `quarto.exe` and Pandoc >=3.7.0.2. No WSL or administrator launch
is required for ordinary editing. Install dependencies before opening the editor;
restart it if its environment does not yet contain their paths.

From a checkout in PowerShell:

```powershell
python -X utf8 -m matsugit setup-cursor
```

The setup records the exact Python/Node paths and installs verified skill copies
on Windows. Later setup updates unchanged copies using receipts and preserves
local edits. Mac/Linux still use the existing symlink installation.

For the Codex plugin, `MATSUGIT_PYTHON` can select an explicit Python executable;
the Windows default is `python`, while Mac/Linux keep `python3`. Dependencies are
never installed simply by opening a document. `setup-editor`, `setup-charts`,
`setup-diagrams` and `setup-export` are separate, explicit download actions.

## Scope and limits

- UTF-8 child-process I/O, native chart environment paths, checked Pandoc Windows
  ZIP installation and native updater locking have focused tests.
- Keep shared decks and their attachments inside the publishing checkout when
  Windows policy prevents symlinks. First Share from outside that checkout stops
  before modifying anything when it cannot leave a live source alias. A shortcut
  or an unsynchronized copy is never silently substituted.
- Windows ARM, network drives, OneDrive file-provider behavior and native host
  keyboard/focus/download behavior still need separate acceptance testing.
- Existing saves remain optimistic/concurrent-edit checked. No retries that
  could overwrite an external edit or changes to conflict resolution were added.

## Verification

```powershell
python -X utf8 -m unittest discover -s tests -p test_windows.py -v
node --test codex-plugin/tests/python.test.mjs
```

The same tests run on Mac/Linux, including real competing-process locks.
On Windows also test an extracted plugin, spaces and non-ASCII paths, CRLF
documents, external edits while typing, conflict recovery, table editing,
HTML/PDF/PPTX export and sharing through a disposable local Git remote. Run the
existing Mac/Linux suites before promoting a Windows compatibility release.
