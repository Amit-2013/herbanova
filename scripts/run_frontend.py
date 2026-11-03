"""Start the static UI server, forwarding API calls to the backend.

Run from the repository root in a second terminal:

    python scripts/run_frontend.py
    python scripts/run_frontend.py --port 3000 --backend http://127.0.0.1:8000

The UI is plain files, so this uses only the standard library. ``/api``,
``/docs`` and ``/openapi.json`` are proxied to the backend unchanged, which
keeps the session cookie first-party and lets the frontend keep its relative
URLs. This is a development/LAN server, not a production web server.
"""
from __future__ import annotations

import argparse
import mimetypes
import posixpath
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
PROXY_PREFIXES = ("/api/", "/api", "/docs", "/openapi.json", "/redoc")
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
              "te", "trailers", "transfer-encoding", "upgrade", "host"}


class FrontendHandler(BaseHTTPRequestHandler):
    server_version = "HerbanovaUI/1.0"
    backend = "http://127.0.0.1:8000"

    def do_GET(self):
        if self._is_proxy():
            return self._proxy()
        return self._static()

    def do_HEAD(self):
        if self._is_proxy():
            return self._proxy()
        return self._static(head_only=True)

    def do_POST(self):
        return self._proxy()

    def do_PUT(self):
        return self._proxy()

    def do_PATCH(self):
        return self._proxy()

    def do_DELETE(self):
        return self._proxy()

    def do_OPTIONS(self):
        return self._proxy()

    # -- routing -----------------------------------------------------------
    def _is_proxy(self) -> bool:
        path = self.path.split("?", 1)[0]
        return any(path == p or path.startswith(p + "/") or path == p.rstrip("/")
                   for p in PROXY_PREFIXES)

    def _static(self, head_only: bool = False) -> None:
        # A URL path always uses "/" separators. url2pathname would turn them
        # into "\" on Windows, which Path reads as an absolute drive path and
        # the guard would then (correctly) refuse.
        raw = unquote(self.path.split("?", 1)[0].split("#", 1)[0])
        if raw in ("", "/", "/ui", "/ui/"):
            raw = "/index.html"
        elif raw.startswith("/ui/"):
            raw = raw[3:]
        # posixpath.normpath removes `..` before it can climb out of static/.
        relative = posixpath.normpath(raw).lstrip("/")
        target = (STATIC / relative).resolve()
        try:
            target.relative_to(STATIC.resolve())
        except ValueError:
            return self._send_text(403, "Forbidden")
        if not target.is_file():
            return self._send_text(404, "Not found")
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def _proxy(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        target = self.backend.rstrip("/") + self.path
        request = urllib.request.Request(target, data=body, headers=headers,
                                         method=self.command)
        try:
            response = urllib.request.urlopen(request, timeout=120)
        except urllib.error.HTTPError as exc:      # an error is still the API's answer
            response = exc
        except urllib.error.URLError as exc:
            return self._send_text(502, f"The backend at {self.backend} is not reachable: "
                                        f"{exc.reason}. Start scripts/run_backend.py.")
        with response:
            payload = response.read()
            self.send_response(response.status)
            for name, value in response.headers.items():
                if name.lower() not in HOP_BY_HOP and name.lower() != "content-length":
                    self.send_header(name, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    def _send_text(self, status: int, text: str) -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} {fmt % args}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Herbanova UI server")
    parser.add_argument("--host", default="127.0.0.1",
                        help="interface to bind (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=3000, help="port (default 3000)")
    parser.add_argument("--backend", default="http://127.0.0.1:8000",
                        help="backend base URL (default http://127.0.0.1:8000)")
    args = parser.parse_args(argv)

    FrontendHandler.backend = args.backend.rstrip("/")
    server = ThreadingHTTPServer((args.host, args.port), FrontendHandler)
    print(f"Herbanova UI on http://{args.host}:{args.port}/ "
          f"proxying API to {FrontendHandler.backend}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
