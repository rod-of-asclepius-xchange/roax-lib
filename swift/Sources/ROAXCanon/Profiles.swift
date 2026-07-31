import Foundation

/// A registered profile and its minimum-disclosure floor
/// (specification section 10.2, `docs/profiles/`).
public struct Profile {
    public let recordType: String
    /// The profile's own non-redactable paths, on top of the reserved floor.
    public let additionalPaths: [Path]

    public init(recordType: String, additionalPaths: [Path]) {
        self.recordType = recordType
        self.additionalPaths = additionalPaths
    }
}

/// The verifier's profile registry.
///
/// **A floor path is SEGMENTS, never display notation, and that is the whole
/// reason this table is written the way it is.** `docs/profiles/vaccination-healthcert.md`
/// prints `notarisationMetadata.reference` for humans, and specification
/// section 5.2 is explicit that a display path is never parsed back. Held as a
/// single key, that entry asks for a leaf whose key is the literal eighteen-
/// character dotted string; no record has one, so the floor would match nothing
/// and be **silently unenforced** while every fixture built the same way agreed
/// with it. Carrying it as two segments makes the mistake unwritable.
///
/// Reserved paths are the one genuine single-dotted-key case, because
/// specification section 11.2 defines them that way.
public struct ProfileRegistry {

    public let profiles: [String: Profile]

    public init(profiles: [Profile]) {
        self.profiles = Dictionary(uniqueKeysWithValues: profiles.map { ($0.recordType, $0) })
    }

    /// The four registered profiles of `docs/profiles/`, plus the corpus-only
    /// synthetic one.
    ///
    /// `org.roax.corpus.synthetic` is deliberately **not** in the
    /// `docs/profiles/` registry and a record MUST NOT be issued under it. It is
    /// registered here because the committed corpus builds structural envelope
    /// fixtures against it, and a verifier with no entry for it would reject
    /// every one of them as `profile-unknown` before reaching the assertion the
    /// vector is about.
    public static let versionOne = ProfileRegistry(profiles: [
        Profile(recordType: "hl7.fhir.bundle", additionalPaths: [
            [.key("resourceType")],
        ]),
        Profile(recordType: "sg.gov.moh.pdt-healthcert", additionalPaths: [
            [.key("version")],
            [.key("type")],
            [.key("validFrom")],
        ]),
        Profile(recordType: "sg.gov.moh.recovery-healthcert", additionalPaths: [
            [.key("version")],
            [.key("type")],
            [.key("validFrom")],
            // The recovery-specific addition, and the important one: a recovery
            // certificate whose expiry can be withheld while the rest verifies
            // is an expired certificate that presents as valid.
            [.key("validUntil")],
        ]),
        Profile(recordType: "sg.gov.moh.vaccination-healthcert", additionalPaths: [
            [.key("validFrom")],
            // TWO segments. Printed as `notarisationMetadata.reference`.
            [.key("notarisationMetadata"), .key("reference")],
        ]),
        Profile(recordType: "org.roax.corpus.synthetic", additionalPaths: []),
    ])

    public func profile(for recordType: String) throws -> Profile {
        guard let profile = profiles[recordType] else {
            throw ROAXError.profileUnknown(recordType)
        }
        return profile
    }

    /// The complete floor: the reserved paths this identity emits as mandatory,
    /// plus the profile's own.
    ///
    /// `docs/conformance-corpus.md` class 14 defines the floor as those plus
    /// what the profile adds, and the reserved half stays in the table even
    /// though the outer-identity binding of section 11.3 now fires first for
    /// every one of them. Trimming it would make the code stop stating the
    /// definition.
    public func floor(for identity: RecordIdentity) throws -> [Path] {
        let profile = try profile(for: identity.recordType)
        return identity.mandatoryDisclosurePaths + profile.additionalPaths
    }
}
