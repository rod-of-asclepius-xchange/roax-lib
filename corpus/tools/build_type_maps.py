#!/usr/bin/env python3
"""Derive a ROAX type map for a MOH healthcert family from the reference schemas.

Specification section 4: the type tag MUST come from the schema and never from the JSON
literal's syntax. This tool exists so that the class 10 and class 11 bindings are derived
rather than observed. Nothing here looks at what a value LOOKS like; it looks only at what the
schema DECLARES, and where the schema declares nothing, or declares something ROAX's tag set
cannot represent, the path is reported UNBOUND rather than guessed.

That distinction is the whole point. A map built by reading the sample would be syntactic
inference with extra steps, and it would poison classes 10 and 11 together.

Resolution rules, and why each is what it is:

  - `$ref` is followed BY FILE PATH, never by `$id`. Two of the reference schemas carry
    copy-pasted `$id` values - recovery points at PDT's path and vaccination at a PDT interim
    path - so a resolver keyed on `$id` silently applies the wrong rules.
  - A union (`oneOf`/`anyOf`/`allOf`, and `ResourceList` in particular) is explored along EVERY
    branch. A binding is accepted only when every branch that resolves the path agrees on the
    tag. First-branch-wins would bind `fhirBundle.entry[*].resource.identifier` against
    `Bundle`, whose `identifier` is a single object, when the entry is an `Organization`, whose
    `identifier` is an array.
  - `type: "number"` alone is UNBOUND, because ROAX has two numeric tags and JSON Schema's
    `number` chooses neither. FHIR's lite schema distinguishes them by PATTERN - `integer` and
    `decimal` are both `type: "number"` and differ only there - so a FHIR-scoped numeric element
    binds cleanly and a bare `type: "number"` elsewhere does not.

Usage:
    python3 build_type_maps.py --references DIR [--out DIR] [--report]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import roax_ref as ref  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.dirname(HERE)

SCHEMA_HOST = "https://schemata.openattestation.com/"

# The upstream commit these bindings were read at. Cited, never copied.
REFERENCE_COMMIT = "09fa75eef40ad7c44a03860272c4d6e6e0f0ddfa"

# FHIR R4 distinguishes its numeric primitives by pattern, not by JSON Schema type: `integer`
# and `decimal` are both `"type": "number"`. These are the two patterns as shipped in
# fhir/4.0.1/lite-schema.json, and matching on them is what makes a FHIR numeric binding
# derived rather than authored.
FHIR_INTEGER_PATTERNS = {
    r"^-?([0]|([1-9][0-9]*))$",
    r"^[1-9][0-9]*$",
    r"^[0]|([1-9][0-9]*)$",
}
FHIR_DECIMAL_PATTERNS = {
    r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?$",
}

TYPE_MAP_VERSION = "0.1.0"

PROFILES = [
    {
        "recordType": "sg.gov.moh.vaccination-healthcert",
        "schemaVersion": "1.0",
        "schema": "sg/gov/moh/vaccination-healthcert/1.0/schema.json",
        "module": "sg/gov/moh/vaccination-healthcert/1.0/sample-data.ts",
        "export": "sampleVaccineHealthCert",
    },
    {
        "recordType": "sg.gov.moh.pdt-healthcert",
        "schemaVersion": "2.0",
        "schema": "sg/gov/moh/pdt-healthcert/2.0/schema.json",
        "module": "sg/gov/moh/pdt-healthcert/2.0/sample-data.ts",
        "export": "sampleEndorsedDocument",
    },
    {
        "recordType": "sg.gov.moh.recovery-healthcert",
        "schemaVersion": "2.0",
        "schema": "sg/gov/moh/recovery-healthcert/2.0/schema.json",
        "module": "sg/gov/moh/recovery-healthcert/2.0/sample-data.ts",
        "export": "sampleDocument",
    },
]


class SchemaSet:
    """Reference schemas, loaded and cross-resolved BY FILE PATH."""

    def __init__(self, src_root: str):
        self.src = src_root
        self.docs = {}

    def load(self, path: str):
        if path not in self.docs:
            with open(path, "r", encoding="utf-8") as handle:
                self.docs[path] = json.load(handle)
        return self.docs[path]

    def rel(self, path: str) -> str:
        """Cite a reference schema the way repository policy requires: by relative path."""
        return "references/schemata/" + os.path.relpath(path, os.path.dirname(self.src.rstrip("/")))

    def deref(self, path, node, depth=0):
        """Follow $ref chains, tracking which FILE the result lives in."""
        while isinstance(node, dict) and "$ref" in node and depth < 64:
            depth += 1
            base, _, frag = node["$ref"].partition("#")
            if base:
                if not base.startswith(SCHEMA_HOST):
                    return path, None
                candidate = os.path.join(self.src, base[len(SCHEMA_HOST):])
                if not os.path.exists(candidate):
                    return path, None
                path = candidate
            cur = self.load(path)
            for part in frag.lstrip("/").split("/"):
                if not part:
                    continue
                part = part.replace("~1", "/").replace("~0", "~")
                if not isinstance(cur, dict) or part not in cur:
                    return path, None
                cur = cur[part]
            node = cur
        return path, node

    def children(self, path, node, seg):
        """Every declaration a segment can reach. A union contributes all its branches."""
        path, node = self.deref(path, node)
        if not isinstance(node, dict):
            return []
        out = []
        if "key" in seg:
            props = node.get("properties", {})
            if seg["key"] in props:
                out.append((path, props[seg["key"]]))
            ap = node.get("additionalProperties")
            if isinstance(ap, dict):
                out.append((path, ap))
        else:
            if "items" in node:
                out.append((path, node["items"]))
        for comb in ("oneOf", "anyOf", "allOf"):
            for branch in node.get(comb, []):
                out.extend(self.children(path, branch, seg))
        return out

    def tag_of(self, path, node):
        """(tag, source) for a scalar declaration, or (None, reason) when ROAX cannot bind it."""
        path, d = self.deref(path, node)
        if not isinstance(d, dict):
            return None, "declaration is not an object"

        cite = self.rel(path)
        t = d.get("type")
        pattern = d.get("pattern")

        if t == "string":
            return ref.TAG_STRING, f"{cite}: type string"
        if t == "boolean":
            return ref.TAG_BOOL, f"{cite}: type boolean"
        if t == "null":
            return ref.TAG_NULL, f"{cite}: type null"
        if t == "integer":
            return ref.TAG_INTEGER, f"{cite}: type integer"
        if t == "number":
            if pattern in FHIR_INTEGER_PATTERNS:
                return ref.TAG_INTEGER, f"{cite}: type number with the FHIR integer pattern"
            if pattern in FHIR_DECIMAL_PATTERNS:
                return ref.TAG_DECIMAL, f"{cite}: type number with the FHIR decimal pattern"
            # ROAX has two numeric tags and JSON Schema's `number` chooses neither. Binding it
            # either way here would be an authored ruling wearing a derivation's clothes.
            return None, f"{cite}: type number with no FHIR numeric pattern - INTEGER or DECIMAL is undetermined"
        if isinstance(t, list):
            return None, f"{cite}: union type {t} - more than one ROAX tag is reachable"

        if "enum" in d and d["enum"] and all(isinstance(x, str) for x in d["enum"]):
            return ref.TAG_STRING, f"{cite}: string enum"
        if "const" in d and isinstance(d["const"], str):
            return ref.TAG_STRING, f"{cite}: string const"
        if "const" in d and isinstance(d["const"], bool):
            return ref.TAG_BOOL, f"{cite}: boolean const"

        for comb in ("oneOf", "anyOf"):
            if comb in d:
                tags = set()
                sources = []
                for branch in d[comb]:
                    tag, src = self.tag_of(path, branch)
                    if tag is not None:
                        tags.add(tag)
                        sources.append(src)
                if len(tags) == 1:
                    return tags.pop(), f"{cite}: {comb}, all scalar branches agree ({sources[0]})"
                if len(tags) > 1:
                    return None, f"{cite}: {comb} branches disagree on the ROAX tag"
                return None, f"{cite}: {comb} with no scalar branch"

        return None, f"{cite}: no type, enum or const declared"


def walk_record(node, segs, out):
    if isinstance(node, ref.RecordMap):
        if not node.items:
            out.append((segs, "EMPTY_OBJECT"))
            return
        for k, v in node.items:
            walk_record(v, segs + [{"key": k}], out)
    elif isinstance(node, list):
        if not node:
            out.append((segs, "EMPTY_ARRAY"))
            return
        for i, v in enumerate(node):
            walk_record(v, segs + [{"index": i}], out)
    else:
        out.append((segs, ref.json_kind(node)))


def to_pattern(segs) -> str:
    """Display-notation pattern with every array index generalized to `[*]`.

    Generalizing is deliberate: a per-index pattern would be a map shaped like one SAMPLE, and
    a type map has to be shaped like the SCHEMA or it does not survive the next record.
    """
    out = ""
    for seg in segs:
        if "key" in seg:
            out += ("." if out else "") + seg["key"]
        else:
            out += "[*]"
    return out


def derive(profile, src_root, record):
    """Return (entries, unbound) for one profile against one sample record.

    The sample supplies the SET OF PATHS to bind, never the tag. Every tag comes from the
    schema, and a path the schema does not determine appears in `unbound`.
    """
    schemas = SchemaSet(src_root)
    schema_path = os.path.join(src_root, profile["schema"])
    root_schema = schemas.load(schema_path)

    leaves = []
    walk_record(record, [], leaves)

    entries = {}
    unbound = {}
    for segs, kind in leaves:
        if kind in ("EMPTY_OBJECT", "EMPTY_ARRAY"):
            # Empty containers get their tag from the flattener, never from the map.
            continue
        pattern = to_pattern(segs)
        key = (pattern, kind)
        if key in entries or key in unbound:
            continue

        frontier = [(schema_path, root_schema)]
        for seg in segs:
            nxt = []
            for path, node in frontier:
                nxt.extend(schemas.children(path, node, seg))
            frontier = nxt
            if not frontier:
                break

        if not frontier:
            unbound[key] = "the schema declares nothing at this path"
            continue

        tags = {}
        reasons = []
        for path, node in frontier:
            tag, why = schemas.tag_of(path, node)
            if tag is None:
                reasons.append(why)
            else:
                tags.setdefault(tag, why)

        if len(tags) == 1:
            tag, source = next(iter(tags.items()))
            entries[key] = {"pattern": pattern, "jsonKind": kind, "tag": tag, "source": source}
        elif len(tags) > 1:
            unbound[key] = "branches disagree: " + ", ".join(sorted(tags.values()))
        else:
            unbound[key] = reasons[0] if reasons else "no scalar declaration reachable"

    return entries, unbound


def build(references, out_dir, report=False):
    import json_literal
    from extract_reference_record import ExtractError, extract

    src_root = os.path.join(references, "schemata", "src")
    if not os.path.isdir(src_root):
        src_root = references
    if not os.path.isdir(src_root):
        raise SystemExit(f"reference checkout not found under {references!r}")

    summary = []
    for profile in PROFILES:
        module = os.path.join(src_root, profile["module"])
        with open(module, "r", encoding="utf-8") as handle:
            try:
                record_text = extract(handle.read(), profile["export"])
            except ExtractError as exc:
                raise SystemExit(f"{profile['recordType']}: {exc}")
        record = json_literal.loads(record_text)

        entries, unbound = derive(profile, src_root, record)
        doc = {
            "typeMapVersion": TYPE_MAP_VERSION,
            "recordType": profile["recordType"],
            "schemaVersion": profile["schemaVersion"],
            "sourceSchemas": [{
                "path": "references/schemata/src/" + profile["schema"],
                "commit": REFERENCE_COMMIT,
                "note": "Resolved by file path, never by $id: two reference schemas carry "
                        "copy-pasted $id values.",
            }],
            "entries": [entries[k] for k in sorted(entries)],
        }

        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, profile["recordType"] + ".json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")

        summary.append({
            "recordType": profile["recordType"],
            "schemaVersion": profile["schemaVersion"],
            "recordFile": "references/schemata/src/" + profile["module"] + "#" + profile["export"],
            "bound": len(entries),
            "unbound": [
                {"pattern": k[0], "jsonKind": k[1], "why": v} for k, v in sorted(unbound.items())
            ],
        })

        if report:
            print(f"=== {profile['recordType']} {profile['schemaVersion']}")
            print(f"    bound   {len(entries)} (pattern, jsonKind) pairs")
            print(f"    unbound {len(unbound)}")
            for k, v in sorted(unbound.items()):
                print(f"      {k[0]}  [{k[1]}]  -  {v}")
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--references", default=os.environ.get("ROAX_REFERENCES"), required=False)
    ap.add_argument("--out", default=os.path.join(CORPUS_DIR, "type-maps"))
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()
    if not args.references:
        raise SystemExit("--references (or ROAX_REFERENCES) is required")
    build(args.references, None if args.no_write else args.out, report=True or args.report)


if __name__ == "__main__":
    main()
