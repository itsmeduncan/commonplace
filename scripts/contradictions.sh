#!/usr/bin/env bash
# contradictions.sh — list facts the graph has marked superseded (invalidated).
# Graphiti doesn't delete contradicted facts; it sets `invalid_at` on the edge and
# keeps the history. This surfaces those so you (or an agent) can review what the
# graph now believes changed. Read-only. Run on the host.
#
# Usage:  ./scripts/contradictions.sh [graph] [limit]
#         ./scripts/contradictions.sh commonplace_personal 20
set -euo pipefail

GRAPH="${1:-commonplace_personal}"
LIMIT="${2:-25}"
: "${FALKORDB_PASSWORD:?Set FALKORDB_PASSWORD (it lives in .env on the host)}"
CONTAINER="${FALKORDB_CONTAINER:-commonplace-falkordb}"

echo "Superseded facts in $GRAPH (most recent first):"
echo
docker exec "$CONTAINER" redis-cli -a "$FALKORDB_PASSWORD" --no-auth-warning \
  GRAPH.QUERY "$GRAPH" \
  "MATCH ()-[r]->() WHERE r.invalid_at IS NOT NULL
   RETURN r.fact AS fact, r.valid_at AS valid_from, r.invalid_at AS invalidated
   ORDER BY r.invalid_at DESC LIMIT $LIMIT" 2>/dev/null

echo
echo "Tip: a healthy graph accumulates some of these — it means contradictions are"
echo "being resolved over time rather than piling up as conflicting 'current' facts."
