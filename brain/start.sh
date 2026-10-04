#!/bin/bash
# Entry point of the brain image: FalkorDB on loopback, then the Graphiti MCP server.
#
# Writes only to /var/lib/falkordb/data (the volume), so the container runs with a
# read-only root filesystem and needs no tmpfs. Python's temporary files (torch asks for
# a temp dir at import) go to $DATA/.tmp, which is emptied at every start.
#
# On TERM or INT it stops the MCP server first, then asks FalkorDB to save and shut
# down, so the last writes reach the volume.
# If either process exits, the other is stopped and the container exits non-zero, so
# Whelk Server's supervisor restarts it.
set -uo pipefail

DATA=/var/lib/falkordb/data

need() {
  if [ -z "${!1:-}" ]; then
    echo "brain: $1 is not set. $2" >&2
    exit 64
  fi
}

need WHELK_SERVER_URL "Run the brain as a Whelk Server product with \"reach_server\": true, or set it to the base URL of an OpenAI-compatible server (no /v1)."
need WHELK_SERVER_TOKEN "Run the brain as a Whelk Server product with \"reach_server\": true, or set it to the bearer the server and the brain share."
need WHELK_BRAIN_MODEL "Set it in the product manifest's env to a chat model your Whelk Server serves."
need WHELK_BRAIN_EMBED_MODEL "Set it in the product manifest's env to an embedding model your Whelk Server serves."

if [ ! -w "$DATA" ]; then
  echo "brain: $DATA is not writable by uid $(id -u). Mount the product volume at $DATA." >&2
  exit 73
fi

export TMPDIR="$DATA/.tmp"
rm -rf "$TMPDIR"
mkdir -m 0700 "$TMPDIR"

redis-server \
  --loadmodule /var/lib/falkordb/bin/falkordb.so \
  --bind 127.0.0.1 \
  --protected-mode yes \
  --port 6379 \
  --dir "$DATA" \
  --appendonly yes \
  --daemonize no \
  --logfile "" &
redis_pid=$!

until redis-cli -h 127.0.0.1 -p 6379 ping >/dev/null 2>&1; do
  if ! kill -0 "$redis_pid" 2>/dev/null; then
    echo "brain: FalkorDB exited during start. Read its log above." >&2
    exit 70
  fi
  sleep 0.2
done

cd /app/mcp
/app/mcp/.venv/bin/python main.py &
mcp_pid=$!

stop() {
  kill -TERM "$mcp_pid" 2>/dev/null
  wait "$mcp_pid" 2>/dev/null
  redis-cli -h 127.0.0.1 -p 6379 shutdown save >/dev/null 2>&1
  wait "$redis_pid" 2>/dev/null
}

trap 'stop; exit 0' TERM INT

wait -n "$redis_pid" "$mcp_pid"
status=$?
echo "brain: a process exited with status $status; stopping the other." >&2
stop
exit "$(( status == 0 ? 1 : status ))"
