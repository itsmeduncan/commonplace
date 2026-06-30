#!/usr/bin/env bash
# backup.sh — snapshot both graphs out of FalkorDB to a timestamped dump.
# Run on the host. Schedule via cron/systemd for real protection, e.g. daily:
#   0 3 * * *  cd ~/commonplace && ./scripts/backup.sh >> ~/commonplace-backup.log 2>&1
#
# Restore with scripts/restore.sh. Consider encrypting + copying off-box (see TODO).
set -euo pipefail

: "${FALKORDB_PASSWORD:?Set FALKORDB_PASSWORD (it lives in .env on the host)}"
CONTAINER="${FALKORDB_CONTAINER:-commonplace-falkordb}"
OUT_DIR="${BACKUP_DIR:-./backups}"
# Date is passed in so the script stays deterministic; default to `date` if unset.
STAMP="${BACKUP_STAMP:-$(date +%F-%H%M%S)}"

mkdir -p "$OUT_DIR"
echo "[backup] triggering SAVE…"
docker exec "$CONTAINER" redis-cli -a "$FALKORDB_PASSWORD" --no-auth-warning SAVE >/dev/null
dest="$OUT_DIR/dump-$STAMP.rdb"
echo "[backup] copying dump.rdb -> $dest"
docker cp "$CONTAINER:/data/dump.rdb" "$dest"
echo "[backup] done: $dest ($(du -h "$dest" | cut -f1))"

# TODO (Phase 3 hardening): gpg-encrypt and rsync the dump to off-box storage,
# and prune backups older than N days.
