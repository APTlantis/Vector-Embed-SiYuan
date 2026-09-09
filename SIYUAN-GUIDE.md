# Local knowledge retrieval is connected

Your notes and imported support files are indexed externally by
**VectorEmbedSiYuan**, using local Ollama **qwen3-embedding:8b**.

Open **Agent**, select **Qwen3 8B (SiYuan 32K)**, and try:

> Use SiYuan Knowledge to search City-Hall for starting a new desktop application.
> Cite source blocks and explain how WGS, PPS, and DRS fit together. Separate
> adopted standards from City Planning drafts. Do not change notes yet.

The **SiYuan Knowledge** MCP connection exposes:

- **search_knowledge**: semantic and keyword retrieval with source/block links.
- **knowledge_status**: project names, index timestamp, and completed coverage.
- **explicit_relationships**: observed links, block references, and exact source-file matches.

If the first embedding run is still active, only completed chunks can be retrieved.
Ask the Agent to check `knowledge_status` before reporting coverage.

## Refresh after importing or editing

Open PowerShell in:

`C:\Users\Administrator\Documents\VectorEmbedSiYuan`

Run:

```powershell
.\run.ps1 refresh
```

Unchanged text reuses its embeddings. Completed batches survive interruption.
Refreshes are manual; this index does not watch edits automatically.

## Let the models grow the workspace

Start with one useful change: a City Hall navigation page linking the standards
to their purposes and existing notes. Ask for evidence and a proposal first.
Then ask the Agent to create that page using native SiYuan tools. Verify its
links and refresh the index.

Keep explicit source relationships separate from proposed semantic connections.
Imported City Hall documents are snapshots. City Planning is non-governing;
check current `D:\.city_hall` sources before implementing software requirements.

The external search tools do not edit notes or run scripts. Note and block changes
use SiYuan's native tools. Changes to a plugin, executable, or separate software
project need a designated source repository and build/test workflow.

## Coverage boundaries

Notes, scripts, code, manifests, configuration, readable SVG metadata, and PDF
text are eligible. History, runtime databases, credentials, caches, plugin
installations, and binary media are cataloged but excluded. No OCR or transcription
is performed. The active workspace lock file may be unreadable.

This is connected to **Agent through MCP**. SiYuan's native semantic-search box
and ordinary editor chat do not automatically use this external index.

The source code, operator guide, recovery instructions, and verification reports
are in `C:\Users\Administrator\Documents\VectorEmbedSiYuan`.
