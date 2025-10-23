# English Kids MCP

[中文文档](README.zh.md)

This project implements a text-only Model Context Protocol (MCP) server for guiding Chinese children (ages 3–10) through kid-friendly English speaking drills. It persists learner progress in SQLite, optionally mirrors curriculum items into a FAISS vector store, and exposes the MCP tool surface required to plug into an n8n flow. A standalone SSE bridge (`/sse`) lets any MCP-capable client subscribe to streamed tool results without additional middleware.

## Highlights

- **Oral practice loop** with Duolingo-style encouragement, XP, and sticker rewards.
- **Age-aware prompts** that stay short (≤8 or ≤12 words) and offer Chinese scaffolding only when a retry is needed.
- **Lightweight spaced repetition** (SM-2 inspired) that blends new cards and due reviews at a 2:1 ratio.
- **Pure-Python deployment** – no web framework. The MCP brain can be embedded in any adapter (CLI, websocket bridge, n8n HTTP node, etc.).
- **Standalone SSE bridge** you can launch with one command for MCP-ready clients.
- **Optional FAISS** index for semantic lookups; a NumPy cosine fallback keeps everything runnable without native extensions.

## System overview

The service is organised into three layers:

1. **Core pedagogy engine** (`KidEnglishMCPServer` in `server.py`) keeps session state, awards XP/stickers, rotates curriculum cards, and applies the spaced-repetition scheduling helpers from `srs.py`.
2. **Persistence & enrichment** combines SQLite tables (`db.py`) with optional FAISS lookups (`vectorstore.py`) and vocabulary references loaded by `references.py`.
3. **SSE delivery** (`sse_server.py`) hosts `/sse`, `/messages`, and `/.well-known/mcp.json` endpoints (with `/invoke` kept for backward compatibility) so external automations (e.g. n8n) can stream MCP tool responses straight into ASR/TTS pipelines.


See [docs/SSE_TUTORIAL.md](docs/SSE_TUTORIAL.md) for an end-to-end walkthrough of the streaming API, including a curl session and the automated regression test that proves the wiring.

## Tool surface

The `KidEnglishMCPServer` class provides the MCP tools described in the design brief:

| Tool | Purpose | Key fields returned |
| ---- | ------- | ------------------- |
| `start_session` | Create or resume a learner session. | `session_id`, `next_activity`, `state_snapshot` |
| `next_activity` | Fetch the next micro-task respecting SRS rules. | `Activity` dataclass |
| `submit_utterance` | Score an ASR transcript, award XP, and advance or remediate. | `Feedback` with `next_activity` or `review_card` |
| `set_goal` | Switch curriculum track mid-session. | Updated `SessionSnapshot` |
| `get_progress` | Parent-friendly summary. | `ProgressSummary` |
| `save_note_for_parent` | Persist a Chinese coaching note. | `None` |

Each activity includes `prompt_text`, `target_phrase`, `rubric`, `timebox_sec`, and a Chinese scaffold string. Feedback returns mastery deltas (`-1`/`0`/`+2`), XP awards, and sticker counts so the outer workflow can mirror Duolingo-style celebrations.

## Project layout

```
.
├── pyproject.toml
├── src/english_kids_mcp
│   ├── __init__.py          # Package exports
│   ├── config.py            # Settings dataclass with env overrides
│   ├── curriculum.json      # Seed curriculum tracks
│   ├── curriculum.py        # Loader + age filtering helpers
│   ├── db.py                # SQLite persistence for sessions/progress
│   ├── evaluation.py        # Heuristic scoring of utterances
│   ├── schemas.py           # Dataclasses for tool payloads
│   ├── server.py            # KidEnglishMCPServer implementation
│   ├── srs.py               # Spaced repetition utilities
│   └── vectorstore.py       # FAISS (or cosine) backed retrieval
└── tests
    └── test_chat_flow.py    # End-to-end flow against the server class
```

## Getting started

1. **Install dependencies** (use a virtual environment when possible):

   ```bash
   pip install -e .[test]
   ```

2. **Run the tests** to confirm the pedagogy loop works:

   ```bash
   pytest
   ```

3. **Run the standalone SSE bridge** when you need a ready-to-use MCP endpoint:

   ```bash
   kid-english-mcp --host 0.0.0.0 --port 8765
   ```
   The HTTP interface follows the Model Context Protocol SSE transport:

   - `GET /.well-known/mcp.json` – machine-readable manifest describing the tools.
   - `GET /sse?stream=<id>` – opens an SSE stream (text/event-stream) for responses. Omit `stream` to auto-generate an identifier.
   - `POST /messages` – accepts JSON-RPC 2.0 payloads such as `{"jsonrpc":"2.0","method":"tools.list"}` and `{"jsonrpc":"2.0","method":"tools.call","params":{"name":"start_session","arguments":{...},"stream":"same-id"}}`.
   - `GET /healthz` – simple health probe.

   Calls without a `stream` field return immediately in the HTTP response. When a `stream` is provided, the request returns `202 Accepted` and the result (or error) is emitted on the matching SSE channel.

4. **Embed the server** inside your adapter. Example:

   ```python
   from english_kids_mcp import KidEnglishMCPServer

   server = KidEnglishMCPServer()
   session = server.start_session("kid_001", "5-6", "greetings", "zh-CN")
   feedback = server.submit_utterance(session["session_id"], "hello")
   ```

   The returned dataclasses are easily serialisable (e.g. `dataclasses.asdict`) before sending them back through MCP channels or HTTP responses.

5. **Wire into n8n** by wrapping each tool in an HTTP node or a small MCP bridge. Feed ASR text to `submit_utterance`, push `feedback_text` to TTS, and display `next_activity.prompt_text` in your UI. The tutorial linked above sketches a reference flow and provides curl + `pytest -k sse` commands to verify the `/sse` bridge before you integrate.

## Optional references directory

The server looks for lexical hints under `references/<age-band>/<goal>/words.txt` (or `references/<age-band>/words.txt`). Each file is optional and stores one vocabulary item per line. When present, the matching words are surfaced in the `Activity.lexicon_words` list so your UI can preload picture hints, flashcards, or additional scaffolding.

Example:

```
references/
└── 5-6/
    └── greetings/
        └── words.txt  # friend, morning, happy, ...
```

## Configuration

Environment variables override defaults defined in `Settings`:

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `MCP_DATABASE_PATH` | `data/english_kids_mcp.sqlite` | SQLite location |
| `MCP_FAISS_INDEX_PATH` | `data/faiss.index` | On-disk FAISS index path |
| `MCP_EMBEDDING_DIM` | `128` | Hash embedding dimension |
| `MCP_MIN_SIMILARITY` | `0.35` | Minimum similarity threshold (reserved for adapters) |

## Next steps

- Swap the heuristic evaluator with an LLM function call to surface nuanced corrections.
- Expand `curriculum.json` with scene-based prompts, phonics challenges, and conversation badges.
- Emit parent dashboards by combining `get_progress` with the saved `parent_notes` table.
- Hook up richer reference packs (sight words, phonics clusters) by dropping them into the `references/` directory.

## License

MIT License
