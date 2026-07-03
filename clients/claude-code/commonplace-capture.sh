#!/usr/bin/env bash
# commonplace-capture.sh — Claude Code Stop hook that nudges a memory-capture
# pass at the end of a substantive session, so the WRITE step of the memory
# protocol stops being discretionary.
#
# The write step is the one agents skip: it's the last thing in a task, easy to
# drop, and nothing forces it. This hook closes that gap without nagging.
#
# Fires at most ONCE per session and only when:
#   - this isn't the continuation we ourselves triggered (no loops), AND
#   - add_memory was NOT already called this session, AND
#   - the session actually did work (>=1 tool_use).
# Otherwise it exits silently (0) and Claude stops normally.
#
# Install: copy to ~/.claude/hooks/commonplace-capture.sh, chmod +x, and register
# under hooks.Stop in ~/.claude/settings.json:
#
#   "hooks": {
#     "Stop": [
#       { "hooks": [ { "type": "command",
#                      "command": "sh ~/.claude/hooks/commonplace-capture.sh",
#                      "timeout": 15 } ] }
#     ]
#   }
#
# Requires: jq. Assumes the commonplace MCP servers are configured in the client.
set -euo pipefail
input=$(cat)

# Don't re-fire on our own continuation → prevents infinite Stop loops.
[ "$(printf '%s' "$input" | jq -r '.stop_hook_active // false')" = "true" ] && exit 0

transcript=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
{ [ -z "$transcript" ] || [ ! -f "$transcript" ]; } && exit 0

# Already captured this session? Nothing to nudge. MCP tools are recorded with a
# namespaced name, e.g. "mcp__commonplace-personal__add_memory" — match that too.
grep -qE '"name":"(mcp__[a-zA-Z0-9_-]+__)?add_memory"' "$transcript" 2>/dev/null && exit 0

# Only bother if the session actually used tools (skip trivial chats).
grep -q '"type":"tool_use"' "$transcript" 2>/dev/null || exit 0

jq -n '{
  decision: "block",
  reason: "commonplace capture: search_nodes to dedupe, then add_memory(agent_id=\"claude-code\") for durable facts only — decisions, preferences, project/people. Personal tier unless confidential (then client). Nothing durable? say so and stop."
}'
