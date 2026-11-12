# Presentation and delivery

In Codex or Cursor, select Document or Slides, then the presentation-screen icon.
The selected format is presented without the editor; arrows/Space navigate slides,
documents keep their reading layout with page scrolling. Escape restores editing.
This never publishes.

The download icon offers Source, HTML slides, ZIP (document + slides + source),
PDF and editable PowerPoint. The current draft can be exported without saving
over the source. Theme and complex-layout fidelity differ in PowerPoint: text
and tables are native; charts/diagrams are images. Review the file before sharing.
Use PDF/HTML for rendered fidelity, or an approved native reference PPTX for
closer PowerPoint styling. Never claim screenshots are editable shapes.

If a sandboxed host cannot deliver the prepared export, use the explicit
**Save to Downloads** action. It saves the existing PDF/PPTX/HTML/ZIP through the
local plugin without rendering again, overwriting another file or publishing.
The dialog identifies the plugin machine and destination, then reports the actual
saved path. A remote plugin writes on its server, not on the user's laptop.
Do not equate a browser download request with a confirmed saved file.

```sh
matsugit export deck.md --format pptx --output deck.pptx
matsugit export deck.org --format pdf --output deck.pdf
matsugit export deck.md --format zip --output deck.zip
matsugit setup-export
```

`setup-export` explicitly installs isolated Playwright/Chromium, needed only for
PDF and Mermaid-to-PowerPoint capture. Do not install implicitly while authoring.
An optional `--reference-doc template.pptx` or theme manifest `powerpoint` file
selects native PowerPoint layouts. CSS cannot be applied directly to PowerPoint.

OneDrive can be a local folder, not an API integration:

```sh
matsugit export-folder /actual/existing/synced/folder
matsugit export deck.md --format pptx --sync-folder
```

Ask for the actual destination if unknown. Do not guess accounts, grant scopes or
upload a real document in tests. This confirms local save, not remote upload.
Repeated synced exports update one stable filename. Unchanged matsugit-owned
exports are replaceable; external edits or untracked files need explicit
`--replace` (or the dialog checkbox). Never discard a colleague's edits implicitly.
Old dated files are not deleted. Source edits alone do not trigger an export.

Named publishing targets are configured independently of source and theme:
The workspace upload dialog's **+** can list repositories through existing
`gh`/`glab` authentication and connect a local checkout. Connecting is not push
approval. Never run login, broaden permissions, enable Pages or install CI just
because a repository was selected. An exact owner/repository name is supported.

```sh
matsugit target set docs --repo /local/docs --provider gitlab --default
matsugit target list
matsugit publish-plan deck.md --target docs
matsugit publish deck.md --target docs
```

The upload icon in Codex offers target review, then an explicit Commit and push
button. A push may trigger existing CI. Additional deployment is a separate
checkbox. The source must first be saved; stale plans and dirty target checkouts
are refused. Configuration and previews never enable hosting or change CI rules.

**Share** keeps Slides, Document and Source links available before CI finishes
and when reopened, including after failed checks. Use `matsugit_links` to return
these addresses to the user; distinguish a known address from a verified live
revision. Before deployment, HTML links can show an older version or return 404.
If the Pages base URL is unknown, configure the target's `site_url` from the
actual hosting address, or let a read-only status check discover it with existing
`gh`/`glab` authentication. Never invent a host or log in implicitly. Both the
native and legacy topics layouts derive per-document URLs; custom `document_url`
and `slides_url` templates override the defaults.

Choose **Source to CI** for server rendering, or **Rendered outputs** for a local
build before pushing. Configure `matsugit target set docs --build ci`; then
`matsugit publish-plan deck.md --target docs` previews the destination. Source CI
pushes normalized Markdown/Org and referenced assets, not locally generated HTML.
Native targets need a reviewed current `setup-ci` installation; `--deploy` requests
its existing workflow. An existing topics-based `scripts/build_pages.py` pipeline
can use `--ci-layout topics --source-dir topics/matsugit`; it owns the final theme.
Do not overwrite CI to make a publish command pass. See `docs/delivery.org` for
the installation boundary, ownership protection and manual deployment rules.

Respect existing project `repo` or `publish_target` settings, private deployment
wrappers and immutable release contracts. Private Tailscale publishing uses the
existing wrapper, not the general plugin publisher. No public hosting, credentials
or new permissions are implied by a request to prepare a deck. Never test with
real private source. ZIP/source and HTML speaker notes may contain non-visible
material: hidden does not mean safe to publish.
# Canonical source and upstream edits

For source CI, `publish-plan SOURCE --target TARGET --build ci --move-source`
reviews an explicit move-and-link operation. `publish` with the same options
asks before committing/pushing. Never enable it silently: source/assets move,
original paths become symlinks, and exact source (including comments) enters Git.
Self-contained assets are required; existing destinations and ambiguous links
are refused. Local-render publishing retains its existing copy workflow.

`matsugit sync SOURCE --check` fetches/reports without touching working files;
`--yes` applies a clean fast-forward. Follow the real source checkout, not a host
default. Never force, auto-stash, or discard a draft to make sync succeed. For
conflicts use Git/Magit and retain both versions. See `docs/canonical-source.org`.
