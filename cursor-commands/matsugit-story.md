# Shape the narrative in matsugit

Use the matsugit skill. Resolve the user's selected Markdown or Org file, then
call `matsugit_open` with `layout: "story"` and `format: "slides"`. Ask for a path
only if it is ambiguous. Do not substitute a list of headings in chat for the
interactive Story workspace.

Overview and Walkthrough keep each slide's title, claim and takeaways together.
Moves carry the whole subtree; Add slide creates an empty title/claim pair.
The sparkles action sends an explicit slide request to the current chat when
the host supports messaging. Keep scope to that slide and reread before editing.
Never overwrite a newer source from an old snapshot.

Use the shared workspace's Save/review and Git sync controls. Opening Story
does not authorize edits, saving, commits, pushes or publication. If the host
cannot display MCP Apps, explain that limitation and offer `matsugit setup-cursor`
or the native Emacs Story view; do not claim a viewer opened when it did not.
