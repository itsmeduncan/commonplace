#!/usr/bin/env python3
"""Tiny retrieval eval: does the graph return the facts we expect?

Runs each query in eval/queries.yaml against the MCP `search_memory_facts` tool
and checks whether the expected substrings show up in the returned facts. Reports
a per-query pass/fail and an overall recall score. Use it as a regression gate
when you change the ontology, models, or (eventually) add a reranker.

Usage:
    pip install "mcp>=1.0" pyyaml
    python eval/run_eval.py --url http://your-server.your-tailnet.ts.net:8000/mcp/

Exit code is non-zero if any query fails, so it can run in CI against a seeded graph.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

try:
    import yaml
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
except ImportError:
    sys.exit("Missing deps. Install:  pip install 'mcp>=1.0' pyyaml")


def _facts_text(result) -> str:
    """Flatten an MCP tool result into searchable text, however it's shaped."""
    chunks = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            chunks.append(text)
    return "\n".join(chunks).lower()


async def run(url: str, queries: list[dict], max_facts: int) -> int:
    passed = 0
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for case in queries:
                q = case["query"]
                expect = [e.lower() for e in case.get("expect", [])]
                result = await session.call_tool(
                    "search_memory_facts", {"query": q, "max_facts": max_facts}
                )
                haystack = _facts_text(result)
                missing = [e for e in expect if e not in haystack]
                ok = not missing
                passed += ok
                mark = "PASS" if ok else "FAIL"
                print(f"[{mark}] {q}")
                if missing:
                    print(f"        missing: {missing}")
    total = len(queries)
    print(f"\nRecall: {passed}/{total} queries passed")
    return 0 if passed == total else 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="MCP endpoint, e.g. http://host:8000/mcp/")
    ap.add_argument("--queries", type=Path, default=Path(__file__).with_name("queries.yaml"))
    ap.add_argument("--max-facts", type=int, default=10)
    args = ap.parse_args()
    data = yaml.safe_load(args.queries.read_text())
    queries = data.get("queries", [])
    if not queries:
        sys.exit(f"No queries in {args.queries}")
    sys.exit(asyncio.run(run(args.url, queries, args.max_facts)))


if __name__ == "__main__":
    main()
