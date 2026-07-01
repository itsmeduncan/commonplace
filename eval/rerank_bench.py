#!/usr/bin/env python3
"""Reranker benchmark: does a candidate reranker beat the current RRF ordering?

The MCP search is hardcoded to NODE_HYBRID_SEARCH_RRF. Adding a reranker is a real
image patch that fights this project's tenets (no LLM in the query path; the MCP
containers have no GPU), so the roadmap says: only do it with a benchmark proving it
beats RRF. This is that benchmark.

For each query in eval/queries.yaml it over-fetches N candidates (which come back in
RRF order), grades each candidate as relevant iff it contains one of the query's
`expect` substrings, and scores the ordering with rank-aware metrics — MRR, recall@k,
nDCG@k. With `--reranker` it re-orders the SAME candidates and reports the head-to-head
delta and a verdict. No reranker (default) just prints the RRF baseline — the number a
reranker has to beat.

This ships NO model and adds no runtime dependency: RRF is measured live over MCP, and
a reranker is a plug-in `rerank(query, candidates) -> reordered` callable you point at
with `--reranker dotted.module:function`. A trivial built-in `lexical` reranker (query/
fact token overlap) is included as a runnable reference — a floor, not the proposed
production reranker.

Usage:
    pip install "mcp>=1.0" pyyaml
    # RRF baseline only:
    python eval/rerank_bench.py --url http://host:8000/mcp/ --token "$PERSONAL_TOKEN"
    # Compare a candidate reranker against RRF:
    python eval/rerank_bench.py --url http://host:8000/mcp/ --reranker lexical
    python eval/rerank_bench.py --url http://host:8000/mcp/ --reranker mypkg.rr:rerank

    # Offline check of the metric math (no server needed):
    python eval/rerank_bench.py --self-test
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import sys
from pathlib import Path


# ---- rank-aware metrics (pure; unit-tested via --self-test) ----

def mrr(rels: list[bool]) -> float:
    """Reciprocal rank of the first relevant item (0 if none)."""
    for i, r in enumerate(rels, start=1):
        if r:
            return 1.0 / i
    return 0.0


def recall_at_k(rels: list[bool], k: int) -> float:
    """Fraction of the candidate set's relevant items found in the top k.

    Measured within the retrieved candidate set (we can't know the whole graph), so
    it's a fair before/after comparison when a reranker reorders the same candidates.
    """
    total = sum(rels)
    if total == 0:
        return 0.0
    return sum(rels[:k]) / total


def ndcg_at_k(rels: list[bool], k: int) -> float:
    """nDCG@k with binary gains."""
    def dcg(seq: list[bool]) -> float:
        # rank i (1-based): gain / log2(i+1)
        from math import log2
        return sum((1.0 if r else 0.0) / log2(i + 1) for i, r in enumerate(seq[:k], start=1))

    ideal = sorted(rels, reverse=True)
    idcg = dcg(ideal)
    return 0.0 if idcg == 0 else dcg(rels) / idcg


# ---- built-in reference reranker ----

def _tokens(text: str) -> set[str]:
    return {t for t in "".join(c if c.isalnum() else " " for c in text.lower()).split() if len(t) > 2}


def lexical(query: str, candidates: list[str]) -> list[str]:
    """Reference reranker: sort by query/candidate token overlap (stable). A floor."""
    q = _tokens(query)
    return sorted(candidates, key=lambda c: len(q & _tokens(c)), reverse=True)


def load_reranker(spec: str):
    """Resolve --reranker: the built-in name 'lexical' or a 'module.path:function'."""
    if spec == "lexical":
        return lexical
    if ":" not in spec:
        sys.exit(f"--reranker must be 'lexical' or 'module.path:function', got {spec!r}")
    mod_name, func_name = spec.split(":", 1)
    try:
        return getattr(importlib.import_module(mod_name), func_name)
    except (ImportError, AttributeError) as e:
        sys.exit(f"Could not load reranker {spec!r}: {e}")


# ---- scoring ----

def _rels(candidates: list[str], expect: list[str]) -> list[bool]:
    exp = [e.lower() for e in expect]
    return [any(e in c.lower() for e in exp) for c in candidates]


def _score(rels: list[bool], k: int) -> dict:
    return {"mrr": mrr(rels), f"recall@{k}": recall_at_k(rels, k), f"ndcg@{k}": ndcg_at_k(rels, k)}


def _mean(dicts: list[dict]) -> dict:
    if not dicts:
        return {}
    return {key: sum(d[key] for d in dicts) / len(dicts) for key in dicts[0]}


def _candidate_lines(result) -> list[str]:
    lines: list[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text:
            lines.extend(line for line in text.splitlines() if line.strip())
    return lines


async def run(url, token, queries, n_candidates, k, reranker) -> None:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    base_scores, rr_scores = [], []
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for case in queries:
                q = case["query"]
                expect = case.get("expect", [])
                result = await session.call_tool(
                    "search_memory_facts", {"query": q, "max_facts": n_candidates}
                )
                candidates = _candidate_lines(result)
                base = _score(_rels(candidates, expect), k)
                base_scores.append(base)
                line = f"{q}\n    RRF     " + "  ".join(f"{m}={v:.3f}" for m, v in base.items())
                if reranker:
                    reordered = reranker(q, list(candidates))
                    rr = _score(_rels(reordered, expect), k)
                    rr_scores.append(rr)
                    line += "\n    rerank  " + "  ".join(f"{m}={v:.3f}" for m, v in rr.items())
                print(line)

    print("\n=== mean over", len(queries), "queries ===")
    base_mean = _mean(base_scores)
    print("RRF baseline:  " + "  ".join(f"{m}={v:.3f}" for m, v in base_mean.items()))
    if reranker:
        rr_mean = _mean(rr_scores)
        print("reranked:      " + "  ".join(f"{m}={v:.3f}" for m, v in rr_mean.items()))
        dmrr = rr_mean["mrr"] - base_mean["mrr"]
        verdict = "BEATS RRF" if dmrr > 0 else ("ties RRF" if dmrr == 0 else "WORSE than RRF")
        print(f"\nMRR delta: {dmrr:+.3f} — reranker {verdict}.")
        print("Only ship a reranker image patch if a real candidate clears RRF by a"
              " margin worth the CPU cost + dependency (see docs/ROADMAP note / issue #10).")


def self_test() -> None:
    # first item relevant -> MRR 1; relevant at rank 3 -> 1/3
    assert mrr([True, False]) == 1.0
    assert abs(mrr([False, False, True]) - 1 / 3) < 1e-9
    assert mrr([False, False]) == 0.0
    # 2 relevant total, 1 in top-1 -> recall@1 = 0.5; both in top-2 -> 1.0
    assert recall_at_k([True, False, True], 1) == 0.5
    assert recall_at_k([True, True, False], 2) == 1.0
    assert recall_at_k([False, False], 2) == 0.0
    # perfect order -> nDCG 1; reversed (relevant last) -> < 1; none -> 0
    assert ndcg_at_k([True, False, False], 3) == 1.0
    assert ndcg_at_k([False, False, True], 3) < 1.0
    assert ndcg_at_k([False, False], 2) == 0.0
    # lexical reranker pulls the token-overlapping candidate to the front
    out = lexical("falkordb database", ["nothing here", "the falkordb database is used"])
    assert out[0] == "the falkordb database is used"
    print("self-test OK")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="MCP endpoint, e.g. http://host:8000/mcp/")
    ap.add_argument("--token", default=None, help="Bearer token for the gateway (per-tier)")
    ap.add_argument("--queries", type=Path, default=Path(__file__).with_name("queries.yaml"))
    ap.add_argument("--candidates", type=int, default=25, help="Candidates to over-fetch per query")
    ap.add_argument("--k", type=int, default=10, help="Cutoff for recall@k / ndcg@k")
    ap.add_argument("--reranker", default=None, help="'lexical' or 'module.path:function'")
    ap.add_argument("--self-test", action="store_true", help="Check the metric math offline and exit")
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return
    if not args.url:
        ap.error("--url is required (or use --self-test)")

    try:
        import yaml
    except ImportError:
        sys.exit("Missing deps. Install:  pip install 'mcp>=1.0' pyyaml")
    queries = (yaml.safe_load(args.queries.read_text()) or {}).get("queries", [])
    if not queries:
        sys.exit(f"No queries in {args.queries}")
    reranker = load_reranker(args.reranker) if args.reranker else None
    asyncio.run(run(args.url, args.token, queries, args.candidates, args.k, reranker))


if __name__ == "__main__":
    main()
