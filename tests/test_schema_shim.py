"""A schema shim normalizálása: amit a Home Assistant és az LLM API-k elfogadnak."""

from __future__ import annotations

import copy

import pytest
from jsonschema import Draft202012Validator
from mcp_schema_shim import PLACEHOLDER_ARG, simplify_schema


def _walk(node):
    """A séma összes dict csomópontja, rekurzívan."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _obj(**props):
    return {"type": "object", "properties": props}


# --- 1.2.1: a HA 2026.9 (probatio) a numerikus exclusive* határt draft-04 boolean-ra írta át,
# és az Anthropic API emiatt az EGÉSZ tool-listát elutasította --------------------------------

def test_integer_exclusive_bounds_become_inclusive():
    out = simplify_schema(_obj(qty={"type": "integer", "exclusiveMinimum": 0, "exclusiveMaximum": 10}))
    assert out["properties"]["qty"] == {"type": "integer", "minimum": 1, "maximum": 9}


def test_number_exclusive_bound_is_kept_as_bound():
    out = simplify_schema(_obj(price={"type": "number", "exclusiveMinimum": 0.5}))
    assert out["properties"]["price"] == {"type": "number", "minimum": 0.5}


def test_exclusive_bound_never_loosens_an_existing_bound():
    out = simplify_schema(_obj(
        lo={"type": "integer", "minimum": 5, "exclusiveMinimum": 0},
        hi={"type": "integer", "maximum": 3, "exclusiveMaximum": 10},
    ))
    assert out["properties"]["lo"]["minimum"] == 5
    assert out["properties"]["hi"]["maximum"] == 3


def test_draft04_boolean_exclusive_is_dropped():
    out = simplify_schema(_obj(n={"type": "integer", "minimum": 0, "exclusiveMinimum": True}))
    assert out["properties"]["n"] == {"type": "integer", "minimum": 0}


def test_no_exclusive_keyword_survives_anywhere():
    # a három érintett upstream tool (pl. add_products_to_shopping_list) mintájára: beágyazva, $ref mögött is
    schema = {
        "type": "object",
        "properties": {
            "products": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "productId": {"type": "integer", "exclusiveMinimum": 0},
                        "amount": {"$ref": "#/$defs/Amount"},
                    },
                },
            },
        },
        "$defs": {"Amount": {"type": "integer", "exclusiveMinimum": 0, "exclusiveMaximum": 1000}},
    }
    out = simplify_schema(schema)
    for node in _walk(out):
        assert "exclusiveMinimum" not in node
        assert "exclusiveMaximum" not in node
    item = out["properties"]["products"]["items"]["properties"]
    assert item["productId"]["minimum"] == 1
    assert item["amount"] == {"type": "integer", "minimum": 1, "maximum": 999}


# --- $ref, unionok -------------------------------------------------------------------------------

@pytest.mark.parametrize("defs_key", ["$defs", "definitions"])
def test_local_refs_are_inlined_and_dollar_keys_removed(defs_key):
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"item": {"$ref": f"#/{defs_key}/Item", "description": "A tétel"}},
        defs_key: {"Item": {"type": "object", "properties": {"id": {"type": "integer"}}}},
    }
    out = simplify_schema(schema)
    item = out["properties"]["item"]
    assert item["properties"]["id"] == {"type": "integer"}
    assert item["description"] == "A tétel"  # a $ref melletti kulcsok megmaradnak
    assert defs_key not in out
    assert not any(k.startswith("$") for node in _walk(out) for k in node)


def test_recursive_ref_terminates():
    schema = {
        "type": "object",
        "properties": {"node": {"$ref": "#/$defs/Node"}},
        "$defs": {"Node": {"type": "object", "properties": {"child": {"$ref": "#/$defs/Node"}}}},
    }
    out = simplify_schema(schema)
    assert out["properties"]["node"]["type"] == "object"
    assert not any("$ref" in node for node in _walk(out))


@pytest.mark.parametrize("union", ["anyOf", "oneOf"])
def test_nullable_union_picks_the_real_type(union):
    out = simplify_schema(_obj(note={union: [{"type": "null"}, {"type": "string"}], "default": None,
                                     "description": "Megjegyzés"}))
    assert out["properties"]["note"] == {"type": "string", "description": "Megjegyzés"}


def test_allof_takes_the_first_part_and_keeps_the_title():
    out = simplify_schema(_obj(n={"allOf": [{"type": "integer"}, {"minimum": 1}], "title": "N"}))
    assert out["properties"]["n"] == {"type": "integer", "title": "N"}


# --- típusok, nem támogatott kulcsok ------------------------------------------------------------

def test_properties_named_like_keywords_are_not_treated_as_keywords():
    # a 'properties' alatti dict mapping, nem séma: az 'items' / 'type' nevű mező nem kulcsszó
    out = simplify_schema(_obj(items={"type": "array", "items": {"type": "integer"}}, type={"type": "string"}))
    assert out["properties"]["items"] == {"type": "array", "items": {"type": "integer"}}
    assert out["properties"]["type"] == {"type": "string"}


def test_missing_types_are_inferred():
    out = simplify_schema({"properties": {
        "choice": {"enum": ["a", "b"]},
        "tags": {"items": {"type": "string"}},
        "obj": {"required": ["x"], "properties": {"x": {"type": "string"}}},
    }})
    assert out["type"] == "object"
    assert out["properties"]["choice"]["type"] == "string"
    assert out["properties"]["tags"]["type"] == "array"
    assert out["properties"]["obj"]["type"] == "object"


def test_unsupported_keywords_and_null_defaults_are_removed():
    out = simplify_schema(_obj(ids={"type": "array", "items": {"type": "integer"}, "uniqueItems": True},
                               name={"type": "string", "default": None}))
    assert "uniqueItems" not in out["properties"]["ids"]
    assert "default" not in out["properties"]["name"]


# --- gyökér: a HA / OpenAI function paraméterként objektumot vár, nem üres properties-szel -------

@pytest.mark.parametrize("schema", [None, {}, {"type": "object"}, {"type": "string"}, {"type": "array"}])
def test_root_is_always_an_object_with_the_placeholder(schema):
    out = simplify_schema(schema)
    assert out["type"] == "object"
    assert out["additionalProperties"] is True
    assert list(out["properties"]) == [PLACEHOLDER_ARG]


def test_existing_properties_get_no_placeholder_and_keep_additional_properties():
    out = simplify_schema({**_obj(q={"type": "string"}), "additionalProperties": False})
    assert list(out["properties"]) == ["q"]
    assert out["additionalProperties"] is False


def test_input_is_not_mutated():
    schema = {"type": "object", "properties": {"n": {"$ref": "#/$defs/N"}},
              "$defs": {"N": {"type": "integer", "exclusiveMinimum": 0}}}
    before = copy.deepcopy(schema)
    simplify_schema(schema)
    assert schema == before


SAMPLES = [
    None,
    _obj(qty={"type": "integer", "exclusiveMinimum": 0}),
    _obj(note={"anyOf": [{"type": "string"}, {"type": "null"}], "default": None}),
    {"type": "object", "properties": {"x": {"$ref": "#/$defs/X"}},
     "$defs": {"X": {"type": "object", "properties": {"y": {"oneOf": [{"type": "integer"}, {"type": "null"}]}}}}},
    {"properties": {"items": {"items": {"enum": ["a"]}, "uniqueItems": True}}},
]


@pytest.mark.parametrize("schema", SAMPLES)
def test_output_is_a_valid_2020_12_schema(schema):
    Draft202012Validator.check_schema(simplify_schema(schema))
