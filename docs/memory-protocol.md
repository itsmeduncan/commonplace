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
write it. There is currently no server-side guard — this rule is enforced by you, the agent.

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
  Engagement, Requirement, …). Phrase memories so those types are extractable.

## Make leverage visible — CITE what you used

When a memory fact informs your answer, **say so briefly** (e.g. "from memory: you prefer
rebase-workflow"). This is how the human can tell the graph is actually being used and is the
cheapest form of observability. If you searched and found nothing relevant, that's fine — just don't
silently ignore memory.

## Quick self-check

- Did I search memory before asking the user something they may have already told me?
- Did I write back anything durable I learned?
- Am I on the correct tier for the sensitivity of this data?
- Did I cite memory I relied on?
