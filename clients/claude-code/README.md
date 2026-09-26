# Claude Code client helpers

Drop-in pieces for using `commonplace` from Claude Code. The MCP wiring and the
[memory protocol](../../docs/memory-protocol.md) are the required setup; these make it
more reliable.

## `commonplace-capture.sh` — enforce the write step

A hook that nudges a memory-capture pass after a substantive session. The memory protocol admits
the gap it fills: models "won't call memory on every turn — it nudges, it doesn't guarantee," and
the **write** step is the one that gets skipped (it's the last thing in a task). Without something
like this, expect the graph to grow only when the agent happens to remember — often just a fact or
two across days of heavy use.

It runs in two modes that share one "already nudged" gate, so a session is nudged **at most once**:

| Mode | Hook event | Fires when | What you see |
| --- | --- | --- | --- |
| `prompt` (primary) | `UserPromptSubmit` | the session so far changed a file (`Edit`/`Write`/`NotebookEdit`) **or** ran `>= 12` tool uses (`COMMONPLACE_CAPTURE_MIN_TOOLS`) | nothing extra — the instruction rides along as context on your next message, and the reply ends with one `memory: …` line |
| `stop` (backstop) | `Stop` | the session changed a file **and** ran `>= 20` tool uses (`COMMONPLACE_CAPTURE_STOP_MIN_TOOLS`) | one extra turn, labelled `Stop hook error: Not an error — end-of-session commonplace capture …` |

Why both: the `prompt` mode is silent but can only act when a next message arrives, so it never
captures the final task of a session. The `stop` mode catches that case, but Claude Code labels
every `Stop` block "Stop hook error" (the hook can't change the label), so it is reserved for big
sessions and its reason opens with "Not an error". Read-only lookups and quick chats trip neither.

The "already handled" test keys on `add_memory` (a **write**) only — never on a `search_*` call.
The memory protocol is search-**first**, so a compliant session opens with a read; counting that read
as proof would suppress the write nudge on exactly the sessions that need it. A pass that finds nothing
durable writes no `add_memory`, so to avoid re-nudging on every later message the hook drops a
per-session marker in `$TMPDIR/commonplace-capture/<session_id>` (plus a sentinel in the instruction
text) and skips once either exists. The `stop` mode also honours `stop_hook_active`, so it can't loop.

### Install

```bash
mkdir -p ~/.claude/hooks
cp clients/claude-code/commonplace-capture.sh ~/.claude/hooks/commonplace-capture.sh
chmod +x ~/.claude/hooks/commonplace-capture.sh
```

Then register **both** modes in `~/.claude/settings.json` (merge with any existing hooks):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "sh ~/.claude/hooks/commonplace-capture.sh prompt",
            "timeout": 15
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "sh ~/.claude/hooks/commonplace-capture.sh stop",
            "timeout": 15
          }
        ]
      }
    ]
  }
}
```

With no argument the script runs in `stop` mode, so an existing `Stop` registration keeps working
(with the new, higher bar). Open `/hooks` once (or restart) to load it into a running session.
Requires `jq`.

### Tradeoff

Most captures now cost nothing visible: they happen inside the reply to your next message. The price
is that a medium session you close without another message goes uncaptured — only big sessions (a file
change and 20+ tool uses) get the end-of-session `Stop` turn. Lower `COMMONPLACE_CAPTURE_STOP_MIN_TOOLS`
to backstop more sessions at the cost of more "Stop hook error" turns; raise
`COMMONPLACE_CAPTURE_MIN_TOOLS` to make the silent path pickier.
