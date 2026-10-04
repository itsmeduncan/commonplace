#!/usr/bin/env python3
"""Build-time patch: process one episode at a time across ALL groups.

On FalkorDB, graphiti keeps each `group_id` in its own graph, and `Graphiti.add_episode`
selects that graph by REBINDING the client's shared driver (`self.driver =
self.driver.clone(database=group_id)`) for the whole extraction. Upstream's QueueService
runs one worker per group, so two groups ingest at once and race on that shared driver:
an episode for group A is written into group B's graph. Reproduced on mcp-v1.1.0 /
graphiti-core 0.30.1 (brain/test/smoke.sh): a `whelk-team` fact landed in the
`whelk-finance` graph. That breaks per-group isolation, which the Whelk brain uses for
access labels, and any agent that scopes writes with `group_id`.

The fix is one asyncio.Lock in QueueService around each episode's processing, so only
one `add_episode` holds the driver at a time. Per-group queues, ordering and the
backpressure patch are unchanged. Extraction is model-bound and SEMAPHORE_LIMIT is 1 on
these stacks already, so the cost is small; a burst across many groups now drains
serially instead of interleaving.

Search is unaffected: graphiti's search paths take a call-scoped driver clone per group.

Idempotent; FAILS THE BUILD if an anchor is missing (CI's docker build exercises this).
"""
import sys
from pathlib import Path

target = Path('/app/mcp/src/services/queue_service.py')
src = target.read_text()

if '_ingest_lock' in src:
    print('serial-ingest patch already applied — nothing to do')
    sys.exit(0)


def replace_once(text: str, anchor: str, replacement: str, what: str) -> str:
    count = text.count(anchor)
    if count != 1:
        sys.exit(f'PATCH FAILED: expected exactly 1 match for {what}, found {count}')
    return text.replace(anchor, replacement, 1)


src = replace_once(
    src,
    '        self._graphiti_client: Any = None\n',
    '        self._graphiti_client: Any = None\n'
    '        # One episode at a time across all groups: add_episode rebinds the shared\n'
    '        # FalkorDB driver to its group, so concurrent groups would cross-write.\n'
    '        self._ingest_lock = asyncio.Lock()\n',
    'the QueueService.__init__ client field',
)

src = replace_once(
    src,
    '                    await process_func()\n',
    '                    async with self._ingest_lock:\n'
    '                        await process_func()\n',
    'the queue worker process_func call',
)

target.write_text(src)
print('serial-ingest patch applied OK')
