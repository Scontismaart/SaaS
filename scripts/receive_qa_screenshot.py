"""Receive local browser QA screenshots into a fixed, non-sensitive artifact folder.

Run only while capturing screenshots: python scripts/receive_qa_screenshot.py
The receiver binds to loopback and accepts a small allowlist of JPEG file names.
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots" / "frontend-2026-09-23"
ALLOWED = {
    "hero-release-desktop.jpg",
    "hero-release-mobile.jpg",
    "login-desktop.jpg",
    "signup-mobile.jpg",
    "dashboard-overview-desktop.jpg",
    "dashboard-overview-mobile.jpg",
    "dashboard-ai-config-desktop.jpg",
}


class ScreenshotReceiver(BaseHTTPRequestHandler):
    def do_POST(self):
        name = self.path.removeprefix("/capture/")
        length = int(self.headers.get("Content-Length", "0"))
        if self.path != f"/capture/{name}" or name not in ALLOWED or not 0 < length <= 4_000_000:
            self.send_error(400)
            return
        content = self.rfile.read(length)
        if not content.startswith(b"\xff\xd8\xff"):
            self.send_error(415)
            return
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / name).write_bytes(content)
        self.send_response(201)
        self.end_headers()


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 4175), ScreenshotReceiver).serve_forever()
