# Open a matsugit workspace

Use the matsugit skill. Open the user's selected Markdown or Org file with the
`matsugit_open` MCP tool, layout `split`, format `document`. Resolve the path
from the user's attached/active file; ask if ambiguous. For an explicitly new
untitled document, use `matsugit_workspace`. The tool returns the interactive
MCP App, not just static HTML. Do not create another editor or web service.

Opening/previewing is local and does not authorize saving, exports or publication.
If no matsugit MCP tools are available, explain `matsugit setup-cursor` and the
need to enable the installed server in Cursor. Do not claim the UI opened if it
did not. CLI-only Cursor sessions can use the normal local render workflow.
