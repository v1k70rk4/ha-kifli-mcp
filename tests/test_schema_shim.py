"""Schema shim normalization: what Home Assistant and the LLM APIs accept."""

from __future__ import annotations

import copy

import pytest
from jsonschema import Draft202012Validator
from mcp_schema_shim import PLACEHOLDER_ARG, simplify_schema

# Known gaps (CodeRabbit on #4): the expected outputs below are correct, the shim does not produce
# them yet. strict=True makes these tests fail once the shim is fixed, so the marker gets removed.
KNOWN_GAP = pytest.mark.xfail(
    strict=True,
    reason="known gap: the shim loosens this constraint – fix pending (runtime change, needs a version bump)",
)


def _walk(node):
    """Every dict node of the schema, recursively."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _obj(**props):
    return {"type": "object", "properties": props}


# --- 1.2.1: Home Assistant 2026.9 (probatio) rewrote numeric exclusive* bounds into the draft-04
# boolean form, and the Anthropic API then rejected the ENTIRE tool list ---------------------------

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


def test_draft04_boolean_exclusive_keyword_is_removed():
    out = simplify_schema(_obj(n={"type": "integer", "minimum": 0, "exclusiveMinimum": True}))
    assert "exclusiveMinimum" not in out["properties"]["n"]


@KNOWN_GAP
def test_draft04_exclusive_integer_minimum_stays_strict():
    # draft-04: minimum 0 + exclusiveMinimum true rejects 0, so for integers the bound is 1
    out = simplify_schema(_obj(n={"type": "integer", "minimum": 0, "exclusiveMinimum": True}))
    assert out["properties"]["n"] == {"type": "integer", "minimum": 1}


def test_no_exclusive_keyword_survives_anywhere():
    # modelled on the three affected upstream tools (e.g. add_products_to_shopping_list): nested and behind a $ref
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


# --- $ref, unions --------------------------------------------------------------------------------

@pytest.mark.parametrize("defs_key", ["$defs", "definitions"])
def test_local_refs_are_inlined_and_dollar_keys_removed(defs_key):
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"item": {"$ref": f"#/{defs_key}/Item", "description": "The item"}},
        defs_key: {"Item": {"type": "object", "properties": {"id": {"type": "integer"}}}},
    }
    out = simplify_schema(schema)
    item = out["properties"]["item"]
    assert item["properties"]["id"] == {"type": "integer"}
    assert item["description"] == "The item"  # keys next to the $ref are kept
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
                                     "description": "A note"}))
    assert out["properties"]["note"] == {"type": "string", "description": "A note"}


def test_allof_keeps_the_type_and_the_title():
    out = simplify_schema(_obj(n={"allOf": [{"type": "integer"}, {"minimum": 1}], "title": "N"}))
    assert out["properties"]["n"]["type"] == "integer"
    assert out["properties"]["n"]["title"] == "N"


@KNOWN_GAP
def test_allof_keeps_constraints_from_every_branch():
    # the input requires an integer of at least 1; dropping the second branch would allow 0
    out = simplify_schema(_obj(n={"allOf": [{"type": "integer"}, {"minimum": 1}], "title": "N"}))
    assert out["properties"]["n"] == {"type": "integer", "minimum": 1, "title": "N"}


# --- types, unsupported keywords -----------------------------------------------------------------

def test_properties_named_like_keywords_are_not_treated_as_keywords():
    # the dict under 'properties' is a mapping, not a schema: fields named 'items' / 'type' are not keywords
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


# --- root: HA / OpenAI expect an object as function parameters, without empty properties ---------

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
