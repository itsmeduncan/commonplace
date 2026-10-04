#!/usr/bin/env python3
"""Drive the brain over MCP the way Whelk Server does, and assert the contract.

Stdlib only (runs in the brain image's own Python). Phases:

  auth  URL        /mcp/ refuses no bearer and a wrong bearer, and admits the right one
  write URL OUT    add_memory into two groups, then search_memory_facts, search_nodes,
                   and get_episodes with uuids (with the group filter); OUT gets the state
  read  URL IN     after a restart: the same facts and the same sources come back

The token comes from BRAIN_TOKEN in the environment, never from the command line.

Each failed check exits non-zero with a sentence that says what differed.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

TEAM, FINANCE = 'whelk-team', 'whelk-finance'
TEAM_TEXT = 'Alice leads Falcon. The launch review is on Tuesday.'
FINANCE_TEXT = 'Bob funds Falcon. The budget is approved.'
TEAM_SOURCE = json.dumps({'source': 'session', 'at': '2026-10-03T12:00:00Z', 'seat': 'alice'})
FINANCE_SOURCE = json.dumps({'source': 'github', 'at': '2026-10-03T12:01:00Z', 'agent': 'ingest'})


def fail(message):
    print(f'FAIL: {message}', file=sys.stderr)
    sys.exit(1)


def check(condition, message):
    if not condition:
        fail(message)
    print(f'ok: {message}')


def post(url, body, headers):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST')
    request.add_header('content-type', 'application/json')
    request.add_header('accept', 'application/json, text/event-stream')
    for key, value in headers.items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, dict(response.headers), response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read().decode()


def rpc_result(text):
    for line in text.splitlines():
        if line.startswith('data:'):
            text = line[5:].strip()
    message = json.loads(text)
    if 'error' in message:
        fail(f'JSON-RPC error: {message["error"]}')
    return message['result']


class Session:
    def __init__(self, url, token):
        self.url = url
        self.headers = {'authorization': f'Bearer {token}'}
        status, headers, text = post(url, self.initialize(), self.headers)
        if status != 200:
            fail(f'initialize answered {status}: {text[:200]}')
        session = {k.lower(): v for k, v in headers.items()}.get('mcp-session-id')
        if session:
            self.headers['mcp-session-id'] = session
        post(url, {'jsonrpc': '2.0', 'method': 'notifications/initialized'}, self.headers)
        self.next_id = 2

    @staticmethod
    def initialize():
        return {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'initialize',
            'params': {
                'protocolVersion': '2025-06-18',
                'capabilities': {},
                'clientInfo': {'name': 'brain-smoke', 'version': '1'},
            },
        }

    def call(self, tool, arguments):
        self.next_id += 1
        body = {
            'jsonrpc': '2.0',
            'id': self.next_id,
            'method': 'tools/call',
            'params': {'name': tool, 'arguments': arguments},
        }
        status, _, text = post(self.url, body, self.headers)
        if status != 200:
            fail(f'{tool} answered HTTP {status}: {text[:200]}')
        result = rpc_result(text)
        if result.get('isError'):
            fail(f'{tool} returned an error: {result}')
        return json.loads(result['content'][0]['text'])


def facts(session, groups):
    found = session.call(
        'search_memory_facts', {'query': 'Falcon', 'group_ids': groups, 'max_facts': 10}
    )
    return found.get('facts', [])


def wait_for_facts(session, groups, count, seconds=180):
    deadline = time.time() + seconds
    while time.time() < deadline:
        found = facts(session, groups)
        if len(found) >= count:
            return found
        time.sleep(2)
    fail(f'only {len(facts(session, groups))} of {count} facts appeared in {seconds}s')


def episodes(session, uuids, groups):
    found = session.call(
        'get_episodes', {'uuids': uuids, 'group_ids': groups, 'max_episodes': len(uuids)}
    )
    return {e['uuid']: e for e in found.get('episodes', [])}


def phase_auth(url, token):
    for label, headers in (
        ('no bearer', {}),
        ('a wrong bearer', {'authorization': 'Bearer not-the-token'}),
        ('a bearer with a wrong scheme', {'authorization': token}),
    ):
        status, _, _ = post(url, Session.initialize(), headers)
        check(status == 401, f'/mcp/ refuses {label} with 401 (got {status})')
    status, _, _ = post(url.rstrip('/'), Session.initialize(), {})
    check(status == 401, f'/mcp without the slash also refuses no bearer (got {status})')
    Session(url, token)
    print('ok: /mcp/ admits the right bearer and completes initialize')


def phase_write(url, token, out):
    session = Session(url, token)
    for name, body, group, source in (
        ('Falcon lead', TEAM_TEXT, TEAM, TEAM_SOURCE),
        ('Falcon funding', FINANCE_TEXT, FINANCE, FINANCE_SOURCE),
    ):
        answer = session.call(
            'add_memory',
            {
                'name': name,
                'episode_body': body,
                'group_id': group,
                'source': 'text',
                'source_description': source,
            },
        )
        check('error' not in answer, f'add_memory queued "{name}" in {group}')

    both = wait_for_facts(session, [TEAM, FINANCE], 2)
    texts = sorted(f['fact'] for f in both)
    check(texts == ['Alice leads Falcon', 'Bob funds Falcon'], f'search_memory_facts finds both facts: {texts}')
    check(all(f.get('episodes') for f in both), 'each fact names its source episodes')
    check(
        {f['fact']: f['group_id'] for f in both} == {'Alice leads Falcon': TEAM, 'Bob funds Falcon': FINANCE},
        'each fact keeps the group it was written to',
    )
    for group, expected in ((TEAM, 'Alice leads Falcon'), (FINANCE, 'Bob funds Falcon')):
        only = [f['fact'] for f in facts(session, [group])]
        check(only == [expected], f'a {group}-only search sees only its own fact: {only}')

    nodes = session.call('search_nodes', {'query': 'Falcon', 'group_ids': [TEAM, FINANCE], 'max_nodes': 10})
    falcons = {n['group_id']: n for n in nodes.get('nodes', []) if n['name'] == 'Falcon'}
    check(sorted(falcons) == sorted([TEAM, FINANCE]), 'search_nodes finds the entity once in each group')

    related = session.call(
        'search_memory_facts',
        {'query': 'Falcon', 'group_ids': [TEAM], 'max_facts': 10, 'center_node_uuid': falcons[TEAM]['uuid']},
    )
    check(
        [f['fact'] for f in related.get('facts', [])] == ['Alice leads Falcon'],
        'a fact search centred on that node (brain.related) returns its facts',
    )

    uuids = [u for f in both for u in f['episodes']]
    by_uuid = episodes(session, uuids, [TEAM, FINANCE])
    check(sorted(by_uuid) == sorted(uuids), 'get_episodes with uuids returns exactly those episodes')
    sources = sorted(e['source_description'] for e in by_uuid.values())
    check(sources == sorted([TEAM_SOURCE, FINANCE_SOURCE]), 'each episode keeps its JSON provenance')
    team_eps = episodes(session, uuids, [TEAM])
    check(
        [e['group_id'] for e in team_eps.values()] == [TEAM],
        'get_episodes with uuids drops an episode from a group the caller did not ask for',
    )

    state = {'facts': {f['uuid']: f['fact'] for f in both}, 'episodes': {u: by_uuid[u]['source_description'] for u in uuids}}
    with open(out, 'w') as handle:
        json.dump(state, handle)


def phase_read(url, token, path):
    with open(path) as handle:
        state = json.load(handle)
    session = Session(url, token)
    found = facts(session, [TEAM, FINANCE])
    check(
        {f['uuid']: f['fact'] for f in found} == state['facts'],
        'after the restart the same facts come back with the same uuids',
    )
    by_uuid = episodes(session, list(state['episodes']), [TEAM, FINANCE])
    check(
        {u: e['source_description'] for u, e in by_uuid.items()} == state['episodes'],
        'after the restart the same sources come back',
    )


if __name__ == '__main__':
    phase, url, *rest = sys.argv[1:]
    token = os.environ['BRAIN_TOKEN']
    {'auth': phase_auth, 'write': phase_write, 'read': phase_read}[phase](url, token, *rest)
