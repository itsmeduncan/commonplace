#!/usr/bin/env bash
# mcp_activity.sh — summarize gateway access logs so you can SEE whether agents
# are actually hitting the graph (the "are Claude Code / Pi reading & writing?"
# question). Reads the gateway container's JSON access log. Read-only; host.
#
# For precise, continuous metrics use the Prometheus endpoint instead:
#   curl -s http://127.0.0.1:9180/metrics | grep caddy_http_requests_total
#
# Usage:  ./scripts/mcp_activity.sh [num_log_lines]
set -euo pipefail

N="${1:-2000}"
CONTAINER="${GATEWAY_CONTAINER:-commonplace-gateway}"

docker logs --tail "$N" "$CONTAINER" 2>&1 | python3 -c '
import json, sys

# Tier is identified by the port the client connected to (8000 personal, 8001 client).
tiers = {"8000": "personal", "8001": "client"}
counts = {}        # (tier, status_class) -> n
total = 0
for line in sys.stdin:
    line = line.strip()
    if not line or not line.startswith("{"):
        continue
    try:
        e = json.loads(line)
    except ValueError:
        continue
    req = e.get("request", {})
    host = str(req.get("host", ""))
    port = host.rsplit(":", 1)[-1] if ":" in host else ""
    tier = tiers.get(port, "?")
    status = e.get("status", 0)
    klass = f"{status // 100}xx" if isinstance(status, int) and status else "?"
    counts[(tier, klass)] = counts.get((tier, klass), 0) + 1
    total += 1

if not total:
    print("No access-log entries found. Either no traffic yet, or the gateway")
    print("is not running. Check: docker compose ps gateway")
    sys.exit(0)

print(f"{total} gateway requests in the last log window\n")
print("%-10s%-8s%8s" % ("tier", "status", "count"))
print("-" * 26)
for (tier, klass), n in sorted(counts.items()):
    print(f"{tier:<10}{klass:<8}{n:>8}")
print()
print("401s mean a client is missing/using the wrong bearer token.")
'
