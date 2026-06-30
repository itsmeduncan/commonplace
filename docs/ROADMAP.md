# commonplace — hardening & maturity roadmap

The path from "a memory store exists" to "agents reflexively leverage it, safely." Sequenced by
dependency and leverage. Checked items have shipped.

## Phase 1 — Foundation (config + docs)

- [x] **Domain ontology** per tier (`graphiti.entity_types`). Constrains extraction; the biggest
      single lever, and it helps the weak local model most.
- [x] **Agent memory protocol** (`docs/memory-protocol.md`) — read/write contract, tier safety,
      cite-back.
- [x] **Write observability** (`scripts/graph_stats.sh`) — node/edge/episode counts per tier.
- [x] **Backup/restore** (`scripts/backup.sh`, `scripts/restore.sh`).
- [x] **Corpus ingestion** (`scripts/ingest_markdown.py`).
- [x] **Retrieval eval** (`eval/`).

## Phase 2 — Measurable & precise

- [x] **Read-side metrics & access logging.** The `gateway` (Caddy) fronts both tiers with JSON
      access logging (an audit trail) and a Prometheus endpoint (`:9180`, host-local). `scripts/
    mcp_activity.sh` summarizes reads/writes per tier — finally answers "is Claude Code actually
      searching before it answers?"
- [x] **Token-budgeted retrieval (client-side).** `scripts/recall.py` over-fetches then trims to a
      token budget. A _server-side_ token-budget mode is still open (would need an image patch).
- [ ] **Local cross-encoder reranker.** Still deferred — and deliberately. Search is hardcoded to
      `NODE_HYBRID_SEARCH_RRF` (graphiti_mcp_server.py:451) and the MCP config exposes no reranker
      provider, so this needs an image patch. The clean options conflict with the project's tenets:
      an LLM reranker (via Ollama) puts an LLM back in the query path (the README explicitly forbids
      this); a BGE cross-encoder adds `sentence-transformers` + a model download and would rerank on
      CPU (the MCP containers have no GPU passthrough; only host Ollama does). Worth doing, but only
      with a benchmark to prove it beats RRF — tracked, not rushed.

## Phase 3 — Safety & isolation

- [x] **Per-client auth.** Gateway requires `Authorization: Bearer <token>`; unauthenticated
      requests get 401.
- [x] **Tier isolation by auth.** Separate `PERSONAL_TOKEN` / `CLIENT_TOKEN`: a client holding only
      the client token cannot reach the personal (hosted-extraction) endpoint at all. Stronger than
      the convention-only rule in the memory protocol, without fragile payload inspection.
- [x] **Audit log.** The gateway access log records who/when/which tier (JSON, in container logs).
- [x] **Pin the base image by digest** (`Dockerfile`). Dependabot's docker ecosystem proposes bumps;
      CI's build verifies the patch still applies.
- [ ] **Payload-level tier guard.** Belt-and-suspenders over token isolation: reject confidential-
      tagged content on the personal endpoint by inspecting `add_memory` bodies. Needs MCP-protocol
      parsing in the proxy — deferred.
- [ ] **Secret rotation + queue backpressure.** Rotating `FALKORDB_PASSWORD` / `ANTHROPIC_API_KEY` /
      the bearer tokens is now a documented op; GPU backpressure (`SEMAPHORE_LIMIT=1`) is server-side
      and still open.

## Phase 4 — Coherence & quality

- [x] **Per-project namespacing.** `add_memory` / ingestion accept `group_id`; the protocol now tells
      agents to scope project memory with it.
- [x] **Contradiction surfacing.** `scripts/contradictions.sh` lists facts the graph marked
      superseded (`invalid_at`), so resolved contradictions are reviewable.
- [ ] **Per-agent identity.** `user_id` is hardcoded `mcp_user`; attributing writes to a specific
      agent needs a server change (the `add_memory` tool exposes no `user_id`).
- [ ] **Episode compaction.** Periodically fold old episodes into stable facts.
- [ ] **Richer ontology (typed fields).** The config route is `name` + `description` only; typed
      fields (like the built-in `Requirement.project_name`) need code-defined entity types in a patch.

## Notes

"Needs an image patch" = a build-time patch to the upstream MCP server (same mechanism as
`patch_transport_security.py`), so it's its own reviewable change, not a config tweak.
