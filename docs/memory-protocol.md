# Agent memory protocol

This is the contract for any LLM agent (Claude Code, Pi, …) that connects to `commonplace`.
The MCP server exposes the tools; **this document is what turns "the tools exist" into "the agent
actually uses memory well."** Without it, agents rarely search or write, and the graph stays empty.

Install it as a Claude Code skill / `CLAUDE.md` section, a Pi system prompt, or paste it into
whatever client you use. Keep all clients on the same protocol so their writes compose.

## The two tiers — never cross them

| Endpoint     | Tool prefix            | Use for                                     |
| ------------ | ---------------------- | ------------------------------------------- |
| `:8000/mcp/` | `commonplace-personal` | your own notes, projects, preferences, life |
| `:8001/mcp/` | `commonplace-client`   | confidential / client / NDA material only   |

**Hard rule: never write confidential or client data to the personal tier.** The personal tier
sends text to a hosted model (Anthropic) for extraction; the client tier extracts locally and never
leaves the host. When in doubt about whether something is confidential, use the client tier or don't
write it. The gateway enforces tier isolation with **separate bearer tokens** — a client given only
the client token cannot reach the personal endpoint — but you should still follow this rule, since a
client configured with both tokens could cross over.

Every request needs `Authorization: Bearer <tier-token>`; configure each client with only the
token(s) for the tiers it's allowed to touch.

## When to READ (search before you answer)

At the **start of a task**, and whenever the user references something that might be remembered
(a person, project, preference, past decision, "like we discussed", "my usual…"), search memory
**before** answering or asking the user to re-explain:

- `search_memory_facts(query=…, max_facts=…)` — relationships/facts between entities.
- `search_nodes(query=…, entity_types=[…])` — entities, optionally filtered by ontology type
  (e.g. `["Preference", "Decision"]`).

Prefer specific queries over broad ones. Pull only what you need (small `max_facts`) — the point is
to spend _fewer_ tokens than re-deriving or re-asking, not to dump the whole graph into context.

## When to WRITE (capture durable facts, not chatter)

After you learn something that will matter **beyond this session**, call `add_memory`:

- **Do write:** stable preferences, decisions + their rationale, people/orgs/projects and how they
  relate, goals, requirements, durable facts about the user's setup.
- **Don't write:** ephemeral chatter, transient task state, anything you'd be embarrassed to surface
  three months from now, secrets/credentials.
- **Check first:** if a quick `search` shows the fact is already there, don't re-add it.
- **Be structured:** prefer passing JSON with explicit context (who/what/when/source) over raw
  prose — it gives the extractor better signal, which matters because the client tier's local model
  is weak. Include a source and timestamp when you can.
- **Match the ontology:** the tiers define entity types (Preference, Project, Person, Decision,
  Engagement, Requirement, …), some with typed fields (e.g. a Decision's rationale, a Deliverable's
  due date, a Risk's owner). Phrase memories so those types — and, when you know them, those field
  values — are extractable.
- **Scope by project:** pass a `group_id` to keep a project's memory in its own namespace within the
  tier (e.g. `group_id="acme-redesign"`). This makes later recall filterable and keeps unrelated
  projects from bleeding together. Omit it for general/personal memory.
- **Identify yourself:** pass an `agent_id` (e.g. `agent_id="claude-code"`, `agent_id="pi"`) so the
  write is attributed to you. It's recorded in the episode's `source_description` — an audit trail of
  which agent wrote what. Optional and backward-compatible; omit it and writes stay anonymous.

## Enforce the write step (recommended)

The write step is the one agents skip. It's the last thing in a task, easy to drop, and nothing
forces it — so in practice the graph grows only when the agent happens to remember, often just a
fact or two across days of heavy use even though everything is "configured." If your client supports
lifecycle hooks, wire one to nudge a capture pass when a session ends.

For Claude Code, ship [`clients/claude-code/commonplace-capture.sh`](../clients/claude-code/commonplace-capture.sh)
as a `Stop` hook. It fires **at most once per substantial session** — only when the session actually
changed something (an edit/write) or ran long and tool-heavy, and hasn't already called `add_memory`
— and returns `decision: "block"` with an instruction to `search_nodes` (dedupe) then `add_memory`,
guarding against loops via `stop_hook_active`. Read-only lookups and quick chats are skipped so the
nudge stays quiet. See [`clients/claude-code/README.md`](../clients/claude-code/README.md) for install
steps (and the `COMMONPLACE_CAPTURE_MIN_TOOLS` knob). This turns "the agent should write durable
facts" into something that reliably happens on real work rather than something it discretionarily
remembers.

## Make leverage visible — CITE sparingly

When a memory fact **materially changed** your answer (you'd have asked the user, or answered
differently, without it), note it in a few words — e.g. "from memory: you prefer rebase-workflow".
That's the cheapest form of observability. But keep it light: don't prefix routine responses, don't
narrate searches that found nothing, and don't cite a fact you'd have known anyway. One quiet line
when it counts beats a citation on every turn.

## Quick self-check

- Did I search memory before asking the user something they may have already told me?
- Did I write back anything durable I learned?
- Am I on the correct tier for the sensitivity of this data?
- Did I cite memory I relied on?
