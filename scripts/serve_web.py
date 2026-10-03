"""Static & proxy dev server for Melpis WhatsApp AI Responder.
Replicates the exact URL mapping, security headers, and reverse proxy of the Nginx container:
- Landing page on '/' (from web/landing/)
- Auth pages on '/accedi/' and '/registrati/' (from web/)
- Legal pages on '/privacy/', '/termini/', '/cookie/' (from web/landing/)
- Dashboard on '/app/' (from web/)
- Proxy '/api/*', '/webhooks/*', '/docs', '/redoc', '/openapi.json' to FastAPI backend on port 8000.

Usage:
  python scripts/serve_web.py [port]  (default 8080)
"""
import http.client
import mimetypes
import os
import sys
import urllib.parse
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEB = Path(__file__).resolve().parent.parent / "web"
LANDING = WEB / "landing"
API_BACKEND_HOST = "127.0.0.1"
API_BACKEND_PORT = 8000

CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; img-src 'self' data: https:; connect-src 'self' http://localhost:* http://127.0.0.1:*; "
    "base-uri 'self'; form-action 'self'"
)


class DevHandler(BaseHTTPRequestHandler):
    def _headers(self, ctype, status=200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def _is_api_path(self, path: str) -> bool:
        return (
            path.startswith("/api/")
            or path.startswith("/webhooks/")
            or path in ("/api/health", "/docs", "/redoc", "/openapi.json")
            or path.startswith("/docs/")
        )

    def _proxy_request(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len > 0 else None

        conn = http.client.HTTPConnection(API_BACKEND_HOST, API_BACKEND_PORT, timeout=60)
        try:
            headers = {k: v for k, v in self.headers.items() if k.lower() != "host"}
            headers["Host"] = f"{API_BACKEND_HOST}:{API_BACKEND_PORT}"
            headers["X-Forwarded-For"] = self.client_address[0]
            headers["X-Forwarded-Proto"] = "http"

            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()

            self.send_response(resp.status, resp.reason)
            for header, value in resp.getheaders():
                if header.lower() not in ("transfer-encoding",):
                    self.send_header(header, value)
            self.end_headers()

            resp_body = resp.read()
            self.wfile.write(resp_body)
        except Exception as exc:
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(f'{{"detail":"Proxy backend error (is backend running on port {API_BACKEND_PORT}?): {exc}"}}'.encode("utf-8"))
        finally:
            conn.close()

    def do_GET(self):
        path = self.path.split("?")[0]
        if self._is_api_path(path):
            self._proxy_request()
            return

        # 1. Clean URL redirects
        if path == "/app":
            self.send_response(301)
            self.send_header("Location", "/app/")
            self.end_headers()
            return
        if path == "/accedi":
            self.send_response(301)
            self.send_header("Location", "/accedi/")
            self.end_headers()
            return
        if path == "/registrati":
            self.send_response(301)
            self.send_header("Location", "/registrati/")
            self.end_headers()
            return
        if path in (
            "/privacy", "/termini", "/cookie", "/prezzi",
            "/settori/ristoranti", "/settori/saloni-bellezza", "/settori/studi-medici", "/settori/hotel"
        ):
            self.send_response(301)
            self.send_header("Location", f"{path}/")
            self.end_headers()
            return

        # 2. Map routes to filesystem files
        target = None

        if path in ("/", "/index.html"):
            target = LANDING / "index.html"
        elif path in ("/privacy/", "/privacy.html"):
            target = LANDING / "privacy.html"
        elif path in ("/termini/", "/termini.html"):
            target = LANDING / "termini.html"
        elif path in ("/cookie/", "/cookie.html"):
            target = LANDING / "cookie.html"
        elif path in ("/accedi/", "/login.html"):
            target = WEB / "login.html"
        elif path in ("/registrati/", "/register.html"):
            target = WEB / "register.html"
        elif path == "/app/" or path == "/app/index.html":
            target = WEB / "index.html"
        elif path.startswith("/app/"):
            try:
                rel_sub = urllib.parse.unquote(path[len("/app/"):], errors="strict")
            except UnicodeDecodeError:
                self.send_error(400, "Invalid UTF-8 in dashboard path")
                return
            if "\\" in rel_sub or any(ord(char) < 32 or ord(char) == 127 for char in rel_sub):
                self.send_error(404)
                return
            candidate = (WEB / rel_sub).resolve()
            try:
                candidate.relative_to(WEB.resolve())
            except ValueError:
                self.send_error(404)
                return
            if candidate.is_dir():
                candidate = candidate / "index.html"
            if candidate.is_file():
                target = candidate
            elif not Path(rel_sub).suffix:
                target = WEB / "index.html"
        elif path in ("/login.js", "/register.js", "/auth.js", "/auth.css", "/config.js"):
            target = WEB / path.lstrip("/")
        elif (LANDING / path.lstrip("/")).is_file():
            target = LANDING / path.lstrip("/")
        elif (LANDING / path.lstrip("/") / "index.html").is_file():
            target = LANDING / path.lstrip("/") / "index.html"
        elif (WEB / path.lstrip("/")).is_file():
            target = WEB / path.lstrip("/")
        elif path.startswith("/fonts/"):
            target = LANDING / path.lstrip("/")
            if not target.is_file():
                target = WEB / path.lstrip("/")

        if target is None or not target.is_file():
            # 404 handler
            self._headers("text/html; charset=utf-8", status=404)
            err_file = LANDING / "404.html"
            if err_file.is_file():
                self.wfile.write(err_file.read_bytes())
            else:
                self.wfile.write(b"<h1>404 Not Found</h1>")
            return

        # Security check: ensure target is inside WEB directory
        try:
            target.resolve().relative_to(WEB.resolve())
        except ValueError:
            self.send_error(403)
            return

        # Content-Type guessing
        ctype, _ = mimetypes.guess_type(str(target))
        if not ctype:
            ctype = "application/octet-stream"
        if target.suffix == ".html":
            ctype = "text/html; charset=utf-8"
        elif target.suffix == ".js":
            ctype = "text/javascript; charset=utf-8"
        elif target.suffix == ".css":
            ctype = "text/css; charset=utf-8"
        elif target.suffix == ".woff2":
            ctype = "font/woff2"
        elif target.suffix == ".webp":
            ctype = "image/webp"

        self._headers(ctype)
        self.wfile.write(target.read_bytes())

    def do_POST(self):
        if self._is_api_path(self.path.split("?")[0]):
            self._proxy_request()
        else:
            self.send_error(405)

    def do_PUT(self):
        if self._is_api_path(self.path.split("?")[0]):
            self._proxy_request()
        else:
            self.send_error(405)

    def do_DELETE(self):
        if self._is_api_path(self.path.split("?")[0]):
            self._proxy_request()
        else:
            self.send_error(405)

    def do_OPTIONS(self):
        if self._is_api_path(self.path.split("?")[0]):
            self._proxy_request()
        else:
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.end_headers()

    def log_message(self, format, *args):
        pass


def run(port=8080):
    server = ThreadingHTTPServer(("127.0.0.1", port), DevHandler)
    print(f"Dev server running on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDev server stopped.")


if __name__ == "__main__":
    p = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run(p)
