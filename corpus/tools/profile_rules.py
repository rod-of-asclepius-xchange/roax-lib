"""Versioned profile value rules, and the reason they are NOT in the canonicalization layer.

A ROAX type map answers one question: which tag does this structured path and observed JSON
kind select (specification section 4.2). A VALUE-DOMAIN constraint is a different question, and
specification section 4.2 puts it in a different place and a different order: "Issuance MUST
first validate against the pinned profile schema and then resolve every emitted leaf through the
exact selected map." Profile validation runs BEFORE resolution and is not part of it.

**Decision D13 already ruled where a rule like this lives, and it is not here.** D13 was ruled
D13a with a split: the protocol layer proves commitment and issuer identity and says so in those
words, while value-domain and clinical validation is "a separate, independently versioned
conformance layer" (`docs/decisions.md`, D13). Merging the two was rejected explicitly, because
it puts profile governance on the critical path of a cryptographic specification. So a
positive-integer narrowing on a dose number is a profile-validation rule by ruling and not by
convenience, and `roax_ref.py` deliberately does not carry it.

What this module is, then, is the ISSUER's half of section 4.2 step 1, executable. `moh_records`
is the issuer for class 10: it takes a real MOH sample and commits it. A real issuer validates
against the pinned profile first, so this table runs there, before any leaf is built. A record
violating a declared rule is refused and never reaches a root.

**Every path is carried as SEGMENTS, never as display notation.** That is the section 5.2 trap
one layer above hashing and it has already been made once in this repository, on the disclosure
floors: `notarisationMetadata.reference` reads as one token and is TWO segments, and a rule
holding the dotted string as a single KEY asks for a leaf no record has, matches nothing, and is
silently unenforced while every fixture built the same way agrees with it. An `anyIndex` segment
is written as `None`.

The rules are versioned by the profile document that declares them, which is the artifact a
deployment cites. `PROFILE_RULE_VERSION` names the revision this table implements.
"""

from __future__ import annotations

import re

# The revision of `docs/profiles/<profile>.md` section 6 this table implements. Bumped with any
# change to a rule below, because a deployment cites a version rather than a file date.
PROFILE_RULE_VERSION = "1.1"

# A grammar-valid ROAX INTEGER whose magnitude is at least 1. The leading `-` is excluded rather
# than tolerated: the rule is POSITIVE, so `-1` and `0` are both outside it, and `-0`
# canonicalizes to `0` and is outside it too.
_POSITIVE_INTEGER = re.compile(r"\A[1-9][0-9]*\Z")


def _positive_integer(text):
    return isinstance(text, str) and _POSITIVE_INTEGER.match(text) is not None


# recordType -> ((segments, rule id, predicate, why), ...)
#
# A segment is a key string, or None for any array index.
PROFILE_VALUE_RULES = {
    "sg.gov.moh.vaccination-healthcert": (
        (
            ("notarisationMetadata", "signedEuHealthCerts", None, "dose"),
            "dose-positive-integer",
            _positive_integer,
            "RULED 2026-07-30. The dose number is bound INTEGER, and the profile narrows it to a "
            "positive integer. The type-map binding alone would leave `0` and every negative "
            "value formally valid under the selected profile, because both are grammar-valid "
            "ROAX INTEGERs. The EU Digital COVID Certificate this field mirrors defines its "
            "dose-sequence number through `dose_posint`, which is `integer` with minimum 1. "
            "A fractional value is already refused one layer down by the INTEGER grammar of "
            "specification section 6.2, so this rule is about `0` and the negatives and nothing "
            "else. See `docs/profiles/vaccination-healthcert.md` section 6.",
        ),
    ),
}


class ProfileRuleError(Exception):
    """A record refused by profile validation, before any leaf was built."""

    def __init__(self, rule_id, path, detail):
        super().__init__(f"{rule_id} at {path}: {detail}")
        self.rule_id = rule_id
        self.path = path
        self.detail = detail


def _matches(pattern, segments):
    if len(pattern) != len(segments):
        return False
    for expected, seg in zip(pattern, segments):
        if expected is None:
            if "index" not in seg:
                return False
        else:
            if "key" not in seg or seg["key"] != expected:
                return False
    return True


def check_record(record_type, leaves):
    """Apply every declared rule for `record_type` to already-flattened leaves.

    `leaves` are `roax_ref.Leaf` values, so each carries its structured segments and its
    canonical carrier value. Running after flattening rather than over the raw JSON is
    deliberate: the rule is stated over the canonical INTEGER text, so it cannot disagree with
    the value the leaf actually commits.

    Raises :class:`ProfileRuleError` on the first violation. A profile validator has no reason
    to enumerate, and stopping at the first refusal keeps a rejection's detail unambiguous.
    """
    import roax_ref as ref

    rules = PROFILE_VALUE_RULES.get(record_type, ())
    if not rules:
        return
    for leaf in leaves:
        for pattern, rule_id, predicate, _why in rules:
            if not _matches(pattern, leaf.segments):
                continue
            if leaf.tag != ref.TAG_INTEGER:
                raise ProfileRuleError(
                    rule_id,
                    ref.display_path(leaf.segments),
                    f"the rule is stated over an INTEGER leaf and this leaf is "
                    f"{ref.TAG_NAMES[leaf.tag]}",
                )
            canonical = ref.canonical_integer(leaf.value)
            if not predicate(canonical):
                raise ProfileRuleError(
                    rule_id, ref.display_path(leaf.segments), f"{canonical} is not positive"
                )


# ---------------------------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------------------------
#
# These rejections are NOT conformance vectors, and the distinction is load-bearing. Ruled
# decision D13a keeps value-domain validation out of the canonicalization layer, so a corpus
# vector for this rule would demand it from five implementations that by that ruling do not carry
# it. What the corpus pins instead is the ACCEPT case: the class-10 vaccination record commits,
# and its `dose` values are 1 and 2. The rejections are pinned here, in the profile layer that
# actually owns them.
#
# The discriminating values are `0` and every negative, and that is the whole point of the rule.
# A fractional `1.5` is already refused one layer down by the section 6.2 INTEGER grammar, which
# `reject-integer-with-fraction` pins, so a self-test using `1.5` would pass without the rule
# existing at all.

def _self_test():
    import roax_ref as ref

    dose_path = [
        {"key": "notarisationMetadata"},
        {"key": "signedEuHealthCerts"},
        {"index": 0},
        {"key": "dose"},
    ]
    profile = "sg.gov.moh.vaccination-healthcert"

    def leaf(value, tag=ref.TAG_INTEGER, segments=None):
        return ref.Leaf(dose_path if segments is None else segments, tag, value)

    failures = []

    def expect_accept(label, leaves):
        try:
            check_record(profile, leaves)
        except ProfileRuleError as exc:
            failures.append(f"{label}: unexpectedly refused ({exc})")

    def expect_reject(label, leaves):
        try:
            check_record(profile, leaves)
        except ProfileRuleError:
            return
        failures.append(f"{label}: accepted, and the rule requires a refusal")

    # The values the shipped sample carries.
    expect_accept("dose 1", [leaf("1")])
    expect_accept("dose 2", [leaf("2")])
    expect_accept("dose 999", [leaf("999")])

    # The values the NARROWING refuses and the INTEGER grammar alone does not. Every one of
    # these is a grammar-valid ROAX INTEGER, so without this rule each would commit.
    for spelling in ("0", "-0", "-1", "-999"):
        assert ref.canonical_integer(spelling) is not None
        expect_reject(f"dose {spelling}", [leaf(spelling)])

    # A leaf at a path the rule does not name is untouched, so the rule cannot widen into one.
    expect_accept("a different path carrying 0", [leaf("0", segments=[{"key": "somethingElse"}])])
    # A profile with no declared rules is untouched.
    try:
        check_record("org.roax.corpus.synthetic", [leaf("0")])
    except ProfileRuleError as exc:
        failures.append(f"unruled profile: unexpectedly refused ({exc})")

    # The rule is stated over an INTEGER leaf, so the same value at another tag is refused rather
    # than silently skipped: skipping would let a map change turn the rule off.
    expect_reject("dose bound STRING", [leaf("1", tag=ref.TAG_STRING)])

    if failures:
        for line in failures:
            print(f"FAIL: {line}")
        return 1
    print(f"validated profile value rules, rule version {PROFILE_RULE_VERSION}")
    return 0


if __name__ == "__main__":
    import sys as _sys

    _sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
    raise SystemExit(_self_test())
