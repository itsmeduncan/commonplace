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
FROM zepai/knowledge-graph-mcp:standalone

# 1) Add the Anthropic SDK (absent from the upstream image) so provider: anthropic works.
RUN cd /app/mcp && uv pip install anthropic

# 2) Allow remote (tailnet/LAN) Host headers — upstream FastMCP rejects them with HTTP 421.
#    See patch_transport_security.py for the full rationale. Fails the build if it can't patch.
COPY patch_transport_security.py /tmp/patch_transport_security.py
RUN /app/mcp/.venv/bin/python /tmp/patch_transport_security.py
