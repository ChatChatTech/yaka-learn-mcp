import http.client
import json
import time
import uuid

from english_kids_mcp import Settings, run_sse_server


def _read_sse_event(response, timeout=5.0):
    deadline = time.time() + timeout
    raw_sock = response.fp.raw._sock  # type: ignore[attr-defined]
    raw_sock.settimeout(timeout)
    data_line = None
    while time.time() < deadline:
        line = response.readline()
        if not line:
            continue
        text = line.decode("utf-8").strip()
        if not text:
            continue
        if text.startswith("data: "):
            data_line = text[6:]
            break
    if data_line is None:
        raise AssertionError("No SSE data received")
    return json.loads(data_line)


def test_sse_server_flow(tmp_path):
    settings = Settings(
        database_path=tmp_path / "sse.sqlite",
        faiss_index_path=tmp_path / "faiss.index",
        embedding_dim=32,
    )
    server = run_sse_server(host="127.0.0.1", port=0, settings=settings)
    meta_conn = None
    try:
        host, port = server.server_address
        stream_id = f"test-{uuid.uuid4().hex}"

        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.putrequest("GET", f"/sse?stream={stream_id}")
        conn.putheader("Accept", "text/event-stream")
        conn.endheaders()
        response = conn.getresponse()
        assert response.status == 200

        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "req-1",
                "method": "tools.call",
                "params": {
                    "name": "start_session",
                    "arguments": {
                        "user_id": "kid-sse",
                        "age_band": "5-6",
                        "goal": "greetings",
                        "locale": "zh-CN",
                    },
                    "stream": stream_id,
                },
            }
        )
        poster = http.client.HTTPConnection(host, port, timeout=5)
        poster.request(
            "POST",
            "/messages",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        post_response = poster.getresponse()
        assert post_response.status == 202

        event = _read_sse_event(response)
        assert event["jsonrpc"] == "2.0"
        assert event["id"] == "req-1"
        result = event["result"]
        assert "session_id" in result
        assert "next_activity" in result
        assert result["next_activity"]["prompt_text"]

        # synchronous JSON-RPC call for discovery
        meta_conn = http.client.HTTPConnection(host, port, timeout=5)
        meta_payload = json.dumps(
            {"jsonrpc": "2.0", "id": "req-meta", "method": "tools.list"}
        )
        meta_conn.request(
            "POST",
            "/messages",
            body=meta_payload,
            headers={"Content-Type": "application/json"},
        )
        meta_response = meta_conn.getresponse()
        assert meta_response.status == 200
        meta_data = json.loads(meta_response.read().decode("utf-8"))
        assert meta_data["result"]["tools"]
    finally:
        conn.close()
        poster.close()
        if meta_conn:
            meta_conn.close()
        server.shutdown()
        server.server_close()
