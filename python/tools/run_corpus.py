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

Exit status is 0 only when every reachable class passes.
A class that cannot run says SKIPPED and contributes no assertions; it never reports green
unrun.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
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
    RoaxError,
    VerifierConfig,
    audit_path,
    build_tree,
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
from roax_canon.flatten import check_reserved_namespace  # noqa: E402
from roax_canon.path import segments_from_json  # noqa: E402
from roax_canon.profiles import CORPUS_SYNTHETIC_PROFILE  # noqa: E402
from ts_sample import load_export  # noqa: E402

REPO = os.path.dirname(os.path.dirname(_HERE))
CORPUS = os.path.join(REPO, "corpus", "conformance-corpus-1.0.json")
TYPE_MAP_DIR = os.path.join(REPO, "corpus", "type-maps")


# ---------------------------------------------------------------------------------
# Result accounting
# ---------------------------------------------------------------------------------


class Results:
    def __init__(self) -> None:
        self.passed: dict[int, int] = defaultdict(int)
        self.failed: dict[int, list[str]] = defaultdict(list)
        self.skipped: dict[int, list[str]] = defaultdict(list)

    def ok(self, cls: int) -> None:
        self.passed[cls] += 1

    def bad(self, cls: int, name: str, detail: str) -> None:
        self.failed[cls].append(f"{name}: {detail}")

    def skip(self, cls: int, name: str, why: str) -> None:
        self.skipped[cls].append(f"{name}: {why}")

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


def salts_by_path(path: str) -> dict[bytes, bytes]:
    doc = load_file(path)
    entries = doc["salts"] if isinstance(doc, dict) else doc
    return {
        encode_path(segments_from_json(e["segments"])): bytes.fromhex(e["salt"])
        for e in entries
    }


def positional_salts(path: str) -> list[bytes]:
    doc = load_file(path)
    entries = doc["salts"] if isinstance(doc, dict) else doc
    return [bytes.fromhex(s) for s in entries]


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
            got = encode_value(x["tag"], unescape(x.get("input"))).hex()
        except RoaxError as exc:
            r.bad(x["class"], x["name"], f"rejected with {exc.code}")
            continue
        r.check(x["class"], x["name"], got, x["encodedHex"])


def run_reject(vectors, r: Results) -> None:
    """Every one of these MUST error, with the reference reason code."""
    for x in vectors:
        cls, name = x["class"], x["name"]
        raw = x.get("input")
        try:
            if isinstance(raw, dict) and set(raw) == {"$jsonText"}:
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
                encode_value(x["tag"], unescape(raw))
            else:
                r.skip(cls, name, "no input shape this runner recognizes")
                continue
        except RoaxError as exc:
            r.check(cls, name, exc.code, x["reason"], "reason: ")
            continue
        r.bad(cls, name, f"accepted; expected rejection {x['reason']!r}")


def run_leaf(vectors, r: Results) -> None:
    for x in vectors:
        segs = segments_from_json(x["segments"])
        got = leaf_hash(segs, x["tag"], unescape(x.get("value")), bytes.fromhex(x["saltHex"])).hex()
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
    :func:`roax_canon.verify.verify_envelope` has no parameter that takes one, and it is
    exercised by every class-14 through class-18 envelope vector.
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
        except FileNotFoundError:
            r.skip(cls, name, f"no corpus type map for {x['recordType']}")
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
                r.bad(cls, name, f"failed closed with {exc.code}; expected tag {x.get('expectTag')}")
            continue
        if x.get("expectFailClosed"):
            r.bad(cls, name, f"resolved to tag {tag}; expected fail-closed")
        else:
            r.check(cls, name, tag, x["expectTag"], "tag: ")


def _record_for(vector, references: str | None):
    """Load a record vector's record, which may live outside this repository."""
    ref = vector["recordFile"]
    if "#" in ref:
        module, export = ref.split("#", 1)
        if references is None:
            return None, "no --references checkout supplied"
        rel = module
        prefix = "references/"
        if rel.startswith(prefix):
            rel = rel[len(prefix) :]
        candidate = os.path.join(references, rel)
        if not os.path.exists(candidate):
            # Allow --references to point either at the parent of `schemata/` or at the
            # checkout itself.
            candidate = os.path.join(references, rel.split("/", 1)[1] if "/" in rel else rel)
        if not os.path.exists(candidate):
            return None, f"{candidate} not found"
        return load_export(candidate, export), None
    return load_file(os.path.join(REPO, ref)), None


def run_record(vectors, maps, r: Results, references, authorize_empty) -> None:
    for x in vectors:
        cls, name = x["class"], x["name"]
        if "envelopeFile" in x:
            r.skip(cls, name, "envelope-carrier record vectors are covered by the envelope class")
            continue
        record, why = _record_for(x, references)
        if record is None:
            r.skip(cls, name, why or "record unavailable")
            continue
        identity = RecordIdentity(
            record_type=x["recordType"],
            schema_version=x["schemaVersion"],
            record_id=x["recordId"],
            issuer_id=x["issuerId"],
            issuer_key_id=x.get("issuerKeyId"),
            type_map_id=x.get("typeMapId"),
        )
        salts_path = os.path.join(REPO, x["saltsFile"])
        if x["saltPairing"] == "positional":
            salts = PositionalSalts(positional_salts(salts_path))
        else:
            salts = MappingSalts(salts_by_path(salts_path))
        try:
            built = build_tree(
                record,
                identity,
                maps(x["recordType"]),
                salts,
                reserved_set=_reserved_set(x),
                authorize_empty_containers=authorize_empty,
            )
        except RoaxError as exc:
            r.bad(cls, name, f"rejected with {exc.code}: {exc.detail}")
            continue
        r.check(cls, name, built.leaf_count, x["leafCount"], "leafCount: ")
        r.check(cls, name, built.root.hex(), x["root"], "root: ")


def _reserved_set(vector) -> str:
    from roax_canon import RESERVED_V1, RESERVED_V2

    return RESERVED_V2 if vector.get("typeMapId") else RESERVED_V1


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
        by_path = salts_by_path(os.path.join(REPO, x["saltsFile"]))
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
            roots.append(built.root.hex())
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
        default=os.path.join(REPO, "references"),
        help="checkout holding the third-party reference schemata; class 10 needs it",
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
    references = args.references if os.path.isdir(args.references) else None

    corpus = json.load(open(CORPUS, encoding="utf-8"))
    vectors = corpus["vectors"]

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
    if references is None:
        print("  references        NOT SUPPLIED - class 10 will report SKIPPED")
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
        hash_alg_allow_list=(
            (corpus["hashAlg"],) if corpus["hashAlg"] == "SHA-256" else ("SHA-256",)
        ),
        resolvers=resolvers,
        authorize_empty_containers=authorize_empty,
    )

    r = Results()
    run_encode_path(vectors.get("encodePath", []), r)
    run_encode_value(vectors.get("encodeValue", []), r)
    run_reject(vectors.get("reject", []), r)
    run_leaf(vectors.get("leaf", []), r)
    run_tree(vectors.get("tree", []), r)
    trees = {
        t["name"]: [bytes.fromhex(h) for h in t["leafHashes"]] for t in vectors.get("tree", [])
    }
    run_inclusion(vectors.get("inclusion", []), trees, r)
    run_negative_proof(vectors.get("negativeProof", []), r)
    run_type_map(vectors.get("typeMap", []), maps, r)
    run_record(vectors.get("record", []), maps, r, references, authorize_empty)
    run_unlinkability(vectors.get("unlinkability", []), r)
    run_normalization(vectors.get("normalization", []), maps, r, authorize_empty)
    run_envelope(vectors.get("envelope", []), config, r)

    classes = sorted(set(r.passed) | set(r.failed) | set(r.skipped))
    print(f"{'class':>5}  {'pass':>6}  {'fail':>6}  {'skip':>6}  status")
    total_fail = 0
    for cls in classes:
        passed = r.passed[cls]
        failed = len(r.failed[cls])
        skipped = len(r.skipped[cls])
        total_fail += failed
        status = "FAIL" if failed else ("PASS" if passed else "SKIPPED - NOT RUN")
        if not failed and skipped:
            status += f" ({skipped} skipped)"
        print(f"{cls:>5}  {passed:>6}  {failed:>6}  {skipped:>6}  {status}")

    missing = [c for c in range(1, 20) if c not in classes]
    if missing:
        print(f"\nclasses with no assertions at all: {missing}")

    if r.skipped:
        print("\nSkipped:")
        for cls in sorted(r.skipped):
            for line in r.skipped[cls]:
                print(f"  class {cls}: {line}")

    if total_fail:
        print(f"\n{total_fail} assertion(s) failed:")
        for cls in sorted(r.failed):
            for line in r.failed[cls] if args.verbose else r.failed[cls][:12]:
                print(f"  class {cls}: {line}")
            if not args.verbose and len(r.failed[cls]) > 12:
                print(f"  class {cls}: ... and {len(r.failed[cls]) - 12} more (--verbose)")
        print("\nRESULT: FAIL")
        return 1

    print(f"\nRESULT: PASS ({sum(r.passed.values())} assertions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
