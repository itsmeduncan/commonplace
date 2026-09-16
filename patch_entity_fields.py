#!/usr/bin/env python3
"""Build-time patch: let config entity types declare optional TYPED fields.

Upstream builds one model per configured entity type in
``utils/type_config.py::build_entity_types``: it prefers a rich model registered in
``models.entity_types.ENTITY_TYPES`` (matched by name), else a documentation-only
model built from name + description. So ``config/*.yaml`` can only give a *custom*
entity a name + description — never structured attributes like ``Decision.rationale``
or ``Deliverable.due_date`` (the rich models exist only for upstream's own hardcoded
types), which conflicts with this project's "ontology lives in config" tenet.

This patch keeps the ontology in config: it adds an optional ``fields:`` list to the
entity-type config schema and teaches ``build_entity_types`` to construct a real typed
model from it. A config-declared ``fields:`` list WINS over any registered upstream
model, so the config is authoritative. Every declared field is made OPTIONAL
(``T | None``, default None) so the weak local extractor is never forced to populate
one — a field it can't fill is left empty, not an error.

Fully backward-compatible: an entity type with no ``fields:`` builds exactly what
upstream would (registered rich model, else doc-only). Two baked files are edited:
  - config/schema.py         — add EntityFieldConfig + EntityTypeConfig.fields
  - utils/type_config.py      — build typed models via pydantic.create_model when fields exist

Idempotent; FAILS THE BUILD if any anchor is missing (CI's docker build exercises this).
The upstream entity-type build path was refactored out of graphiti_mcp_server.py into
utils/type_config.py; re-anchor here if a future bump moves it again.

Tracks: https://github.com/itsmeduncan/commonplace/issues/14
"""
import sys
from pathlib import Path

MCP_ROOT = Path('/app/mcp/src')


def replace_once(text: str, anchor: str, replacement: str, what: str) -> str:
    n = text.count(anchor)
    if n != 1:
        sys.exit(f'PATCH FAILED: expected exactly 1 match for {what}, found {n}')
    return text.replace(anchor, replacement, 1)


# ---- 1) config/schema.py: add a typed-field config model + a `fields` list ----
schema_path = MCP_ROOT / 'config' / 'schema.py'
schema = schema_path.read_text()

if 'class EntityFieldConfig' not in schema:
    schema = replace_once(
        schema,
        'class EntityTypeConfig(BaseModel):\n'
        '    """Entity type configuration.\n'
        '\n'
        '    If ``name`` matches a model registered in ``models.entity_types.ENTITY_TYPES``,\n'
        '    the rich Pydantic model (with its attributes and extraction instructions) is\n'
        '    registered with graphiti-core. Otherwise a documentation-only model is built\n'
        '    from ``name`` + ``description`` for backward compatibility.\n'
        '    """\n'
        '\n'
        '    name: str\n'
        '    description: str\n',
        'class EntityFieldConfig(BaseModel):\n'
        '    """An optional typed attribute on an entity type."""\n'
        '\n'
        "    name: str\n"
        "    type: str = 'str'  # str | int | float | bool (anything else falls back to str)\n"
        "    description: str = ''\n"
        '\n'
        '\n'
        'class EntityTypeConfig(BaseModel):\n'
        '    """Entity type configuration.\n'
        '\n'
        '    If ``name`` matches a model registered in ``models.entity_types.ENTITY_TYPES``,\n'
        '    the rich Pydantic model (with its attributes and extraction instructions) is\n'
        '    registered with graphiti-core. Otherwise a documentation-only model is built\n'
        '    from ``name`` + ``description`` for backward compatibility.\n'
        '\n'
        '    A config-declared ``fields:`` list wins over any registered model, so the\n'
        '    ontology stays in config (issue #14).\n'
        '    """\n'
        '\n'
        '    name: str\n'
        '    description: str\n'
        '    fields: list[EntityFieldConfig] = Field(default_factory=list)\n',
        'the EntityTypeConfig definition in schema.py',
    )
    schema_path.write_text(schema)
    print('entity-fields patch: schema.py OK')
else:
    print('entity-fields patch: schema.py already patched')


# ---- 2) utils/type_config.py: build typed models from the new `fields` ----
tc_path = MCP_ROOT / 'utils' / 'type_config.py'
tc = tc_path.read_text()

if 'from pydantic import BaseModel, create_model\n' in tc:
    tc = replace_once(
        tc,
        'from pydantic import BaseModel, create_model\n',
        'from pydantic import BaseModel, Field, create_model\n',
        'the pydantic import in type_config.py',
    )

if '# issue #14: config-declared typed fields' not in tc:
    tc = replace_once(
        tc,
        '    result: dict[str, type[BaseModel]] = {}\n'
        '    for cfg in entity_type_configs:\n'
        '        registered = ENTITY_TYPES.get(cfg.name)\n'
        '        result[cfg.name] = (\n'
        '            registered if registered is not None else _doc_only_model(cfg.name, cfg.description)\n'
        '        )\n'
        '    return result\n',
        '    result: dict[str, type[BaseModel]] = {}\n'
        '    for cfg in entity_type_configs:\n'
        '        # issue #14: config-declared typed fields win over any registered model,\n'
        '        # so the ontology stays in config. All fields are OPTIONAL so the (often\n'
        "        # weak, local) extractor is never forced to populate one it can't fill.\n"
        "        typed_fields = getattr(cfg, 'fields', None)\n"
        '        if typed_fields:\n'
        "            _PYTYPES = {'str': str, 'int': int, 'float': float, 'bool': bool}\n"
        '            field_defs = {\n'
        '                f.name: (\n'
        '                    _PYTYPES.get(f.type, str) | None,\n'
        '                    Field(default=None, description=f.description),\n'
        '                )\n'
        '                for f in typed_fields\n'
        '            }\n'
        '            result[cfg.name] = create_model(\n'
        '                cfg.name, __doc__=cfg.description, **field_defs\n'
        '            )\n'
        '            continue\n'
        '        registered = ENTITY_TYPES.get(cfg.name)\n'
        '        result[cfg.name] = (\n'
        '            registered if registered is not None else _doc_only_model(cfg.name, cfg.description)\n'
        '        )\n'
        '    return result\n',
        'the build_entity_types loop in type_config.py',
    )

tc_path.write_text(tc)
print('entity-fields patch: type_config.py OK')
