"""Committed salt sets: the input side that replaced salt derivation.

Decision D4 is ruled D4b, so a salt is 16 bytes drawn independently from a CSPRNG and nothing
can re-derive one (`docs/spec/roax-canon-1.md` section 7). A fixed vector file therefore cannot
compute its salts at build time: they have to be DRAWN ONCE and COMMITTED, and every later build
reads them back.

That is why these files are not `fixture_io` fixtures. A fixture is regenerated on every build
and compared, which is exactly what a random value cannot survive - a fresh draw would differ
every run and `--check` would fail forever. A salt set is a committed INPUT, like the type maps.

Drawing is therefore an explicit, separate act: `build_corpus.py --draw-salts`. It is not part
of a normal build, and a normal build that finds a salt set missing FAILS rather than drawing
one, because a drawn-on-demand salt would give this machine a root no other machine could
reproduce.

Two carriers, named by `pairing`, and the difference is not stylistic:

  "path"        one entry per leaf carrying explicit segments, exactly the `salts` array of
                `schemas/envelope-1.0.json`. Self-describing. Everything hand-authored uses it.

  "positional"  a bare array of salts in encodePath order. CORPUS-ONLY, and it MUST NEVER
                become an envelope shape. Specification section 7.2 rejects it for an envelope
                because it makes pairing depend on reproducing the section 9 sort before the
                salts can be read at all; in a corpus vector reproducing that sort is the thing
                under test, so a mispairing fails the vector instead of yielding a silently
                wrong root. Class 10 needs it because its records are the genuine third-party
                MOH reference samples at 69 and 70 leaves, and a path-keyed set would enumerate
                every path of a shipped reference sample into this PUBLIC repository, which
                AGENTS.md forbids - not even a fragment. A positional array discloses only the
                leaf count, and the vector already publishes that as `leafCount`.

See `docs/conformance-corpus.md` class 10, which states the same reasoning and warns that if the
two are ever harmonized, the dangerous direction is making envelopes positional.
"""

from __future__ import annotations

import json
import os
import re
import secrets

SALT_BYTES = 16

_HERE = os.path.dirname(os.path.abspath(__file__))
_DIR = os.path.join(os.path.dirname(_HERE), "fixtures", "salts")

# Corpus-relative, for the `saltsFile` a vector records.
REPO_PREFIX = "corpus/fixtures/salts/"


_drawing = False
_used = set()


class _JsonInteger(int):
    """A JSON integer that retains its source spelling for canonical-form checks."""

    def __new__(cls, literal: str):
        value = super().__new__(cls, literal)
        value.literal = literal
        return value


class _OtherNumber:
    def __init__(self, literal: str):
        self.literal = literal


def set_drawing(flag: bool) -> None:
    """Enable draw mode. Set once, by build_corpus.py --draw-salts, and never during a build."""
    global _drawing
    _drawing = bool(flag)


def drawing() -> bool:
    return _drawing


def set_directory(directory: str) -> None:
    """Override the committed-input directory, primarily for read-only gate regressions."""
    global _DIR
    _DIR = os.path.abspath(directory)


def begin_build() -> None:
    """Forget which carriers the previous build consumed."""
    _used.clear()


def path_for(name: str) -> str:
    return os.path.join(_DIR, name + ".json")


def reference_for(name: str) -> str:
    """What a vector's `saltsFile` says, which is repository-relative and not machine-relative."""
    return REPO_PREFIX + name + ".json"


def _render(doc) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def _invalid(name: str, message: str):
    raise SystemExit(f"corpus defect: salt-set carrier {reference_for(name)}: {message}")


def _unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate member {key!r}")
        out[key] = value
    return out


def _exact_members(name: str, value, expected, label: str) -> dict:
    if type(value) is not dict:
        _invalid(name, f"{label} must be an object")
    unknown = sorted(set(value) - set(expected))
    missing = sorted(set(expected) - set(value))
    if unknown:
        _invalid(name, f"{label} has unknown member(s) {unknown!r}")
    if missing:
        _invalid(name, f"{label} is missing member(s) {missing!r}")
    return value


def _salt(name: str, value, label: str) -> None:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{32}", value) is None:
        _invalid(name, f"{label} must be exactly 16 bytes as lowercase 32-hex")


def _unsigned_integer(name: str, value, label: str) -> int:
    if type(value) is not _JsonInteger or re.fullmatch(r"(?:0|[1-9][0-9]*)",
                                                        value.literal) is None:
        _invalid(name, f"{label} must be a canonical non-negative JSON integer")
    return int(value)


def _path(name: str, raw, label: str):
    if type(raw) is not list:
        _invalid(name, f"{label} must be an array")
    segments = []
    for index, value in enumerate(raw):
        segment_label = f"{label}[{index}]"
        if type(value) is not dict:
            _invalid(name, f"{segment_label} must be an object")
        if "key" in value:
            segment = _exact_members(name, value, {"key"}, segment_label)
            if type(segment["key"]) is not str:
                _invalid(name, f"{segment_label}.key must be a string")
            segments.append({"key": segment["key"]})
        else:
            segment = _exact_members(name, value, {"index"}, segment_label)
            parsed = _unsigned_integer(name, segment["index"], f"{segment_label}.index")
            if parsed > 4294967295:
                _invalid(name, f"{segment_label}.index must be at most 4294967295")
            segments.append({"index": parsed})
    return segments


def _validate(name: str, document) -> dict:
    if type(document) is not dict:
        _invalid(name, "top level must be an object")
    pairing = document.get("pairing")
    if pairing == "path":
        root = _exact_members(name, document, {"pairing", "salts"}, "top level")
        salts = root["salts"]
        if type(salts) is not list:
            _invalid(name, "salts must be an array")
        if len(salts) < 5:
            _invalid(name, "salts must contain at least 5 entries")
        seen = set()
        import roax_ref as ref
        for index, raw in enumerate(salts):
            label = f"salts[{index}]"
            entry = _exact_members(name, raw, {"segments", "salt"}, label)
            _salt(name, entry["salt"], f"{label}.salt")
            segments = _path(name, entry["segments"], f"{label}.segments")
            try:
                encoded = ref.encode_path(segments)
            except (UnicodeError, ref.RoaxError, ValueError) as exc:
                _invalid(name, f"{label}.segments is invalid: {exc}")
            if encoded in seen:
                _invalid(name, f"{label}.segments duplicates an earlier encoded path")
            seen.add(encoded)
    elif pairing == "positional":
        root = _exact_members(
            name, document, {"pairing", "leafCount", "salts"}, "top level"
        )
        salts = root["salts"]
        if type(salts) is not list:
            _invalid(name, "salts must be an array")
        leaf_count = _unsigned_integer(name, root["leafCount"], "leafCount")
        if leaf_count < 5:
            _invalid(name, "leafCount must be at least 5")
        if leaf_count != len(salts):
            _invalid(
                name,
                f"leafCount {leaf_count} does not equal the {len(salts)} salts",
            )
        for index, value in enumerate(salts):
            _salt(name, value, f"salts[{index}]")
    else:
        _invalid(name, f"pairing must be 'path' or 'positional', got {pairing!r}")
    return document


def _read(name: str) -> dict:
    try:
        with open(path_for(name), "r", encoding="utf-8") as handle:
            document = json.load(
                handle,
                object_pairs_hook=_unique_object,
                parse_int=_JsonInteger,
                parse_float=_OtherNumber,
                parse_constant=_OtherNumber,
            )
    except FileNotFoundError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        _invalid(name, f"invalid JSON: {exc}")
    return _validate(name, document)


def draw(name: str, ordered, pairing: str) -> dict:
    """Draw a fresh salt set for `ordered` and write it. Only ever called under --draw-salts.

    `secrets.token_bytes` and not `random`: the entropy floor is normative (spec section 7), and
    a corpus whose salts came from a seeded PRNG would model the very defect class 12 exists to
    catch.
    """
    if pairing == "path":
        doc = {
            "pairing": "path",
            "salts": [
                {"segments": leaf.segments, "salt": secrets.token_bytes(SALT_BYTES).hex()}
                for leaf in ordered
            ],
        }
    elif pairing == "positional":
        doc = {
            "pairing": "positional",
            "leafCount": len(ordered),
            "salts": [secrets.token_bytes(SALT_BYTES).hex() for _ in ordered],
        }
    else:
        raise SystemExit(f"unknown salt pairing {pairing!r}")

    os.makedirs(_DIR, exist_ok=True)
    with open(path_for(name), "w", encoding="utf-8") as handle:
        handle.write(_render(doc))
    return doc


def load(name: str) -> dict:
    """Read a committed salt set. A missing one is a build failure, never a fresh draw."""
    try:
        document = _read(name)
    except FileNotFoundError:
        raise SystemExit(
            f"corpus defect: salt set {name!r} is not committed at {reference_for(name)}.\n"
            f"Salts are independent random draws under decision D4b and cannot be recomputed, so "
            f"a build never draws one on demand - that would produce a root no other machine "
            f"could reproduce. Run `build_corpus.py --draw-salts` once and commit the result."
        )
    _used.add(name)
    return document


def committed_names():
    """Every committed salt set, so a build can report one that no vector references."""
    if not os.path.isdir(_DIR):
        return []
    return sorted(
        name[:-5]
        for name in os.listdir(_DIR)
        if name.endswith(".json") and os.path.isfile(os.path.join(_DIR, name))
    )


def validate_all() -> int:
    """Validate every committed carrier without marking an unreferenced one as consumed."""
    names = committed_names()
    if not names:
        raise SystemExit(f"corpus defect: salt-set directory {_DIR} contains no JSON carriers")
    for name in names:
        _read(name)
    return len(names)


def used_names():
    return set(_used)


def name_from_reference(reference: str) -> str:
    if not reference.startswith(REPO_PREFIX) or not reference.endswith(".json"):
        raise SystemExit(f"corpus defect: invalid salt-set reference {reference!r}")
    name = reference[len(REPO_PREFIX):-5]
    if not name or "/" in name:
        raise SystemExit(f"corpus defect: invalid salt-set reference {reference!r}")
    return name


def assert_name_set(expected) -> None:
    """Require the carrier directory to equal the generator's consumed input set."""
    committed = set(committed_names())
    expected = set(expected)
    missing = sorted(expected - committed)
    orphaned = sorted(committed - expected)
    if missing:
        raise SystemExit(
            "corpus defect: salt-set carrier(s) are not committed: "
            + ", ".join(reference_for(name) for name in missing)
        )
    if orphaned:
        raise SystemExit(
            "corpus defect: salt-set carrier orphan(s) no generated vector or fixture uses: "
            + ", ".join(reference_for(name) for name in orphaned)
        )
