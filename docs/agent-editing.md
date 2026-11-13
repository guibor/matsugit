# Scoped agent edits

For an edit to an existing slide, the plugin provides two shared tools in every
MCP host. They work on the saved Markdown or Org source, not a separate deck.

1. Call `matsugit_read_slide` with an absolute `path` and a `slide` number from
   Story. Verify the returned title, section and source. Duplicate titles are
   allowed. Pass `etag` from a previous workspace request when available: a
   different saved revision is rejected rather than selecting a moved slide.
2. Call `matsugit_edit_slide` with the returned `edit_id` and an `edits` list of
   `{old, new}` passages. Each old passage must occur exactly once inside that
   slide. Include surrounding text to distinguish repeated passages.
3. Use `preview_only: true` when reviewing a proposed edit. It returns the
   resulting slide without writing. Otherwise an authorized edit saves through
   the workspace's existing version-checked save path. It never publishes.

All replacements refer to the same snapshot. Overlapping replacements, changes
to another slide, unfinished blocks and edits that change slide/section
boundaries are refused. Use Story for adding, moving or removing slides.
Continuation pages remain part of their H2 slide in Story.

The entire saved document must still match the read revision, even if another
writer changed a different slide. On `outcome: conflict`, reread and review the
latest source. Do not bypass the check with a whole-file write. A snapshot
expires after ten minutes, after a successful edit or conflict, or when the
server restarts.
Read again; the source document itself does not expire. Pending snapshots are
bounded to 128 per server. Slides are limited to 64 KiB, with at most 32
replacements and 128 KiB of combined old/new text per request.

## Unsaved typing

These tools cannot see an author's unsaved panel draft. The workspace continues
to combine separate edits and offer overlapping changes for review. A saved
agent edit does not mean that unsaved typing was saved. Existing recovery and
explicit Save behavior are unchanged. Unrelated external editors can still
write directly to the file; this is not a filesystem lock or a guarantee against
an external process writing during the final save.

## Setup checks

`matsugit_doctor`, **More > Check setup**, and `python3 -m matsugit doctor` use
the same read-only prerequisite report. `--json` produces schema-versioned data
for support scripts (exit 0 when required checks pass, 1 otherwise). Optional
tools are listed separately. Checks do not install software, change accounts,
read documents or publish. A version check is not proof that a host panel or a
complete render works; those still need an end-to-end test.
