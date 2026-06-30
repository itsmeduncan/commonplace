#!/usr/bin/env python3
"""Build-time patch: allow non-localhost Host headers on the Graphiti MCP HTTP transport.

The MCP SDK's FastMCP auto-enables DNS-rebinding protection at construction time with
`allowed_hosts` limited to localhost (it decides this before the server later switches the
bind host to 0.0.0.0). FastMCP then passes that localhost-only TransportSecuritySettings
object *explicitly* into its pydantic Settings, so the FASTMCP_ env vars cannot override it.
The result: remote clients (LAN IP or Tailscale MagicDNS) get `HTTP 421 Invalid Host header`.

This stack is tailnet/LAN-only and is consumed by agents (Claude Code, Pi), not browsers, so
the DNS-rebinding threat model does not apply. We disable that protection by editing the baked
server source. The patch is idempotent and FAILS THE BUILD if its anchor points are missing
(so a future image revision can't silently ship an unpatched, unreachable server).

To tighten instead of disabling, replace the construction below with:
    TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["localhost:*", "127.0.0.1:*", "your-server.your-tailnet.ts.net:*", "<lan-ip>:*"],
    )
"""
import re
import sys
from pathlib import Path

target = Path('/app/mcp/src/graphiti_mcp_server.py')
src = target.read_text()

import_line = 'from mcp.server.transport_security import TransportSecuritySettings'
if import_line not in src:
    src, n = re.subn(
        r'from mcp\.server\.fastmcp import FastMCP',
        'from mcp.server.fastmcp import FastMCP\n' + import_line,
        src,
        count=1,
    )
    if n != 1:
        sys.exit('PATCH FAILED: could not find the FastMCP import to anchor on')

if 'transport_security=TransportSecuritySettings' not in src:
    src, n = re.subn(
        r"mcp = FastMCP\(\s*'Graphiti Agent Memory',\s*instructions=GRAPHITI_MCP_INSTRUCTIONS,\s*\)",
        (
            "mcp = FastMCP(\n"
            "    'Graphiti Agent Memory',\n"
            '    instructions=GRAPHITI_MCP_INSTRUCTIONS,\n'
            '    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),\n'
            ')'
        ),
        src,
        count=1,
    )
    if n != 1:
        sys.exit("PATCH FAILED: could not find the FastMCP('Graphiti Agent Memory', ...) construction")

target.write_text(src)
print('transport_security patch applied OK')
