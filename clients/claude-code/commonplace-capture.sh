#!/usr/bin/env bash
# commonplace-capture.sh — Claude Code hook that nudges a memory-capture pass
# after a substantive session, so the WRITE step of the memory protocol stops
# being discretionary.
#
# The write step is the one agents skip: it's the last thing in a task, easy to
# drop, and nothing forces it. This hook closes that gap without nagging.
#
# One script, two modes (first argument), sharing one "already nudged" gate:
#
#   prompt  UserPromptSubmit hook — the PRIMARY, silent path. When the session so
#           far did substantial work (mutated a file, or >= COMMONPLACE_CAPTURE_
#           MIN_TOOLS tool_uses, default 12), it injects the capture instruction as
#           additionalContext on the next user message. No "Stop hook error" label,
#           no extra turn — the capture rides along with the next reply.
#
#   stop    Stop hook (default) — the BACKSTOP for big sessions that may end with no
#           next prompt. Fires only when the session mutated a file AND ran
#           >= COMMONPLACE_CAPTURE_STOP_MIN_TOOLS tool_uses (default 20). Claude Code
#           labels every Stop block "Stop hook error", so the reason opens with
#           "Not an error" to say what it is.
#
# Either mode exits silently (0) when:
#   - add_memory was already called this session, OR
#   - either mode already nudged this session (per-session marker file, plus the
#     sentinel in the transcript), OR
#   - (stop) this is the continuation we ourselves triggered (no loops).
#
# Install: see clients/claude-code/README.md. Requires: jq.
#
# POSIX sh only (no `pipefail`): Claude Code runs the hook command through the
# system shell, which is dash on most Linux hosts. `set -o pipefail` is a bashism
# and aborts dash with "Illegal option -o pipefail", turning every hook call into
# an error. `set -eu` is enough here — the only pipes end in the command whose
# status we care about, so pipefail buys nothing.
set -eu
mode=${1:-stop}
input=$(cat)

sentinel='commonplace-capture-nudge'
instruction="commonplace capture: silently search_nodes to dedupe, then add_memory(agent_id=\"claude-code\") for durable facts only — decisions, preferences, project/people. Personal tier unless confidential (then client). Do NOT narrate the pass: emit ONE terse line — \`memory: saved N — <2-4 word gist>\`, or \`memory: nothing durable\`. <!-- $sentinel -->"

field() { printf '%s' "$input" | jq -r "$1"; }

# Don't re-fire on our own Stop continuation → prevents infinite Stop loops.
[ "$mode" = "stop" ] && [ "$(field '.stop_hook_active // false')" = "true" ] && exit 0

transcript=$(field '.transcript_path // empty')
{ [ -z "$transcript" ] || [ ! -f "$transcript" ]; } && exit 0

# Already WROTE to memory this session? Then a capture happened — nothing to nudge.
# Match add_memory ONLY. Do NOT count search_nodes/search_memory_facts as proof: the
# protocol is search-FIRST, so a read-first lookup at task start would trip this guard
# and suppress the write nudge on exactly the compliant sessions the hook exists to
# serve. MCP tools are recorded namespaced, e.g. "mcp__commonplace-personal__add_memory";
# JSON spacing varies between clients, so allow optional whitespace after the colon.
grep -qE '"name":[[:space:]]*"(mcp__[a-zA-Z0-9_-]+__)?add_memory"' "$transcript" 2>/dev/null && exit 0

# Already nudged once this session (by either mode)? Don't re-nudge. A nothing-durable
# pass legitimately writes no add_memory, so keying only on add_memory would re-fire
# after each later message. The marker file is the shared gate between the two modes;
# the transcript sentinel covers sessions nudged before the marker existed.
session=$(field '.session_id // empty')
marker_dir="${TMPDIR:-/tmp}/commonplace-capture"
marker="$marker_dir/${session:-unknown}"
[ -n "$session" ] && [ -f "$marker" ] && exit 0
grep -qF "$sentinel" "$transcript" 2>/dev/null && exit 0

# Only nudge after a session that did REAL work. "Real work" = the session changed
# something (an edit, a write, a notebook edit) and/or ran long and tool-heavy.
mutated=$(grep -cE '"name":[[:space:]]*"(Edit|Write|NotebookEdit)"' "$transcript" 2>/dev/null || true)
tool_uses=$(grep -cE '"type":[[:space:]]*"tool_use"' "$transcript" 2>/dev/null || true)
mutated=${mutated:-0}
tool_uses=${tool_uses:-0}

substantial_for_prompt() {
  [ "$mutated" -gt 0 ] || [ "$tool_uses" -ge "${COMMONPLACE_CAPTURE_MIN_TOOLS:-12}" ]
}

substantial_for_stop() {
  [ "$mutated" -gt 0 ] && [ "$tool_uses" -ge "${COMMONPLACE_CAPTURE_STOP_MIN_TOOLS:-20}" ]
}

mark_nudged() {
  [ -n "$session" ] || return 0
  mkdir -p "$marker_dir" && : >"$marker"
}

case "$mode" in
  prompt)
    substantial_for_prompt || exit 0
    mark_nudged
    jq -n --arg ctx "Before answering this message, run a $instruction" '{
      hookSpecificOutput: { hookEventName: "UserPromptSubmit", additionalContext: $ctx }
    }'
    ;;
  stop)
    substantial_for_stop || exit 0
    mark_nudged
    jq -n --arg reason "Not an error — end-of-session $instruction" '{
      decision: "block", reason: $reason
    }'
    ;;
  *)
    echo "commonplace-capture.sh: unknown mode '$mode' — use 'prompt' (UserPromptSubmit) or 'stop' (Stop)." >&2
    exit 1
    ;;
esac
