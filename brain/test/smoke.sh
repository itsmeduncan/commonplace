#!/usr/bin/env bash
# End-to-end smoke test of the brain image, run the way Whelk Server runs the product.
#
#   docker build -f brain/Dockerfile -t commonplace-brain:local .
#   brain/test/smoke.sh [image]
#
# Everything it makes is scratch and is removed on exit: one --internal network (no route
# off the host), one volume, and containers named ${BRAIN_SMOKE_PREFIX:-cpbrain-smoke}-*.
# It touches no other container, volume or port.
#
# What it proves:
#   1. the container runs with a read-only root filesystem and NO tmpfs;
#   2. /mcp/ refuses no bearer and a wrong bearer, and admits WHELK_SERVER_TOKEN;
#   3. FalkorDB is not reachable from outside the container;
#   4. add_memory, search_memory_facts, search_nodes and get_episodes(uuids) work;
#   5. every model call went to WHELK_SERVER_URL/v1 with the token and the configured
#      models, and a packet capture of the container's network namespace shows no
#      connection and no DNS lookup for any other host;
#   6. the facts and their sources survive a graceful stop and a new container.
#
# The token is generated here, passed by --env-file (mode 600) and environment, and never
# printed.
set -euo pipefail

IMAGE=${1:-${BRAIN_IMAGE:-commonplace-brain:local}}
SNIFFER=${BRAIN_SMOKE_SNIFFER:-nicolaka/netshoot:v0.13}
P=${BRAIN_SMOKE_PREFIX:-cpbrain-smoke}
NET=$P-net VOL=$P-data FAKE=$P-fake NS=$P-ns BRAIN=$P-brain
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)
chmod 0755 "$WORK"

cleanup() {
  status=$?
  if [ "$status" -ne 0 ]; then
    if [ -n "${BRAIN_SMOKE_LOGS:-}" ]; then
      mkdir -p "$BRAIN_SMOKE_LOGS"
      docker logs "$BRAIN" >"$BRAIN_SMOKE_LOGS/brain.log" 2>&1 || true
      docker logs "$FAKE" >"$BRAIN_SMOKE_LOGS/fake.log" 2>&1 || true
    fi
    echo "--- brain log (tail)"; docker logs "$BRAIN" 2>&1 | tail -60 || true
    echo "--- fake Whelk Server log (tail)"; docker logs "$FAKE" 2>&1 | tail -30 || true
  fi
  if [ -n "${BRAIN_SMOKE_LOGS:-}" ] && [ -f "$WORK/brain.pcap" ]; then
    mkdir -p "$BRAIN_SMOKE_LOGS"
    cp "$WORK/brain.pcap" "$BRAIN_SMOKE_LOGS/brain.pcap"
  fi
  docker rm -f "$BRAIN" "$NS" "$FAKE" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  docker volume rm "$VOL" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT
docker rm -f "$BRAIN" "$NS" "$FAKE" >/dev/null 2>&1 || true

step() { printf '\n== %s\n' "$*"; }
fail() { echo "FAIL: $*" >&2; exit 1; }

export BRAIN_TOKEN FAKE_TOKEN
BRAIN_TOKEN=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
FAKE_TOKEN=$BRAIN_TOKEN
umask 077
printf 'WHELK_SERVER_URL=http://whelk-server:41235\nWHELK_SERVER_TOKEN=%s\n' "$BRAIN_TOKEN" >"$WORK/server.env"
umask 022

step "scratch network, volume, fake Whelk Server and packet capture"
docker network create --internal "$NET" >/dev/null
docker volume create "$VOL" >/dev/null
docker run -d --name "$FAKE" --network "$NET" --network-alias whelk-server --read-only \
  -e FAKE_TOKEN -v "$HERE:/test:ro" --entrypoint /app/mcp/.venv/bin/python \
  "$IMAGE" /test/fake_openai.py 41235 >/dev/null
docker run -d --name "$NS" --network "$NET" --cap-add NET_ADMIN --cap-add NET_RAW \
  -v "$WORK:/cap" "$SNIFFER" tcpdump -i any -nn -U -w /cap/brain.pcap >/dev/null
FAKE_IP=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}" "$FAKE")
NS_IP=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}" "$NS")

start_brain() {
  docker run -d --name "$BRAIN" --network "container:$NS" \
    --read-only --init --security-opt no-new-privileges \
    --env-file "$WORK/server.env" \
    -e WHELK_BRAIN_MODEL=fake-chat -e WHELK_BRAIN_EMBED_MODEL=fake-embed \
    -v "$VOL:/var/lib/falkordb/data" "$IMAGE" >/dev/null
  for _ in $(seq 1 120); do
    if docker exec "$BRAIN" /app/mcp/.venv/bin/python -c \
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" \
      >/dev/null 2>&1; then
      return 0
    fi
    [ "$(docker inspect -f '{{.State.Running}}' "$BRAIN")" = true ] || break
    sleep 1
  done
  docker logs "$BRAIN" 2>&1 | tail -40
  fail "the brain did not become healthy"
}

probe() {
  docker run --rm --network "$NET" --user "$(id -u):$(id -g)" -e BRAIN_TOKEN \
    -v "$HERE:/test:ro" -v "$WORK:/out" --entrypoint /app/mcp/.venv/bin/python \
    "$IMAGE" /test/mcp_probe.py "$@"
}

step "start the brain: read-only root, no tmpfs, scratch volume"
start_brain
[ "$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' "$BRAIN")" = true ] || fail "root is writable"
[ "$(docker inspect -f '{{len .HostConfig.Tmpfs}}' "$BRAIN")" = 0 ] || fail "a tmpfs is mounted"
echo "ok: root filesystem is read-only and no tmpfs is mounted"
[ "$(docker exec "$BRAIN" id -u)" = 10251 ] || fail "the brain does not run as uid 10251"
echo "ok: the brain runs as uid 10251"

step "bearer gate on /mcp/"
probe auth "http://$NS:8000/mcp/"

step "FalkorDB is internal only"
if docker run --rm --network "$NET" --entrypoint /app/mcp/.venv/bin/python "$IMAGE" -c \
  "import socket; socket.create_connection(('$NS', 6379), timeout=3)" >/dev/null 2>&1; then
  fail "FalkorDB answers on the container's network address"
fi
echo "ok: port 6379 refuses a connection from another container"

step "write, search and fetch sources"
probe write "http://$NS:8000/mcp/" /out/state.json

step "restart on the same volume"
docker stop -t 30 "$BRAIN" >/dev/null
docker rm "$BRAIN" >/dev/null
start_brain
probe read "http://$NS:8000/mcp/" /out/state.json

step "every model call went to WHELK_SERVER_URL with the token"
docker logs "$FAKE" >"$WORK/fake.log" 2>&1
python3 - "$WORK/fake.log" <<'PY'
import collections, json, sys
lines = [json.loads(l) for l in open(sys.argv[1]) if l.startswith('{')]
calls = collections.Counter((l['path'], l.get('model'), l['auth']) for l in lines)
for key, count in sorted(calls.items()):
    print(f'  {count:4d}  {key[0]}  model={key[1]}  auth={key[2]}')
allowed = {('/v1/chat/completions', 'fake-chat', 'ok'), ('/v1/embeddings', 'fake-embed', 'ok')}
stray = set(calls) - allowed
if not lines or stray:
    sys.exit(f'FAIL: unexpected calls to the fake server: {sorted(stray)}')
if {k[0] for k in calls} != {'/v1/chat/completions', '/v1/embeddings'}:
    sys.exit('FAIL: the brain did not call both the chat and the embeddings route')
print('ok: only /v1/chat/completions (fake-chat) and /v1/embeddings (fake-embed), all with the token')
formats = {l.get('format') for l in lines if l['path'] == '/v1/chat/completions'}
if formats != {'text'}:
    sys.exit(f'FAIL: chat calls must ask for JSON in the prompt with response_format text; saw {sorted(map(str, formats))}')
print('ok: every chat call asked for JSON in the prompt (response_format text)')
PY

step "no traffic to any other host"
docker stop "$NS" >/dev/null
pcap() {
  docker run --rm -v "$WORK:/cap" --entrypoint tcpdump "$SNIFFER" -nn -vv -r /cap/brain.pcap "$1" 2>/dev/null
}
pcap "src host $NS_IP and tcp[tcpflags] & tcp-syn != 0 and tcp[tcpflags] & tcp-ack == 0" >"$WORK/syn.txt"
pcap "src host $NS_IP and udp" >"$WORK/udp.txt"
pcap "src host 127.0.0.11 and udp" >"$WORK/dns.txt"
python3 - "$WORK/syn.txt" "$WORK/udp.txt" "$WORK/dns.txt" "$FAKE_IP" <<'PY'
import re, sys
syn, udp, dns = (open(path).read() for path in sys.argv[1:4])
fake = sys.argv[4]
targets = sorted(set(re.findall(r' > (\d+\.\d+\.\d+\.\d+)\.(\d+):', syn)))
names = sorted(set(re.findall(r'q: (?:A|AAAA)\? (\S+?)\.? ', dns)))
print(f'  outbound TCP connections: {targets}')
print(f'  outbound UDP packets: {len(udp.splitlines())}')
print(f'  names resolved through the container resolver: {names}')
if not targets or not names:
    sys.exit('FAIL: the capture shows no outbound connection or no lookup; the capture is broken')
if any(host != fake for host, _ in targets):
    sys.exit(f'FAIL: the brain opened a connection to a host other than WHELK_SERVER_URL ({fake})')
if udp.strip():
    sys.exit('FAIL: the brain sent UDP off the container')
if any(name != 'whelk-server' for name in names):
    sys.exit('FAIL: the brain looked up a name other than the WHELK_SERVER_URL host')
print(f'ok: every outbound connection went to {fake}:41235, the only name looked up is whelk-server')
PY

step "PASS"
