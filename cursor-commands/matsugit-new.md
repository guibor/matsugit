# Turn notes into a matsugit deck

Use the matsugit skill. The user may not know Markdown: speak in slide words
(title, claim, columns, table, chart, takeaway), never in syntax, unless asked.

1. Find the material: the attached or active file, pasted notes, or ask once
   what the deck should argue and for whom. Do not invent facts, numbers,
   quotations or sources; mark gaps as questions for the user instead.
2. Propose the story first, in chat: one line per slide with its title and the
   claim it makes. Wait for the user's agreement or edits before writing.
3. Write one new Markdown file beside the notes (never overwrite an existing
   file). Start with `slide-layout: structured`. Use the bounded slide recipes;
   prefer simple layouts over clever ones.
4. Run `matsugit_check` on the file and fix every problem it reports.
5. Open it with `matsugit_open`, layout `split`, format `slides`, editor `visual`.
6. Tell the user, in two or three plain sentences, how to continue: edit text
   on the left, `Add` for a new slide or layout, `Check` when something looks
   wrong, Story to reorder slides.

Creating and previewing is local. It does not authorize saving over other
files, exports or publication. If no matsugit MCP tools are available, explain
`matsugit setup-cursor` and offer the local render workflow instead. Do not
claim the workspace opened if it did not.
