# Make a matsugit deck

Use the matsugit skill. The user may not know Markdown: speak in slide words
(title, claim, columns, table, chart, takeaway), never in syntax, unless asked.
Speed matters most on a first try: get a real draft in front of them, then
improve it together.

1. Find the material: the attached or active file, pasted notes, or what they
   wrote after the command. If there is nothing at all, ask exactly one
   question and stop: "What do you need to present, and to whom? One line is
   enough. Or say *tour* and I'll open a one-minute sample first." On "tour",
   do what /matsugit-tour does.
2. Draft straight away; do not ask for approval of an outline first. Five to
   eight slides: a title and a one-sentence claim on each, so the titles alone
   tell the story. Use the bounded slide recipes, varied where the content
   fits (key numbers, comparison, timeline, decision request), simple
   otherwise. Never invent facts, numbers, quotations or sources: where
   evidence is missing, write a short placeholder such as "[add the pilot
   result]" so the gap is visible.
3. Write one new Markdown file beside the notes, or in the project folder
   (never overwrite an existing file). Start with `slide-layout: structured`.
4. Run `matsugit_check` on it and fix every problem it reports.
5. Open it with `matsugit_open`, layout `story`, format `slides`. Story shows
   the storyline: every title and claim, in order. That is where they agree
   the argument, by editing it directly.
6. Reply in at most three short lines: the deck is open in Story; change any
   title or claim there, or drag to reorder; switch to Side by side to see the
   slides, and ask you for any change ("make slide 3 a chart", "tighten the
   claims"). Name any placeholders they need to fill.

Creating and previewing is local. It does not authorize saving over other
files, exports or publication. If no matsugit MCP tools are available, explain
`matsugit setup-cursor` in one sentence. Do not claim the workspace opened if
it did not.
