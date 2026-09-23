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
#   - the session did SUBSTANTIAL work — it mutated a file (Edit/Write/
#     NotebookEdit) or ran a long tool-heavy session (>= COMMONPLACE_CAPTURE_
#     MIN_TOOLS tool_uses, default 12). Read-only lookups and quick chats are
#     skipped so the hook stays quiet on trivial sessions.
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
#
# POSIX sh only (no `pipefail`): Claude Code runs the hook command through the
# system shell, which is dash on most Linux hosts. `set -o pipefail` is a bashism
# and aborts dash with "Illegal option -o pipefail", turning every Stop into a
# hook error. `set -eu` is enough here — the only pipes end in the command whose
# status we care about, so pipefail buys nothing.
set -eu
input=$(cat)

# Don't re-fire on our own continuation → prevents infinite Stop loops.
[ "$(printf '%s' "$input" | jq -r '.stop_hook_active // false')" = "true" ] && exit 0

transcript=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
{ [ -z "$transcript" ] || [ ! -f "$transcript" ]; } && exit 0

# Already WROTE to memory this session? Then a capture happened — nothing to nudge.
# Match add_memory ONLY. Do NOT count search_nodes/search_memory_facts as proof: the
# protocol is search-FIRST, so a read-first lookup at task start would trip this guard
# and suppress the write nudge on exactly the compliant sessions the hook exists to
# serve. MCP tools are recorded namespaced, e.g. "mcp__commonplace-personal__add_memory";
# JSON spacing varies between clients, so allow optional whitespace after the colon.
grep -qE '"name":[[:space:]]*"(mcp__[a-zA-Z0-9_-]+__)?add_memory"' "$transcript" 2>/dev/null && exit 0

# Already nudged once this session? Don't re-nudge on every following user turn. A
# nothing-durable pass legitimately writes no add_memory, so keying only on add_memory
# would re-fire the nudge after each later message. `stop_hook_active` guards only the
# immediate continuation; this covers subsequent turns. The reason below carries a
# unique sentinel — its presence in the transcript proves the hook already fired.
grep -qF 'commonplace-capture-nudge' "$transcript" 2>/dev/null && exit 0

# Only nudge after a session that did REAL work — otherwise the end-of-session
# turn is pure noise. "Real work" = the session changed something (an edit, a
# write, a notebook edit), OR it was a long, tool-heavy session (research that
# likely surfaced durable facts). Read-only lookups and quick chats stay silent.
# Override the length bar with COMMONPLACE_CAPTURE_MIN_TOOLS (default 12).
min_tools=${COMMONPLACE_CAPTURE_MIN_TOOLS:-12}
mutated=$(grep -cE '"name":[[:space:]]*"(Edit|Write|NotebookEdit)"' "$transcript" 2>/dev/null || true)
tool_uses=$(grep -cE '"type":[[:space:]]*"tool_use"' "$transcript" 2>/dev/null || true)
[ "${mutated:-0}" -eq 0 ] && [ "${tool_uses:-0}" -lt "$min_tools" ] && exit 0

jq -n '{
  decision: "block",
  reason: "commonplace capture: silently search_nodes to dedupe, then add_memory(agent_id=\"claude-code\") for durable facts only — decisions, preferences, project/people. Personal tier unless confidential (then client). Do NOT narrate the pass: emit ONE terse line and nothing else — `memory: saved N — <2-4 word gist>`, or `memory: nothing durable`. <!-- commonplace-capture-nudge -->"
}'
