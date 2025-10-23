"""Standalone SSE server exposing the KidEnglishMCPServer tools."""

from __future__ import annotations

import argparse
import json
import queue
import threading
import time
import uuid
from dataclasses import asdict, is_dataclass
from pathlib import Path
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from .config import Settings
from .server import KidEnglishMCPServer


HEARTBEAT_INTERVAL = 8
SSE_ENDPOINT = "/sse"


def _to_payload(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _to_payload(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_payload(item) for item in value]
    return value


class SSEConnectionManager:
    """Track queues for active SSE clients."""

    def __init__(self) -> None:
        self._queues: Dict[str, queue.Queue] = {}
        self._lock = threading.Lock()

    def register(self, stream_id: str) -> queue.Queue:
        with self._lock:
            if stream_id not in self._queues:
                self._queues[stream_id] = queue.Queue()
            return self._queues[stream_id]

    def publish(self, stream_id: str, message: Dict[str, Any]) -> None:
        with self._lock:
            q = self._queues.get(stream_id)
        if q is not None:
            q.put(message)

    def discard(self, stream_id: str) -> None:
        with self._lock:
            self._queues.pop(stream_id, None)


class KidEnglishHTTPRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler serving SSE streams and MCP invocations."""

    server_version = "KidEnglishMCPSSE/0.4"

    def do_GET(self) -> None:  # noqa: N802  (BaseHTTPRequestHandler API)
        parsed = urlparse(self.path)
        if parsed.path in {SSE_ENDPOINT, "/events"}:
            self._handle_events(parsed)
            return
        if parsed.path == "/healthz":
            self._handle_health()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/invoke":
            self._handle_invoke()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    # ------------------------------------------------------------------
    # Helpers

    def _handle_health(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        payload = json.dumps({"status": "ok", "time": int(time.time())}).encode("utf-8")
        self.wfile.write(payload)

    def _handle_events(self, parsed) -> None:
        params = parse_qs(parsed.query)
        stream_id = params.get("stream", [str(uuid.uuid4())])[0]
        manager: SSEConnectionManager = self.server.manager  # type: ignore[attr-defined]
        queue_ = manager.register(stream_id)

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        self.wfile.write(b": connected\n\n")
        self.wfile.flush()

        try:
            while True:
                try:
                    message = queue_.get(timeout=HEARTBEAT_INTERVAL)
                except queue.Empty:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    continue

                data = json.dumps(message, ensure_ascii=False).encode("utf-8")
                self.wfile.write(b"event: message\n")
                self.wfile.write(b"data: " + data + b"\n\n")
                self.wfile.flush()

                if message.get("done"):
                    break
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            manager.discard(stream_id)

    def _handle_invoke(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, f"Invalid JSON: {exc}")
            return

        tool = payload.get("tool")
        arguments = payload.get("arguments", {})
        stream_id = payload.get("stream_id")

        if not tool:
            self.send_error(HTTPStatus.BAD_REQUEST, "Missing tool name")
            return

        mcp_server: KidEnglishMCPServer = self.server.mcp  # type: ignore[attr-defined]

        if not hasattr(mcp_server, tool):
            self.send_error(HTTPStatus.NOT_FOUND, f"Unknown tool: {tool}")
            return

        method = getattr(mcp_server, tool)

        try:
            result = method(**arguments)
        except TypeError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, f"Argument error: {exc}")
            return
        except Exception as exc:  # pragma: no cover - defensive
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return

        payload_result = {
            "id": str(uuid.uuid4()),
            "tool": tool,
            "result": _to_payload(result),
        }

        if stream_id:
            manager: SSEConnectionManager = self.server.manager  # type: ignore[attr-defined]
            payload_result["done"] = True
            manager.publish(stream_id, payload_result)
            self.send_response(HTTPStatus.ACCEPTED)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "queued", "stream": stream_id}).encode("utf-8"))
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload_result, ensure_ascii=False).encode("utf-8"))


class KidEnglishHTTPServer(ThreadingHTTPServer):
    """Threading server injecting MCP server dependencies."""

    def __init__(self, address, handler, mcp_server: KidEnglishMCPServer, manager: SSEConnectionManager):
        super().__init__(address, handler)
        self.mcp = mcp_server
        self.manager = manager


def run_sse_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    settings: Optional[Settings] = None,
    curriculum_path: Optional[Path] = None,
    references_path: Optional[Path] = None,
) -> KidEnglishHTTPServer:
    """Create and start the SSE HTTP server."""

    mcp_server = KidEnglishMCPServer(
        settings=settings,
        curriculum_path=curriculum_path,
        references_path=references_path,
    )
    manager = SSEConnectionManager()
    http_server = KidEnglishHTTPServer((host, port), KidEnglishHTTPRequestHandler, mcp_server, manager)
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    return http_server


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Kid English MCP SSE server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8765, help="Port number (default: 8765)")
    parser.add_argument("--database", help="Path to SQLite database override")
    parser.add_argument("--references", help="Path to optional references directory")
    parser.add_argument("--curriculum", help="Path to custom curriculum JSON")
    args = parser.parse_args(argv)

    settings = Settings.load()
    if args.database:
        settings = Settings(
            database_path=args.database,
            faiss_index_path=settings.faiss_index_path,
            embedding_dim=settings.embedding_dim,
            min_similarity=settings.min_similarity,
        )

    mcp_server = KidEnglishMCPServer(
        settings=settings,
        curriculum_path=Path(args.curriculum).resolve() if args.curriculum else None,
        references_path=Path(args.references).resolve() if args.references else None,
    )
    manager = SSEConnectionManager()
    http_server = KidEnglishHTTPServer((args.host, args.port), KidEnglishHTTPRequestHandler, mcp_server, manager)

    print(f"Serving KidEnglish MCP SSE server on http://{args.host}:{args.port}")
    try:
        http_server.serve_forever()
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        http_server.server_close()


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
