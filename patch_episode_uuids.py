#!/usr/bin/env python3
"""Build-time patch: let `get_episodes` fetch episodes by UUID.

A fact (an entity edge) names the episodes it came from in its `episodes` list. Upstream
`get_episodes` (mcp-v1.1.0) can only list the newest episodes of a group, so a client
cannot turn those UUIDs back into the source of a fact. This adds an optional `uuids`
parameter: with it, `get_episodes` returns exactly those episodes, so a client can show
where each fact came from.

FalkorDB keeps each group in its own graph (graphiti clones the driver per `group_id`),
so the lookup runs once per requested group against that group's graph and merges the
results. An episode in a group the caller did not ask for never comes back. Without
`group_ids`, the configured default group applies, as it does for the listing path.

Additive and backward-compatible: omitting `uuids` reproduces the current behavior. The
patch is idempotent and FAILS THE BUILD if an anchor is missing (CI's docker build
exercises this).
"""
import sys
from pathlib import Path

target = Path('/app/mcp/src/graphiti_mcp_server.py')
src = target.read_text()

if 'get_episodes_by_uuids' in src:
    print('episode-uuids patch already applied — nothing to do')
    sys.exit(0)


def replace_once(text: str, anchor: str, replacement: str, what: str) -> str:
    count = text.count(anchor)
    if count != 1:
        sys.exit(f'PATCH FAILED: expected exactly 1 match for {what}, found {count}')
    return text.replace(anchor, replacement, 1)


src = replace_once(
    src,
    'async def get_episodes(\n'
    '    group_ids: str | list[str] | None = None,\n'
    '    max_episodes: int = 10,\n'
    ') -> EpisodeSearchResponse | ErrorResponse:\n',
    'async def get_episodes(\n'
    '    group_ids: str | list[str] | None = None,\n'
    '    max_episodes: int = 10,\n'
    '    uuids: list[str] | None = None,\n'
    ') -> EpisodeSearchResponse | ErrorResponse:\n',
    'the get_episodes signature',
)

src = replace_once(
    src,
    '        max_episodes: Maximum number of episodes to return (default: 10)\n'
    '    """\n',
    '        max_episodes: Maximum number of episodes to return (default: 10)\n'
    '        uuids: Optional episode UUIDs (for example the `episodes` of a fact). When set,\n'
    '            only these episodes come back, from the requested groups only.\n'
    '    """\n',
    'the get_episodes docstring',
)

src = replace_once(
    src,
    '        if effective_group_ids:\n'
    '            episodes = await EpisodicNode.get_by_group_ids(\n'
    '                client.driver, effective_group_ids, limit=max_episodes\n'
    '            )\n',
    '        if uuids:\n'
    '            episodes = await get_episodes_by_uuids(\n'
    '                client.driver, effective_group_ids, list(uuids), max_episodes\n'
    '            )\n'
    '        elif effective_group_ids:\n'
    '            episodes = await EpisodicNode.get_by_group_ids(\n'
    '                client.driver, effective_group_ids, limit=max_episodes\n'
    '            )\n',
    'the get_episodes lookup',
)

src = replace_once(
    src,
    '@mcp.tool()\n'
    'async def get_episodes(\n',
    'async def get_episodes_by_uuids(driver, group_ids: list[str], uuids: list[str], limit: int):\n'
    '    """Fetch episodes by UUID from each group\'s graph, keeping only the asked groups."""\n'
    '    from graphiti_core.nodes import EpisodicNode\n'
    '\n'
    '    found = []\n'
    '    for gid in dict.fromkeys(group_ids):\n'
    '        for episode in await EpisodicNode.get_by_uuids(driver.clone(database=gid), uuids):\n'
    '            if episode.group_id == gid:\n'
    '                found.append(episode)\n'
    '    return found[: max(limit, 0)]\n'
    '\n'
    '\n'
    '@mcp.tool()\n'
    'async def get_episodes(\n',
    'the get_episodes tool decorator',
)

target.write_text(src)
print('episode-uuids patch applied OK')
