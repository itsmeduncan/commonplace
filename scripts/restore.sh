#!/usr/bin/env bash
# restore.sh — restore a FalkorDB data-dir tarball made by backup.sh.
# This REPLACES the live data (RDB + AOF) with the archive's contents.
# Run on the host. Usage:
#   ./scripts/restore.sh ./backups/falkordb-2026-06-30-030000.tar.gz
set -euo pipefail

TARBALL="${1:?Usage: restore.sh <path-to-falkordb-*.tar.gz>}"
[ -f "$TARBALL" ] || { echo "No such backup: $TARBALL" >&2; exit 1; }
VOLUME="${FALKORDB_VOLUME:-commonplace_falkordb_data}"

echo "[restore] This will overwrite the live graphs from: $TARBALL"
printf '[restore] Type "yes" to continue: '
read -r confirm
[ "$confirm" = "yes" ] || { echo "[restore] aborted."; exit 1; }

echo "[restore] stopping falkordb…"
docker compose stop falkordb

# The container is stopped, so replace the volume contents via a throwaway helper
# that mounts the named volume. Clears the dir first, then unpacks the archive.
echo "[restore] replacing volume $VOLUME…"
docker run --rm -i -v "$VOLUME":/restore alpine sh -c \
  'rm -rf /restore/..?* /restore/.[!.]* /restore/* 2>/dev/null; tar -xzf - -C /restore' < "$TARBALL"

echo "[restore] starting falkordb…"
docker compose start falkordb
echo "[restore] done. Verify with: ./scripts/graph_stats.sh"
