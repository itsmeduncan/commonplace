#!/usr/bin/env python3
"""Build-time patch: let config entity types declare optional TYPED fields.

Upstream (mcp-v1.0.2) builds one fieldless Pydantic model per configured entity type
(`type(name, (BaseModel,), {'__doc__': description})`), so `config/*.yaml` can only give
an entity a name + description — never structured attributes like `Decision.rationale` or
`Deliverable.due_date`. graphiti supports typed entity fields (its built-in `Requirement`
has `project_name`), but that route needs code-defined models, which conflicts with this
project's "ontology lives in config" tenet.

This patch keeps the ontology in config: it adds an optional `fields:` list to the entity-
type config schema and teaches the build loop to construct a real typed model from it. Every
declared field is made OPTIONAL (`T | None`, default None) so the weak local extractor is
never forced to populate one — a field it can't fill is simply left empty, not an error.

Fully backward-compatible: an entity type with no `fields:` builds the exact same fieldless
model as before. Two baked files are edited:
  - config/schema.py         — add EntityFieldConfig + EntityTypeConfig.fields
  - graphiti_mcp_server.py    — build typed models via pydantic.create_model when fields exist

Idempotent; FAILS THE BUILD if any anchor is missing (CI's docker build exercises this).

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
        '    """Entity type configuration."""\n'
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
        '    """Entity type configuration."""\n'
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


# ---- 2) graphiti_mcp_server.py: build typed models from the new `fields` ----
gms_path = MCP_ROOT / 'graphiti_mcp_server.py'
gms = gms_path.read_text()

if 'create_model' not in gms:
    gms = replace_once(
        gms,
        'from pydantic import BaseModel\n',
        'from pydantic import BaseModel, Field, create_model\n',
        'the pydantic import in graphiti_mcp_server.py',
    )

if '_TYPED_FIELD_PYTYPES' not in gms:
    gms = replace_once(
        gms,
        '                    # Create a dynamic Pydantic model for each entity type\n'
        "                    # Note: Don't use 'name' as it's a protected Pydantic attribute\n"
        '                    entity_model = type(\n'
        '                        entity_type.name,\n'
        '                        (BaseModel,),\n'
        '                        {\n'
        "                            '__doc__': entity_type.description,\n"
        '                        },\n'
        '                    )\n'
        '                    custom_types[entity_type.name] = entity_model\n',
        '                    # Create a dynamic Pydantic model for each entity type\n'
        "                    # Note: Don't use 'name' as it's a protected Pydantic attribute\n"
        '                    typed_fields = getattr(entity_type, \'fields\', None)\n'
        '                    if typed_fields:\n'
        '                        # Typed attributes from config. All OPTIONAL so the (often\n'
        '                        # weak, local) extractor is never forced to populate a field.\n'
        "                        _TYPED_FIELD_PYTYPES = {'str': str, 'int': int, 'float': float, 'bool': bool}\n"
        '                        field_defs = {\n'
        '                            f.name: (\n'
        '                                _TYPED_FIELD_PYTYPES.get(f.type, str) | None,\n'
        '                                Field(default=None, description=f.description),\n'
        '                            )\n'
        '                            for f in typed_fields\n'
        '                        }\n'
        '                        entity_model = create_model(\n'
        '                            entity_type.name,\n'
        '                            __doc__=entity_type.description,\n'
        '                            **field_defs,\n'
        '                        )\n'
        '                    else:\n'
        '                        entity_model = type(\n'
        '                            entity_type.name,\n'
        '                            (BaseModel,),\n'
        '                            {\n'
        "                                '__doc__': entity_type.description,\n"
        '                            },\n'
        '                        )\n'
        '                    custom_types[entity_type.name] = entity_model\n',
        'the entity-model build loop in graphiti_mcp_server.py',
    )

gms_path.write_text(gms)
print('entity-fields patch: graphiti_mcp_server.py OK')
