#!/usr/bin/env python3
"""Run the ROAX conformance corpus against this Python implementation.

    python3 python/tools/run_corpus.py [--references PATH] [--empty-containers MODE]

This is a **third** runner, deliberately standalone.
It does not extend `corpus/tools/run.sh`, which is the existing two-implementation gate
and whose steps 1 through 3 are about those two agreeing with each other and with the
committed bytes.
Nothing under `corpus/` is read as source: this runner consumes the vector file, the
fixtures and the corpus-side type maps, which is exactly what
`corpus/README.md` documents as the interface for "an implementation that is not one of
these two".

Exit status is 0 only when all 20 classes pass with no unavailable vectors.
An assertion failure exits 1.
A vector or class that cannot run says NOT RUN with the reason and exits 2; it never
reports green unrun.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
sys.path.insert(0, _HERE)

from roax_canon import (  # noqa: E402
    DEFAULT_PROFILES,
    DisplayPatternTypeMap,
    MappingSalts,
    PINNED_UNICODE_VERSION,
    PositionalSalts,
    RecordIdentity,
    RESERVED_V1,
    RESERVED_V2,
    RoaxError,
    VerifierConfig,
    audit_path,
    build_tree,
    DEFAULT_ORDERING,
    check_ordering,
    display_path,
    draw_salt,
    encode_path,
    encode_value,
    leaf_hash,
    load_file,
    loads,
    merkle_tree_head,
    runtime_unicode_version,
    unicode_tables_match_pin,
    verify_envelope,
    verify_inclusion,
)
from roax_canon.errors import ErrorCode  # noqa: E402
from roax_canon.flatten import check_reserved_namespace, flatten  # noqa: E402
from roax_canon.disclose import disclosed_copy, full_copy  # noqa: E402
from roax_canon.jsonio import JsonNumber, as_int, is_json_string  # noqa: E402
from roax_canon.path import segments_from_json  # noqa: E402
from roax_canon.profiles import CORPUS_SYNTHETIC_PROFILE  # noqa: E402
from ts_sample import load_export  # noqa: E402

REPO = os.path.dirname(os.path.dirname(_HERE))
CORPUS = os.path.join(REPO, "corpus", "conformance-corpus-1.0.json")
TYPE_MAP_DIR = os.path.join(REPO, "corpus", "type-maps")
EXPECTED_CLASSES = tuple(range(1, 22))
REFERENCES_INSTRUCTION = "rerun with --references /path/to/schemata"

# Every vector group this runner consumes. A group present in the corpus file and absent from
# this tuple is a HARD FAILURE rather than a quiet skip, because the quiet skip is the exact
# defect shape the corpus exists to prevent: a runner that does not know a group reads it as zero
# vectors and reports the same green it reported before the group was added.
CONSUMED_GROUPS = (
    "encodePath",
    "encodeValue",
    "reject",
    "leaf",
    "tree",
    "inclusion",
    "negativeProof",
    "typeMap",
    "record",
    "unlinkability",
    "normalization",
    "envelope",
    "roundTrip",
    "ordering",
)


# ---------------------------------------------------------------------------------
# Result accounting
# ---------------------------------------------------------------------------------


class Results:
    def __init__(self) -> None:
        self.passed: dict[int, int] = defaultdict(int)
        self.failed: dict[int, list[str]] = defaultdict(list)
        self.not_run: dict[int, list[str]] = defaultdict(list)

    def ok(self, cls: int) -> None:
        self.passed[cls] += 1

    def bad(self, cls: int, name: str, detail: str) -> None:
        self.failed[cls].append(f"{name}: {detail}")

    def unavailable(self, cls: int, name: str, why: str) -> None:
        self.not_run[cls].append(f"{name}: {why}")

    def check(self, cls: int, name: str, got: Any, want: Any, what: str = "") -> None:
        if got == want:
            self.ok(cls)
        else:
            self.bad(cls, name, f"{what}got {got!r}, want {want!r}")


# ---------------------------------------------------------------------------------
# Corpus input escape forms (`corpus/README.md`, "Input escape forms")
# ---------------------------------------------------------------------------------


def from_utf16(units: list[str]) -> str:
    """Build a string from UTF-16 code units, unpaired surrogates included.

    ``surrogatepass`` is required: plain ``utf-16-be`` raises on a lone ``d800``, which
    would make the unpaired-surrogate vectors untestable rather than testable.
    A conforming JSON writer cannot emit one as well-formed UTF-8, which is why the corpus
    carries them this way at all.
    """
    raw = bytes.fromhex("".join(units))
    return raw.decode("utf-16-be", errors="surrogatepass")


def unescape(node: Any) -> Any:
    """Resolve ``$utf16`` anywhere inside a vector input."""
    if isinstance(node, dict):
        if set(node) == {"$utf16"}:
            return from_utf16([str(u) for u in node["$utf16"]])
        return {k: unescape(v) for k, v in node.items()}
    if isinstance(node, list):
        return [unescape(v) for v in node]
    return node


def carrier(tag: Any, raw: Any) -> Any:
    """Turn a corpus value carrier into what this package's ``encode_value`` accepts.

    One tag needs it. A corpus tag-5 BYTES value travels as LOWERCASE HEX, which is also the
    disclosed-envelope carrier (`schemas/envelope-1.0.json`), while this package's
    :func:`roax_canon.encode_value` takes the octets themselves and rejects anything else. That
    strictness is correct for a library boundary and the decode belongs here, in the runner that
    owns the carrier format, rather than being relaxed into the library.

    The corpus had no tag-5 vector until FHIR `base64Binary` was ruled BYTES on 2026-07-30, so
    this boundary was simply unexercised rather than known-good.
    """
    if tag == 5:
        if not is_json_string(raw):
            raise ValueError(f"a BYTES carrier must be a hex string, got {raw!r}")
        return bytes.fromhex(raw)
    return unescape(raw)


def _salt_entries(path: str, expected_pairing: str) -> list[Any]:
    doc = load_file(path)
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: salt document must be an object")
    allowed = (
        frozenset({"pairing", "leafCount", "salts"})
        if expected_pairing == "positional"
        else frozenset({"pairing", "salts"})
    )
    unknown = sorted(set(doc) - allowed)
    if unknown:
        raise ValueError(f"{path}: unknown salt document members {unknown}")
    actual_pairing = doc.get("pairing")
    if actual_pairing != expected_pairing:
        raise ValueError(
            f"{path}: salt document declares pairing {actual_pairing!r}, "
            f"vector requires {expected_pairing!r}"
        )
    entries = doc.get("salts")
    if not isinstance(entries, list):
        raise ValueError(f"{path}: salt document must carry a `salts` array")
    if expected_pairing == "positional":
        if "leafCount" not in doc:
            raise ValueError(f"{path}: positional salt document must carry `leafCount`")
        count = as_int(doc["leafCount"], field="leafCount")
        if count != len(entries):
            raise ValueError(
                f"{path}: positional salt document declares {count} leaves "
                f"but carries {len(entries)} salts"
            )
    return entries


def _salt_bytes(value: Any, *, path: str) -> bytes:
    if (
        not is_json_string(value)
        or len(value) != 32
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise ValueError(f"{path}: salt must be exactly 32 lowercase hex characters")
    return bytes.fromhex(value)


def salts_by_path(path: str) -> dict[bytes, bytes]:
    entries = _salt_entries(path, "path")
    by_path: dict[bytes, bytes] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"segments", "salt"}:
            raise ValueError(f"{path}: each path-paired salt needs only `segments` and `salt`")
        encoded = encode_path(segments_from_json(entry["segments"]))
        if encoded in by_path:
            raise ValueError(
                f"{path}: duplicate salt path {display_path(segments_from_json(entry['segments']))!r}"
            )
        by_path[encoded] = _salt_bytes(entry["salt"], path=path)
    return by_path


def positional_salts(path: str) -> list[bytes]:
    entries = _salt_entries(path, "positional")
    return [_salt_bytes(salt, path=path) for salt in entries]


# ---------------------------------------------------------------------------------
# Per-class runners
# ---------------------------------------------------------------------------------


def run_encode_path(vectors, r: Results) -> None:
    for x in vectors:
        segs = segments_from_json(x["segments"])
        r.check(x["class"], x["name"], encode_path(segs).hex(), x["encodedHex"], "encodedHex: ")
        if "displayPath" in x:
            r.check(x["class"], x["name"], display_path(segs), x["displayPath"], "displayPath: ")


def run_encode_value(vectors, r: Results) -> None:
    for x in vectors:
        try:
            got = encode_value(x["tag"], carrier(x["tag"], x.get("input"))).hex()
        except RoaxError as exc:
            r.bad(x["class"], x["name"], f"rejected with {exc.code}")
            continue
        r.check(x["class"], x["name"], got, x["encodedHex"])


# Reference reason codes this implementation spells differently, with the measurement.
#
# A corpus `reason` is the REFERENCE implementations' spelling and not a normative code. Every
# reject vector agreed with this implementation's spelling until the record-shaped reject vectors
# of the 2026-07-30 type rulings arrived; those are the first whose reason is a FAIL-CLOSED, and
# the four implementations name that one condition four ways. `corpus/tools/roax_ref.py` and
# `roax_ref.mjs` say `type-map-uncovered-path`, this package says `type-unresolved`, and the
# TypeScript and Rust libraries say `type-map-fail-closed` (`corpus/README.md`).
#
# A DECLARED equivalence rather than a way to pass: it maps one reference code to the one local
# code naming the same condition, so a rejection for a DIFFERENT reason still fails.
REFERENCE_REASON_ALIASES = {
    "type-map-uncovered-path": ErrorCode.TYPE_UNRESOLVED,
}


def run_reject(vectors, maps, r: Results) -> None:
    """Every one of these MUST error, with the reference reason code or its declared alias."""
    for x in vectors:
        cls, name = x["class"], x["name"]
        raw = x.get("input")
        expected = REFERENCE_REASON_ALIASES.get(x["reason"], x["reason"])
        try:
            if "recordType" in x:
                # A whole-record rejection, flattened through that profile's COMMITTED map. The
                # map has to be the committed one rather than a permissive stand-in, because
                # several of these vectors assert that a path has NO binding for an observed
                # kind, which a resolve-everything map would make unfalsifiable.
                flatten(
                    loads(raw["$jsonText"]),
                    maps(x["recordType"]),
                    authorize_empty_containers=True,
                )
            elif isinstance(raw, dict) and set(raw) == {"$jsonText"}:
                loads(raw["$jsonText"])
            elif isinstance(raw, dict) and set(raw) == {"$segments"}:
                segs = segments_from_json(unescape(raw["$segments"]))
                # Both checks, in the order a flattener applies them: the reserved
                # namespace guard is on the record's first segment and runs at the input
                # boundary, and encoding is what rejects an index out of 32-bit range.
                check_reserved_namespace(segs)
                encode_path(segs)
            elif "segments" in x:
                segs = segments_from_json(x["segments"])
                check_reserved_namespace(segs)
                encode_path(segs)
            elif x.get("tag") is not None:
                encode_value(x["tag"], carrier(x["tag"], raw))
            else:
                r.bad(cls, name, "unsupported reject-vector input shape")
                continue
        except RoaxError as exc:
            r.check(cls, name, exc.code, expected, "reason: ")
            continue
        r.bad(cls, name, f"accepted; expected rejection {expected!r}")


def declared_ordering(vector) -> str:
    """The ordering a vector DECLARES, asserted rather than tolerated (spec section 9).

    Tolerating it would be the group guard's defect one level down: an unknown field inside a
    group this runner already consumes passes silently, so a `hash`-ordered vector added to an
    ordering-sensitive group would be computed as `path` and reported green.
    """
    ordering = vector.get("ordering")
    if ordering is None:
        raise ValueError(
            f"{vector['name']} is in an ordering-sensitive group and declares no ordering; "
            f"specification section 9 requires the ordering to be explicit"
        )
    return check_ordering(ordering)


#: The groups whose expected values depend on the leaf ordering, and the ones this runner actually
#: THREADS the declaration through. Held apart deliberately: a group that is ordering-sensitive but
#: not threaded would compute a ``hash``-ordered vector as ``path`` and report green, which is the
#: quiet-skip defect one loop down from the group guard.
ORDERING_SENSITIVE_GROUPS = (
    "leaf",
    "record",
    "unlinkability",
    "normalization",
    "envelope",
    "roundTrip",
)
ORDERING_THREADED_GROUPS = frozenset({"leaf", "record"})


def check_declared_orderings_supported(vectors) -> str | None:
    """Check EVERY ordering-sensitive vector, not only the ones in a threaded group.

    A vector declaring nothing is a corpus defect. One declaring an ordering its group is not
    computed under fails CLOSED here rather than being computed under the default.
    """
    for group in ORDERING_SENSITIVE_GROUPS:
        for v in vectors.get(group, []):
            ordering = declared_ordering(v)
            if ordering != DEFAULT_ORDERING and group not in ORDERING_THREADED_GROUPS:
                return (
                    f"{group} vector {v['name']} declares ordering {ordering}, but this runner "
                    f"computes the {group} group under {DEFAULT_ORDERING} only. Thread the "
                    f"declaration through that loop before adding such a vector; computing it "
                    f"under the default would report a green it did not earn."
                )
    return None


def run_leaf(vectors, r: Results) -> None:
    for x in vectors:
        segs = segments_from_json(x["segments"])
        # A leaf vector is ordering-sensitive even though it carries no tree: the ordering
        # reaches the preimage through DOMAIN (specification section 9.5, H1).
        got = leaf_hash(
            segs,
            x["tag"],
            carrier(x["tag"], x.get("value")),
            bytes.fromhex(x["saltHex"]),
            ordering=declared_ordering(x),
        ).hex()
        r.check(x["class"], x["name"], got, x["leafHash"])


def run_tree(vectors, r: Results) -> None:
    for x in vectors:
        leaves = [bytes.fromhex(h) for h in x["leafHashes"]]
        r.check(x["class"], x["name"], merkle_tree_head(leaves).hex(), x["root"])


def run_inclusion(vectors, trees, r: Results) -> None:
    for x in vectors:
        got = verify_inclusion(
            bytes.fromhex(x["leafHash"]),
            x["index"],
            x["treeSize"],
            [bytes.fromhex(h) for h in x["auditPath"]],
            bytes.fromhex(x["root"]),
        )
        r.check(x["class"], x["name"], got, x["expect"], "verify: ")
        # Generating the audit path for that index must reproduce the one carried, which
        # is the half a verify-only runner would miss.
        source = trees.get(f"tree-n{x['treeSize']}")
        if source is not None and x["expect"]:
            regenerated = [h.hex() for h in audit_path(x["index"], source)]
            r.check(x["class"], x["name"], regenerated, x["auditPath"], "generated auditPath: ")


def run_negative_proof(vectors, r: Results) -> None:
    """These MUST NOT verify.

    STATED LIMIT, because `corpus/README.md` is explicit that a runner handing a leaf hash
    straight to a fold primitive is testing the primitive rather than the defence.
    These vectors carry a leaf hash and no ``(path, tag, value, salt)``, so the full
    disclosed-copy path cannot be driven from them: there is nothing to recompute a leaf
    hash from. What this asserts is the RFC 9162 half.
    The defence specification section 10 step 2 actually requires - never accepting a
    caller-supplied leaf hash - is structural in this implementation, because
    :func:`roax_canon.verify.verify_envelope` has no parameter that takes one.
    This runner invokes that full-verifier entry point for 54 envelope vectors: 3 in
    class 11, 34 in class 14, 5 in class 15, 8 in class 17 and 4 in class 18.
    That is an entry-point count, not a claim that all 54 reach leaf recomputation.
    """
    for x in vectors:
        got = verify_inclusion(
            bytes.fromhex(x["leafHash"]),
            x["index"],
            x["treeSize"],
            [bytes.fromhex(h) for h in x["auditPath"]],
            bytes.fromhex(x["root"]),
        )
        r.check(x["class"], x["name"], got, False, f"attack {x['attack']}: ")


def run_type_map(vectors, maps, r: Results) -> None:
    for x in vectors:
        cls, name = x["class"], x["name"]
        try:
            resolver = maps(x["recordType"])
        except RoaxError as exc:
            if x.get("expectMapRejected"):
                r.ok(cls)
            else:
                r.bad(cls, name, f"map rejected with {exc.code}")
            continue
        except FileNotFoundError as exc:
            path = exc.filename or os.path.join(TYPE_MAP_DIR, f"{x['recordType']}.json")
            r.bad(cls, name, f"committed corpus type map is missing: {path}")
            continue
        if x.get("expectMapRejected"):
            r.bad(cls, name, "map was accepted; expected rejection")
            continue
        segs = segments_from_json(x["segments"])
        try:
            tag = resolver.resolve(segs, x["jsonKind"])
        except RoaxError as exc:
            if x.get("expectFailClosed"):
                r.check(cls, name, exc.code, ErrorCode.TYPE_UNRESOLVED, "reason: ")
            else:
                r.bad(
                    cls, name, f"failed closed with {exc.code}; expected tag {x.get('expectTag')}"
                )
            continue
        if x.get("expectFailClosed"):
            r.bad(cls, name, f"resolved to tag {tag}; expected fail-closed")
        else:
            r.check(cls, name, tag, x["expectTag"], "tag: ")


def _record_for(vector, references: str | None):
    """Return ``(record, unavailable_reason, failure_reason)`` for one record vector.

    Exactly one reason is populated when no record can be returned.
    """
    ref = vector["recordFile"]
    if "#" in ref:
        module, export = ref.split("#", 1)
        if not references:
            return (
                None,
                f"no reference checkout was configured; {REFERENCES_INSTRUCTION}",
                None,
            )
        references = os.path.abspath(references)
        if not os.path.isdir(references):
            return (
                None,
                f"reference checkout path is not a directory: {references}; "
                f"{REFERENCES_INSTRUCTION}",
                None,
            )
        rel = module
        prefix = "references/"
        if rel.startswith(prefix):
            rel = rel[len(prefix) :]
        candidates = [os.path.join(references, rel)]
        # Allow --references to point either at the parent of `schemata/` or at the
        # checkout itself.
        fallback = os.path.join(references, rel.split("/", 1)[1] if "/" in rel else rel)
        if fallback not in candidates:
            candidates.append(fallback)
        candidate = next((path for path in candidates if os.path.exists(path)), None)
        if candidate is None:
            attempted = " and ".join(candidates)
            return (
                None,
                f"reference module was not found; attempted {attempted}; "
                f"{REFERENCES_INSTRUCTION}",
                None,
            )
        try:
            return load_export(candidate, export), None, None
        except Exception as exc:
            # The extractor is an input boundary. Any ordinary read or parse exception
            # is reported as a failed attempt rather than escaping without a terminal
            # corpus result.
            return (
                None,
                None,
                f"could not extract {export!r} from reference module {candidate}: "
                f"{type(exc).__name__}: {exc}",
            )
    return load_file(os.path.join(REPO, ref)), None, None


def run_record(vectors, maps, r: Results, references, authorize_empty) -> None:
    for x in vectors:
        cls, name = x["class"], x["name"]
        if "envelopeFile" in x:
            r.bad(cls, name, "unsupported record-vector envelope carrier")
            continue
        reserved_set = _reserved_set(x)
        record, why_not_run, failure = _record_for(x, references)
        if failure is not None:
            r.bad(cls, name, failure)
            continue
        if record is None:
            r.unavailable(cls, name, why_not_run or "record unavailable")
            continue
        identity = RecordIdentity(
            record_type=x["recordType"],
            schema_version=x["schemaVersion"],
            record_id=x["recordId"],
            issuer_id=x["issuerId"],
            issuer_key_id=x.get("issuerKeyId"),
            type_map_id=x.get("typeMapId"),
            ordering=declared_ordering(x),
        )
        salts_path = os.path.join(REPO, x["saltsFile"])
        try:
            if x["saltPairing"] == "positional":
                salt_values = positional_salts(salts_path)
                salts = PositionalSalts(salt_values)
                salt_count = len(salt_values)
            elif x["saltPairing"] == "path":
                by_path = salts_by_path(salts_path)
                salts = MappingSalts(by_path)
                salt_count = len(by_path)
            else:
                raise ValueError(f"unknown vector saltPairing {x['saltPairing']!r}")
        except (OSError, KeyError, TypeError, ValueError, RoaxError) as exc:
            r.bad(cls, name, f"invalid committed salt set: {type(exc).__name__}: {exc}")
            continue
        try:
            built = build_tree(
                record,
                identity,
                maps(x["recordType"]),
                salts,
                reserved_set=reserved_set,
                authorize_empty_containers=authorize_empty,
            )
        except FileNotFoundError as exc:
            path = exc.filename or os.path.join(TYPE_MAP_DIR, f"{x['recordType']}.json")
            r.bad(cls, name, f"committed corpus type map is missing: {path}")
            continue
        except RoaxError as exc:
            r.bad(cls, name, f"rejected with {exc.code}: {exc.detail}")
            continue
        if salt_count != built.leaf_count:
            r.bad(
                cls,
                name,
                f"committed salt set has {salt_count} entries for {built.leaf_count} leaves",
            )
            continue
        r.check(cls, name, built.leaf_count, x["leafCount"], "leafCount: ")
        r.check(cls, name, built.root.hex(), x["root"], "root: ")


def run_round_trip(vectors, maps, r: Results, config, authorize_empty) -> None:
    """Class 20: issue, disclose, then verify the copy THIS package produced.

    Every other class runs :func:`verify_envelope` against bytes the corpus generator wrote.
    That is the gap this class closes: a package can emit a disclosed copy its own verifier
    refuses and still pass every other vector, because no other vector asks it to PRODUCE one.

    So this drives the real entry points - :func:`full_copy` and :func:`disclosed_copy` - and
    then puts their output through :func:`verify_envelope`. Assembling an envelope here instead
    would test this file rather than the package.
    """
    for x in vectors:
        cls, name = x["class"], x["name"]
        descriptor = x.get("typeMap") or {}
        identity = RecordIdentity(
            record_type=x["recordType"],
            schema_version=x["schemaVersion"],
            record_id=x["recordId"],
            issuer_id=x["issuerId"],
            issuer_key_id=x.get("issuerKeyId"),
            type_map_id=descriptor.get("id"),
            type_map_version=descriptor.get("version"),
        )
        reserved_set = RESERVED_V2 if descriptor else RESERVED_V1
        record = load_file(os.path.join(REPO, x["recordFile"]))
        by_path = salts_by_path(os.path.join(REPO, x["saltsFile"]))
        try:
            built = build_tree(
                record,
                identity,
                maps(x["recordType"]),
                MappingSalts(by_path),
                reserved_set=reserved_set,
                authorize_empty_containers=authorize_empty,
            )
        except RoaxError as exc:
            r.bad(cls, name, f"issuance rejected with {exc.code}: {exc.detail}")
            continue
        r.check(cls, name, built.leaf_count, x["leafCount"], "leafCount: ")
        r.check(cls, name, built.root.hex(), x["root"], "root: ")

        reveal = [segments_from_json(p) for p in x["disclosePaths"]]
        try:
            produced = {
                "expectedFullCopyFile": full_copy(built),
                "expectedDisclosedCopyFile": disclosed_copy(reveal, built),
            }
        except RoaxError as exc:
            r.bad(cls, name, f"disclosure rejected with {exc.code}: {exc.detail}")
            continue

        for field_name, envelope in produced.items():
            expected = load_file(os.path.join(REPO, x[field_name]))
            # Compared SEMANTICALLY. JSON member order, whether `displayPath` is emitted, the
            # order of `disclosure.leaves` and the order of a full copy's `salts` are not fixed
            # by the specification, so asserting any of them would fail a conforming
            # implementation. A number's SOURCE TEXT must survive: `JsonNumber` subclasses `str`
            # and carries it, which is exactly what the full copy's record literals need
            # (section 6.4).
            difference = _first_difference(
                _normalized_for_comparison(_comparable(envelope)),
                _normalized_for_comparison(_comparable(expected)),
            )
            if difference is None:
                r.ok(cls)
            else:
                r.bad(cls, name, f"{field_name}: {difference}")
            # And the half no static fixture can assert: this package's verifier over this
            # package's own output. A producer that omitted a per-leaf value carrier fails HERE
            # even though every leaf hash it computed was right.
            result = verify_envelope(envelope, config)
            if result.accepted == x["expectSelfVerifies"]:
                r.ok(cls)
            else:
                r.bad(
                    cls,
                    name,
                    f"{field_name}: this package issued an envelope its own verifier "
                    f"refused: {result.reason} ({result.detail[:120]})",
                )


def _normalized_for_comparison(envelope):
    """An envelope's comparison form with the aspects the specification does not fix removed.

    Applied to BOTH sides, so what survives the comparison is what the specification says.
    Three things are relaxed and nothing else: ``disclosure.leaves`` is ordered by leaf index
    and a full copy's ``salts`` by its entry's structured path, because every leaf carries its
    own index and every salt entry its own path, so neither array order carries anything; and
    ``displayPath`` is DROPPED, because it is display only and never hashed (section 5.2) and
    `schemas/envelope-1.0.json` leaves it out of ``disclosedLeaf.required``, so a conforming
    producer may omit it and a comparison that noticed would fail conforming work.

    Everything else stays exact - both array lengths, every leaf's segments, index, tag, value
    carrier, salt and audit path, and every scalar identity field - so a producer that omitted
    a per-leaf value carrier still fails, which is the defect this class exists for.
    """
    if not isinstance(envelope, Mapping):
        return envelope
    out = dict(envelope)
    salts = out.get("salts")
    if isinstance(salts, list):
        out["salts"] = sorted(
            salts,
            key=lambda entry: json.dumps(
                entry.get("segments") if isinstance(entry, Mapping) else None, sort_keys=True
            ),
        )
    disclosure = out.get("disclosure")
    if isinstance(disclosure, Mapping) and isinstance(disclosure.get("leaves"), list):
        leaves = [
            {k: value for k, value in leaf.items() if k != "displayPath"}
            if isinstance(leaf, Mapping)
            else leaf
            for leaf in disclosure["leaves"]
        ]
        out["disclosure"] = {**disclosure, "leaves": sorted(leaves, key=_leaf_index)}
    return out


def _leaf_index(leaf) -> int:
    """The leaf index a `_comparable` leaf carries, as the number literal it kept."""
    if not isinstance(leaf, Mapping):
        return -1
    carrier = leaf.get("index")
    if isinstance(carrier, Mapping):
        return int(carrier.get("$numberLiteral", -1))
    return int(carrier) if carrier is not None else -1


def _comparable(node):
    """Members sorted, numbers kept as source text."""
    if isinstance(node, Mapping):
        out = {}
        for key in sorted(node):
            out[key] = _comparable(node[key])
        return out
    if isinstance(node, list):
        return [_comparable(item) for item in node]
    if isinstance(node, JsonNumber):
        return {"$numberLiteral": str(node)}
    if isinstance(node, bool) or node is None or isinstance(node, str):
        return node
    if isinstance(node, int):
        return {"$numberLiteral": str(node)}
    return node


def _first_difference(got, want, at=""):
    """The first place two comparable forms differ, or None. A whole envelope printed twice is
    not a readable failure, and this class catches one missing member on one leaf."""
    if got == want:
        return None
    if isinstance(got, list) and isinstance(want, list):
        if len(got) != len(want):
            return f"{at or '/'}: {len(got)} entries, expected {len(want)}"
        for index, (a, b) in enumerate(zip(got, want)):
            found = _first_difference(a, b, f"{at}/{index}")
            if found is not None:
                return found
        return None
    if isinstance(got, dict) and isinstance(want, dict):
        for key in sorted(set(got) | set(want)):
            if key not in got:
                return f"{at}/{key}: ABSENT, expected {want[key]!r}"
            if key not in want:
                return f"{at}/{key}: {got[key]!r}, expected ABSENT"
            found = _first_difference(got[key], want[key], f"{at}/{key}")
            if found is not None:
                return found
        return None
    return f"{at or '/'}: {got!r}, expected {want!r}"


def _reserved_set(vector) -> str:
    return RESERVED_V2 if vector.get("typeMapId") else RESERVED_V1


def run_ordering(vectors, maps, r: Results, authorize_empty) -> None:
    """Class 21. One record issued under BOTH leaf orderings (specification section 9).

    The vector carries both roots, both leaf-hash sequences in TREE order and both leaf
    counts, so this class cannot be passed by computing one ordering. The cross-ordering
    assertions are what would still catch an implementation reproducing both roots by
    accident: the two leaf-hash SETS must be disjoint, because the ordering is inside DOMAIN
    and therefore inside every leaf preimage (section 9.5, H1).
    """
    for x in vectors:
        cls, name = x["class"], x["name"]
        try:
            record = load_file(os.path.join(REPO, x["recordFile"]))
        except OSError as exc:
            r.bad(cls, name, f"record fixture unreadable: {exc}")
            continue
        # ONE salt set serves both sides: salts are assigned in encodePath order under BOTH
        # orderings (specification section 9), and the committed set is drawn over the
        # hash-ordered superset, which also carries the roax.ordering leaf.
        try:
            by_path = salts_by_path(os.path.join(REPO, x["saltsFile"]))
        except (OSError, KeyError, TypeError, ValueError, RoaxError) as exc:
            r.bad(cls, name, f"invalid committed salt set: {type(exc).__name__}: {exc}")
            continue

        seen: dict[str, tuple[str, list[str]]] = {}
        for ordering, expected in x["orderings"].items():
            identity = RecordIdentity(
                record_type=x["recordType"],
                schema_version=x["schemaVersion"],
                record_id=x["recordId"],
                issuer_id=x["issuerId"],
                issuer_key_id=x.get("issuerKeyId"),
                type_map_id=x.get("typeMapId"),
                ordering=check_ordering(ordering),
            )
            try:
                built = build_tree(
                    record,
                    identity,
                    maps(x["recordType"]),
                    MappingSalts(by_path),
                    reserved_set=_reserved_set(x),
                    authorize_empty_containers=authorize_empty,
                )
            except RoaxError as exc:
                r.bad(cls, name, f"{ordering}: rejected with {exc.code}: {exc.detail}")
                break
            hashes = [h.hex() for h in built.leaf_hashes]
            r.check(cls, name, built.leaf_count, expected["leafCount"], f"{ordering} leafCount: ")
            r.check(cls, name, built.root.hex(), expected["root"], f"{ordering} root: ")
            r.check(cls, name, hashes, expected["leafHashes"], f"{ordering} leafHashes: ")
            r.check(
                cls,
                name,
                [display_path(leaf.path) for leaf in built.leaves],
                expected["displayPaths"],
                f"{ordering} displayPaths: ",
            )
            seen[ordering] = (built.root.hex(), hashes)
        else:
            if "path" in seen and "hash" in seen:
                r.check(cls, name, seen["path"][0] != seen["hash"][0], True, "roots differ: ")
                overlap = sorted(set(seen["path"][1]) & set(seen["hash"][1]))
                r.check(cls, name, overlap, [], "leaf hashes disjoint: ")


def run_unlinkability(vectors, r: Results) -> None:
    """Behavioural: draw with THIS implementation's generator and assert the relations.

    Nothing is compared against a pinned value, because under ruled decision D4b there is
    none to pin.

    HONEST LIMIT, repeated from `docs/conformance-corpus.md` class 12: this detects a
    deterministic or reused salt.
    It cannot detect a weak or predictable CSPRNG, and no fixed vector file can.
    """
    for x in vectors:
        cls, name = x["class"], x["name"]
        paths = [segments_from_json(p) for p in x["paths"]]
        encoded = [encode_path(p) for p in paths]
        if len(set(encoded)) != len(encoded):
            r.bad(cls, name, "vector names the same encoded path twice; corpus defect")
            continue
        value = unescape(x.get("value"))
        salts_per_trial: list[list[bytes]] = []
        hashes_per_trial: list[list[bytes]] = []
        for _ in range(x["trials"]):
            drawn = [draw_salt() for _ in paths]
            salts_per_trial.append(drawn)
            hashes_per_trial.append(
                [leaf_hash(p, x["tag"], value, s) for p, s in zip(paths, drawn)]
            )

        within = all(len(set(trial)) == len(trial) for trial in salts_per_trial)
        r.check(cls, name, within, True, "distinct salts within an issuance: ")

        across_salts = all(
            len({trial[i] for trial in salts_per_trial}) == len(salts_per_trial)
            for i in range(len(paths))
        )
        r.check(cls, name, across_salts, True, "distinct salts across issuances: ")

        across_hashes = all(
            len({trial[i] for trial in hashes_per_trial}) == len(hashes_per_trial)
            for i in range(len(paths))
        )
        r.check(cls, name, across_hashes, True, "distinct leaf hashes across issuances: ")


def run_normalization(vectors, maps, r: Results, authorize_empty) -> None:
    for x in vectors:
        cls, name = x["class"], x["name"]
        identity = RecordIdentity(
            record_type=x["recordType"],
            schema_version=x["schemaVersion"],
            record_id=x["recordId"],
            issuer_id=x["issuerId"],
            issuer_key_id=x.get("issuerKeyId"),
        )
        try:
            by_path = salts_by_path(os.path.join(REPO, x["saltsFile"]))
        except (OSError, KeyError, TypeError, ValueError, RoaxError) as exc:
            r.bad(cls, name, f"invalid committed salt set: {type(exc).__name__}: {exc}")
            continue
        roots = []
        for key in ("recordFileNFD", "recordFileNFC"):
            record = load_file(os.path.join(REPO, x[key]))
            built = build_tree(
                record,
                identity,
                maps(x["recordType"]),
                MappingSalts(by_path),
                authorize_empty_containers=authorize_empty,
            )
            if len(by_path) != built.leaf_count:
                r.bad(
                    cls,
                    name,
                    f"committed salt set has {len(by_path)} entries for "
                    f"{built.leaf_count} leaves",
                )
                roots = []
                break
            roots.append(built.root.hex())
        if not roots:
            continue
        r.check(cls, name, roots[0] == roots[1], x["expectSameRoot"], "same root: ")
        if "root" in x:
            r.check(cls, name, roots[0], x["root"], "root: ")


def run_envelope(vectors, config, r: Results) -> None:
    for x in vectors:
        cls, name = x["class"], x["name"]
        envelope = load_file(os.path.join(REPO, x["envelopeFile"]))
        cfg = config
        if "verifierConfig" in x:
            vc = x["verifierConfig"]
            cfg = VerifierConfig(
                profiles=config.profiles,
                hash_alg_allow_list=tuple(vc["hashAlgAllowList"]),
                resolvers=config.resolvers,
                reserved_set=config.reserved_set,
                anchored_root=bytes.fromhex(vc["anchoredRoot"]),
                anchored_hash_alg=vc["anchoredHashAlg"],
                registry_address=vc["registryAddress"],
                registry_chain_id=vc.get("registryChainId"),
                authorize_empty_containers=config.authorize_empty_containers,
            )
        result = verify_envelope(envelope, cfg)
        r.check(cls, name, result.accepted, x["expectAccept"], "accept: ")
        if "reason" in x:
            r.check(cls, name, result.reason, x["reason"], f"reason ({result.detail[:90]}): ")


# ---------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--references",
        default=os.environ.get("ROAX_REFERENCES") or os.path.join(REPO, "references"),
        help=(
            "checkout holding the third-party reference schemata; class 10 needs it "
            "(default: ROAX_REFERENCES, then repository references/)"
        ),
    )
    parser.add_argument(
        "--empty-containers",
        choices=("structural", "authorized"),
        default="structural",
        help=(
            "how an empty container is tagged. 'structural' emits EMPTY_ARRAY and "
            "EMPTY_OBJECT without consulting the type map, which is what the committed "
            "corpus asserts. 'authorized' applies the rule specification section 3.3 "
            "states, under which an unauthorized empty container fails closed."
        ),
    )
    parser.add_argument("--verbose", action="store_true", help="list every failure")
    args = parser.parse_args()

    authorize_empty = args.empty_containers == "authorized"
    references = args.references

    corpus = json.load(open(CORPUS, encoding="utf-8"))
    vectors = corpus["vectors"]

    unconsumed = [name for name in vectors if name not in CONSUMED_GROUPS]
    if unconsumed:
        print(
            "FAILED: the corpus carries vector group(s) this runner does not consume: "
            + ", ".join(sorted(unconsumed))
        )
        print("  A group read as absent would report the same green as before it existed.")
        return 1

    unsupported = check_declared_orderings_supported(vectors)
    if unsupported is not None:
        print(f"FAILED: {unsupported}")
        return 1

    print("ROAX-CANON/1 conformance corpus, Python implementation")
    print(
        f"  corpus            {corpus['corpusVersion']}  canon {corpus['canon']}"
        f"  hashAlg {corpus['hashAlg']}"
    )
    print(f"  corpus Unicode    {corpus['unicodeVersion']}   pin {PINNED_UNICODE_VERSION}")
    print(
        f"  runtime Unicode   {runtime_unicode_version()}"
        f"  {'matches the pin' if unicode_tables_match_pin() else 'DOES NOT MATCH THE PIN'}"
    )
    print(f"  python            {sys.version.split()[0]}")
    print(f"  empty containers  {args.empty_containers}")
    if not authorize_empty:
        print(
            "    NOTE: 'structural' is the committed corpus's behaviour and diverges from\n"
            "    specification section 3.3, which requires the selected map to authorize a\n"
            "    structured path and observed kind before EMPTY_ARRAY or EMPTY_OBJECT is\n"
            "    emitted. Run with --empty-containers=authorized to see the difference."
        )
    if not references:
        print(f"  references        NOT RUN - not configured; {REFERENCES_INSTRUCTION}")
    elif not os.path.isdir(references):
        print(
            f"  references        NOT RUN - {os.path.abspath(references)} is not a directory;\n"
            f"                    {REFERENCES_INSTRUCTION}"
        )
    else:
        print(f"  references        {references}")
    print()

    cache: dict[str, DisplayPatternTypeMap] = {}

    def maps(record_type: str) -> DisplayPatternTypeMap:
        if record_type not in cache:
            cache[record_type] = DisplayPatternTypeMap.from_file(
                os.path.join(TYPE_MAP_DIR, f"{record_type}.json")
            )
        return cache[record_type]

    # The synthetic profile exists only inside this corpus and must never be issued
    # against, so it is registered here rather than in the library's default registry.
    registry = DEFAULT_PROFILES.with_profile(CORPUS_SYNTHETIC_PROFILE)
    resolvers = {}
    for record_type in registry.record_types():
        candidate = os.path.join(TYPE_MAP_DIR, f"{record_type}.json")
        if os.path.exists(candidate):
            resolvers[record_type] = maps(record_type)
    config = VerifierConfig(
        profiles=registry,
        # Specification section 7.4 defines a construction for SHA-256 alone and leaves
        # `Poseidon-BN254` registered but unparameterized, so a corpus naming any other
        # algorithm cannot exist yet and a branch for one would be dead either way. The
        # allow-list is the verifier's own (section 7.4, H3) rather than the document's,
        # so sourcing it from `corpus["hashAlg"]` would be the wrong shape regardless.
        hash_alg_allow_list=("SHA-256",),
        resolvers=resolvers,
        authorize_empty_containers=authorize_empty,
    )

    r = Results()
    run_encode_path(vectors.get("encodePath", []), r)
    run_encode_value(vectors.get("encodeValue", []), r)
    run_reject(vectors.get("reject", []), maps, r)
    run_leaf(vectors.get("leaf", []), r)
    run_tree(vectors.get("tree", []), r)
    trees = {
        t["name"]: [bytes.fromhex(h) for h in t["leafHashes"]] for t in vectors.get("tree", [])
    }
    run_inclusion(vectors.get("inclusion", []), trees, r)
    run_negative_proof(vectors.get("negativeProof", []), r)
    run_type_map(vectors.get("typeMap", []), maps, r)
    run_record(vectors.get("record", []), maps, r, references, authorize_empty)
    run_ordering(vectors.get("ordering", []), maps, r, authorize_empty)
    run_unlinkability(vectors.get("unlinkability", []), r)
    run_normalization(vectors.get("normalization", []), maps, r, authorize_empty)
    run_envelope(vectors.get("envelope", []), config, r)
    run_round_trip(vectors.get("roundTrip", []), maps, r, config, authorize_empty)

    observed_classes = set(r.passed) | set(r.failed) | set(r.not_run)
    missing_classes = [cls for cls in EXPECTED_CLASSES if cls not in observed_classes]
    for cls in missing_classes:
        r.unavailable(
            cls,
            "entire class",
            "no assertion, failure, or unavailable vector was recorded for this class",
        )

    classes = sorted(set(EXPECTED_CLASSES) | observed_classes)
    print(f"{'class':>5}  {'pass':>6}  {'fail':>6}  {'not run':>7}  status")
    total_fail = 0
    total_not_run = 0
    classes_passed = 0
    for cls in classes:
        passed = r.passed.get(cls, 0)
        failed = len(r.failed.get(cls, ()))
        not_run = len(r.not_run.get(cls, ()))
        total_fail += failed
        total_not_run += not_run
        if failed:
            status = "FAIL"
        elif not_run:
            status = "INCOMPLETE - NOT RUN" if passed else "NOT RUN"
        elif passed:
            status = "PASS"
            classes_passed += 1
        else:
            status = "NOT RUN"
        print(f"{cls:>5}  {passed:>6}  {failed:>6}  {not_run:>7}  {status}")

    if total_not_run:
        print("\nNot run:")
        for cls in sorted(r.not_run):
            for line in r.not_run[cls]:
                print(f"  class {cls}: {line}")

    if total_fail:
        print(f"\n{total_fail} assertion(s) failed:")
        for cls in sorted(r.failed):
            for line in r.failed[cls] if args.verbose else r.failed[cls][:12]:
                print(f"  class {cls}: {line}")
            if not args.verbose and len(r.failed[cls]) > 12:
                print(f"  class {cls}: ... and {len(r.failed[cls]) - 12} more (--verbose)")
        print(
            f"\nRESULT: FAIL ({sum(r.passed.values())} passed; {total_fail} failed; "
            f"{total_not_run} not run; {classes_passed}/{len(EXPECTED_CLASSES)} classes passed)"
        )
        return 1

    if total_not_run:
        print(
            f"\nRESULT: INCOMPLETE / NOT RUN ({sum(r.passed.values())} assertions passed; "
            f"{total_not_run} not run; {classes_passed}/{len(EXPECTED_CLASSES)} classes passed)"
        )
        return 2

    print(
        f"\nRESULT: PASS ({sum(r.passed.values())} assertions; "
        f"{classes_passed}/{len(EXPECTED_CLASSES)} classes passed; 0 not run)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
