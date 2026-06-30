# commonplace

A self-hosted, two-tier [Graphiti](https://github.com/getzep/graphiti) knowledge graph that MCP
clients (for example **Claude Code** and **Pi**) read from and write to over a private
[Tailscale](https://tailscale.com) network. One privacy tier extracts with a hosted model for best
quality; the other extracts entirely on a local GPU so confidential data never leaves the box.

It runs on a single always-on Linux host with Docker and (optionally) a consumer NVIDIA GPU. Your
laptops and other devices are pure clients — they host nothing.

---

## Why two tiers

Knowledge-graph ingestion uses an LLM to extract entities and relationships from text. That
extraction is where your data is exposed to a model. `commonplace` splits memory by who is
allowed to do that extraction:

| Tier                    | Graph                  | Extraction model                   | Where it runs  | Use for                                                                 |
| ----------------------- | ---------------------- | ---------------------------------- | -------------- | ----------------------------------------------------------------------- |
| **personal**            | `commonplace_personal` | Claude Haiku 4.5 (hosted)          | Anthropic API  | your own notes, projects, life — best graph quality, pennies per ingest |
| **client-confidential** | `commonplace_client`   | `mistral:7b-instruct-q4_0` (local) | the host's GPU | confidential, local-only material that must never leave the machine     |

**Retrieval is cheap and private on both tiers.** Search is embeddings + BM25 + graph traversal
with **no LLM in the query path**. The GPU only ever does slow, asynchronous _background_
extraction — query latency is never affected. Slow local extraction is therefore fine.

Both tiers share **one embedder** (Ollama `nomic-embed-text`, 768-dim) and **one FalkorDB**
holding two separate graphs, so the two memories stay isolated but the infrastructure stays simple.

---

## Architecture

```
        Claude Code                       Pi
         (client)                      (client)
                │                              │
                └──────────────┬───────────────┘
                      Tailscale (MagicDNS, tailnet-only)
                               │
        ┌──────────────────────┴───────────────────────┐
        │  your server  (Docker; everything below)      │
        │                                               │
        │  :8000/mcp/  mcp-personal ──┐                 │
        │     LLM: Claude Haiku 4.5   │                 │
        │     (hosted, ANTHROPIC key) │   ┌───────────┐ │
        │     embed: nomic-embed-text─┼──▶│  FalkorDB │ │
        │                             │   │  :6379    │ │
        │  :8001/mcp/  mcp-client ────┤   │ ┌───────┐ │ │
        │     LLM: mistral:7b (LOCAL) │   │ │persnl │ │ │
        │     embed: nomic-embed-text─┘   │ │client │ │ │
        │            │                    │ └───────┘ │ │
        │            ▼ GPU                │  UI :3000 │ │
        │     ┌──────────────┐           └───────────┘ │
        │     │ Ollama :11434│                          │
        │     │ nomic-embed  │  ◀── shared embedder      │
        │     │ mistral:7b   │  ◀── local extraction     │
        │     └──────────────┘                          │
        └───────────────────────────────────────────────┘
```

- **One FalkorDB**, two graphs selected per-instance by `FALKORDB_DATABASE`
  (`commonplace_personal` vs `commonplace_client`).
- **Two Graphiti MCP instances** (`commonplace-mcp:local`, built from
  `zepai/knowledge-graph-mcp:standalone` — see `Dockerfile`), HTTP transport, served at path
  **`/mcp/`** (trailing slash).
- **One shared Ollama embedder** (`nomic-embed-text`, 768-dim) used by _both_ instances. Do not
  mix embedders — vectors from different embedders are not comparable.

### Endpoint / graph map

> Replace `your-server.your-tailnet.ts.net` with your host's Tailscale MagicDNS name throughout
> (run `tailscale status` on the host to find it).

| Tier        | Host endpoint (tailnet)                            | Internal port | Graph (`FALKORDB_DATABASE`) | LLM                        | `SEMAPHORE_LIMIT` |
| ----------- | -------------------------------------------------- | ------------- | --------------------------- | -------------------------- | ----------------- |
| personal    | `http://your-server.your-tailnet.ts.net:8000/mcp/` | 8000          | `commonplace_personal`      | `claude-haiku-4-5`         | 5                 |
| client      | `http://your-server.your-tailnet.ts.net:8001/mcp/` | 8000          | `commonplace_client`        | `mistral:7b-instruct-q4_0` | 1                 |
| FalkorDB    | `127.0.0.1:6379` (host-local only)                 | 6379          | both graphs                 | —                          | —                 |
| FalkorDB UI | `http://your-server.your-tailnet.ts.net:3000`      | 3000          | browse either graph         | —                          | —                 |

---

## Requirements

On the **host**:

- **Docker** with Compose v2.
- **[Ollama](https://ollama.com)** running on the host, serving the shared embedder and the local
  extraction model. The MCP containers reach it over HTTP — the GPU is used by Ollama, not by the
  containers, so no GPU passthrough into Docker is required. A consumer NVIDIA GPU with ~8 GB VRAM
  runs `mistral:7b-instruct-q4_0` comfortably; CPU-only works but local extraction is slow.
- **[Tailscale](https://tailscale.com)** — the MCP endpoints are served over the tailnet, not the
  public internet.
- An **Anthropic API key** — only for the hosted `personal` tier. The `client` tier is fully local
  and needs no key.

On each **client** (laptop, etc.): Tailscale, plus an MCP-capable client (Claude Code, Pi, …).

---

## Setup

Run on the host, from a clone of this repo (e.g. `~/commonplace`):

```bash
# 1. Pull the models Ollama will serve
ollama pull nomic-embed-text
ollama pull mistral:7b-instruct-q4_0

# 2. Configure secrets
cp .env.example .env
#    edit .env: set a strong FALKORDB_PASSWORD, and ANTHROPIC_API_KEY for the personal tier
#    (openssl rand -hex 24  generates a good password)

# 3. Build the local image and start the stack
docker compose up -d
docker compose ps        # all services should report healthy
```

Then point a client at the two endpoints — see [Client configuration](#client-configuration).

> **Local-only?** If you don't want the hosted tier, remove the `mcp-personal` service from
> `docker-compose.yml` (or just don't add it as a client). The `client` tier runs without any
> Anthropic key.

---

## Gotchas (learned the hard way — read before you copy this)

These are the landmines specific to the current (2026) Graphiti MCP server. Several contradict
older docs.

1. **There is no `openai_generic` provider string.** To use Ollama you set `provider: "openai"`
   and point `api_url` at a non-OpenAI URL; the server then auto-selects its `OpenAIGenericClient`
   internally. That generic client is what avoids OpenAI's beta `responses.parse()` (which Ollama
   does not implement). Setting `provider: "openai_generic"` is invalid.
2. **There is no `small_model` setting.** The MCP server has a single `llm.model`. On the openai
   path it uses that same model for the "small" slot too. The infamous `gpt-4.1-mini` is only a
   fallback used when `model` is `None` — pinning `llm.model` is enough to never hit it.
3. **`json_schema` structured output is always on for the local path and cannot be disabled**, and
   **`instructor` is not used there** — retries are built-in (tenacity, 4 attempts). There is no
   config knob for either. If a small local model produces invalid JSON, the only lever is a more
   capable model.
4. **Ollama must be reachable from inside the containers.** Ollama runs on the _host_, so each MCP
   service needs `extra_hosts: ["host.docker.internal:host-gateway"]` and an `api_url` of
   `http://host.docker.internal:11434/v1`. Ollama must listen on `0.0.0.0:11434` (it does by default).
5. **`FALKORDB_DATABASE` selects the graph; `group_id` does not.** Two graphs in one FalkorDB =
   two instances with the same `FALKORDB_URI` and different `FALKORDB_DATABASE`. `group_id` only
   namespaces nodes _within_ a graph.
6. **FalkorDB host/port are parsed from `FALKORDB_URI`** — `FALKORDB_HOST`/`FALKORDB_PORT` are
   ignored. The only env overrides read are `FALKORDB_URI` and `FALKORDB_PASSWORD`.
7. **FalkorDB password is set via `REDIS_ARGS=--requirepass …`**, an env var — _not_ by overriding
   the container `command` (that would stop the FalkorDB module from loading).
8. **Use the `:standalone` image, not `:latest`.** `zepai/knowledge-graph-mcp:latest` bundles its
   own FalkorDB; `:standalone` expects an external one — required to share a single FalkorDB across
   two instances.
9. **The MCP path has a trailing slash: `/mcp/`** (FastMCP default; not configurable).
10. **Anthropic model id: use the bare alias `claude-haiku-4-5`, not `claude-haiku-4-5-latest`.**
    The `-latest` suffix is an OpenAI-ism; the Anthropic API 404s on it (`not_found_error: model`).
    The bare alias resolves to the current dated snapshot (`claude-haiku-4-5-20251001`).
11. **The Anthropic provider needs an explicit numeric `llm.temperature`.** graphiti passes
    `temperature=config.temperature`; with none set it sends `null` and the API 400s
    (`temperature: Input should be a valid number`), so every personal-tier episode queues but
    never processes. The OpenAI/Ollama generic client tolerates `null`, so this bites only the
    Anthropic tier. Set e.g. `temperature: 0.0`.
12. **The `:standalone` image ships WITHOUT the `anthropic` SDK.** `provider: anthropic` then fails
    at startup — "Anthropic client not available in current graphiti-core version" (the factory's
    `HAS_ANTHROPIC` is False because `import anthropic` raises). The bundled `Dockerfile` adds it
    (`uv pip install anthropic`).
13. **graphiti-core builds a default OpenAI reranker at init** that demands `OPENAI_API_KEY` even
    though the search path uses `NODE_HYBRID_SEARCH_RRF` (no cross-encoder). Give each tier a dummy
    `OPENAI_API_KEY` so it can construct; point `OPENAI_BASE_URL` at Ollama so even an accidental
    call stays on-box. In practice it is never called.
14. **FastMCP rejects non-localhost Host headers with HTTP 421 "Invalid Host header".** It
    auto-enables DNS-rebinding protection with a localhost-only allow-list at construction and passes
    that object explicitly into its pydantic Settings, so the `FASTMCP_…` env vars cannot override it
    (init kwargs beat env). The bundled `patch_transport_security.py` (run in the Dockerfile) disables
    the protection — safe on a tailnet, where the network is the trust boundary and clients are agents,
    not browsers. To tighten, set explicit `allowed_hosts` instead.
15. **The container env var for the OpenAI-compatible base URL is `OPENAI_API_URL`** (graphiti's
    config expansion), not `OPENAI_BASE_URL`. Note the reranker (#13) is the opposite — it reads the
    OpenAI SDK's `OPENAI_BASE_URL`. Two different names for two different clients.

---

## Operate

Run on the host, from the repo directory (e.g. `~/commonplace`).

```bash
# Bring the stack up (after .env is filled in)
docker compose up -d

# Status / health
docker compose ps
docker compose logs -f mcp-personal     # or mcp-client, falkordb

# Restart one instance after a config change (config/*.yaml does not hot-reload)
docker compose up -d --force-recreate mcp-client

# Rebuild the local image after editing the Dockerfile or patch_transport_security.py
docker compose up -d --build

# Stop / start (data persists in the falkordb_data volume)
docker compose stop
docker compose start

# Tear down (KEEP data)
docker compose down
# Tear down AND delete the graphs
docker compose down -v
```

Quick MCP health check (from a client, over the tailnet or LAN):

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://your-server.your-tailnet.ts.net:8000/mcp/
curl -s -o /dev/null -w "%{http_code}\n" http://your-server.your-tailnet.ts.net:8001/mcp/
```

---

## Backup & restore

FalkorDB is Redis under the hood; both graphs live in one keyspace, persisted to the
`falkordb_data` volume at `/data`.

```bash
# Backup: trigger a save, then copy the dump out of the container
docker compose exec falkordb redis-cli -a "$FALKORDB_PASSWORD" SAVE
docker compose cp falkordb:/data/dump.rdb ./backups/dump-$(date +%F).rdb

# Restore: stop, drop the dump back into the volume, start
docker compose stop falkordb
docker compose cp ./backups/dump-YYYY-MM-DD.rdb falkordb:/data/dump.rdb
docker compose start falkordb
```

(`$FALKORDB_PASSWORD` is in `.env`; `redis-cli` reads it from the container env.)

---

## Networking / exposure

- **Default: MagicDNS + port.** The MCP ports bind to `0.0.0.0` on the host and are reached over
  the tailnet at `http://your-server.your-tailnet.ts.net:8000/mcp/` and `:8001/mcp/`. This is
  tailnet-reachable (and LAN-reachable) but **not** public — do not port-forward these on your router.
- **FalkorDB `:6379` binds to `127.0.0.1` only** (host-local) — clients never touch it directly.
- **Keep the host single-homed.** The host's primary interface should hold exactly one IPv4. If a
  second address appears (e.g. a static IP _plus_ a DHCP lease), Tailscale can advertise two
  WireGuard endpoints and the tunnel flaps, which **black-holes TCP over MagicDNS while the LAN and
  `tailscale ping` still appear to work** (disco pings roam across endpoints; real TCP does not).
  On Ubuntu this most often comes from cloud-init re-enabling DHCP — disable its network management
  (`echo 'network: {config: disabled}' | sudo tee /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg`).
  Symptom to watch for: `ip -brief addr show <iface>` listing more than one address on your LAN subnet.
- **HTTPS upgrade (optional).** To serve the MCP endpoints as tailnet-only HTTPS names instead of
  raw ports:
  ```bash
  tailscale serve --bg --https=8443 http://localhost:8000   # personal
  tailscale serve --bg --https=8444 http://localhost:8001   # client
  ```
  then point clients at `https://your-server.your-tailnet.ts.net:8443/mcp/` etc. MagicDNS:port is
  the simpler default and is what the client config below uses.

---

## Client configuration

> Replace `your-server.your-tailnet.ts.net` with your host's Tailscale MagicDNS name (`tailscale
status`). The identical ports/paths are also served on the host's LAN IP, which is a handy
> fallback if MagicDNS is ever unreachable.

### Claude Code (user scope)

```bash
claude mcp add --scope user --transport http commonplace-personal http://your-server.your-tailnet.ts.net:8000/mcp/
claude mcp add --scope user --transport http commonplace-client   http://your-server.your-tailnet.ts.net:8001/mcp/
claude mcp list   # both should report ✓ Connected
```

(New servers load on the next Claude Code start.)

### Pi (extension + `~/.pi/agent/mcp.json`)

Pi has no native MCP — add the community bridge, then a global `mcp.json`:

```bash
pi install npm:@spences10/pi-mcp     # records the bridge in settings.json
```

Each server entry must include `"type": "http"`; a `url`-only entry triggers an OAuth handshake
this server doesn't support. The extension lazy-connects by default — set
`MY_PI_MCP_EAGER_CONNECT=1` to connect and discover tools at startup.

```json
{
  "mcpServers": {
    "commonplace-personal": {
      "type": "http",
      "url": "http://your-server.your-tailnet.ts.net:8000/mcp/"
    },
    "commonplace-client": {
      "type": "http",
      "url": "http://your-server.your-tailnet.ts.net:8001/mcp/"
    }
  }
}
```

---

## Adding another client

Any device on the tailnet can use the same two endpoints — there is nothing per-client on the
server. To add one:

1. Join the device to the tailnet (`tailscale up`) and confirm it can reach the host
   (`tailscale ping your-server`).
2. For Claude Code, run the two `claude mcp add … /mcp/` commands above (user scope).
3. For any MCP client, add both servers with `"type": "http"` pointing at
   `:8000/mcp/` and `:8001/mcp/`.
4. Nothing to change on the host — graphs and auth are shared; reads/writes from the new client
   land in the same two graphs.
5. For HTTPS, expose via `tailscale serve` (above) and use the `https://…` URLs instead.

---

## Repo layout

```
commonplace/
├── docker-compose.yml           # FalkorDB + 2 MCP instances, restart: unless-stopped
├── Dockerfile                   # commonplace-mcp:local — standalone image + anthropic SDK + patch
├── patch_transport_security.py  # build-time: allow remote Host headers (disable DNS-rebind guard)
├── config/
│   ├── personal.yaml            # instance A — Anthropic Haiku extraction
│   └── client.yaml              # instance B — local Ollama extraction
├── .env.example                 # template; copy to .env on the host (gitignored)
├── .dockerignore                # keeps .env and other secrets out of the build context
├── CLAUDE.md                    # guidance for Claude Code working in this repo
├── LICENSE                      # MIT
└── README.md
```

Secrets live only in `.env` on the host and are never committed. The repo is the source of
truth: edit a clone, push to your fork, `git pull` on the host, `docker compose up -d`.

---

## License

[MIT](LICENSE).
