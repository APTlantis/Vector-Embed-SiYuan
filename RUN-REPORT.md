# Completed local embedding and SiYuan integration

Verified September 8, 2026.

## Result

- 855 eligible files embedded into 1,643 searchable chunks.
- 1,196 deduplicated, 4,096-dimensional vectors from `qwen3-embedding:8b`.
- 1,022 observed relationships retained separately from semantic similarity.
- 696 eligible files associated with City-Hall.
- All 1,643 live chunks have vectors; an unchanged refresh required zero new embeddings.
- SQLite integrity check passed; compacted database is approximately 86 MB.

The catalog also records excluded material. Its one unreadable item is the active
workspace `.lock`; its one missing item is an internal transient filesystem check.
Neither represents an unembedded user document. Inventory snapshot time is
2026-09-08 09:37:10 UTC. Later imports and note edits need a refresh.

## Actual in-app verification

SiYuan 3.8.3 launched the registered **SiYuan Knowledge** MCP server. A native
Agent session using **Qwen3 8B (SiYuan 32K)** successfully called
`knowledge_status` and `search_knowledge`, then answered the City Hall versus
City Planning question with source block links. No notes were edited by the test.

Session: `20260908201838-vesmoke`.
Evidence: `reports/agent-smoke-summary.json` and `reports/agent-smoke.jsonl`.

The runtime uses a separate 32K chat profile to fit SiYuan's Agent prompt.
Query embeddings run on the CPU with the same embedding model, leaving GPU
memory for chat. Live Ollama status confirmed zero embedding VRAM usage and
the chat model's 32,768-token context. This resolved the earlier GPU exhaustion.
Bulk document embedding still uses the GPU.

The extraction, provenance, incremental invalidation, and MCP tests passed 11/11.
Additional evidence is in `reports/completion.json` and
`reports/cpu-retrieval-smoke.json`.

## Use and maintain

Open SiYuan Agent, select **Qwen3 8B (SiYuan 32K)**, and ask it to use
**SiYuan Knowledge**. The in-app guide is under
**Local AI in SiYuan → Using the local knowledge index**.

After imports or edits, run `./run.ps1 refresh` from this project folder.
The external index is available through Agent tools; SiYuan's native semantic
search box and ordinary editor chat do not automatically use it.

See `README.md` for commands and `WORKING-WITH-MODELS.md` for a practical
retrieve, cite, propose, edit, verify, and refresh workflow. Imported City Hall
notes remain snapshots; current canonical standards live at `D:\.city_hall`.
