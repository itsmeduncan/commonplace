#!/usr/bin/env bash
# restore.sh — restore a FalkorDB dump produced by backup.sh.
# Run on the host. This REPLACES the live data with the dump's contents.
# Usage:
#   ./scripts/restore.sh ./backups/dump-2026-06-30-030000.rdb
set -euo pipefail

DUMP="${1:?Usage: restore.sh <path-to-dump.rdb>}"
[ -f "$DUMP" ] || { echo "No such dump: $DUMP" >&2; exit 1; }
CONTAINER="${FALKORDB_CONTAINER:-commonplace-falkordb}"

echo "[restore] This will overwrite the live graphs with: $DUMP"
printf '[restore] Type "yes" to continue: '
read -r confirm
[ "$confirm" = "yes" ] || { echo "[restore] aborted."; exit 1; }

echo "[restore] stopping falkordb…"
docker compose stop falkordb
echo "[restore] copying dump into the data volume…"
docker compose cp "$DUMP" "falkordb:/data/dump.rdb"
echo "[restore] starting falkordb…"
docker compose start falkordb
echo "[restore] done. Verify with: ./scripts/graph_stats.sh"
