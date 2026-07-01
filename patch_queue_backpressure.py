#!/usr/bin/env python3
"""Build-time patch: GPU queue backpressure on add_memory.

Extraction is GPU-bound and processed by ONE sequential worker per group_id
(SEMAPHORE_LIMIT=1). The processing queue is an unbounded asyncio.Queue, so a client
that calls add_memory faster than the GPU extracts will grow the queue — and process
memory — without limit, with no signal back to the client that the system is saturated.

This adds optional backpressure: with `graphiti.max_queue_size` set, add_memory refuses a
new episode once that group's pending queue is at capacity, returning an actionable
"retry shortly" error instead of silently enqueuing. It reuses the server's existing
QueueService.get_queue_size(), so only two baked files change:
  - config/schema.py         — add GraphitiAppConfig.max_queue_size (default 0 = unbounded)
  - graphiti_mcp_server.py    — reject in add_memory when the queue is full

Backward-compatible: default 0 keeps today's unbounded behavior. Note that enabling it
will make a large bulk ingest (e.g. scripts/ingest_markdown.py) reject once saturated —
that is the point; pace the ingest or leave the cap at 0 while backfilling.

Idempotent; FAILS THE BUILD if any anchor is missing (CI's docker build exercises this).

Tracks: https://github.com/itsmeduncan/commonplace/issues/12
"""
import sys
from pathlib import Path

MCP_ROOT = Path('/app/mcp/src')


def replace_once(text: str, anchor: str, replacement: str, what: str) -> str:
    n = text.count(anchor)
    if n != 1:
        sys.exit(f'PATCH FAILED: expected exactly 1 match for {what}, found {n}')
    return text.replace(anchor, replacement, 1)


# ---- 1) config/schema.py: add an optional queue cap ----
schema_path = MCP_ROOT / 'config' / 'schema.py'
schema = schema_path.read_text()

if 'max_queue_size' not in schema:
    schema = replace_once(
        schema,
        '    entity_types: list[EntityTypeConfig] = Field(default_factory=list)\n',
        '    entity_types: list[EntityTypeConfig] = Field(default_factory=list)\n'
        '    max_queue_size: int = Field(\n'
        '        default=0,\n'
        "        description='Max pending episodes per group before add_memory refuses (0 = unbounded).',\n"
        '    )\n',
        'the GraphitiAppConfig.entity_types anchor in schema.py',
    )
    schema_path.write_text(schema)
    print('queue-backpressure patch: schema.py OK')
else:
    print('queue-backpressure patch: schema.py already patched')


# ---- 2) graphiti_mcp_server.py: reject when the group's queue is full ----
gms_path = MCP_ROOT / 'graphiti_mcp_server.py'
gms = gms_path.read_text()

if 'max_queue_size' not in gms:
    gms = replace_once(
        gms,
        '        effective_group_id = group_id or config.graphiti.group_id\n',
        '        effective_group_id = group_id or config.graphiti.group_id\n'
        '\n'
        '        # GPU queue backpressure: refuse new episodes when this group\'s ingestion\n'
        '        # queue is already at capacity, so a flood can\'t grow memory unbounded under\n'
        '        # the GPU-bound sequential worker. 0 = unbounded (default).\n'
        '        max_queue_size = config.graphiti.max_queue_size\n'
        '        if max_queue_size and queue_service.get_queue_size(effective_group_id) >= max_queue_size:\n'
        '            return ErrorResponse(\n'
        '                error=(\n'
        "                    f'Queue full for group {effective_group_id} ({max_queue_size} episodes '\n"
        "                    'pending) — retry shortly. Extraction is GPU-bound and runs sequentially.'\n"
        '                )\n'
        '            )\n',
        'the effective_group_id anchor in add_memory',
    )
    gms_path.write_text(gms)
    print('queue-backpressure patch: graphiti_mcp_server.py OK')
else:
    print('queue-backpressure patch: graphiti_mcp_server.py already patched')
