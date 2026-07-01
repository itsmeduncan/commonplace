# Derived from the upstream Graphiti MCP standalone image.
#
# Why this exists: the published `zepai/knowledge-graph-mcp:standalone` image
# (currently 1.0.2 / graphiti-core 0.28.2) ships WITHOUT the Anthropic SDK, so the
# personal tier's `llm.provider: anthropic` fails at startup with
#   "Anthropic client not available in current graphiti-core version"
# (the factory's HAS_ANTHROPIC flag is False because `import anthropic` raises).
#
# Adding the SDK restores the native Anthropic client. The same image is used for
# both tiers — the extra package is harmless for the local-only client tier.
# Pinned by digest for reproducible builds — the `:standalone` tag is a moving
# target, so a digest pin makes upstream upgrades deliberate (Dependabot's docker
# ecosystem proposes bumps; CI's image build verifies the patch still applies).
FROM zepai/knowledge-graph-mcp:standalone@sha256:460bafb39439d99ff001ea6ef03efbe0bd5d9e6afe2655edf926da4fd9df97c5

# 1) Add the Anthropic SDK (absent from the upstream image) so provider: anthropic works.
RUN cd /app/mcp && uv pip install anthropic

# 2) Allow remote (tailnet/LAN) Host headers — upstream FastMCP rejects them with HTTP 421.
#    See patch_transport_security.py for the full rationale. Fails the build if it can't patch.
COPY patch_transport_security.py /tmp/patch_transport_security.py
RUN /app/mcp/.venv/bin/python /tmp/patch_transport_security.py

# 3) Add per-agent identity to add_memory (optional agent_id → source_description attribution).
#    See patch_agent_identity.py. Fails the build if its anchors drift (issue #13).
COPY patch_agent_identity.py /tmp/patch_agent_identity.py
RUN /app/mcp/.venv/bin/python /tmp/patch_agent_identity.py

# 4) Let config entity types declare optional TYPED fields (e.g. Decision.rationale).
#    See patch_entity_fields.py. Fails the build if its anchors drift (issue #14).
COPY patch_entity_fields.py /tmp/patch_entity_fields.py
RUN /app/mcp/.venv/bin/python /tmp/patch_entity_fields.py

# 5) Payload-level tier guard: add_memory refuses content matching graphiti.reject_pattern.
#    See patch_content_guard.py. Fails the build if its anchors drift (issue #11).
COPY patch_content_guard.py /tmp/patch_content_guard.py
RUN /app/mcp/.venv/bin/python /tmp/patch_content_guard.py
