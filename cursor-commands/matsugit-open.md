# Open a matsugit workspace

Use the matsugit skill. Open the user's selected Markdown or Org file with the
`matsugit_open` MCP tool, layout `split`, format `document`. Resolve the path
from the user's attached/active file; ask if ambiguous. For an explicitly new
untitled document, use `matsugit_workspace`. The tool returns the interactive
MCP App, not just static HTML. Do not create another editor or web service;
`matsugit open` below is the only fallback.

Opening/previewing is local and does not authorize saving, exports or publication.
If no matsugit MCP tools are available, or the workspace does not appear, open it in
the browser instead: from the matsugit checkout run `python3 -m matsugit open <absolute path>`
and give the user the address it prints, in one line. Then mention once that `matsugit setup-cursor`
puts it beside the chat. Do not claim the UI opened if it did not.
