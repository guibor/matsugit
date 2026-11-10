# Prepare source-only CI publication

Follow the matsugit delivery skill. Review the selected source, target and
configured CI build mode. Prefer a read-only `matsugit publish-plan` check, or
open the interactive workspace so the user can review and explicitly confirm
publication in its Publish dialog. Preparing a plan does not authorize a push.

For someone who does not use Git, point to the workspace's `Share` button
instead: it saves, sends, brings in colleagues' changes and reports whether the
site is live, one confirmed step at a time. Sharing is still theirs to confirm.

Do not enable hosting, rewrite existing CI rules, change credentials or use
`--yes` without explicit approval. Explain which files will be committed and
whether an existing pipeline runs on push or needs an explicit deployment request.
