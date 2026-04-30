#!/usr/bin/env python3
"""Tiny HTTP proxy for Anthropic with enforced minimum interval between upstream calls.

Use this when a backend issues multiple internal LLM calls per user request and you need
hard pacing between those internal calls.

Environment variables:
- THROTTLE_HOST (default: 0.0.0.0)
- THROTTLE_PORT (default: 9100)
- THROTTLE_MIN_INTERVAL_SECONDS (default: 60)
- THROTTLE_UPSTREAM_BASE (default: https://api.anthropic.com)
"""

from __future__ import annotations

import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


HOST = os.getenv("THROTTLE_HOST", "0.0.0.0")
PORT = int(os.getenv("THROTTLE_PORT", "9100"))
MIN_INTERVAL_SECONDS = float(os.getenv("THROTTLE_MIN_INTERVAL_SECONDS", "60"))
UPSTREAM_BASE = os.getenv("THROTTLE_UPSTREAM_BASE", "https://api.anthropic.com").rstrip("/")

_last_call_ts = 0.0
_call_lock = threading.Lock()


def _filter_headers(handler: BaseHTTPRequestHandler) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in handler.headers.items():
        lk = key.lower()
        if lk in {"host", "content-length", "connection", "accept-encoding"}:
            continue
        headers[key] = value
    return headers


def _throttle() -> None:
    global _last_call_ts
    with _call_lock:
        now = time.monotonic()
        wait_for = MIN_INTERVAL_SECONDS - (now - _last_call_ts)
        if wait_for > 0:
            print(f"[throttle] sleeping {wait_for:.1f}s before upstream call", flush=True)
            time.sleep(wait_for)
        _last_call_ts = time.monotonic()


class AnthropicThrottleProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _proxy(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length > 0 else None

        upstream_url = urljoin(f"{UPSTREAM_BASE}/", self.path.lstrip("/"))
        req = Request(
            upstream_url,
            data=body,
            method=self.command,
            headers=_filter_headers(self),
        )

        _throttle()

        try:
            with urlopen(req, timeout=300) as resp:
                payload = resp.read()
                self.send_response(resp.status)
                for key, value in resp.headers.items():
                    lk = key.lower()
                    if lk in {"transfer-encoding", "connection", "content-encoding"}:
                        continue
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        except HTTPError as exc:
            payload = exc.read() if hasattr(exc, "read") else b""
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if payload:
                self.wfile.write(payload)
        except URLError as exc:
            msg = f"{{\"error\":\"upstream_error\",\"detail\":\"{exc}\"}}".encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    def do_GET(self) -> None:  # noqa: N802
        self._proxy()

    def do_POST(self) -> None:  # noqa: N802
        self._proxy()

    def do_PUT(self) -> None:  # noqa: N802
        self._proxy()

    def do_DELETE(self) -> None:  # noqa: N802
        self._proxy()

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[proxy] {self.address_string()} - {fmt % args}", flush=True)


if __name__ == "__main__":
    print(
        f"Starting Anthropic throttle proxy on {HOST}:{PORT} -> {UPSTREAM_BASE} "
        f"(min interval: {MIN_INTERVAL_SECONDS}s)",
        flush=True,
    )
    server = ThreadingHTTPServer((HOST, PORT), AnthropicThrottleProxyHandler)
    server.serve_forever()
