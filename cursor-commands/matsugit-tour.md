# Show me how matsugit works

Use the matsugit skill. Call `matsugit_tour` with the absolute path of the open
project folder (the folder of the active file if there is no project). It puts
a short sample deck, `matsugit-tour.md`, in that folder and opens it beside the
chat; an existing one is opened as it is.

Then reply in three short lines, no more:
1. "This sample explains itself: start by changing the first title on the left."
2. "Try Add at the top, then Compare options."
3. "When you're ready, tell me what you need to present, or paste your notes,
   and I'll make your own deck the same way."

Do not explain Markdown, list features or describe the workspace beyond that.
If `matsugit_tour` is not available, the matsugit workspace is not connected:
say so in one sentence and offer to set it up (`matsugit setup-cursor`).
