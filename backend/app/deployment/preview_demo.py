"""Local demo of the preview router (no domain needed).

Run from the backend folder:   python scripts/preview_demo.py
Then open the printed URL in Chrome. Chrome resolves *.localhost to your own
machine, so  http://preview-<id>.localhost:8080  just works.
(curl/Python may not resolve it on Windows; use the Host header trick printed below.)

What it does:
  1. starts a tiny "sandbox" web server on port 3001
  2. registers a preview for it (valid 30 minutes)
  3. starts the router on port 8080
"""

import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make "app" importable

import uvicorn  # noqa: E402

from app.deployment.preview_registry import InMemoryPreviewRegistry, PreviewService  # noqa: E402
from app.deployment.preview_router import create_router_app  # noqa: E402

UPSTREAM_PORT = 3001
ROUTER_PORT = 8080
BASE_DOMAIN = "localhost"

PAGE = b"""<!doctype html><html><body style="font-family:sans-serif;padding:2rem">
<h1>Hello from a TeslaLab preview</h1>
<p>This page is served by a sandbox on port 3001, reached through the preview router.</p>
</body></html>"""


class SandboxPage(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *args):
        pass


def main() -> None:
    sandbox = ThreadingHTTPServer(("127.0.0.1", UPSTREAM_PORT), SandboxPage)
    threading.Thread(target=sandbox.serve_forever, daemon=True).start()

    registry = InMemoryPreviewRegistry()
    service = PreviewService(registry, BASE_DOMAIN, scheme="http", public_port=ROUTER_PORT)
    info = service.register_preview("demo-tenant", "demo-project", f"http://127.0.0.1:{UPSTREAM_PORT}")

    host = info.url.split("://")[1]
    print(f"PREVIEW_URL={info.url}", flush=True)
    print(f'Or with curl:  curl -H "Host: {host}" http://127.0.0.1:{ROUTER_PORT}/', flush=True)

    app = create_router_app(registry, BASE_DOMAIN, scheme="http")
    uvicorn.run(app, host="127.0.0.1", port=ROUTER_PORT, log_level="warning")


if __name__ == "__main__":
    main()