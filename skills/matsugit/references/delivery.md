# Presentation and delivery

In the Codex workspace, the presentation-screen icon enters slide-only mode.
Arrow keys/Space advance, Escape restores editing. This never publishes.

The download icon offers Source, HTML slides, ZIP (document + slides + source),
PDF and editable PowerPoint. The current draft can be exported without saving
over the source. Theme and complex-layout fidelity differ in PowerPoint: text
and tables are native; charts/diagrams are images. Review the file before sharing.
Use PDF/HTML for rendered fidelity, or an approved native reference PPTX for
closer PowerPoint styling. Never claim screenshots are editable shapes.

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
Existing exports are retained; repeated synced-folder exports create dated copies.

Named publishing targets are configured independently of source and theme:

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

Respect existing project `repo` or `publish_target` settings, private deployment
wrappers and immutable release contracts. Private Tailscale publishing uses the
existing wrapper, not the general plugin publisher. No public hosting, credentials
or new permissions are implied by a request to prepare a deck. Never test with
real private source. ZIP/source and HTML speaker notes may contain non-visible
material: hidden does not mean safe to publish.
