#!/usr/bin/env python3
"""Build-time patch: ask for JSON in the prompt, not through a constrained format.

graphiti's OpenAIGenericClient asks for structured output with `response_format`, as
`json_schema` (constrained decoding) or `json_object`. LM Studio accepts only
`json_schema` or `text`, and for an MLX reasoning model such as qwen3.8-27b-mlx its
constrained `json_schema` decoding returns an empty message with finish_reason `stop`.
graphiti then raises "LLM returned an empty response" and no episode is ever extracted.
The same model, asked in plain text with the schema in the prompt, returns valid JSON.

This patch adds a third mode, `prompt`: the schema goes into the prompt the way
`json_object` mode already puts it there, and the request sends `response_format`
`text`, which every OpenAI-compatible server accepts. The brain image defaults to it,
because Whelk Server fronts whatever engine the operator runs: brain/config.yaml sets
`structured_output_mode: prompt`. The config schema learns the third value too.

Idempotent; FAILS THE BUILD if an anchor is missing.
"""
import sys
from pathlib import Path

target = Path(
    '/app/mcp/.venv/lib/python3.13/site-packages/graphiti_core/llm_client/openai_generic_client.py'
)
src = target.read_text()

if "'json_object', 'prompt']" in src:
    print('prompt-json patch already applied — nothing to do')
    sys.exit(0)


def replace_once(text: str, anchor: str, replacement: str, what: str) -> str:
    count = text.count(anchor)
    if count != 1:
        sys.exit(f'PATCH FAILED: expected exactly 1 match for {what}, found {count}')
    return text.replace(anchor, replacement, 1)


src = replace_once(
    src,
    "StructuredOutputMode = Literal['json_schema', 'json_object']",
    "StructuredOutputMode = Literal['json_schema', 'json_object', 'prompt']",
    'the StructuredOutputMode literal',
)
src = replace_once(
    src,
    "        if response_model is None or self.structured_output_mode == 'json_object':",
    "        if self.structured_output_mode == 'prompt':\n"
    "            return {'type': 'text'}\n"
    "        if response_model is None or self.structured_output_mode == 'json_object':",
    'the response_format builder',
)
src = replace_once(
    src,
    "        if response_model is not None and self.structured_output_mode == 'json_object':",
    "        if response_model is not None and self.structured_output_mode in ('json_object', 'prompt'):",
    'the schema-in-prompt condition',
)

target.write_text(src)

schema = Path('/app/mcp/src/config/schema.py')
ssrc = schema.read_text()
if "Literal['json_schema', 'json_object', 'prompt']" not in ssrc:
    ssrc = replace_once(
        ssrc,
        "    structured_output_mode: Literal['json_schema', 'json_object'] = Field(",
        "    structured_output_mode: Literal['json_schema', 'json_object', 'prompt'] = Field(",
        'the config schema literal',
    )
    schema.write_text(ssrc)
print('prompt-json patch applied')
