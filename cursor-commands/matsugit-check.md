# Find and explain what is wrong with a deck

Use the matsugit skill. Resolve the user's selected or active Markdown/Org file;
ask only if it is ambiguous. Call `matsugit_check` with its path.

Report in plain language, grouped by slide number and title: what is wrong, why
it matters on the slide, and what you would change. Problems first, tips after.
Do not paste raw syntax rules unless the user asks. If nothing is reported, say
so, and add that this checks structure, not how the slides look.

Then ask whether to fix them. On agreement, reread the file, make the smallest
edit for each problem, keep the user's words and numbers, and run
`matsugit_check` again until no problems remain. Leave tips as suggestions
unless asked. If the file is open in the workspace, tell the user it will offer
to review the change.

Checking is read-only. It does not authorize saving, exports or publication. If
no matsugit MCP tools are available, use `matsugit lint FILE` and a local
render, and say that the fuller check needs `matsugit setup-cursor`.
