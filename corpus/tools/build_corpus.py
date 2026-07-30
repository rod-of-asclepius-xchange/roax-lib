#!/usr/bin/env python3
"""Build `corpus/conformance-corpus-1.0.json` with implementation A.

Every expected value in the output is computed here. Nothing is copied from the prior
canonicalization research: its roots were produced under an earlier domain string, an
unprefixed salt preimage, no `recordId` in the preimage and no reserved leaves, so none of its
whole-record numbers transfer.

Usage:
    python3 build_corpus.py [--out PATH] [--references DIR]

`--references` points at a read-only checkout of the Open-Attestation schemata package. When it
is absent class 10 reports NOT RUN and `--check` exits 2, never success.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import corpus_plan as plan  # noqa: E402
import fixture_io  # noqa: E402
import moh_records  # noqa: E402
import roax_ref as ref
import salt_sets  # noqa: E402
import synthetic_records  # noqa: E402
from envelope_fixtures import build_envelope_fixtures  # noqa: E402
from roax_ref import RoaxError  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(CORPUS_DIR)

CORPUS_VERSION = "1.0.0"

# docs/conformance-corpus.md section 3 states the class count, and schemas/conformance-corpus-1.0.json
# sets classRef's maximum to match. All three MOVE TOGETHER: a stale count here means the
# highest-numbered class is never checked for coverage, which is the silent skip the coverage
# report exists to prevent. 17 until the ten engineering decisions were ruled on 2026-07-28, which
# added class 18 (outside-the-root authority, decision D8) and class 19 (NFC end to end, D12).
CLASS_COUNT = 19
# docs/conformance-corpus.md class 8 makes these leaf counts mandatory, and
# schemas/conformance-corpus-1.0.json names this check as what enforces that, since a requirement
# on the SET of tree vectors is not expressible per vector. Held separately from
# `corpus_plan.TREE_SIZES` on purpose: a check reading the same constant the build iterates would
# agree with any edit to it, including one that dropped a non-power-of-two size and left the split
# rule untested.
MANDATORY_TREE_SIZES = (1, 2, 3, 5, 7, 8, 9, 130)
HASH_ALG = "SHA-256"
# Section 6.1 pins Unicode 15.1. Implementation A runs Python's own tables; the value written
# here is the pin, and `build_corpus.py --report` prints the tables actually used so a mismatch
# between the pin and the generator is visible rather than assumed.
UNICODE_VERSION = "15.1"


# ---------------------------------------------------------------------------------------------
# Input escape forms, documented in corpus/README.md
# ---------------------------------------------------------------------------------------------


def resolve_input(value):
    """Resolve a corpus `input` into the form an implementation consumes.

    Plain JSON values pass through. `{"$utf16": [...]}` builds a string from UTF-16 code units,
    which is how a lone surrogate is carried without putting one in the file. `{"$segments":
    [...]}` carries a path that the corpus schema's own `segments` definition cannot express.
    `{"$jsonText": "..."}` carries record text to be handed to the JSON reader.
    """
    if isinstance(value, dict):
        if "$utf16" in value:
            return "".join(chr(int(u, 16)) for u in value["$utf16"])
        if "$segments" in value:
            return [resolve_segment(s) for s in value["$segments"]]
        if "$jsonText" in value:
            return value["$jsonText"]
    return value


def resolve_segment(seg):
    if "key" in seg:
        return {"key": resolve_input(seg["key"])}
    return {"index": seg["index"]}


# ---------------------------------------------------------------------------------------------
# Vector builders
# ---------------------------------------------------------------------------------------------


def build_encode_path():
    out = []
    for name, cls, segments in plan.ENCODE_PATH:
        out.append({
            "name": name,
            "class": cls,
            "segments": segments,
            "encodedHex": ref.encode_path(segments).hex(),
            "displayPath": ref.display_path(segments),
        })
    return out


def build_encode_value():
    out = []
    for name, cls, tag, value in plan.ENCODE_VALUE:
        entry = {"name": name, "class": cls, "tag": tag}
        if value is not None:
            entry["input"] = value
        entry["encodedHex"] = ref.encode_value(tag, value).hex()
        out.append(entry)
    return out


def build_reject():
    """Every reject vector is RUN here, and its `reason` is the code the implementation raised.

    A vector whose input does not actually error is a corpus defect and fails the build. The
    alternative - writing the expected reason by hand - would let a vector claim a rejection
    that no implementation performs.
    """
    out = []
    for name, cls, tag, raw in plan.REJECT:
        entry = {"name": name, "class": cls}
        if tag is not None:
            entry["tag"] = tag
        entry["input"] = raw
        try:
            run_reject(tag, raw)
        except RoaxError as exc:
            entry["reason"] = exc.code
        else:
            raise SystemExit(f"corpus defect: reject vector {name!r} did not error")
        out.append(entry)
    return out


def run_reject(tag, raw):
    """Feed a reject vector to the implementation the way a runner must."""
    resolved = resolve_input(raw)
    if isinstance(raw, dict) and "$segments" in raw:
        ref.check_reserved_namespace(resolved)
        ref.encode_path(resolved)
        return
    if isinstance(raw, dict) and "$jsonText" in raw:
        import json_literal
        node = json_literal.loads(resolved)
        # A duplicate key is only observable once the flattener walks the map, so walk it with a
        # type map that resolves everything to STRING. The flattener rejects the duplicate
        # before any tag is consulted.
        ref.flatten(node, _AllStringsTypeMap())
        return
    ref.encode_value(tag, resolved)


class _AllStringsTypeMap:
    """A type map used only to reach the flattener's structural rejections.

    It is NOT part of the corpus and MUST NOT be mistaken for a default-tag fallback, which
    specification section 4.2 forbids. It exists so that a parser-boundary reject vector can be
    driven through `flatten` without a real map, and every vector using it errors before any tag
    it returns is used.
    """

    def resolve(self, segments, kind):
        return ref.TAG_STRING


def build_unlinkability():
    """Class 12, and it ASSERTS RATHER THAN PINS.

    Decision D4 is ruled D4b, so salts are independent random draws and no fixed expectation can
    exist for what an implementation must draw freshly. The vector describes an issuance to
    perform and the relations the results MUST satisfy; this builder performs it.

    Three assertions, one per mistake docs/conformance-corpus.md class 12 names:

      within-issuance salts distinct   catches ONE DRAW PER RECORD reused across its leaves,
                                       which a single-path vector cannot see, because such an
                                       implementation still varies that path between trials;
      across-issuance salts distinct   catches a DETERMINISTIC salt and one REUSED ACROSS
                                       RECORDS, which is the patient-linkage failure itself;
      across-issuance leaf hashes      the property the class is named for, and the one a
        distinct                       reader checks: the same subject, path and value twice
                                       must not produce the same leaf hash.

    There is deliberately no within-issuance LEAF HASH assertion. Two different paths carry
    different encoded paths into the section 8 preimage, so their leaf hashes differ whatever
    the salts do, and asserting it would be coverage that cannot fail.

    HONEST LIMIT, also stated in the class: this detects a deterministic or reused salt. It does
    NOT detect a weak CSPRNG - 16 bytes from a badly seeded generator passes every trial while
    providing far less than the 128 bits spec section 7 requires. No fixed vector file can test
    a randomness source.
    """
    out = []
    for name, cls, paths, tag, value, trials, record_ids in plan.UNLINKABILITY:
        # Two entries that are different JSON text and the SAME path once NFC is applied pass the
        # schema's uniqueItems (spec section 6.1), and the within-issuance assertion would then
        # compare a path a record can hold only once. `encode_path` normalizes, so comparing
        # encoded forms is the duplicate-path rejection `ordered_leaves` makes over a record's
        # union; this class issues no record and never reaches that one.
        if len({ref.encode_path(p) for p in paths}) != len(paths):
            raise SystemExit(
                f"corpus defect: unlinkability vector {name!r} names two paths that are equal "
                f"once NFC is applied"
            )
        seen_salts = set()
        seen_hashes = set()
        for trial in range(trials):
            drawn = [secrets.token_bytes(16) for _ in paths]
            if len({s.hex() for s in drawn}) != len(drawn):
                raise SystemExit(
                    f"corpus defect: unlinkability vector {name!r} drew a repeated salt within "
                    f"one issuance at trial {trial}"
                )
            for segments, salt in zip(paths, drawn):
                key = (ref.encode_path(segments).hex(), salt.hex())
                if key in seen_salts:
                    raise SystemExit(
                        f"corpus defect: unlinkability vector {name!r} repeated a salt across "
                        f"issuances"
                    )
                seen_salts.add(key)
                h = ref.leaf_hash(HASH_ALG, segments, tag, value, salt).hex()
                hkey = (ref.encode_path(segments).hex(), h)
                if hkey in seen_hashes:
                    raise SystemExit(
                        f"corpus defect: unlinkability vector {name!r} repeated a leaf hash "
                        f"across issuances at the same path"
                    )
                seen_hashes.add(hkey)

        vec = {
            "name": name,
            "class": cls,
            "paths": paths,
            "tag": tag,
            "value": value,
            "trials": trials,
            "expectDistinctSaltsWithinIssuance": True,
            "expectDistinctSaltsAcrossIssuances": True,
            "expectDistinctLeafHashesAcrossIssuances": True,
        }
        if record_ids is not None:
            vec["recordIds"] = record_ids
        out.append(vec)
    return out


def build_leaf():
    """Leaf vectors at one shared path, so a difference can only come from tag or value.

    The corpus schema has no "these two must differ" assertion and does not need one: both leaf
    hashes are in the file, so an implementation that reproduces them reproduces the
    distinction. The names say which pairs carry the intent.
    """
    salt = bytes.fromhex(plan.LEAF_SALT)
    out = []
    for name, cls, tag, value in plan.ENCODE_VALUE:
        entry = {
            "name": "leaf-" + name,
            "class": cls,
            "segments": plan.VALUE_PATH,
            "tag": tag,
        }
        if value is not None:
            entry["value"] = value
        entry["saltHex"] = plan.LEAF_SALT
        entry["leafHash"] = ref.leaf_hash(HASH_ALG, plan.VALUE_PATH, tag, value, salt).hex()
        out.append(entry)

    # The same leaf value at every interesting path, so that class 4 and class 6 are tested
    # through leaf construction and not only through encodePath.
    for name, cls, segments in plan.ENCODE_PATH:
        out.append({
            "name": "leaf-at-" + name,
            "class": cls,
            "segments": segments,
            "tag": ref.TAG_STRING,
            "value": "x",
            "saltHex": plan.LEAF_SALT,
            "leafHash": ref.leaf_hash(HASH_ALG, segments, ref.TAG_STRING, "x", salt).hex(),
        })
    return out


def synthetic_tree_leaves(n):
    """Deterministic stand-in leaf hashes for the tree class.

    Class 8 tests MTH and the RFC 9162 split rule, not leaf construction, so its leaves are
    generated rather than built from records. The rule is stated here and in corpus/README.md
    so that both implementations regenerate identical trees; a consumer of the corpus does not
    need it, because every tree vector carries its leaf hashes explicitly.
    """
    return [
        ref.H(HASH_ALG, f"ROAX-CORPUS/{CORPUS_VERSION}/tree/{n}/{i}".encode("ascii"))
        for i in range(n)
    ]


def build_tree_and_inclusion():
    missing = [n for n in MANDATORY_TREE_SIZES if n not in plan.TREE_SIZES]
    if missing:
        raise SystemExit(
            f"corpus defect: class 8 requires leaf counts {list(MANDATORY_TREE_SIZES)} "
            f"(docs/conformance-corpus.md class 8) and the plan omits {missing}"
        )
    trees = []
    inclusions = []
    for n in plan.TREE_SIZES:
        leaves = synthetic_tree_leaves(n)
        root = ref.mth(HASH_ALG, leaves)
        trees.append({
            "name": f"tree-n{n}",
            "class": 8,
            "leafHashes": [h.hex() for h in leaves],
            "root": root.hex(),
        })
        # An inclusion proof for EVERY leaf at each size. A corpus that samples a few indices
        # misses exactly the boundary the split rule gets wrong.
        for i in range(n):
            path = ref.inclusion_path(HASH_ALG, i, leaves)
            ok = ref.verify_inclusion(HASH_ALG, leaves[i], i, n, path, root)
            if not ok:
                raise SystemExit(f"corpus defect: self-generated proof n={n} i={i} does not verify")
            inclusions.append({
                "name": f"inclusion-n{n}-i{i}",
                "class": 8,
                "leafHash": leaves[i].hex(),
                "index": i,
                "treeSize": n,
                "auditPath": [h.hex() for h in path],
                "root": root.hex(),
                "expect": True,
            })
    return trees, inclusions


def flip_last_byte(h: bytes) -> bytes:
    return h[:-1] + bytes([h[-1] ^ 0x01])


def build_negative_proof():
    out = []
    for name, cls, attack, n, index in plan.NEGATIVE_PROOF:
        leaves = synthetic_tree_leaves(n)
        root = ref.mth(HASH_ALG, leaves)
        vec = {"name": name, "class": cls, "attack": attack, "treeSize": n, "index": index}

        if attack == "index-out-of-range":
            base = ref.inclusion_path(HASH_ALG, 0, leaves)
            vec["leafHash"] = leaves[0].hex()
            vec["auditPath"] = [h.hex() for h in base]
            vec["root"] = root.hex()
        elif attack == "internal-node-as-leaf":
            # The dogtag C1 hazard. An internal node is presented as though it were a leaf,
            # with the audit path that would carry it to the root if the tree were two leaves
            # deep. RFC 9162 rejects it because verification consumes the TRUE tree size and
            # runs out of path before `sn` reaches 0.
            k = 1
            while k * 2 < n:
                k *= 2
            internal = ref.mth(HASH_ALG, leaves[:k])
            sibling = ref.mth(HASH_ALG, leaves[k:])
            vec["leafHash"] = internal.hex()
            vec["auditPath"] = [sibling.hex()]
            vec["root"] = root.hex()
        else:
            base = ref.inclusion_path(HASH_ALG, index, leaves)
            if attack == "wrong-root":
                vec["leafHash"] = leaves[index].hex()
                vec["auditPath"] = [h.hex() for h in base]
                vec["root"] = flip_last_byte(root).hex()
            elif attack == "flipped-sibling":
                tampered = list(base)
                tampered[0] = flip_last_byte(tampered[0])
                vec["leafHash"] = leaves[index].hex()
                vec["auditPath"] = [h.hex() for h in tampered]
                vec["root"] = root.hex()
            elif attack == "truncated-audit-path":
                vec["leafHash"] = leaves[index].hex()
                vec["auditPath"] = [h.hex() for h in base[:-1]]
                vec["root"] = root.hex()
            elif attack == "extended-audit-path":
                vec["leafHash"] = leaves[index].hex()
                vec["auditPath"] = [h.hex() for h in base] + [root.hex()]
                vec["root"] = root.hex()
            else:  # pragma: no cover - the plan is a closed list
                raise SystemExit(f"unknown attack {attack}")

        # A negative vector that verifies is a corpus defect, not a passing test.
        if ref.verify_inclusion(
            HASH_ALG,
            bytes.fromhex(vec["leafHash"]),
            vec["index"],
            vec["treeSize"],
            [bytes.fromhex(h) for h in vec["auditPath"]],
            bytes.fromhex(vec["root"]),
        ):
            raise SystemExit(f"corpus defect: negative vector {name!r} verifies")
        out.append(vec)
    return out


# ---------------------------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------------------------


def build_moh_type_map_vectors(notes):
    """Class 11 over the derived MOH type maps. The outcome is computed, never asserted."""
    out = []
    for name, record_type, segments, kind in plan.MOH_TYPE_MAP_VECTORS:
        type_map = moh_records.load_type_map(record_type)
        if type_map is None:
            raise SystemExit(
                f"class 11 FAILED for {name}: "
                f"corpus/type-maps/{record_type}.json is missing"
            )
        vec = {"name": name, "class": 11, "recordType": record_type,
               "segments": segments, "jsonKind": kind}
        try:
            vec["expectTag"] = type_map.resolve(segments, kind)
        except RoaxError:
            vec["expectFailClosed"] = True
        out.append(vec)
    return out


def build(references=None, notes=None, check=False):
    """Build the corpus. In check mode no fixture is written; every one is compared instead.

    The fixtures were built at IMPORT time before, so `--check` had already rewritten all of
    them by the time it reached its own comparison - it erased the edit it existed to catch and
    dirtied a clean checkout doing it. Generation is explicit now, and the mode is set first.
    """
    fixture_io.set_mode("check" if check else "write")
    salt_sets.begin_build()
    if not salt_sets.drawing():
        salt_sets.validate_all()
    notes = notes if notes is not None else []
    trees, inclusions = build_tree_and_inclusion()

    records = list(synthetic_records.build_record_vectors())
    moh, moh_notes = moh_records.build_record_vectors(references)
    records.extend(moh)
    notes.extend(moh_notes)

    type_map_vectors = synthetic_records.build_type_map_vectors()
    envelopes = build_envelope_fixtures(HASH_ALG)

    unlinkability = build_unlinkability()
    normalization = synthetic_records.build_normalization_vectors()

    return {
        "corpusVersion": CORPUS_VERSION,
        "canon": ref.CANON,
        "hashAlg": HASH_ALG,
        "unicodeVersion": UNICODE_VERSION,
        "vectors": {
            "encodePath": build_encode_path(),
            "encodeValue": build_encode_value(),
            "reject": build_reject(),
            "leaf": build_leaf(),
            "tree": trees,
            "inclusion": inclusions,
            "negativeProof": build_negative_proof(),
            "typeMap": type_map_vectors + build_moh_type_map_vectors(notes),
            "record": records,
            "unlinkability": unlinkability,
            "normalization": normalization,
            "envelope": envelopes,
        },
    }


def serialize(corpus) -> str:
    """Serialize so that implementation B's output is byte-identical.

    `ensure_ascii=False` matches JSON.stringify, which does not escape non-ASCII. Both emit two
    space indentation, `": "` after a key and a trailing newline.
    """
    return json.dumps(corpus, indent=2, ensure_ascii=False) + "\n"


def coverage(corpus):
    """Which of the CLASS_COUNT classes have vectors. A class with none is a coverage gap."""
    seen = {}
    for kind, vectors in corpus["vectors"].items():
        for v in vectors:
            seen.setdefault(v["class"], {}).setdefault(kind, 0)
            seen[v["class"]][kind] += 1
    return seen


def _is_external_record(vector):
    """Whether a record vector's record lives outside this repository.

    `recordFile` is one of the two carriers the corpus schema admits; the other is a full
    envelope copy, which is always a fixture inside `corpus/` and therefore never external. A
    vector carrying only `envelopeFile` must not be read as external here, and it must not raise
    either: both callers walk the COMMITTED file, which a future vector may legitimately use that
    carrier in.
    """
    return "recordFile" in vector and not vector["recordFile"].startswith("corpus/")


def _external_record_vectors(corpus):
    """Names of record vectors whose record file lives outside this repository."""
    return {v["name"] for v in corpus["vectors"].get("record", []) if _is_external_record(v)}


def _external_salt_names(corpus):
    """Salt carriers retained for external rows when this run cannot load their records."""
    return {
        salt_sets.name_from_reference(v["saltsFile"])
        for v in corpus["vectors"].get("record", [])
        if _is_external_record(v)
    }


def _without_external_records(corpus):
    trimmed = dict(corpus)
    trimmed["vectors"] = dict(corpus["vectors"])
    trimmed["vectors"]["record"] = [
        v for v in corpus["vectors"].get("record", []) if not _is_external_record(v)
    ]
    return json.dumps(trimmed, sort_keys=True)


def extract_samples(references, out_dir, notes):
    """Extract the MOH samples to `out_dir` so the runner can read them.

    They go wherever the caller asks and never into this repository: `.gitignore` excludes
    `references/` and `schemata/` deliberately, and an extracted sample committed here would
    republish a third-party record by another route.
    """
    from extract_reference_record import ExtractError, extract

    src_root = moh_records.find_src_root(references)
    if src_root is None:
        notes.append(
            moh_records.NotRunNote(
                "extraction NOT RUN: no reference checkout supplied; rerun with "
                "--references <path-to-schemata>"
            )
        )
        return
    os.makedirs(out_dir, exist_ok=True)
    for profile in build_type_maps_profiles():
        module = os.path.join(src_root, profile["module"])
        if not os.path.exists(module):
            notes.append(
                moh_records.NotRunNote(
                    f"extraction NOT RUN for {profile['export']}: {module} not found"
                )
            )
            continue
        with open(module, "r", encoding="utf-8") as handle:
            try:
                text = extract(handle.read(), profile["export"])
            except ExtractError as exc:
                raise SystemExit(
                    f"extraction FAILED for {profile['export']}: {exc}"
                ) from exc
        with open(os.path.join(out_dir, profile["export"] + ".json"), "w",
                  encoding="utf-8") as handle:
            handle.write(text)


def build_type_maps_profiles():
    import build_type_maps
    return build_type_maps.PROFILES


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join(CORPUS_DIR, "conformance-corpus-1.0.json"))
    ap.add_argument("--references", default=os.environ.get("ROAX_REFERENCES"))
    ap.add_argument(
        "--salt-sets",
        default=None,
        help="read committed salt-set inputs from DIR instead of corpus/fixtures/salts",
    )
    ap.add_argument("--report", action="store_true", help="print per-class coverage")
    ap.add_argument("--draw-salts", action="store_true",
                    help="draw fresh salt sets into corpus/fixtures/salts/ and exit. Run ONCE "
                         "and commit the result: under decision D4b a salt is an independent "
                         "random draw that nothing can re-derive, so a normal build reads the "
                         "committed sets and never draws one (spec section 7). IT LEAVES THE "
                         "TREE INCONSISTENT: drawing runs a full build, so every envelope and "
                         "record fixture is rewritten under the new salts while the corpus file "
                         "itself keeps its old roots, and --check fails until a normal build "
                         "follows.")
    ap.add_argument("--check", action="store_true",
                    help="rebuild and compare the corpus AND every fixture against the "
                         "committed files instead of writing them; writes nothing")
    ap.add_argument("--extract-to", default=None,
                    help="also write the extracted MOH samples here, for the runner to read")
    args = ap.parse_args()
    if args.salt_sets is not None:
        salt_sets.set_directory(args.salt_sets)

    if args.draw_salts:
        # Draw and exit. Deliberately not part of any build: a build that drew its own salts
        # would produce a root no other machine could reproduce, which is the silent divergence
        # this corpus is the enforcement mechanism against.
        if args.check:
            raise SystemExit("--draw-salts and --check are contradictory: one writes, one compares")
        salt_sets.set_drawing(True)
        notes = []
        build(args.references, notes, check=False)
        drawn = salt_sets.committed_names()
        print(f"drew {len(drawn)} salt set(s) into {salt_sets.REPO_PREFIX}")
        for name in drawn:
            print(f"  {name}")
        print("commit these; a normal build reads them and never draws.")
        print("then run a normal build: every envelope and record fixture has just been "
              "rewritten under the new salts and the corpus file still carries the old roots.")
        return

    notes = []
    corpus = build(args.references, notes, check=args.check)
    text = serialize(corpus)
    check_incomplete = args.check and any(
        isinstance(note, moh_records.NotRunNote) for note in notes
    )

    if args.check:
        with open(args.out, "r", encoding="utf-8") as handle:
            committed_for_salts = json.load(handle)
        salt_sets.assert_name_set(
            salt_sets.used_names() | _external_salt_names(committed_for_salts)
        )

        # The fixtures first. The corpus vectors reference them by path, so a corpus that
        # round-trips over a tampered fixture is not a pass.
        differences = fixture_io.differences()
        if differences:
            print(f"MISMATCH: {len(differences)} fixture(s) differ from a fresh build "
                  f"or are not produced by one")
            for path, why in differences:
                print(f"  {os.path.relpath(path, REPO_ROOT)}: {why}")
            raise SystemExit(1)

        with open(args.out, "r", encoding="utf-8") as handle:
            committed_text = handle.read()
        if committed_text == text:
            print(f"ok: {args.out} and every fixture round-trip through implementation A "
                  f"byte for byte")
            if check_incomplete:
                print(
                    "INCOMPLETE: class 10 external records were NOT CHECKED; rerun with "
                    "--references <path-to-schemata>"
                )
        else:
            # Class 10 names records that live outside this repository, so without a reference
            # checkout a fresh build legitimately cannot contain them. Compare everything else
            # and SAY which part went unchecked, rather than reporting either a clean pass or a
            # defect when neither is true.
            committed = json.loads(committed_text)
            fresh = json.loads(text)
            missing = _external_record_vectors(committed) - _external_record_vectors(fresh)
            if missing and _without_external_records(committed) == _without_external_records(fresh):
                check_incomplete = True
                print(f"INCOMPLETE: {args.out} round-trips through implementation A except for "
                      f"{len(missing)} external record vector(s)")
                for name in sorted(missing):
                    print(
                        f"  NOT CHECKED: {name} - rerun with "
                        "--references <path-to-schemata>"
                    )
            else:
                print(f"MISMATCH: {args.out} differs from a fresh build by implementation A")
                raise SystemExit(1)
    else:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
        # Write mode records no per-fixture difference, so anything here is an orphan - and
        # write mode is the run that CREATES one, by renaming a vector and leaving the old file.
        # Reported rather than failed: writing is not a gate.
        for path, why in fixture_io.differences():
            notes.append(f"{os.path.relpath(path, REPO_ROOT)}: {why}")

    if args.extract_to:
        extract_samples(args.references, args.extract_to, notes)
        check_incomplete = check_incomplete or (
            args.check
            and any(isinstance(note, moh_records.NotRunNote) for note in notes)
        )

    total = sum(len(v) for v in corpus["vectors"].values())
    print(f"{'checked' if args.check else 'wrote'} {args.out}: {total} vectors")
    for note in notes:
        print(f"  note: {note}")

    if args.report:
        import unicodedata
        print(f"  generator Unicode tables: {unicodedata.unidata_version} (corpus pins {UNICODE_VERSION})")
        cov = coverage(corpus)
        for cls in range(1, CLASS_COUNT + 1):
            if cls in cov:
                detail = ", ".join(f"{k}={n}" for k, n in sorted(cov[cls].items()))
                print(f"  class {cls:2d}: {detail}")
            elif cls == 10 and check_incomplete:
                print(
                    "  class 10: NOT RUN - rerun with "
                    "--references <path-to-schemata>"
                )
            else:
                print(f"  class {cls:2d}: NO VECTORS - coverage gap")

    if check_incomplete:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
