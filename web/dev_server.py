#!/usr/bin/env python3
"""Static file server for web/ that also reverse-proxies /api/* to the
FastAPI backend on 127.0.0.1.

Why this exists: on Lightning AI Studio (and similar remote dev boxes),
the browser only gets a forwarded HTTPS URL for one port. "localhost"
typed into browser JS on that page still means the user's own laptop,
not the Studio VM, so the frontend can never reach FastAPI directly on
its own port from there. Routing API calls through this same-origin
server (which forwards them to FastAPI over the VM's loopback
interface) fixes that without exposing port 8000 at all.

Stdlib only, on purpose: this is a thin dev proxy, not a production
gateway.
"""

import http.server
import json
import os
import socketserver
import sys
import urllib.error
import urllib.request

WEB_PORT = int(os.getenv("WEB_PORT", "5500"))
API_PORT = os.getenv("API_PORT", "8000")
BACKEND_URL = os.getenv("RUPSAA_BACKEND_URL", f"http://127.0.0.1:{API_PORT}")

API_PREFIX = "/api"
# Generation is serialised on one GPU, so a reply can wait behind others; keep the proxy patient.
PROXY_TIMEOUT = int(os.getenv("RUPSAA_PROXY_TIMEOUT", "300"))

# Hop-by-hop headers (RFC 7230 6.1) plus ones the HTTP client sets itself
# from `data=`/the request line — never forward these in either direction.
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}


class Handler(http.server.SimpleHTTPRequestHandler):
    def _is_api(self):
        return self.path == API_PREFIX or self.path.startswith(API_PREFIX + "/")

    def do_GET(self):
        self._proxy() if self._is_api() else super().do_GET()

    def do_HEAD(self):
        self._proxy() if self._is_api() else super().do_HEAD()

    def do_POST(self):
        self._proxy() if self._is_api() else self.send_error(404)

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST

    def _proxy(self):
        target_url = BACKEND_URL + (self.path[len(API_PREFIX):] or "/")

        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        headers = {k: v for k, v in self.headers.items() if k.lower() not in _HOP_BY_HOP}
        # Tell the API who the real client is (used for per-client rate limiting; the API only
        # trusts this header when the request comes from this proxy on loopback).
        prior = self.headers.get("X-Forwarded-For")
        headers["X-Forwarded-For"] = f"{prior}, {self.client_address[0]}" if prior else self.client_address[0]

        req = urllib.request.Request(target_url, data=body, headers=headers, method=self.command)

        try:
            with urllib.request.urlopen(req, timeout=PROXY_TIMEOUT) as resp:
                self._send_proxied_response(resp.status, resp.headers, resp.read())
        except urllib.error.HTTPError as err:
            self._send_proxied_response(err.code, err.headers, err.read())
        except (urllib.error.URLError, OSError) as err:
            payload = json.dumps(
                {"detail": f"Rupsaa backend unreachable at {BACKEND_URL}: {err}"}
            ).encode("utf-8")
            self._send_proxied_response(502, {"Content-Type": "application/json"}, payload)

    def _send_proxied_response(self, status, headers, body):
        self.send_response(status)
        for key, value in headers.items():
            if key.lower() not in _HOP_BY_HOP:
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        # Dev server: never let the browser cache static files (config.js in
        # particular) or API responses across a restart/edit.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("[web] " + (fmt % args) + "\n")


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    with ThreadingHTTPServer(("0.0.0.0", WEB_PORT), Handler) as httpd:
        print(f"Serving web/ on 0.0.0.0:{WEB_PORT}, proxying {API_PREFIX}/* -> {BACKEND_URL}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
