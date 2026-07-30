"""Class 10 - record vectors over the three real Singapore MOH samples.

The samples are read in place from a read-only reference checkout and are never copied into
this repository, so `recordFile` names the third-party module and export rather than a file
here. `corpus/README.md` documents the extraction a runner performs first.

Only the profiles whose type map binds EVERY scalar the sample contains get a vector. A profile
with an unbound path does not get one, and it does not get a guessed binding either: under
specification section 4.2 an uncovered path fails closed, so a record containing one is not
committable and there is no root to pin. Those paths become class 11 fail-closed vectors
instead, which is a real assertion rather than a placeholder.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_type_maps  # noqa: E402
import roax_ref as ref  # noqa: E402
from corpus_plan import ISSUER_ID, ISSUER_KEY_ID  # noqa: E402
import salt_sets  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS_DIR = os.path.dirname(HERE)
TYPE_MAP_DIR = os.path.join(CORPUS_DIR, "type-maps")


class NotRunNote(str):
    """A displayed note that also makes a check incomplete."""


# One stable record identifier per sample.
# These are corpus identifiers, not anything the samples carry: `recordId` is committed as the
# reserved envelope identity leaf (specification section 11.2), while every salt is an independent
# draw with no identity preimage (specification section 7).
RECORD_IDS = {
    "sg.gov.moh.vaccination-healthcert": "urn:uuid:aaaaaaa1-0000-4000-8000-000000000001",
    "sg.gov.moh.pdt-healthcert": "urn:uuid:aaaaaaa2-0000-4000-8000-000000000002",
    "sg.gov.moh.recovery-healthcert": "urn:uuid:aaaaaaa3-0000-4000-8000-000000000003",
}


def find_src_root(references):
    if not references:
        return None
    # Accept the parent layout used by this repository's gitignored `references/schemata`
    # checkout, the checkout root documented as `--references /path/to/schemata`, and a direct
    # path to its `src` directory.
    for candidate in (
        os.path.join(references, "schemata", "src"),
        os.path.join(references, "src"),
    ):
        if os.path.isdir(candidate):
            return candidate
    return references if os.path.isdir(references) else None


def load_type_map(record_type):
    import json
    path = os.path.join(TYPE_MAP_DIR, record_type + ".json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return ref.TypeMap(json.load(handle))


def _salt_doc(name, ordered):
    """Draw under --draw-salts, otherwise read the committed set.

    POSITIONAL for this class, and that is the point rather than an economy: these are the
    genuine third-party MOH reference samples, so a path-keyed set would enumerate every path of
    a shipped sample into this public repository. See salt_sets and docs/conformance-corpus.md
    class 10.
    """
    if salt_sets.drawing():
        return salt_sets.draw(name, ordered, "positional")
    return salt_sets.load(name)


def build_record_vectors(references):
    """Return (vectors, notes). `notes` records every omission, loudly.

    A missing reference checkout produces vectors=[] and a note. It MUST NOT produce silence:
    class 10 reporting green while unrun is the defect this whole document is about.
    """
    notes = []
    src_root = find_src_root(references)
    if src_root is None:
        notes.append(
            NotRunNote(
                "class 10 NOT RUN: no reference checkout supplied. "
                "Rerun with --references <path-to-schemata>; the three MOH samples live outside "
                "this repository by design."
            )
        )
        return [], notes

    import json_literal
    from extract_reference_record import ExtractError, extract

    vectors = []
    for profile in build_type_maps.PROFILES:
        record_type = profile["recordType"]
        type_map = load_type_map(record_type)
        if type_map is None:
            raise SystemExit(
                f"class 10 FAILED for {record_type}: committed corpus type map is missing"
            )

        module = os.path.join(src_root, profile["module"])
        if not os.path.exists(module):
            notes.append(
                NotRunNote(
                    f"class 10 NOT RUN for {record_type}: {profile['module']} not found under "
                    f"--references"
                )
            )
            continue
        with open(module, "r", encoding="utf-8") as handle:
            try:
                text = extract(handle.read(), profile["export"])
            except ExtractError as exc:
                raise SystemExit(
                    f"class 10 FAILED for {record_type}: extraction failed - {exc}"
                ) from exc
        record = json_literal.loads(text)
        record_id = RECORD_IDS[record_type]
        record_file = "references/schemata/src/" + profile["module"] + "#" + profile["export"]

        name_no_key = f"record-{record_type}-no-key-id"
        try:
            identity = (record_type, profile["schemaVersion"], record_id, ISSUER_ID)
            ordered = ref.ordered_leaves(record, type_map, *identity)
            salts = ref.salt_set_from_document(_salt_doc(name_no_key, ordered), ordered)
            root, leaves, _salts, _hashes = ref.build_tree(
                "SHA-256", record, type_map, salts, *identity
            )
        except ref.RoaxError as exc:
            # The honest outcome for a profile whose reference schema does not determine a tag
            # for every scalar in its own shipped sample.
            notes.append(
                f"class 10 OMITTED for {record_type}: the record is not committable under the "
                f"fail-closed rule of specification section 4.2 - {exc.code} at {exc.detail}. "
                f"The unbound paths are class 11 fail-closed vectors instead."
            )
            continue

        vectors.append({
            "name": name_no_key,
            "class": 10,
            "recordType": record_type,
            "schemaVersion": profile["schemaVersion"],
            "issuerId": ISSUER_ID,
            "recordFile": record_file,
            "saltsFile": salt_sets.reference_for(name_no_key),
            "saltPairing": "positional",
            "recordId": record_id,
            "leafCount": len(leaves),
            "root": root.hex(),
        })

        # The same record with issuer.keyId present. Section 11.2: an absent issuer.keyId emits
        # NO leaf, so the two vectors differ by exactly one leaf and by their whole root. An
        # implementation that emits a NULL leaf or an empty string for the absent case matches
        # neither.
        name_with_key = f"record-{record_type}-with-key-id"
        identity2 = (record_type, profile["schemaVersion"], record_id, ISSUER_ID, ISSUER_KEY_ID)
        ordered2 = ref.ordered_leaves(record, type_map, *identity2)
        salts2 = ref.salt_set_from_document(_salt_doc(name_with_key, ordered2), ordered2)
        root2, leaves2, _s2, _h2 = ref.build_tree(
            "SHA-256", record, type_map, salts2, *identity2
        )
        if len(leaves2) != len(leaves) + 1 or root2 == root:
            raise SystemExit(f"corpus defect: issuer.keyId did not add exactly one leaf for {record_type}")
        vectors.append({
            "name": name_with_key,
            "class": 10,
            "recordType": record_type,
            "schemaVersion": profile["schemaVersion"],
            "issuerId": ISSUER_ID,
            "issuerKeyId": ISSUER_KEY_ID,
            "recordFile": record_file,
            "saltsFile": salt_sets.reference_for(name_with_key),
            "saltPairing": "positional",
            "recordId": record_id,
            "leafCount": len(leaves2),
            "root": root2.hex(),
        })

    return vectors, notes


def unbound_paths(references):
    """The (recordType, pattern, jsonKind, why) tuples class 11 turns into fail-closed vectors."""
    src_root = find_src_root(references)
    if src_root is None:
        return []
    out = []
    for entry in build_type_maps.build(os.path.dirname(os.path.dirname(src_root)), None):
        for u in entry["unbound"]:
            out.append((entry["recordType"], u["pattern"], u["jsonKind"], u["why"]))
    return out
