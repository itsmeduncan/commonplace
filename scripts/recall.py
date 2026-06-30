#!/usr/bin/env python3
"""Token-budgeted recall against a commonplace tier.

`search_memory_facts` is count-based (`max_facts`); agents/humans often want
"the most relevant facts that fit in N tokens" instead. This client-side helper
over-fetches, then trims to a token budget — the cheap-retrieval, page-memory-in
pattern the system is for. (A server-side token-budget mode is a roadmap item;
this covers it from the client without touching the server.)

Usage:
    pip install "mcp>=1.0"
    python scripts/recall.py "what did we decide about auth?" \\
        --url http://your-server.your-tailnet.ts.net:8000/mcp/ \\
        --token "$PERSONAL_TOKEN" --budget 800
"""
from __future__ import annotations

import argparse
import asyncio
import sys

try:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
except ImportError:
    sys.exit("Missing dependency. Install the MCP SDK:  pip install 'mcp>=1.0'")

CHARS_PER_TOKEN = 4  # rough heuristic; avoids a tokenizer dependency


def est_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def _fact_lines(result) -> list[str]:
    lines: list[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            lines.extend(line for line in text.splitlines() if line.strip())
    return lines


async def recall(url: str, token: str | None, query: str, budget: int, over_fetch: int) -> None:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "search_memory_facts", {"query": query, "max_facts": over_fetch}
            )

    used, kept = 0, 0
    for line in _fact_lines(result):
        cost = est_tokens(line)
        if used + cost > budget:
            break
        print(line)
        used += cost
        kept += 1
    print(f"\n— {kept} facts, ~{used}/{budget} tokens —", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", help="What to recall")
    ap.add_argument("--url", required=True, help="MCP endpoint (trailing slash)")
    ap.add_argument("--token", default=None, help="Bearer token for the gateway (per-tier)")
    ap.add_argument("--budget", type=int, default=800, help="Token budget for returned facts")
    ap.add_argument("--over-fetch", type=int, default=25, help="Facts to fetch before trimming")
    args = ap.parse_args()
    asyncio.run(recall(args.url, args.token, args.query, args.budget, args.over_fetch))


if __name__ == "__main__":
    main()
