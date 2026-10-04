# commonplace brain — the image Whelk Server runs as its `brain` product (WHK-251).
#
# ONE container holding the Graphiti MCP server AND FalkorDB, so Whelk Server can run it as
# one digest-pinned product. That is why this is built from the COMBINED upstream image
# (`zepai/knowledge-graph-mcp:latest`), not `:standalone` like the two-tier stack's
# Dockerfile: here there is no separate FalkorDB to share.
#
# Build from the repo root (the patches live there):
#   docker build -f brain/Dockerfile -t commonplace-brain:local .
#
# Pinned by digest (the multi-arch index) — `:latest` moves. This is upstream revision
# 11538f6 / mcp-v1.1.0 / graphiti-core 0.30.1, the same revision the `:standalone` pin in
# ../Dockerfile carries, so the shared patches apply to both.
FROM zepai/knowledge-graph-mcp:latest@sha256:a2536b6d59b4afb359a13aeaa4a9d2f4db195af14231168efda6a3d166228956

# 1) No hosted-model path: drop the Anthropic SDK the upstream image ships. Drop the
#    FalkorDB browser UI (a second listening port this product never opens), the node
#    binary that served it, and the upstream build's sfw tool.
RUN uv pip uninstall --python /app/mcp/.venv/bin/python anthropic \
 && rm -rf /var/lib/falkordb/browser /usr/local/bin/node /usr/local/bin/sfw

# 2) Shared patches (see their docstrings). Each FAILS THE BUILD if its anchor drifts.
#    transport-security: the brain is also reachable by a URL the operator names
#    (WHELK_HUB_BRAIN_URL), so the Host header is not always localhost; the bearer gate
#    below is the access control. episode-uuids: get_episodes(uuids=…) returns the sources
#    of a fact. serial-ingest: one episode at a time across groups, so an episode cannot be
#    written into another group's graph (each Whelk access label is a group).
COPY patch_transport_security.py patch_episode_uuids.py patch_serial_ingest.py /tmp/
RUN /app/mcp/.venv/bin/python /tmp/patch_transport_security.py \
 && /app/mcp/.venv/bin/python /tmp/patch_episode_uuids.py \
 && /app/mcp/.venv/bin/python /tmp/patch_serial_ingest.py

# 3) Brain-only: the bearer gate on /mcp/ against WHELK_SERVER_TOKEN.
COPY brain/whelk_bearer.py /app/mcp/src/whelk_bearer.py
COPY brain/patch_bearer.py brain/patch_prompt_json.py /tmp/
RUN /app/mcp/.venv/bin/python /tmp/patch_bearer.py \
 && /app/mcp/.venv/bin/python /tmp/patch_prompt_json.py \
 && /app/mcp/.venv/bin/python -m compileall -q /app/mcp/src \
 && rm -f /tmp/patch_*.py

# 4) The Whelk config, the entry point and the third-party notices.
COPY brain/config.yaml /app/mcp/config/config.yaml
COPY brain/start.sh /usr/local/bin/brain-start
COPY brain/NOTICE /usr/share/doc/commonplace-brain/NOTICE

# 5) Run unprivileged. The data dir is the only path that takes a write; a named volume
#    mounted there takes this ownership on first use.
RUN chmod 0755 /usr/local/bin/brain-start \
 && chown -R 10251:10251 /var/lib/falkordb/data \
 && chmod 0700 /var/lib/falkordb/data

LABEL org.opencontainers.image.title="commonplace brain" \
      org.opencontainers.image.description="Graphiti MCP + FalkorDB in one container, configured as the Whelk Server org brain" \
      org.opencontainers.image.source="https://github.com/itsmeduncan/commonplace" \
      org.opencontainers.image.licenses="MIT AND Apache-2.0 AND SSPL-1.0 AND (LicenseRef-RSALv2 OR SSPL-1.0 OR AGPL-3.0-only)"

ENV GRAPHITI_TELEMETRY_ENABLED=false \
    PYTHONDONTWRITEBYTECODE=1 \
    BROWSER=0 \
    SEMAPHORE_LIMIT=1 \
    CONFIG_PATH=/app/mcp/config/config.yaml

USER 10251:10251
WORKDIR /app/mcp
VOLUME ["/var/lib/falkordb/data"]
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=3 \
  CMD ["/app/mcp/.venv/bin/python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]

ENTRYPOINT ["/usr/local/bin/brain-start"]
