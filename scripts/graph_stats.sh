#!/usr/bin/env bash
# graph_stats.sh — snapshot how much each graph holds, as a proxy for whether
# agents are actually WRITING to memory. Run it over time (or on a cron) and
# watch the counts: if they don't grow while you work, nothing is being captured.
#
# Read-only. Runs on the host (needs the falkordb container + FALKORDB_PASSWORD
# from the environment / .env). Usage:
#   ./scripts/graph_stats.sh                 # both tiers
#   ./scripts/graph_stats.sh commonplace_personal
set -euo pipefail

GRAPHS=("${@:-commonplace_personal commonplace_client}")
# shellcheck disable=SC2206
GRAPHS=(${GRAPHS[@]})

: "${FALKORDB_PASSWORD:?Set FALKORDB_PASSWORD (it lives in .env on the host)}"
CONTAINER="${FALKORDB_CONTAINER:-commonplace-falkordb}"

q() { # graph, cypher -> single scalar
  docker exec "$CONTAINER" redis-cli -a "$FALKORDB_PASSWORD" --no-auth-warning \
    GRAPH.QUERY "$1" "$2" 2>/dev/null | sed -n '2p' | tr -d ' '
}

printf '%-24s %10s %10s %10s\n' "graph" "nodes" "edges" "episodes"
printf '%-24s %10s %10s %10s\n' "------" "-----" "-----" "--------"
for g in "${GRAPHS[@]}"; do
  nodes=$(q "$g" "MATCH (n) RETURN count(n)")
  edges=$(q "$g" "MATCH ()-[r]->() RETURN count(r)")
  # Episodic nodes are the raw ingested snippets; entities are extracted from them.
  eps=$(q "$g" "MATCH (n:Episodic) RETURN count(n)")
  printf '%-24s %10s %10s %10s\n' "$g" "${nodes:-?}" "${edges:-?}" "${eps:-?}"
done

echo
echo "Tip: a healthy, actively-used tier grows over days of work. Flat counts mean"
echo "the agents aren't calling add_memory — check your client's memory protocol."
