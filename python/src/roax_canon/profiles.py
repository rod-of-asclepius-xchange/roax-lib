"""The profile registry and the minimum-disclosure floor (specification section 10.2).

> **Each profile MUST declare a set of non-redactable paths, and a disclosed copy that
> omits any of them MUST be rejected.**

Without it a holder can withhold the very fields that say what the record is, and the
disclosed copy still verifies against a genuine root.
The verifier then holds a cryptographically valid proof of something it cannot identify.
This is adopted from dogtag's ``NON_OBFUSCATABLE``, enforced inside the integrity gate
itself at `dogtag-mono-repo` ``crates/dogtag-standard-rs/src/verify.rs:253`` and
``:273-277``.

**A floor path is SEGMENTS, never display notation.**
That is the section 5.2 display-path trap one layer above hashing, and this repository has
already made it once.
`docs/profiles/vaccination-healthcert.md` section 4 prints
``notarisationMetadata.reference`` for humans, and read as a single key it asks for a leaf
whose key is literally that eighteen-character dotted string.
No record has one, so the floor would match nothing and be **silently unenforced** while
every fixture built the same way agreed with it.
Carried here as two segments, so the mistake cannot be written.

**``roax.issuer.keyId`` is deliberately not in any floor.**
Requiring its disclosure would permanently bind an anchored record to the key it was
issued under, leaving a holder whose issuer has rotated keys with no path to verify.
Specification sections 10.2 and 12.2 rule that out rather than merely prefer it, and this
is the module an editor would edit to put it back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .path import Key, Segment
from .record import RESERVED_V1, RESERVED_V2

__all__ = [
    "RESERVED_FLOOR_V1",
    "RESERVED_FLOOR_V2",
    "Profile",
    "ProfileRegistry",
    "DEFAULT_PROFILES",
    "CORPUS_SYNTHETIC_PROFILE",
]


def _k(*names: str) -> tuple[Segment, ...]:
    return tuple(Key(n) for n in names)


#: The five reserved paths specification section 11.2 marks mandatory to disclose, minus
#: ``roax.typeMap.id``, which `schemas/envelope-1.0.json` does not carry.
RESERVED_FLOOR_V1: tuple[tuple[Segment, ...], ...] = (
    _k("roax.recordType"),
    _k("roax.schemaVersion"),
    _k("roax.recordId"),
    _k("roax.issuer.id"),
)

#: The full five of specification section 10.2, as `schemas/envelope-2.0.json` carries
#: them.
RESERVED_FLOOR_V2: tuple[tuple[Segment, ...], ...] = (
    _k("roax.recordType"),
    _k("roax.schemaVersion"),
    _k("roax.typeMap.id"),
    _k("roax.recordId"),
    _k("roax.issuer.id"),
)


@dataclass(frozen=True, slots=True)
class Profile:
    """One registered ``recordType``.

    ``extra_non_redactable`` is what this profile adds **on top of** the reserved floor,
    as structured segments.
    """

    record_type: str
    extra_non_redactable: tuple[tuple[Segment, ...], ...] = ()
    issuable: bool = True

    def floor(self, *, reserved_set: str = RESERVED_V1) -> tuple[tuple[Segment, ...], ...]:
        base = RESERVED_FLOOR_V2 if reserved_set == RESERVED_V2 else RESERVED_FLOOR_V1
        return base + self.extra_non_redactable


class ProfileRegistry:
    """The verifier's own profile allow-list.

    > **An unknown profile MUST fail closed, with a stated reason, and MUST NEVER default
    > to a guess** (specification section 12.2).

    This is the same rule specification section 4.2 applies to an unknown path, applied
    one level up, and it is the verifier's own configuration rather than a policy read out
    of the document, exactly like the ``hashAlg`` allow-list of section 7.4 H3.
    """

    def __init__(self, profiles: Sequence[Profile] = ()) -> None:
        self._by_type = {p.record_type: p for p in profiles}

    def __contains__(self, record_type: object) -> bool:
        return record_type in self._by_type

    def get(self, record_type: str) -> Profile | None:
        return self._by_type.get(record_type)

    def with_profile(self, profile: Profile) -> "ProfileRegistry":
        """A registry with one more profile, leaving this one unchanged."""
        return ProfileRegistry(tuple(self._by_type.values()) + (profile,))

    def record_types(self) -> tuple[str, ...]:
        return tuple(self._by_type)


#: The four registered profiles, from `docs/profiles/`.
DEFAULT_PROFILES = ProfileRegistry(
    (
        Profile("hl7.fhir.bundle", (_k("resourceType"),)),
        Profile(
            "sg.gov.moh.pdt-healthcert",
            (_k("version"), _k("type"), _k("validFrom")),
        ),
        Profile(
            "sg.gov.moh.recovery-healthcert",
            # `validUntil` is the recovery-specific addition and it is the important one:
            # a recovery certificate whose expiry can be withheld while the rest verifies
            # is an expired certificate that presents as valid.
            (_k("version"), _k("type"), _k("validFrom"), _k("validUntil")),
        ),
        Profile(
            "sg.gov.moh.vaccination-healthcert",
            # Two segments, not one dotted key. See the module docstring.
            (_k("validFrom"), (Key("notarisationMetadata"), Key("reference"))),
        ),
    )
)

#: `org.roax.corpus.synthetic` exists only inside the conformance corpus.
#: It is syntactically valid under the envelope schema's reverse-DNS pattern and is
#: deliberately **not** in the `docs/profiles/` registry, so a record MUST NOT be issued
#: under it. ``issuable=False`` states that in code rather than in a comment.
CORPUS_SYNTHETIC_PROFILE = Profile("org.roax.corpus.synthetic", (), issuable=False)
