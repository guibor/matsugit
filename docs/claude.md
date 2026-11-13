# matsugit in Claude

matsugit works in Claude Code and in Claude Desktop. It is the same workspace
as in Cursor and Codex: one Markdown file is your slides, your reading document
and your source.

## Claude Code

Install the plugin from inside Claude Code:

```text
/plugin marketplace add guibor/matsugit
/plugin install matsugit@matsugit
```

You need Node 22+, Python 3.10+, Git and [Quarto](https://quarto.org/docs/get-started/).
The plugin brings the skill, the slash commands and the workspace server.

Then try `/matsugit:matsugit-tour`, or ask "turn these notes into a deck".
Claude Code namespaces plugin commands with `matsugit:`; Cursor's equivalent
commands do not have this prefix.

Claude Code lives in a terminal and cannot show a panel beside the chat. So when
Claude opens a deck, the workspace opens in your default browser instead, on
its own, and Claude gives you the address. Everything works there: Side by
side, Story, Check, Add, Present, Share and Save. Two differences:

- **Ask AI copies the request.** Paste it into Claude Code; there is no chat in
  the browser to send it to.
- **The tab is the app.** Claude keeps editing the file on disk while you work;
  the tab takes its changes in, merges them with your typing, or asks you to
  review when you both changed the same sentence.

The address works on this computer only and carries a private code. Other
websites are refused by the local host's token, Host and Origin checks. It stops
five minutes after you close the tab; ask
Claude to open the deck again to get a new one.
When Claude runs on another computer, the address is local to that computer;
it needs an explicitly configured private tunnel, not public hosting.

| Command | What happens |
| --- | --- |
| `/matsugit:matsugit-tour` | A seven-slide sample that explains itself opens in your browser |
| `/matsugit:matsugit-new` | Claude drafts a deck from your notes and opens it in Story |
| `/matsugit:matsugit-slides` | The workspace opens on a file |
| `/matsugit:matsugit-check` | Problems, slide by slide, in plain words |
| `/matsugit:matsugit-story` | The storyline view, for reordering |
| `/matsugit:matsugit-help` | What to ask for and what each button does |

Settings: `MATSUGIT_BROWSER=0` in the environment keeps Claude Code from opening
the browser (Claude then reports the file as opened, with no view);
`MATSUGIT_BROWSER=1` uses the browser in any host. Without the plugin, the
skill alone can still open the workspace: `python3 -m matsugit open deck.md`
from a checkout.

## Claude Desktop

Claude Desktop supports MCP Apps. Where local MCP Apps are supported and enabled,
the workspace opens inside the conversation. If no panel appears, ask for
`matsugit_browser` to open the same file in your browser.
From a matsugit checkout:

```sh
python3 -m matsugit setup-claude-desktop --check   # see what would change
python3 -m matsugit setup-claude-desktop
```

This adds one `matsugit` server to Claude Desktop's
`claude_desktop_config.json`, keeps every other server and setting, backs up
the previous file beside it, and refuses to replace a `matsugit` entry it did
not write. It records the Node, Python, Quarto and `PATH` this shell finds,
because a desktop app does not start from a shell. Quit and reopen Claude
Desktop, then ask "Show me how matsugit works".

Claude asks before it shows an app the first time: choose **Allow once** or
**Always allow**.

To remove it, delete the `matsugit` entry under `mcpServers` in that file (on
a Mac, `~/Library/Application Support/Claude/claude_desktop_config.json`).

Integration reference: [Claude plugin manifests](https://code.claude.com/docs/en/plugins-reference)
and [local MCP setup](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop).
