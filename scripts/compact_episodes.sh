#!/usr/bin/env bash
# compact_episodes.sh — reclaim old raw episodes while KEEPING the facts derived
# from them. Report-only by default; destructive only with --apply.
#
# Why this is safe (and why it does NOT use the MCP `delete_episode` verb):
#   Graphiti extracts entities + facts from each episode at INGEST time, so the
#   distillation you actually want ("fold episodes into stable facts") has already
#   happened by the time an episode is old. The raw `:Episodic` snippet is then
#   redundant provenance — it costs storage and adds noise to episode retrieval.
#
#   Graphiti's own remove_episode / MCP delete_episode CASCADES: it deletes any
#   fact edge whose episodes[0] == that episode, and any entity the episode was the
#   sole MENTIONS source for (graphiti-core 0.28.2, graphiti.py::remove_episode).
#   Using it to prune old episodes would therefore delete the very facts we want to
#   keep. So we compact one level BELOW graphiti, in FalkorDB: DETACH DELETE the old
#   `:Episodic` nodes (which drops only their :MENTIONS edges). `:Entity` nodes and
#   `:RELATES_TO` fact edges are not attached to the episodic node, so they survive
#   untouched — the fact text, valid_at/invalid_at, and embeddings all live on the
#   fact edge itself.
#
# Side effect (benign): surviving fact edges keep an `episodes` UUID list that will
# now contain references to deleted episodes. That list is provenance only; RRF
# search (fact text + embeddings) does not depend on it, and the cascade logic we
# bypassed is the only thing that reads episodes[0]. Cleaning the lists would mean
# rewriting many edges for no functional gain, so we leave them.
#
# Timestamps are ISO-8601 strings (graphiti serializes datetimes with .isoformat()),
# so a lexical `<` against a UTC cutoff is a correct chronological comparison.
#
# Runs on the host (needs the falkordb container + FALKORDB_PASSWORD from the
# environment / .env). Compaction is per-graph and explicit — no "both tiers" default
# for the destructive path.
#
# Usage:
#   ./scripts/compact_episodes.sh                                   # report personal, >90d
#   ./scripts/compact_episodes.sh commonplace_client --older-than 180
#   ./scripts/compact_episodes.sh commonplace_personal --older-than 90 --apply
set -euo pipefail

GRAPH="commonplace_personal"
DAYS=90
APPLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --older-than) DAYS="${2:?--older-than needs a number of days}"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    -h | --help)
      sed -n '2,33p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    -*) echo "error: unknown flag '$1' (see --help)" >&2; exit 1 ;;
    *) GRAPH="$1"; shift ;;
  esac
done

case "$DAYS" in
  '' | *[!0-9]*) echo "error: --older-than must be a whole number of days, got '$DAYS'" >&2; exit 1 ;;
esac

# Load .env from the repo root so the script works when run directly.
_root="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
[ -z "${FALKORDB_PASSWORD:-}" ] && [ -f "$_root/.env" ] && { set -a; . "$_root/.env"; set +a; }

: "${FALKORDB_PASSWORD:?Set FALKORDB_PASSWORD (it lives in .env on the host)}"
CONTAINER="${FALKORDB_CONTAINER:-commonplace-falkordb}"

# GNU date (the host is Linux). Cutoff is UTC to match graphiti's utc_now().
CUTOFF="$(date -u -d "${DAYS} days ago" +%Y-%m-%dT%H:%M:%S 2>/dev/null)" || {
  echo "error: need GNU date (this runs on the Linux host). 'date -d' unsupported here." >&2
  exit 1
}

q() { # cypher -> single scalar (2nd line of GRAPH.QUERY output, trimmed)
  docker exec "$CONTAINER" redis-cli -a "$FALKORDB_PASSWORD" --no-auth-warning \
    GRAPH.QUERY "$GRAPH" "$1" 2>/dev/null | sed -n '2p' | tr -d ' '
}

total_eps=$(q "MATCH (n:Episodic) RETURN count(n)")
old_eps=$(q "MATCH (n:Episodic) WHERE n.created_at < '$CUTOFF' RETURN count(n)")
facts=$(q "MATCH ()-[r:RELATES_TO]->() RETURN count(r)")
oldest=$(q "MATCH (n:Episodic) RETURN min(n.created_at)")

echo "Graph:        $GRAPH"
echo "Cutoff:       older than ${DAYS}d  (created_at < ${CUTOFF}Z)"
echo "Episodes:     ${total_eps:-0} total, ${old_eps:-0} older than cutoff"
echo "Oldest:       ${oldest:-—}"
echo "Facts (kept): ${facts:-0} :RELATES_TO edges — these are NOT touched"
echo

if [ "${old_eps:-0}" = "0" ]; then
  echo "Nothing to compact. Done."
  exit 0
fi

if [ "$APPLY" -ne 1 ]; then
  echo "DRY RUN — no changes made. Re-run with --apply to delete the ${old_eps} old"
  echo "episode(s) above. Facts stay; only the raw snippets go."
  echo "Back up first:  ./scripts/backup.sh"
  exit 0
fi

echo "!! --apply: deleting ${old_eps} :Episodic node(s) older than ${DAYS}d from $GRAPH."
echo "   Facts (:RELATES_TO) are preserved. This is irreversible without a backup"
echo "   (./scripts/backup.sh)."
echo

q "MATCH (n:Episodic) WHERE n.created_at < '$CUTOFF' DETACH DELETE n" >/dev/null

after_eps=$(q "MATCH (n:Episodic) RETURN count(n)")
after_facts=$(q "MATCH ()-[r:RELATES_TO]->() RETURN count(r)")
echo "Done. Episodes: ${total_eps:-0} -> ${after_eps:-0}   Facts: ${facts:-0} -> ${after_facts:-0} (unchanged)."
if [ "${facts:-0}" != "${after_facts:-0}" ]; then
  echo "WARNING: fact count changed — investigate before compacting further." >&2
  exit 1
fi
