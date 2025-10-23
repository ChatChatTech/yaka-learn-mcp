# Streaming MCP tutorial

This walkthrough shows how to run the Kid English MCP server as a standalone process and consume
Server-Sent Events (SSE) from a terminal client. By the end you will:

1. Install the package and launch the SSE HTTP bridge.
2. Subscribe to `/sse` and issue JSON-RPC tool invocations through `/messages`.
3. Inspect the streamed payloads and close the session cleanly.
4. Re-run the automated regression test (`pytest -k sse`) to verify the integration.

## 1. Install dependencies

Create and activate a virtual environment, then install the project in editable mode with test
extras (FAISS is optional; NumPy cosine fallback is included).

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[test]
```

## 2. Launch the SSE bridge

Run the CLI entry point. It initialises the pedagogy engine, SQLite storage, and the SSE HTTP
server. The example below binds to port `8765`, stores state in `data/`, and loads the default
curriculum and optional vocabulary references (if present).

```bash
kid-english-mcp --host 0.0.0.0 --port 8765
```

You should see output similar to:

```
Serving KidEnglish MCP SSE server on http://0.0.0.0:8765
```

Leave this process running while you experiment with the client in the next step.

## 3. Subscribe and invoke tools

Open a second terminal session (or use another tab) and subscribe to the SSE stream. You can choose
any `stream` identifier; it just needs to match the one you post in the JSON-RPC payload.

```bash
curl -N http://127.0.0.1:8765/sse?stream=demo-stream
```

The `-N` flag keeps the connection open so curl prints heartbeat comments until a message arrives.

With the stream open, issue a tool call. MCP over HTTP expects JSON-RPC 2.0 payloads. The following
example uses the `tools.call` method to invoke `start_session` and create a learner session for a
5–6 year old practising greetings.

```bash
curl -X POST http://127.0.0.1:8765/messages \
  -H 'Content-Type: application/json' \
  -d '{
        "jsonrpc": "2.0",
        "id": "demo-1",
        "method": "tools.call",
        "params": {
          "name": "start_session",
          "arguments": {
            "user_id": "kid-demo",
            "age_band": "5-6",
            "goal": "greetings",
            "locale": "zh-CN"
          },
          "stream": "demo-stream"
        }
      }'
```

The SSE terminal prints a JSON event when the tool completes:

```
event: message
data: {"jsonrpc": "2.0", "id": "demo-1", "result": {"session_id": "...", "next_activity": {...}}, "done": true}
```

Use the returned `session_id` to submit utterances or fetch the next activity:

```bash
curl -X POST http://127.0.0.1:8765/messages \
  -H 'Content-Type: application/json' \
  -d '{
        "jsonrpc": "2.0",
        "id": "demo-2",
        "method": "tools.call",
        "params": {
          "name": "submit_utterance",
          "arguments": {
            "session_id": "<SESSION FROM PREVIOUS STEP>",
            "utterance_text": "hello"
          },
          "stream": "demo-stream"
        }
      }'
```

Each call pushes a new event through the same `/sse` connection. Close the stream with `Ctrl+C`
once you are done.

### Synchronous (non-streaming) mode

If you omit the `stream` field inside `params` the server responds synchronously with a JSON object.
This is useful for scripts that do not require SSE but still want to reuse the standalone bridge.

### Discovering tools via JSON-RPC

Before streaming you can inspect the server manifest (`GET /.well-known/mcp.json`) or call the
`tools.list` method to retrieve the machine-readable tool metadata:

```bash
curl -X POST http://127.0.0.1:8765/messages \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"meta","method":"tools.list"}'
```

## 4. Verify with the automated test

The repository ships with a regression test that boots the SSE server on an ephemeral port,
subscribes to `/sse`, and asserts the streamed result structure. Run it alone or as part of the full
suite:

```bash
pytest -k sse
```

A successful run confirms that tool invocations are correctly marshalled onto the SSE channel.

## 5. Optional vocabulary references

Drop plain-text word lists under `references/<age-band>/<goal>/words.txt` (one word per line, `#`
for comments). When present, matching words are injected into the `lexicon_words` field of each
activity and can be surfaced in your UI as flashcards or picture hints.

Example structure:

```
references/
└── 5-6/
    └── greetings/
        └── words.txt
```

Restart the SSE server after updating the reference files to ensure the changes are picked up.
