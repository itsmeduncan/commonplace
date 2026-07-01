#!/usr/bin/env python3
"""Build-time patch: add per-agent identity to the `add_memory` MCP tool.

Upstream `add_memory` (mcp-v1.0.2) has no way to record WHICH agent wrote an episode —
every write is anonymous. graphiti's `EpisodicNode` has no dedicated author field, and
`group_id` is already spoken for (it selects the graph / namespaces projects), so we
attribute writes through `source_description`, which is persisted on the episode and is
searchable. This keeps the change additive and backward-compatible: `agent_id` is an
optional new parameter, and omitting it reproduces the current behavior exactly.

The patch edits the baked server source (`/app/mcp/src/graphiti_mcp_server.py`). It is
idempotent and FAILS THE BUILD if any anchor is missing, so a future image revision can't
silently ship an unpatched (identity-less) server. CI's `docker build` exercises this.

Tracks: https://github.com/itsmeduncan/commonplace/issues/13
"""
import sys
from pathlib import Path

target = Path('/app/mcp/src/graphiti_mcp_server.py')
src = target.read_text()

if 'agent_id' in src:
    print('agent-identity patch already applied — nothing to do')
    sys.exit(0)


def replace_once(text: str, anchor: str, replacement: str, what: str) -> str:
    count = text.count(anchor)
    if count != 1:
        sys.exit(f'PATCH FAILED: expected exactly 1 match for {what}, found {count}')
    return text.replace(anchor, replacement, 1)


# 1) Add the optional parameter to the tool signature.
src = replace_once(
    src,
    "    uuid: str | None = None,\n) -> SuccessResponse | ErrorResponse:",
    "    uuid: str | None = None,\n"
    "    agent_id: str | None = None,\n"
    ") -> SuccessResponse | ErrorResponse:",
    'the add_memory signature',
)

# 2) Document it in the tool docstring (this is the description agents actually see).
src = replace_once(
    src,
    '        uuid (str, optional): Optional UUID for the episode\n',
    '        uuid (str, optional): Optional UUID for the episode\n'
    '        agent_id (str, optional): Identifier of the agent writing this memory. Recorded in\n'
    '                                 the episode\'s source_description for attribution/audit.\n',
    'the add_memory docstring',
)

# 3) Fold agent_id into source_description before the episode is queued.
src = replace_once(
    src,
    '        # Use the provided group_id or fall back to the default from config\n'
    '        effective_group_id = group_id or config.graphiti.group_id\n',
    '        # Use the provided group_id or fall back to the default from config\n'
    '        effective_group_id = group_id or config.graphiti.group_id\n'
    '\n'
    '        # Per-agent identity: attribute the write to a specific agent. graphiti has no\n'
    '        # author field, so we record it in source_description (persisted + searchable).\n'
    '        effective_source_description = (\n'
    "            f'[agent:{agent_id}] {source_description}'.strip()\n"
    '            if agent_id\n'
    '            else source_description\n'
    '        )\n',
    'the effective_group_id anchor',
)

# 4) Pass the attributed description through to the queue.
src = replace_once(
    src,
    '            source_description=source_description,\n',
    '            source_description=effective_source_description,\n',
    'the queue_service.add_episode source_description argument',
)

target.write_text(src)
print('agent-identity patch applied OK')
