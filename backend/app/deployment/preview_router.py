"""Subdomain-per-project reverse proxy for previews.

  https://preview-<16 hex>.<base_domain>/anything  ->  the project's sandbox

Behaviour:
- Host header must match preview-<16 hex>.<base_domain> exactly, else 404.
- Unknown preview -> 404. Expired preview -> 410 Gone.
- Traffic is forwarded ONLY to the upstream stored in the registry. Nothing in
  the request (path, headers, X-Forwarded-*) can change where it goes.
- Hop-by-hop headers are dropped; X-Forwarded-* are set by the router.
- Responses get nosniff / noindex / no-referrer headers.

Limitations (Day 2): no WebSocket proxying (Next.js hot reload will not work
through the router, pages still load), and request/response bodies are buffered.

SECURITY NOTE: never set platform cookies with Domain=.<base_domain>, or every
preview (which runs untrusted generated code) could read them.

Run locally:  see scripts/preview_demo.py
"""

from __future__ import annotations

import re
import time
from contextlib import asynccontextmanager
from typing import Callable, Optional, Protocol

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from .preview_registry import PREVIEW_PREFIX, PreviewRoute

MAX_BODY_BYTES = 10 * 1024 * 1024
UPSTREAM_TIMEOUT_SECONDS = 30.0
HEALTH_PATH = "/__router/health"

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}
# Request headers the router sets itself (never trust the client's version).
ROUTER_SET = {"host", "content-length", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto"}
# Response headers that no longer match after httpx decodes/buffers the body.
# Also drop "server"/"date": the router's own server sets them, and the sandbox's
# "server" header would reveal what software runs behind the preview.
DROP_FROM_RESPONSE = HOP_BY_HOP | {"content-length", "content-encoding", "server", "date"}
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


class RouteLookup(Protocol):
    def get(self, preview_id: str) -> Optional[PreviewRoute]: ...


def create_router_app(
    registry: RouteLookup,
    base_domain: str,
    *,
    scheme: str = "https",
    clock: Callable[[], float] = time.time,
    upstream_client: Optional[httpx.AsyncClient] = None,
) -> Starlette:
    host_pattern = re.compile(
        rf"^{re.escape(PREVIEW_PREFIX)}([0-9a-f]{{16}})\.{re.escape(base_domain.lower())}\Z"
    )
    client = upstream_client or httpx.AsyncClient(
        timeout=httpx.Timeout(UPSTREAM_TIMEOUT_SECONDS), follow_redirects=False
    )

    async def proxy(request: Request) -> Response:
        raw_host = request.headers.get("host", "")
        match = host_pattern.match(raw_host.split(":")[0].lower())
        if match is None:
            if request.url.path == HEALTH_PATH:
                return JSONResponse({"status": "ok"})
            return PlainTextResponse("Not found", status_code=404)

        route = registry.get(match.group(1))
        if route is None:
            return PlainTextResponse("Preview not found", status_code=404)
        if clock() >= route.expires_at:
            return PlainTextResponse("This preview has expired", status_code=410)

        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            return PlainTextResponse("Request body too large", status_code=413)
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            return PlainTextResponse("Request body too large", status_code=413)

        # The upstream is fixed by the registry. The path is appended as plain text
        # (never URL-joined), so a path like //evil.com cannot change the host.
        raw_path = request.scope.get("raw_path")
        path = raw_path.decode("latin-1") if raw_path else request.url.path
        if not path.startswith("/"):
            path = "/" + path
        query = request.scope.get("query_string", b"").decode("latin-1")
        url = route.upstream + path + (f"?{query}" if query else "")

        headers = [
            (k, v) for k, v in request.headers.items()
            if k.lower() not in HOP_BY_HOP and k.lower() not in ROUTER_SET
        ]
        headers += [("x-forwarded-host", raw_host), ("x-forwarded-proto", scheme)]
        if request.client:
            headers.append(("x-forwarded-for", request.client.host))

        try:
            upstream = await client.request(
                request.method, url, headers=headers, content=body, follow_redirects=False
            )
        except httpx.TimeoutException:
            return PlainTextResponse("Preview timed out", status_code=504)
        except httpx.HTTPError:
            return PlainTextResponse("Preview is not reachable", status_code=502)

        response = Response(content=upstream.content, status_code=upstream.status_code)
        for key, value in upstream.headers.multi_items():
            lower = key.lower()
            if lower in DROP_FROM_RESPONSE:
                continue
            if lower == "location" and value.startswith(route.upstream):
                value = f"{scheme}://{raw_host}{value[len(route.upstream):]}"
            response.headers.append(key, value)
        for key, value in (
            ("x-content-type-options", "nosniff"),
            ("x-robots-tag", "noindex, nofollow"),
            ("referrer-policy", "no-referrer"),
        ):
            if key not in response.headers:
                response.headers[key] = value
        return response

    @asynccontextmanager
    async def lifespan(app):
        yield
        await client.aclose()

    return Starlette(routes=[Route("/{path:path}", proxy, methods=METHODS)], lifespan=lifespan)