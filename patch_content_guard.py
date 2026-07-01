#!/usr/bin/env python3
"""Build-time patch: payload-level tier guard on add_memory.

Tier isolation today is enforced by separate bearer tokens (a client with only the
client token can't reach the personal endpoint). This adds belt-and-suspenders at the
payload level: a tier configured with `graphiti.reject_pattern` refuses any add_memory
whose name / source_description / body matches that regex, so confidential-tagged
material can't land on the personal (hosted-extraction) tier even if a client is
misconfigured with both tokens.

The guard lives IN the server's add_memory tool — not in a proxy — because the server
has already parsed the JSON-RPC payload, so no MCP-protocol parsing (and no risky
streaming reverse-proxy in the request path) is needed. Two baked files are edited:
  - config/schema.py         — add GraphitiAppConfig.reject_pattern (optional)
  - graphiti_mcp_server.py    — reject matching content before the episode is queued

Backward-compatible: no reject_pattern configured → no guard, identical behavior.
Idempotent; FAILS THE BUILD if any anchor is missing (CI's docker build exercises this).

Tracks: https://github.com/itsmeduncan/commonplace/issues/11
"""
import sys
from pathlib import Path

MCP_ROOT = Path('/app/mcp/src')


def replace_once(text: str, anchor: str, replacement: str, what: str) -> str:
    n = text.count(anchor)
    if n != 1:
        sys.exit(f'PATCH FAILED: expected exactly 1 match for {what}, found {n}')
    return text.replace(anchor, replacement, 1)


# ---- 1) config/schema.py: add an optional reject_pattern to the graphiti config ----
schema_path = MCP_ROOT / 'config' / 'schema.py'
schema = schema_path.read_text()

if 'reject_pattern' not in schema:
    schema = replace_once(
        schema,
        '    entity_types: list[EntityTypeConfig] = Field(default_factory=list)\n',
        '    entity_types: list[EntityTypeConfig] = Field(default_factory=list)\n'
        "    reject_pattern: str | None = Field(\n"
        '        default=None,\n'
        "        description='Optional regex; add_memory refuses content matching it (tier guard).',\n"
        '    )\n',
        'the GraphitiAppConfig.entity_types anchor in schema.py',
    )
    schema_path.write_text(schema)
    print('content-guard patch: schema.py OK')
else:
    print('content-guard patch: schema.py already patched')


# ---- 2) graphiti_mcp_server.py: reject matching content early in add_memory ----
gms_path = MCP_ROOT / 'graphiti_mcp_server.py'
gms = gms_path.read_text()

if 'reject_pattern' not in gms:
    gms = replace_once(
        gms,
        "    if graphiti_service is None or queue_service is None:\n"
        "        return ErrorResponse(error='Services not initialized')\n"
        '\n'
        '    try:\n',
        "    if graphiti_service is None or queue_service is None:\n"
        "        return ErrorResponse(error='Services not initialized')\n"
        '\n'
        '    # Payload-level tier guard: on a tier configured with a reject_pattern (the\n'
        '    # personal/hosted tier), refuse content that matches so confidential-tagged\n'
        '    # material never reaches hosted extraction. Belt-and-suspenders over token isolation.\n'
        '    reject_pattern = config.graphiti.reject_pattern\n'
        '    if reject_pattern:\n'
        '        import re as _re\n'
        "        if _re.search(reject_pattern, f'{name}\\n{source_description}\\n{episode_body}'):\n"
        '            return ErrorResponse(\n'
        '                error=(\n'
        "                    'Rejected by tier guard: content matches this tier\\'s reject_pattern. '\n"
        "                    'This endpoint refuses confidential-tagged material — use the local/client tier.'\n"
        '                )\n'
        '            )\n'
        '\n'
        '    try:\n',
        'the add_memory services-check boundary in graphiti_mcp_server.py',
    )
    gms_path.write_text(gms)
    print('content-guard patch: graphiti_mcp_server.py OK')
else:
    print('content-guard patch: graphiti_mcp_server.py already patched')
