# Expandable HTML evidence

The inline canvas is a preview. Use **Expand** to interact at normal size;
**Close** returns without resetting its state. This avoids unreliable input
inside scaled slide iframes.

Use a self-contained UTF-8 local HTML file (max 2 MiB) inside the source project:

```markdown
::: {.canvas src="visual.html" title="Operating assumptions"}
:::
```

Org uses `#+begin_canvas :src "visual.html" :title "Operating assumptions"`
and `#+end_canvas`. `/canvas` inserts the block in either workspace format.
Explain the visual in ordinary text outside the empty block. Expand inspects the
same frame without losing state. Reading documents keep in-flow figures rather
than slide-sized boxes; takeaways belong beside the argument, not fixed to a page.

No remote URLs, external resources or raw unbounded HTML. Inline CSS/SVG and data
images are supported. Scripts are off unless `interactive="true"` is explicitly
authored for a trusted visual. The iframe stays opaque, blocks resource fetches,
and cannot access the parent editor or use forms/popups. It is not a malware
sandbox; avoid navigation code and untrusted HTML. No document code is
run by the renderer. Do not add interactive=true without the user's intent.

HTML/ZIP/native CI preserve it; PDF is static and requires review. PPTX rejects
canvases: use a static image instead. Existing CI installations need a canvas-capable
renderer; update publishing targets separately from the local plugin.
Select Document or Slides before Present; Escape restores editing in both hosts.
