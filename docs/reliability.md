# Change reliability

The Markdown or Org file is the source of truth. History is a private, bounded
local safety net; generated slides are not a second editable original.

## Delivery checklist

- [x] Review the prepared scoped-edit and diagnostic changes (630876e).
- [x] Audit local and GitHub branches against fbe1ad1.
- [x] Add durable checkpoints, including concurrent writers and failure tests.
- [x] Add document and explicitly targeted slide restore as undoable draft edits.
- [x] Add a Changes entry point and independent revision observations.
- [x] Verify reconnect/upgrade continuity and editing in simulated host envelopes.
- [x] Install the checks workflow, rebuild the bundle and validate version 0.35.0.
- [ ] Run the native Codex/Cursor acceptance checklist in docs/testing.org.
- [ ] Verify the first GitHub Actions run on the released commit.

The existing save and merge behavior stays in place while these contracts are
added. Broad synchronization refactoring is not a prerequisite. Checkpoints
contain source text, not copies of referenced images or themes. The interface
must disclose this when restoring. Unknown external authors remain unknown.

## Branch audit

Checked GitHub heads and local refs on 2026-11-14. Main is fbe1ad1.

- `codex/trust-and-first-use` (630876e): previously unmerged; included in this release.
- `codex/vscode-editor` (3d51ed3): separate host preview; retain, do not merge here.
- `claude/project-thread-ji0mqf` (6f1857f): adapt the missing-Pandoc test guard
  to current tests rather than merge the historical package names.
- `claude/project-thread-qpi90c` (c75bf82): use the current checks workflow
  instead of the older CI recipe.
- `codex/relationship-visual-refinement` (31cbd5a): old layout experiment;
  retain for a separate visual review, not this release.
- `codex/plugin-review-fixes`, `codex/review-smaller-bundle`,
  `codex/share-links-immediate`, `codex/windows-compat`, `claude-plugin` and
  `smaller-bundle`: their branch tips are already ancestors of main.

No branches or unrelated working changes were deleted during the audit.

## Verification on 2026-11-14

The Python suite completed 428 tests with 31 skips and no failures. Node
completed 198 tests: 197 passed and one skipped. Twenty focused browser runs
passed against the built bundle: 13 standard-host runs and seven Cursor-style
runs, covering fit, source checks, history, saving, concurrent agent edits,
Share and Story navigation. The standard runs also cover merge review,
recovery, diagnostics, export, general editing and a real 0.34 panel reconnecting
to the new server while retaining its draft.

The real Quarto parity check passed for local export, preview and installed
native CI, with Markdown/Org and built-in/synthetic themes. The reading-view
browser check passed at desktop and mobile widths. These use synthetic files
and local remotes; they do not establish native desktop acceptance or a live
GitLab deployment. The source-tree size is 8.24 MB, advisory under the revised
secondary size goal; downstream ZIP sizes must be measured separately.

## Boundaries

History is private to this machine and profile, under the recovery directory's
`history/` subdirectory. It keeps up to 64 events per document, 2,048 globally,
and 128 MiB of distinct source text. SQLite storage is capped at 160 MiB plus
its bounded transaction journal. Each document is at most 2 MiB. Retention
keeps the newest event of each kind; if these alone fill the budget, new writes
fail explicitly rather than silently deleting protected checkpoints.

Only an approved Share relocation transfers history to a new path. An arbitrary
rename is a new identity; the old history is retained, not guessed or discarded.
Copies and separate worktrees have separate history. Checkpoints are source-only,
not image/theme backups. Git history includes up to 30 local commits and follows
renames. No remote fetch is performed. Commit author labels are recorded Git
metadata, not verified real-world identity. Scoped agent edits are labeled as
such, never attributed to an inferred agent name.

Slide styling is unchanged. Rendering now supports independent document and
slide outputs, a reading projection of claims, and read-only rendered-fit
warnings. These operate on the same authored source; they never rewrite it or
silently split or shrink an overcrowded slide. This release does not promise
real-time co-editing, automatic Git reconciliation, cross-machine history or
native host acceptance.

The 8 MB footprint target is secondary to reliability and functionality.
Generated server code stays readable. Strict size enforcement is available for
distributions with an actual upload limit, not imposed on ordinary releases.
