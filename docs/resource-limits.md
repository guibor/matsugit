# Local rendering resource limits

The workspace accepts source documents up to 2 MiB. The Python renderer accepts
up to 8 MiB, checks UTF-8 byte length, and bounds reads even if a file grows.
Attachments are streamed while hashing, rather than read wholesale into memory.
The default limit is 128 MiB per unique attachment and 512 MiB across unique
attachments in one normalization. Repeated references reuse the copied file.
Local HTML canvases retain the stricter 2 MiB limit.

A rejected attachment leaves no partial copy. Previously completed attachments
can remain in that failed operation's output directory. Errors do not overwrite
the source document. An oversized source is rejected before invoking Pandoc.

Operators can set positive byte limits through the environment:
`MATSUGIT_MAX_SOURCE_BYTES`, `MATSUGIT_MAX_ASSET_BYTES`, and
`MATSUGIT_MAX_TOTAL_ASSET_BYTES`. Document metadata cannot relax these limits.
These settings affect Python rendering, not the workspace's fixed 2 MiB limit.

These are input/copy bounds, not an operating-system resource sandbox. Quarto,
Pandoc, image decoders and browser rendering can use additional memory or disk.
External resources referenced by a document may be fetched by downstream tools;
the local attachment budget does not bound those remote downloads. Run untrusted
documents with appropriate process, filesystem and network limits.
