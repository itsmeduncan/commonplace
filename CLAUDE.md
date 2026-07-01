# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`commonplace` is **infrastructure only** — a Docker Compose stack, two MCP config files, a
Dockerfile, and five build-time patches. There is no application source, no test suite, and no lint
step. It deploys a self-hosted, two-tier [Graphiti](https://github.com/getzep/graphiti) knowledge
graph that Claude Code and Pi use as long-term memory over a Tailscale tailnet.

**Read `README.md` first** — it is the real documentation. It contains the architecture diagram, the
endpoint/graph map, a 15-item "Gotchas" list, and client-config instructions. This file summarizes
only the load-bearing facts and points back to it.

## Deployment model (source of truth lives in two places)

- The **repo** is the source of truth for config. Edit a clone → push → on the host
  `git pull` → `docker compose up -d`.
- **Runtime + secrets** live only on the **host** (a Linux server with Docker, Ollama, and an
  optional consumer NVIDIA GPU) in the repo directory (e.g. `~/commonplace`). Other devices are
  pure clients — they host nothing.
- Secrets are in `.env` on the host only (gitignored; `.dockerignore` also excludes it from the
  build context). `.env.example` is the template. Never commit real values.

## Architecture invariants (don't break these)

- **One FalkorDB, two graphs.** Both MCP instances share one FalkorDB; the graph is selected per
  instance by `FALKORDB_DATABASE` (`commonplace_personal` vs `commonplace_client`). `group_id` does
  **not** select the graph — it only namespaces nodes within one.
- **Two MCP instances, one custom image.** `commonplace-mcp:local` is built locally from
  `zepai/knowledge-graph-mcp:standalone` (see `Dockerfile`) — the upstream `:standalone` image lacks
  the `anthropic` SDK and rejects remote Host headers, so the Dockerfile adds the SDK and runs
  `patch_transport_security.py` (plus `patch_agent_identity.py` → `add_memory` `agent_id`,
  `patch_entity_fields.py` → optional typed entity fields, `patch_content_guard.py` →
  `reject_pattern` tier guard, and `patch_queue_backpressure.py` → `max_queue_size` GPU
  backpressure). Use `:standalone`, never `:latest` (the latter bundles its own
  FalkorDB and can't share one).
- **Offline-first.** Both tiers extract **locally** (`mistral:7b-instruct-q4_0` on the GPU) **by
  default** — no API keys, nothing leaves the box. The **personal tier** (`config/personal.yaml`, host
  `:8000`) is env-switchable to a HOSTED model for non-confidential data: set
  `PERSONAL_LLM_PROVIDER=anthropic` / `PERSONAL_LLM_MODEL=claude-haiku-4-5` / `PERSONAL_SEMAPHORE_LIMIT=5`
  / `ANTHROPIC_API_KEY` in `.env` (both provider blocks always exist; `provider` picks one). The
  **client tier** (`config/client.yaml`, host `:8001`) is always local — confidential data never
  leaves the box. Concurrency: `SEMAPHORE_LIMIT` defaults to 1 (GPU-bound); raise the personal tier to
  5 if you switch it to hosted. Both env-overridable in `docker-compose.yml`. Optional GPU
  backpressure: set `graphiti.max_queue_size` and `add_memory` refuses new episodes once that many are
  pending (via `patch_queue_backpressure.py`); 0 = unbounded (default).
- **Gateway fronts both tiers.** The `gateway` service (Caddy, `gateway/Caddyfile`) owns host ports
  `:8000`/`:8001`; the MCP containers are internal-only (`expose`, no host ports). It enforces
  **per-tier bearer auth** (`PERSONAL_TOKEN`/`CLIENT_TOKEN`) — separate tokens = tier isolation — and
  emits JSON access logs (audit) + Prometheus metrics (`:9180`, host-local). Clients must send
  `Authorization: Bearer <token>`. Optional defense-in-depth: set `graphiti.reject_pattern` (a regex)
  in a tier's config and `add_memory` refuses matching content (payload-level guard, via
  `patch_content_guard.py`) — e.g. the personal tier rejecting confidential-tagged writes.
- **Shared embedder.** Both tiers use Ollama `nomic-embed-text` (768-dim). Do **not** change the
  embedder on only one tier — vectors from different embedders are not comparable.
- **MCP path has a trailing slash: `/mcp/`** (FastMCP default, not configurable). FalkorDB UI is on
  `:3000`; FalkorDB `:6379` binds to `127.0.0.1` only.
- Ollama runs on the host, so each MCP service needs `extra_hosts: host.docker.internal:host-gateway`
  and an `api_url` of `http://host.docker.internal:11434/v1`.

## Config quirks that look like bugs but aren't

These trip up every edit — full explanations are in README §Gotchas:

- The Anthropic tier **requires an explicit numeric `llm.temperature`** (e.g. `0.0`); a null value
  makes the API 400 and silently stalls all personal-tier ingestion.
- Anthropic model id is the **bare alias `claude-haiku-4-5`** — `-latest` 404s on the Anthropic API.
- To use Ollama, set `provider: "openai"` with a non-OpenAI `api_url` (the server auto-selects its
  generic client). There is no `openai_generic` provider and no `small_model` setting.
- Each tier needs a **dummy `OPENAI_API_KEY`** (set in compose) because graphiti-core builds a default
  OpenAI reranker at init even though the search path (RRF) never calls it.
- graphiti reads the OpenAI-compatible base URL from `OPENAI_API_URL`; the reranker reads
  `OPENAI_BASE_URL`. Two different names for two different clients.

## Memory model & tooling

- **Ontology lives in config.** Each tier's `config/*.yaml` defines `graphiti.entity_types` (`name` +
  `description`, so the description IS the extraction instruction). An entity may also declare optional
  typed `fields:` (`name`/`type`/`description`; `type` ∈ str|int|float|bool, default str) — enabled by
  `patch_entity_fields.py`. Fields are always Optional so the weak local model is never forced to fill
  one. Edit these to tune what gets captured; keep the tiers' shared types aligned.
- **Agent behavior is documented, not coded.** `docs/memory-protocol.md` is the read/write contract
  (search-first, write durable facts, **never cross tiers**, cite-back). Change it to change how
  agents use memory.
- **Tooling:** `scripts/graph_stats.sh` (write counts), `scripts/mcp_activity.sh` (read counts from
  gateway logs), `scripts/recall.py` (token-budgeted recall), `scripts/contradictions.sh` (superseded
  facts), `scripts/compact_episodes.sh` (prune old `:Episodic` snippets, keep facts — report-only
  until `--apply`), `scripts/backup.sh` / `restore.sh`, `scripts/ingest_markdown.py` (corpus →
  episodes), `eval/run_eval.py` (retrieval recall). The MCP-client scripts take `--token`. MCP verbs:
  `add_memory(name, episode_body, group_id?, source, source_description?, agent_id?)` (`agent_id`
  attributes the write to an agent via `source_description` — added by `patch_agent_identity.py`),
  `search_memory_facts(query, max_facts)`, `search_nodes(query, entity_types?)`.
- **Deferred work** (local reranker) is
  tracked as [GitHub issues](https://github.com/itsmeduncan/commonplace/issues) — those need an image
  patch, not config. Read/auth/metrics/digest-pin shipped via the gateway + Dockerfile.

## Commands (run on the host, from the repo directory, e.g. `~/commonplace`)

Redeploy is wrapped by `scripts/commonplace update` (pull → `--build` → `--force-recreate` the
config-sensitive services; `--reset` hard-resets to origin/main after a force-push). Secret rotation
is `scripts/commonplace rotate <falkordb|personal-token|client-token|tokens|all>` — regenerates the
secret in `.env` (backing it up to a gitignored `.env.bak.<stamp>`) and recreates only the affected
services; rotating a bearer token means every client must be updated or it 401s. Raw compose:

```bash
docker compose up -d                              # bring the stack up (after .env is filled)
docker compose ps                                 # status / health
docker compose logs -f mcp-personal               # or mcp-client, falkordb
docker compose up -d --force-recreate mcp-client  # apply a config/*.yaml change to one instance
docker compose up -d --build                      # rebuild after editing Dockerfile or the patch
docker compose down                               # stop, KEEP data (falkordb_data volume)
docker compose down -v                            # stop AND delete the graphs
```

Editing a `config/*.yaml` does not hot-reload — `--force-recreate` the affected instance. Editing the
`Dockerfile` or any `patch_*.py` requires `--build`.

Health check from a client (tailnet or LAN):

```bash
# 401 without a token (gateway auth working); 307 with the right tier token.
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer $PERSONAL_TOKEN" http://your-server.your-tailnet.ts.net:8000/mcp/
```

Backup/restore is via `scripts/backup.sh` / `scripts/restore.sh` (tarball of FalkorDB's data dir,
RDB+AOF; the dir is `/var/lib/falkordb/data`, where the `falkordb_data` volume mounts) — see README §Backup.

## Access / networking

- The **gateway** owns host ports `:8000`/`:8001` (the MCP containers are internal-only), reached
  over the tailnet at `http://your-server.your-tailnet.ts.net:8000/mcp/` and `:8001/mcp/` (also
  LAN-reachable; **not** public). Every request needs `Authorization: Bearer <tier-token>`.
  Prometheus metrics are on `:9180` (host-local only).
- The transport patch disables FastMCP's DNS-rebinding protection — safe here because the tailnet is
  the trust boundary and clients are agents, not browsers. To tighten, set explicit `allowed_hosts`
  (see the patch's docstring) instead of disabling.
- **Host-networking caveat:** keep the host single-homed (one IPv4 on its primary interface). A
  second address (e.g. a static IP plus a stray DHCP lease) makes Tailscale advertise two WireGuard
  endpoints and the tunnel flaps, which black-holes TCP over MagicDNS while LAN and `tailscale ping`
  still appear to work. On Ubuntu this usually comes from cloud-init re-enabling DHCP — disable its
  network management (`/etc/cloud/cloud.cfg.d/99-disable-network-config.cfg`). See README §Networking.
