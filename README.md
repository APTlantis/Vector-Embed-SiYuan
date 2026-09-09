# VectorEmbedSiYuan

Local retrieval for the notes and imported support files in `E:\.siyuan`.
Ollama creates embeddings with **qwen3-embedding:8b**. SiYuan's **qwen3-siyuan:8b** Agent
uses the index through the **SiYuan Knowledge** MCP connection.

## Use it in SiYuan

Open **Agent**, select **Qwen3 8B (SiYuan 32K)**, and ask:

> Use SiYuan Knowledge to search City-Hall for how to start a new desktop app.
> Cite the source blocks. Separate adopted standards from City Planning drafts.
> Give me the next concrete steps without changing any notes yet.

The Agent can call `search_knowledge`, `knowledge_status`, and
`explicit_relationships`. These tools retrieve evidence; SiYuan's native editing
tools handle note changes you request. Ordinary editor chat and the native
semantic-search box do **not** automatically query this external index.

The connection launches its Python process when SiYuan starts. No web server,
cloud service, separate vector-database installation, or scheduled task is needed.
Ollama must be running for semantic queries.

The SiYuan chat profile reuses `qwen3:8b` weights with `num_ctx=32768`; the original
model is preserved. The native Agent's initial prompt measured 10,969 tokens and
was truncated to 2,050 with Ollama's original 4K runtime context. The separate
profile prevents that specific context mismatch. Its reproducible definition is
`Modelfile.siyuan`: `ollama create qwen3-siyuan:8b -f Modelfile.siyuan`.
Large context and simultaneous chat/embedding models require more memory; the
initial bulk embedding pass should finish before heavy Agent use.
Query embeddings use the same 8B embedding model on the CPU (`query_options.num_gpu=0`).
Bulk document embedding uses the GPU. This keeps the 32K chat model and the
embedding model from exhausting GPU memory during an Agent tool call.

## Refresh after importing or editing

From this project directory in PowerShell:

```powershell
.\run.ps1 refresh
.\run.ps1 status
.\run.ps1 search -Query 'What evidence is required before a desktop release?' -Project 'City-Hall'
```

`refresh` inventories the physical workspace, replaces changed chunks, and embeds
only missing content/model pairs. Completed batches survive interruption; run
`refresh` again to resume. The initial run can take substantial time on an 8B model.
The index is a snapshot, not a live subscription to note edits. Check
`knowledge_status` for its last inventory time and actual coverage.

Run one refresh at a time. Retrieval may run during embedding; it sees only chunks
whose vectors have already committed. A changing or unreadable file is recorded
with an error and its old chunks are excluded until a successful refresh.

## What is indexed

- Live `.sy` notes: readable AST content, document titles and hierarchy, document
  IDs, source block IDs, and `siyuan://blocks/...` links.
- Imported scripts, source code, manifests, configuration, and text assets:
  file paths, SHA-256 hashes, and original line ranges.
- SVGs: readable labels and semantic metadata. Embedded image bytes and drawing
  geometry are omitted; original file line ranges are not asserted for extracted SVG text.
- PDFs: extractable text with page labels. Scanned pages require a separate OCR step.
- Saved Wikipedia HTML: readable article text, excluding markup, scripts, styling,
  and navigation when the article container is present.
- Explicit links and block references, plus exact content-hash matches between
  imported assets and files under `D:\.city_hall`.

All physical files are inventoried, including history and internal state.
Configuration, credentials, caches, history copies, databases, installed plugins,
and generated dependency folders/lockfiles are not embedded. Image, audio, video, ZIP,
and other binary formats remain cataloged with an exclusion reason. This version
does not OCR, transcribe, or unpack archives. The active
workspace's `.lock` may be unreadable; that does not prevent knowledge retrieval.

Some imported assets have no observed link to a project. They remain searchable
without a project filter as `unassigned-assets`; no semantic ownership is invented.

The live D-drive source is used only for exact hash comparisons, not added as a
second corpus. City Hall notes are **imported snapshots**, not proof that a
canonical standard is current. City Planning is explicitly non-governing.
The indexing pipeline never edits source files, native vector tables, or raw
SiYuan `.sy` files. The setup helpers use supported APIs to register the connection
and create the operator guide; existing imported notes are preserved.

## Storage and recovery

`index/catalog.sqlite3` stores file metadata, chunks, float32 vectors, keyword
search, and relationships. Model name **and digest**, extractor version, chunk
settings, and text hashes prevent inappropriate cache reuse. Query embeddings
use Qwen's instruction format. Vector and keyword rankings are combined; similarity
is never stored as an asserted relationship.

The index contains local note text and should receive the same backup/access care
as your notes. It is derived data and can be rebuilt. Missing files are retained
as catalog records but excluded from retrieval. Old vectors are retained as a
resume cache, not automatically deleted.

`config.json` controls the workspace, model, chunk sizes, and limits.
`run.ps1` and the registered MCP command use the bundled Python runtime, with
NumPy 2.3.5 and pypdf in the verified environment. If that runtime moves, update `run.ps1`
and re-register using the replacement Python environment with NumPy and pypdf installed.

To remove only this connection, run:

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' .\connect_siyuan.py --remove --apply
```

This preserves other MCP servers, provider credentials, models, notes, and the
external index. The prior Agent/editor model IDs are recorded in
`reports/connection-before.json`. Registration does not modify native embedding
configuration. It corrects an embedding-only Agent/editor selection to the local 32K chat profile
when detected; removal keeps that working chat selection.

## Let models improve the knowledge workspace

See [WORKING-WITH-MODELS.md](WORKING-WITH-MODELS.md). The practical loop is retrieve,
cite, propose a small change, apply it through native SiYuan tools when requested,
verify the resulting blocks, and refresh. Embeddings provide recall; tools,
bounded tasks, and source checks make useful changes possible.

## Verify

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -v
```

Tests cover AST/block provenance, chunk boundaries, SVG payload filtering,
exclusions, unchanged-content skipping, changed/deleted source invalidation,
model-space separation, and the MCP read-only tool surface.

Implementation references: [Ollama embed API](https://docs.ollama.com/api/embed),
[Qwen3 Embedding](https://github.com/QwenLM/Qwen3-Embedding),
[SiYuan 3.8.3 MCP client](https://github.com/siyuan-note/siyuan/blob/v3.8.3/kernel/mcp/client/mcp.go),
[SiYuan API](https://github.com/siyuan-note/siyuan/blob/v3.8.3/docs/API.md).
