import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from app.deployment.preview_registry import InMemoryPreviewRegistry, PreviewService
from app.deployment.preview_router import MAX_BODY_BYTES, create_router_app

A, B = "tenant-a", "tenant-b"
DOMAIN = "localhost"


# -- a tiny real HTTP server that echoes what it receives -----------------
class EchoHandler(BaseHTTPRequestHandler):
    def _respond(self):
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length).decode() if length else ""
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/landing")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        payload = json.dumps({
            "server": self.server.label,
            "method": self.command,
            "path": self.path,
            "body": body,
            "headers": {k.lower(): v for k, v in self.headers.items()},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Set-Cookie", "a=1")
        self.send_header("Set-Cookie", "b=2")
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_PUT = _respond

    def log_message(self, *args):
        pass


@pytest.fixture
def start_upstream():
    servers = []

    def start(label):
        server = ThreadingHTTPServer(("127.0.0.1", 0), EchoHandler)
        server.label = label
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_port}"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def stack():
    clock = Clock()
    registry = InMemoryPreviewRegistry()
    service = PreviewService(registry, DOMAIN, scheme="http", public_port=8080, clock=clock)
    app = create_router_app(registry, DOMAIN, scheme="http", clock=clock)
    return service, registry, app, clock


def host_of(info):
    return info.url.split("://")[1]  # preview-<id>.localhost:8080


def call(app, method, path, host, **kwargs):
    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            headers = {"host": host, **kwargs.pop("headers", {})}
            return await client.request(method, path, headers=headers, **kwargs)

    return asyncio.run(run())


# -- host matching ---------------------------------------------------------
def test_unknown_or_malformed_hosts_get_404(stack):
    service, registry, app, _ = stack
    info = service.register_preview(A, "p1", "http://127.0.0.1:3000")
    pid = info.preview_id
    for host in ["localhost", "evil.com", "preview-abc.localhost", f"preview-{pid}.evil.com",
                 f"x.preview-{pid}.localhost", f"preview-{pid}.localhost.evil.com",
                 f"preview-{'0' * 16}.localhost", f"PREVIEW-{pid.upper()}.localhost.evil.com"]:
        assert call(app, "GET", "/", host).status_code == 404, host


def test_health_endpoint_only_on_non_preview_hosts(stack):
    _, _, app, _ = stack
    ok = call(app, "GET", "/__router/health", "localhost:8080")
    assert ok.status_code == 200 and ok.json() == {"status": "ok"}
    assert call(app, "GET", "/other", "localhost:8080").status_code == 404


def test_x_forwarded_host_cannot_select_a_preview(stack, start_upstream):
    service, _, app, _ = stack
    info = service.register_preview(A, "p1", start_upstream("one"))
    response = call(app, "GET", "/", "evil.com", headers={"x-forwarded-host": host_of(info)})
    assert response.status_code == 404


# -- forwarding --------------------------------------------------------------
def test_forwards_method_path_query_and_body(stack, start_upstream):
    service, _, app, _ = stack
    info = service.register_preview(A, "p1", start_upstream("one"))
    response = call(app, "POST", "/api/items?x=1&y=two", host_of(info), content=b'{"name": "widget"}',
                    headers={"content-type": "application/json"})
    data = response.json()
    assert response.status_code == 200
    assert data["server"] == "one"
    assert data["method"] == "POST"
    assert data["path"] == "/api/items?x=1&y=two"
    assert data["body"] == '{"name": "widget"}'


def test_router_sets_forwarding_headers_and_ignores_spoofed_ones(stack, start_upstream):
    service, _, app, _ = stack
    info = service.register_preview(A, "p1", start_upstream("one"))
    response = call(app, "GET", "/", host_of(info),
                    headers={"x-forwarded-host": "evil.example", "x-forwarded-for": "6.6.6.6", "upgrade": "h2c"})
    seen = response.json()["headers"]
    assert seen["x-forwarded-host"] == host_of(info)
    assert seen["x-forwarded-proto"] == "http"
    assert seen["x-forwarded-for"] != "6.6.6.6"
    assert "upgrade" not in seen


def test_path_cannot_redirect_traffic_to_another_host(stack, start_upstream):
    service, _, app, _ = stack
    info = service.register_preview(A, "p1", start_upstream("one"))
    # Full URL on purpose: a bare "//evil.com/steal" would be rewritten by httpx
    # itself (scheme-relative URL) before it ever reached the router.
    response = call(app, "GET", "http://testserver//evil.com/steal", host_of(info))
    assert response.status_code == 200
    assert response.json()["server"] == "one"  # still our sandbox, never evil.com
    # Python's http.server collapses a leading "//" itself, so compare without it.
    assert response.json()["path"].lstrip("/") == "evil.com/steal"


def test_redirects_are_rewritten_to_the_public_url(stack, start_upstream):
    service, _, app, _ = stack
    info = service.register_preview(A, "p1", start_upstream("one"))
    response = call(app, "GET", "/redirect", host_of(info))
    assert response.status_code == 302
    assert response.headers["location"] == f"http://{host_of(info)}/landing"


def test_response_headers_multiple_cookies_and_hardening(stack, start_upstream):
    service, _, app, _ = stack
    info = service.register_preview(A, "p1", start_upstream("one"))
    response = call(app, "GET", "/", host_of(info))
    assert response.headers.get_list("set-cookie") == ["a=1", "b=2"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "noindex" in response.headers["x-robots-tag"]
    assert response.headers["referrer-policy"] == "no-referrer"


def test_unreachable_upstream_gives_502(stack):
    service, _, app, _ = stack
    info = service.register_preview(A, "p1", "http://127.0.0.1:59999")
    assert call(app, "GET", "/", host_of(info)).status_code == 502


def test_oversized_request_body_is_rejected(stack, start_upstream):
    service, _, app, _ = stack
    info = service.register_preview(A, "p1", start_upstream("one"))
    response = call(app, "POST", "/", host_of(info), content=b"x" * (MAX_BODY_BYTES + 1))
    assert response.status_code == 413


# -- expiry ---------------------------------------------------------------
def test_expired_preview_returns_410_then_404_after_purge(stack, start_upstream):
    service, registry, app, clock = stack
    info = service.register_preview(A, "p1", start_upstream("one"))
    assert call(app, "GET", "/", host_of(info)).status_code == 200
    clock.now = info.expires_at
    assert call(app, "GET", "/", host_of(info)).status_code == 410
    service.reap()
    assert call(app, "GET", "/", host_of(info)).status_code == 410  # still "gone" during the grace period
    clock.now += 2 * 3600
    service.reap()
    assert call(app, "GET", "/", host_of(info)).status_code == 404


def test_stopped_preview_is_gone_immediately(stack, start_upstream):
    service, _, app, _ = stack
    info = service.register_preview(A, "p1", start_upstream("one"))
    service.stop_preview(A, "p1")
    assert call(app, "GET", "/", host_of(info)).status_code == 404


# -- the Day 2 test: 3 previews in parallel ----------------------------------
def test_three_previews_in_parallel_do_not_cross_talk(stack, start_upstream):
    service, _, app, clock = stack
    previews = {
        "alpha": service.register_preview(A, "alpha", start_upstream("alpha")),
        "beta": service.register_preview(A, "beta", start_upstream("beta")),
        "gamma": service.register_preview(B, "gamma", start_upstream("gamma")),  # different tenant
    }

    async def hit_all(requests_each=15):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            async def one(name, i):
                response = await client.get(f"/page/{i}", headers={"host": host_of(previews[name])})
                return name, i, response

            jobs = [one(name, i) for i in range(requests_each) for name in previews]
            return await asyncio.gather(*jobs)

    results = asyncio.run(hit_all())
    assert len(results) == 45
    for name, i, response in results:
        assert response.status_code == 200
        assert response.json()["server"] == name  # each preview only ever hits its own sandbox
        assert response.json()["path"] == f"/page/{i}"

    # Expiring one preview leaves the other two untouched.
    service.stop_preview(A, "beta")
    after = {name: call(app, "GET", "/", host_of(info)).status_code for name, info in previews.items()}
    assert after == {"alpha": 200, "beta": 404, "gamma": 200}


def test_sandbox_server_header_is_not_exposed(stack, start_upstream):
    service, _, app, _ = stack
    info = service.register_preview(A, "p1", start_upstream("one"))
    response = call(app, "GET", "/", host_of(info))
    assert "server" not in response.headers
