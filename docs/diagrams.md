# Meaning-first diagrams

Prefer D2 for relationship maps, nested systems and branching processes when its
automatic layout suits the argument. Keep Mermaid for existing diagrams, sequence
syntax and workflows where it is more convenient. For insight/action rows,
comparisons and whole-panel implications, prefer matsugit's semantic blocks.
Do not replace a working diagram merely to use a different language.

Install the optional local renderer once (Node.js 22+ and npm required):

```sh
matsugit setup-diagrams
```

This installs a locked upstream `@d2lang/d2` WASM package into
`~/.local/share/matsugit/diagrams`. Rendering is offline; no dependency download
happens during preview. `MATSUGIT_DIAGRAM_RUNTIME` overrides that directory.

## Markdown

````markdown
```d2
direction: right
research: Customer research
insight: Unmet needs
decision: Product direction
research -> insight: reveals
insight -> decision: informs
```
````

Use `matsugit template d2 --fragment`, or `/d2` in the Codex/Cursor workspace,
to insert an editable diagram slide. A fenced block can also use Pandoc
attributes: ```` ```{.d2 layout="dagre" caption="How evidence informs a decision"} ````.
`elk` is the default; `dagre` and `tala` are also available. Layout engines are
not guaranteed to arrange every graph well: inspect readability before sharing.

## Org

```org
#+begin_src d2
direction: right
research -> insight: reveals
insight -> decision: informs
#+end_src
```

The source remains text in either format. Diagrams render as SVG in documents,
slides, columns and PDF. Editable PowerPoint embeds the diagram as an image, not
individually editable shapes; edit the D2 source to regenerate it.

## Theme contract

Add `"diagrams": "diagrams.json"` to a theme manifest. The file is optional and
inherits like `charts`. Without it, D2 uses ELK and derives its colors from the
chart palette (or the neutral palette if none exists).

```json
{
  "layout": "elk",
  "palette": {"B1": "#0033A0", "B2": "#0033A0", "N1": "#071F55"}
}
```

The palette uses D2 theme tokens and six-digit hex colors. Inspect actual node,
edge and label contrast; do not hard-code a brand into individual diagram blocks.
The initial integration uses D2's bundled Source Sans Pro fonts for consistent
text measurement. It does not automatically load arbitrary CSS/web fonts.
Explicit D2 styling in the source remains possible, but shared styles belong in
the theme. The media fitter preserves aspect ratio without cropping evidence.

## Boundaries

- One self-contained D2 board per block, up to 64 KB, with a 45-second render limit.
- Imports see only a virtual file, never the host filesystem. External imports,
  icons/images, active links and multi-board output are unsupported.
- The upstream D2 parser owns syntax. SVG output is checked for active content
  and external resources before inclusion. Document Python or shell is never run.
- Cache keys include source, theme, engine version and wrapper. Editing another
  paragraph reuses the diagram; changing the diagram triggers a full preview.
- Existing Mermaid source and rendering remain supported unchanged.

For a CI runner, provision Node.js 22+ and run the copied
`python3 .matsugit-ci/diagrams.py --setup` before its build. Generated CI templates
include that setup step. Existing workflows must be reviewed and updated explicitly;
upgrading the local plugin does not change a remote runner or deploy a document.
