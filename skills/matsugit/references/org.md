# Org uses the same semantic model

Use `#+TITLE:`, `#+SLIDE_LAYOUT: structured`, and
`#+SLIDE_SECTION_DIVIDERS: false`. `*` is a section, `**` starts a slide,
and the immediately following `***` is its smaller claim. `-----` continues
the slide. Booleans use `true`/`false`, not Lisp values.

Use native `#+begin_takeaway` / `#+end_takeaway` blocks, and similarly `source`,
`notes`, `columns`, `rows`, `metrics`, `comparison`, `timeline`, `decision`,
`implication`, `mapping`, `annotated`, `evidence`, `callout` and `chart`.
Attributes use Org header arguments, e.g. `:target "evidence"` or `:unit "days"`.

Inside component blocks use `#+begin_region :title "Heading"` ...
`#+end_region`, not headlines: Pandoc loses headlines inside special blocks.
Columns/rows may use `#+begin_column :title "Heading" :width "65%"` or
`#+begin_row :title "Heading"`, omitting titles for untitled regions.
Generate correct scaffolding with `matsugit template NAME --format org`.

Native tables, links, emphasis, LaTeX, source blocks and images retain Org syntax.
Table alignment uses native `<l>` / `<c>` / `<r>` cookies. A `<<target>>` at the
start of a table cell names its text for a saved evidence callout.
Mermaid uses `#+begin_src mermaid`; Vega-Lite uses `#+begin_src vega-lite`.
For merged/multiline tables use readable grids in `#+begin_export markdown`;
the visual editor reads and returns this block without HTML or a sidecar.
No arbitrary code or Babel is executed; includes/setup files are refused.

`render`, `lint`, `publish`, `--handout` and theme selection are the same commands.
Native publications retain editable `source.org` and generated `source.md`.
Do not edit both. Existing copied CI needs an explicit upgrade to rebuild Org;
for Markdown-only CI use `matsugit convert --from org --to markdown` on stdin.
Never replace another repository's CI or publish documents just to test parity.
