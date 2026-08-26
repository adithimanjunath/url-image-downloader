"""Shared pytest fixtures."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

_FAKE_JPEG_BYTES = b"\xff\xd8\xff\xe0fake-jpeg-body-for-tests"


class _Handler(BaseHTTPRequestHandler):
    """Serves a fake image for /ok.jpg and any /ok/<anything> path (so a
    test can build many distinct URLs against one handler); anything else
    is a 404.
    """

    def do_GET(self) -> None:
        if self.path == "/ok.jpg" or self.path.startswith("/ok/"):
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(_FAKE_JPEG_BYTES)))
            self.end_headers()
            self.wfile.write(_FAKE_JPEG_BYTES)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        pass  # silence BaseHTTPRequestHandler's default per-request stderr logging


@pytest.fixture
def local_server() -> Iterator[str]:
    """A real HTTP server on 127.0.0.1 with an OS-assigned port.

    Used only by the CLI end-to-end tests, which need to prove the whole
    pipeline works over a real socket. Unit tests elsewhere use
    httpx.MockTransport instead — no test in this suite makes a request
    to the real internet.
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        assert isinstance(host, str)  # always true for the AF_INET address we bound above
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join()
