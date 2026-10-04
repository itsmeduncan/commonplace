#!/usr/bin/env python3
"""Build-time patch (brain image only): serve /mcp/ behind the Whelk bearer gate.

Replaces the HTTP transport's `await mcp.run_streamable_http_async()` with
`whelk_bearer.serve(mcp)`, which runs the same Starlette app under the same uvicorn
settings, wrapped in a constant-time bearer check against WHELK_SERVER_TOKEN. See
brain/whelk_bearer.py. The module is copied next to the server source, which main.py
already puts on sys.path.

Idempotent; FAILS THE BUILD if the anchor is missing, so an upstream bump cannot ship a
brain whose port is open to every local process.
"""
import sys
from pathlib import Path

target = Path('/app/mcp/src/graphiti_mcp_server.py')
src = target.read_text()

if 'whelk_bearer' in src:
    print('bearer patch already applied — nothing to do')
    sys.exit(0)

def replace_once(text: str, anchor: str, replacement: str, what: str) -> str:
    count = text.count(anchor)
    if count != 1:
        sys.exit(f'PATCH FAILED: expected exactly 1 match for {what}, found {count}')
    return text.replace(anchor, replacement, 1)


src = replace_once(
    src,
    '        await mcp.run_streamable_http_async()\n',
    '        from whelk_bearer import serve as serve_with_bearer\n'
    '\n'
    '        await serve_with_bearer(mcp)\n',
    'the HTTP transport run call',
)

src = replace_once(
    src,
    '        await mcp.run_sse_async()\n',
    '        raise SystemExit(\n'
    "            'The brain serves only the HTTP transport, behind its bearer gate. '\n"
    "            'Set server.transport to http.'\n"
    '        )\n',
    'the SSE transport run call',
)

if not Path('/app/mcp/src/whelk_bearer.py').is_file():
    sys.exit('PATCH FAILED: /app/mcp/src/whelk_bearer.py is missing; COPY it before this patch')

target.write_text(src)
print('bearer patch applied OK')
