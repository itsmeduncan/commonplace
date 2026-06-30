#!/usr/bin/env bash
# backup.sh — snapshot FalkorDB's whole data dir (RDB + AOF) to a timestamped
# tarball. Captures both graphs. Run on the host. Schedule via cron, e.g. daily:
#   0 3 * * *  cd ~/commonplace && ./scripts/backup.sh >> ~/commonplace-backup.log 2>&1
#
# Restore with scripts/restore.sh. Consider encrypting + copying off-box (see TODO).
set -euo pipefail

# Load .env from the repo root so the script works when run directly.
_root="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
[ -z "${FALKORDB_PASSWORD:-}" ] && [ -f "$_root/.env" ] && { set -a; . "$_root/.env"; set +a; }

: "${FALKORDB_PASSWORD:?Set FALKORDB_PASSWORD (it lives in .env on the host)}"
CONTAINER="${FALKORDB_CONTAINER:-commonplace-falkordb}"
OUT_DIR="${BACKUP_DIR:-./backups}"
STAMP="${BACKUP_STAMP:-$(date +%F-%H%M%S)}"

redis() { docker exec "$CONTAINER" redis-cli -a "$FALKORDB_PASSWORD" --no-auth-warning "$@"; }

# Ask the server where it actually writes, rather than hardcoding a path.
DIR="$(redis CONFIG GET dir | tail -1 | tr -d '\r')"
[ -n "$DIR" ] || { echo "error: could not determine FalkorDB data dir" >&2; exit 1; }

mkdir -p "$OUT_DIR"
echo "[backup] flushing to disk (SAVE + AOF rewrite)…"
redis SAVE >/dev/null
redis BGREWRITEAOF >/dev/null || true
sleep 1

dest="$OUT_DIR/falkordb-$STAMP.tar.gz"
echo "[backup] archiving $DIR -> $dest"
docker exec "$CONTAINER" tar -czf - -C "$DIR" . > "$dest"
echo "[backup] done: $dest ($(du -h "$dest" | cut -f1))"

# TODO (further hardening): gpg-encrypt + rsync off-box, and prune old backups.
