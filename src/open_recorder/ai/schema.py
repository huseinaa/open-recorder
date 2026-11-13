"""The shape of an AI answer: a short reply plus the ops to apply. The ops are the same edit
language the timeline uses (core/ops), so whatever the AI does, Ctrl+Z undoes."""
from __future__ import annotations

from ..core.model import ASPECTS, FITS, LANE_KINDS, MASKS

AI_OPS = ["cut_range", "split", "delete", "ripple_delete", "trim", "move", "add_clip", "add_recording",
          "add_lane", "set_lane", "add_blur", "set_blur", "detach_audio", "set_transform", "set_mask",
          "reset_layout", "set_volume", "set_sequence", "link", "unlink"]

_num = {"type": "number"}
_str = {"type": "string"}
_bool = {"type": "boolean"}
_ids = {"type": "array", "items": _str}

OP_SCHEMA = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": AI_OPS},
        "t": _num, "start": _num, "end": _num, "src_in": _num, "src_out": _num,
        "clip": _str, "clips": _ids, "lane": _str, "lanes": _ids, "media": _str, "recording": _str,
        "ripple": _bool, "link": _bool, "relayout": _bool, "hidden": _bool, "muted": _bool, "locked": _bool,
        "x": _num, "y": _num, "w": _num, "h": _num, "opacity": _num, "radius": _num,
        "strength": _num, "volume": _num, "index": {"type": "integer"}, "name": _str,
        "kind": {"type": "string", "enum": list(LANE_KINDS)},
        "mask": {"type": "string", "enum": list(MASKS)},
        "fit": {"type": "string", "enum": list(FITS)},
        "aspect": {"type": "string", "enum": list(ASPECTS)},
    },
    "required": ["op"],
}

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "ops": {"type": "array", "items": OP_SCHEMA},
    },
    "required": ["reply", "ops"],
}


# ---------- OpenAI's strict structured output (Codex) ----------
_UNSUPPORTED = ("maxLength", "minLength")


def strict(schema):
    """Every object lists all its keys as required and allows no others; a key that was
    optional becomes nullable instead, and prune() removes those nulls again."""
    if isinstance(schema, list):
        return [strict(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out = {k: v for k, v in schema.items() if k not in _UNSUPPORTED}
    if "items" in out:
        out["items"] = strict(out["items"])
    for key in ("anyOf", "oneOf", "allOf"):
        if key in out:
            out[key] = strict(out[key])
    if "properties" in out:
        required = set(schema.get("required") or [])
        props = {}
        for name, sub in out["properties"].items():
            sub = strict(sub)
            props[name] = sub if name in required else _nullable(sub)
        out["properties"] = props
        out["required"] = list(props)
        out["additionalProperties"] = False
    return out


def _nullable(schema: dict) -> dict:
    schema = dict(schema)
    kind = schema.get("type")
    if isinstance(kind, str) and kind != "null":
        schema["type"] = [kind, "null"]
    elif isinstance(kind, list) and "null" not in kind:
        schema["type"] = [*kind, "null"]
    if "enum" in schema and None not in schema["enum"]:
        schema["enum"] = [*schema["enum"], None]
    return schema


def prune(value, schema):
    """Drop the nulls strict() allowed for keys the original schema made optional."""
    if not isinstance(schema, dict):
        return value
    if isinstance(value, dict) and "properties" in schema:
        required = set(schema.get("required") or [])
        return {k: prune(v, schema["properties"].get(k)) for k, v in value.items()
                if not (v is None and k not in required)}
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        return [prune(v, schema["items"]) for v in value]
    return value
