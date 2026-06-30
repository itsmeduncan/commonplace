# commonplace — hardening & maturity roadmap

This tracks the path from "a memory store exists" to "agents reflexively leverage it, safely."
It's sequenced by dependency and leverage. Phase 1 is implementable purely in this repo; later
phases need an image patch, a new service, or runtime/GPU work, so they're called out honestly
rather than half-shipped.

## Phase 1 — Foundation (this repo, no new services)

- [x] **Domain ontology** per tier (`graphiti.entity_types` in `config/*.yaml`). The single biggest
      lever: constrains extraction (helps the weak local model most) and enables typed
      `search_nodes`. Verified against the server schema (`name` + `description`).
- [x] **Agent memory protocol** (`docs/memory-protocol.md`) — when/how to read/write, tier safety,
      cite-back. This is what converts capability into agent behavior.
- [x] **Write observability** (`scripts/graph_stats.sh`) — node/edge/episode counts per tier as a
      proxy for whether agents are actually capturing.
- [x] **Backup/restore automation** (`scripts/backup.sh`, `scripts/restore.sh`) — scheduled,
      testable, instead of ad-hoc `SAVE`.
- [x] **Corpus ingestion** (`scripts/ingest_markdown.py`) — load an existing markdown corpus (notes
      vault, docs) into a tier so the graph is useful on day one.
- [x] **Retrieval eval skeleton** (`eval/`) — question → expected-facts, to catch regressions when
      models/ontology/reranker change.

## Phase 2 — Make leverage measurable & precise (needs an image patch or a small proxy)

- [ ] **MCP access logging / metrics.** The upstream server logs no tool calls, so reads are
      invisible. Add a thin logging reverse-proxy in front of `:8000`/`:8001` (or patch the server)
      recording `{ts, tier, tool, client, latency, result_size}`. Answers "did Claude Code search
      before answering, and how often?" per client. **Blocked on:** new service or image patch.
- [ ] **Local cross-encoder reranker.** Search is hardcoded to `NODE_HYBRID_SEARCH_RRF`
      (graphiti_mcp_server.py:451). A local reranker (e.g. `bge-reranker` via Ollama) would lift
      top-K precision with zero egress and fits the "GPU does background work" model. **Blocked on:**
      image patch to swap the search recipe + pulling a reranker model on the host.
- [ ] **Token-budgeted retrieval.** `search_memory_facts` is count-based (`max_facts`), not
      token-aware. A token-budget mode lets agents page memory deterministically. **Blocked on:**
      image patch or a client-side wrapper.

## Phase 3 — Safety & isolation hardening

- [ ] **Server-side tier guard.** Today cross-tier safety is convention only (see memory-protocol).
      Enforce at the boundary: the personal endpoint should refuse content tagged confidential, ideally
      via separate per-tier credentials. **Blocked on:** auth proxy / image patch.
- [ ] **Per-client auth + audit log.** No authn today (tailnet = trust boundary). Revocable per-client
      tokens (via `tailscale serve` mTLS or an auth proxy) + an audit trail of who read/wrote which
      tier — important for the confidential tier. **Blocked on:** auth proxy.
- [ ] **Pin the base image by digest.** `zepai/knowledge-graph-mcp:standalone` is a moving tag; CI
      catches a break but a digest pin (+ Dependabot, already configured) makes upgrades deliberate.
- [ ] **Secret rotation + queue backpressure.** Rotate `FALKORDB_PASSWORD`/`ANTHROPIC_API_KEY`;
      ensure a write flood doesn't starve the GPU (`SEMAPHORE_LIMIT=1`).

## Phase 4 — Coherence & quality

- [ ] **Per-agent / per-project identity.** `user_id` is hardcoded `mcp_user`; add per-agent identity
      and `group_id` per project so writes are attributable and filterable.
- [ ] **Contradiction surfacing & compaction.** Graphiti invalidates superseded facts; agents should
      surface contradictions for confirmation and periodically compact old episodes into stable facts.
- [ ] **Richer ontology (typed fields).** The config route supports only `name` + `description`. Typed
      fields (like the built-in `Requirement.project_name`) need code-defined entity types in a patch.

## Notes

"Blocked on: image patch" means it can't honestly ship as config alone — it needs a build-time patch
to the upstream MCP server (the same mechanism as `patch_transport_security.py`) or a sidecar
service. Those are deliberate, reviewable changes, not config tweaks, so they're their own PRs.
