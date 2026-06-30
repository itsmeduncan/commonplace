#!/usr/bin/env python3
"""Ingest a directory of markdown files into a commonplace tier as episodes.

Turns an existing corpus (a notes vault, a docs folder) into graph memory so the
KB is useful on day one instead of starting empty. Each file becomes one or more
episodes via the MCP `add_memory` tool; extraction happens asynchronously on the
server, so this returns quickly and the graph fills in over the following minutes.

Usage:
    pip install "mcp>=1.0"        # the official MCP client SDK
    python scripts/ingest_markdown.py ~/notes \\
        --url http://your-server.your-tailnet.ts.net:8000/mcp/ \\
        --group-id commonplace_personal

Notes:
- Point --url at the PERSONAL or CLIENT endpoint deliberately. Never ingest
  confidential material through the personal (hosted-extraction) endpoint.
- Large files are split on top-level (`# `) and second-level (`## `) headings so
  episodes stay a reasonable size for the extractor.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

try:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
except ImportError:
    sys.exit("Missing dependency. Install the MCP SDK:  pip install 'mcp>=1.0'")

MAX_CHARS = 6000  # rough cap per episode; weak local models choke on huge inputs


def chunk_markdown(text: str) -> list[str]:
    """Split on headings, then hard-wrap any oversized chunk."""
    parts = re.split(r"(?m)^(?=#{1,2} )", text)
    chunks: list[str] = []
    for part in (p.strip() for p in parts if p.strip()):
        if len(part) <= MAX_CHARS:
            chunks.append(part)
        else:
            for i in range(0, len(part), MAX_CHARS):
                chunks.append(part[i : i + MAX_CHARS])
    return chunks


async def ingest(directory: Path, url: str, group_id: str | None, dry_run: bool, token: str | None) -> None:
    files = sorted(directory.rglob("*.md"))
    if not files:
        sys.exit(f"No .md files found under {directory}")
    print(f"Found {len(files)} markdown files under {directory}")

    if dry_run:
        total = sum(len(chunk_markdown(f.read_text(encoding='utf-8', errors='replace'))) for f in files)
        print(f"[dry-run] would create ~{total} episodes. No changes made.")
        return

    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            sent = 0
            for f in files:
                rel = f.relative_to(directory)
                for n, chunk in enumerate(chunk_markdown(f.read_text(encoding='utf-8', errors='replace'))):
                    name = f"{rel}" if n == 0 else f"{rel} [{n + 1}]"
                    args = {
                        "name": name,
                        "episode_body": chunk,
                        "source": "text",
                        "source_description": f"markdown ingest: {rel}",
                    }
                    if group_id:
                        args["group_id"] = group_id
                    await session.call_tool("add_memory", args)
                    sent += 1
                    print(f"  + {name}")
            print(f"\nQueued {sent} episodes. Extraction runs in the background — "
                  f"watch ./scripts/graph_stats.sh for the graph to grow.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("directory", type=Path, help="Directory of .md files to ingest (searched recursively)")
    ap.add_argument("--url", required=True, help="MCP endpoint, e.g. http://host:8000/mcp/ (trailing slash)")
    ap.add_argument("--group-id", default=None, help="Graph to target (defaults to the endpoint's own)")
    ap.add_argument("--token", default=None, help="Bearer token for the gateway (per-tier)")
    ap.add_argument("--dry-run", action="store_true", help="Count episodes without sending anything")
    args = ap.parse_args()
    asyncio.run(ingest(args.directory, args.url, args.group_id, args.dry_run, args.token))


if __name__ == "__main__":
    main()
