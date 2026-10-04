"""Bearer gate for the Whelk brain's MCP HTTP transport.

Whelk Server publishes the brain's port on the host's loopback address, so any local
process can open it. This gate makes the port useless without the token: every HTTP
request except `GET /health` must carry `Authorization: Bearer <WHELK_SERVER_TOKEN>`,
the same token Whelk Server holds for the product and sends when it calls the brain.

The comparison is constant-time. With no token set the server refuses to start rather
than serve an open port. `serve()` mirrors FastMCP's `run_streamable_http_async()` with
the gate wrapped around the Starlette app.

`serve()` also mounts the transport at `/mcp/` rather than FastMCP's `/mcp`. Upstream
answers `/mcp/` with a 307 to `/mcp`, and Whelk Server's MCP client does not follow
redirects, so the documented `/mcp/` must answer directly.
"""
import hmac
import json
import os

OPEN_PATHS = frozenset({'/health'})

REFUSAL = json.dumps(
    {
        'error': (
            'The brain refused the request: it needs the header '
            '"Authorization: Bearer <token>" with the token Whelk Server holds for this '
            'product. Call the brain through Whelk Server, or read the token from the '
            "product's server.token file."
        )
    }
).encode()


class BearerGate:
    """ASGI middleware that admits a request only with the expected bearer token."""

    def __init__(self, app, token: str):
        self.app = app
        self.expected = f'Bearer {token}'.encode()

    async def __call__(self, scope, receive, send):
        if scope['type'] in ('http', 'websocket') and not self._admits(scope):
            await self._refuse(scope, send)
            return
        await self.app(scope, receive, send)

    def _admits(self, scope) -> bool:
        if scope['type'] == 'http' and scope['path'] in OPEN_PATHS:
            return True
        presented = [value for name, value in scope['headers'] if name == b'authorization']
        return len(presented) == 1 and hmac.compare_digest(presented[0], self.expected)

    async def _refuse(self, scope, send):
        if scope['type'] == 'websocket':
            await send({'type': 'websocket.close', 'code': 1008})
            return
        await send(
            {
                'type': 'http.response.start',
                'status': 401,
                'headers': [
                    (b'content-type', b'application/json'),
                    (b'www-authenticate', b'Bearer'),
                    (b'content-length', str(len(REFUSAL)).encode()),
                ],
            }
        )
        await send({'type': 'http.response.body', 'body': REFUSAL})


def required_token() -> str:
    token = os.environ.get('WHELK_SERVER_TOKEN', '')
    if not token:
        raise SystemExit(
            'WHELK_SERVER_TOKEN is not set, so the brain will not open its port. '
            'Run the brain as a Whelk Server product with reach_server, or set the variable.'
        )
    return token


async def serve(mcp) -> None:
    import uvicorn

    mcp.settings.streamable_http_path = '/mcp/'
    app = BearerGate(mcp.streamable_http_app(), required_token())
    config = uvicorn.Config(
        app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
    )
    await uvicorn.Server(config).serve()
