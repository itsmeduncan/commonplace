# Claude Code client helpers

Drop-in pieces for using `commonplace` from Claude Code. The MCP wiring and the
[memory protocol](../../docs/memory-protocol.md) are the required setup; these make it
more reliable.

## `commonplace-capture.sh` — enforce the write step

A `Stop` hook that nudges a memory-capture pass at the end of a substantive session. The
memory protocol admits the gap it fills: models "won't call memory on every turn — it nudges,
it doesn't guarantee," and the **write** step is the one that gets skipped (it's the last thing
in a task). Without something like this, expect the graph to grow only when the agent happens to
remember — often just a fact or two across days of heavy use.

The hook fires **at most once per session**, and only when the session did **substantial work** —
it changed a file (`Edit`/`Write`/`NotebookEdit`) or ran long and tool-heavy (`>= 12` tool uses,
override with `COMMONPLACE_CAPTURE_MIN_TOOLS`) — and hasn't already called `add_memory`. Read-only
lookups and quick chats are skipped, so the hook stays quiet on trivial sessions instead of tacking a
capture turn onto every one. It guards against loops via `stop_hook_active`, so a session with
nothing durable self-terminates in one no-op turn.

### Install

```bash
cp clients/claude-code/commonplace-capture.sh ~/.claude/hooks/commonplace-capture.sh
chmod +x ~/.claude/hooks/commonplace-capture.sh
```

Then register it under `hooks.Stop` in `~/.claude/settings.json` (merge with any existing hooks):

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "sh ~/.claude/hooks/commonplace-capture.sh",
            "timeout": 15
          }
        ]
      }
    ]
  }
}
```

Open `/hooks` once (or restart) to load it into a running session. Requires `jq`.

### Tradeoff

Costs one extra model turn at the end of a session that did real work — occasionally a no-op "nothing
to capture" turn. Because the bar is now "mutated a file or ran long," read-only and quick sessions
skip it entirely, so the everyday noise is gone; the cost lands only where a session plausibly
produced something worth remembering. That's the price of making capture reliable instead of relying
on the agent to remember the last, most-skippable step. Raise `COMMONPLACE_CAPTURE_MIN_TOOLS` to make
it quieter still, or lower it to catch shorter research sessions.
