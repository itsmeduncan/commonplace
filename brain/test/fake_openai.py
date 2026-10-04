#!/usr/bin/env python3
"""A tiny OpenAI-compatible server that stands in for Whelk Server in the brain smoke test.

Stdlib only. It serves the two routes the brain calls, /v1/chat/completions and
/v1/embeddings, and logs one JSON line per request (path, model, whether the bearer
matched) so the test can prove what the brain sent and with which key.

Extraction is deterministic: a sentence of the form "<Name> <verb> <Name>." in the
CURRENT MESSAGE (or TEXT) block becomes two entities and one fact. Every other
structured call gets the smallest instance its JSON schema allows. Embeddings are hashed bags of words, so text
that shares words lands close together.

Usage: FAKE_TOKEN=... python3 fake_openai.py [port]
"""
import hashlib
import json
import math
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ['FAKE_TOKEN']
DIMENSIONS = 768
TRIPLE = re.compile(r'\b([A-Z][a-z]+) (leads|owns|reviews|funds) ([A-Z][a-z]+)\b')
CURRENT = re.compile(r'<(CURRENT[ _]MESSAGE|TEXT)>(.*?)</\1>', re.S)


LOG_LOCK = threading.Lock()


def log(**fields):
    line = json.dumps(fields) + '\n'
    with LOG_LOCK:
        sys.stdout.write(line)
        sys.stdout.flush()


def current_message(messages):
    text = '\n'.join(m.get('content') or '' for m in messages if m.get('role') == 'user')
    found = CURRENT.search(text)
    return found.group(2) if found else ''


def triples(messages):
    return TRIPLE.findall(current_message(messages))


def minimal(schema, defs):
    if '$ref' in schema:
        return minimal(defs[schema['$ref'].split('/')[-1]], defs)
    if 'anyOf' in schema:
        return minimal(schema['anyOf'][0], defs)
    kind = schema.get('type')
    if kind == 'object':
        props = schema.get('properties', {})
        return {k: minimal(props[k], defs) for k in schema.get('required', props.keys())}
    if kind == 'array':
        return []
    if kind == 'integer':
        return 0
    if kind == 'number':
        return 0.0
    if kind == 'boolean':
        return False
    if kind == 'null':
        return None
    return 'none'


def structured(name, schema, messages):
    if name == 'ExtractedEntities':
        names = dict.fromkeys(n for s, _, o in triples(messages) for n in (s, o))
        return {'extracted_entities': [{'name': n, 'entity_type_id': 0} for n in names]}
    if name == 'ExtractedEdges':
        return {
            'edges': [
                {
                    'source_entity_name': s,
                    'target_entity_name': o,
                    'relation_type': verb.upper(),
                    'fact': f'{s} {verb} {o}',
                }
                for s, verb, o in triples(messages)
            ]
        }
    return minimal(schema, schema.get('$defs', {}))


PROMPT_SCHEMA = 'Respond with a JSON object in the following format:'


def prompt_schema(messages):
    for message in reversed(messages):
        text = message.get('content') or ''
        at = text.rfind(PROMPT_SCHEMA)
        if at < 0:
            continue
        try:
            schema, _ = json.JSONDecoder().raw_decode(text[at + len(PROMPT_SCHEMA):].lstrip())
            return schema
        except ValueError:
            return {}
    return {}


def embed(text):
    vector = [0.0] * DIMENSIONS
    for word in re.findall(r'[a-z0-9]+', text.lower()):
        vector[int(hashlib.sha256(word.encode()).hexdigest(), 16) % DIMENSIONS] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('content-type', 'application/json')
        self.send_header('content-length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        log(path=self.path, method='GET', auth=self.auth())
        self.reply(404, {'error': 'not served'})

    def auth(self):
        return 'ok' if self.headers.get('authorization') == f'Bearer {TOKEN}' else 'bad'

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('content-length', 0))) or b'{}')
        auth = self.auth()
        if auth != 'ok':
            log(path=self.path, model=body.get('model'), auth=auth)
            return self.reply(401, {'error': 'bad key'})
        if self.path == '/v1/embeddings':
            inputs = body['input'] if isinstance(body['input'], list) else [body['input']]
            log(path=self.path, model=body.get('model'), auth=auth, inputs=len(inputs))
            return self.reply(
                200,
                {
                    'object': 'list',
                    'model': body.get('model'),
                    'data': [
                        {'object': 'embedding', 'index': i, 'embedding': embed(str(t))}
                        for i, t in enumerate(inputs)
                    ],
                    'usage': {'prompt_tokens': 1, 'total_tokens': 1},
                },
            )
        if self.path == '/v1/chat/completions':
            messages = body.get('messages', [])
            fmt = (body.get('response_format') or {}).get('json_schema') or {}
            schema, mode = fmt.get('schema', {}), 'json_schema'
            if not fmt:
                schema, mode = prompt_schema(messages), (body.get('response_format') or {}).get('type', 'none')
            name = fmt.get('name') or schema.get('title', '')
            content = structured(name, schema, messages)
            log(path=self.path, model=body.get('model'), auth=auth, schema=name, format=mode)
            return self.reply(
                200,
                {
                    'id': 'fake',
                    'object': 'chat.completion',
                    'created': 0,
                    'model': body.get('model'),
                    'choices': [
                        {
                            'index': 0,
                            'finish_reason': 'stop',
                            'message': {'role': 'assistant', 'content': json.dumps(content)},
                        }
                    ],
                    'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
                },
            )
        log(path=self.path, model=body.get('model'), auth=auth)
        self.reply(404, {'error': 'not served'})


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 41235
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
