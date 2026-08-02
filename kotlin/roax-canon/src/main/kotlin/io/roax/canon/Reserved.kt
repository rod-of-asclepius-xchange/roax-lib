package io.roax.canon

/**
 * Which reserved leaves a record commits.
 *
 * Two envelope schema versions exist and ROAX-CANON/1 section 11 says a verifier "selects one
 * schema per envelope and MUST NOT merge them", so this is an explicit selection rather than a
 * compatibility hack. The leaf, salt and root constructions of sections 6 through 8 are identical
 * under both; what differs is the reserved set.
 */
enum class EnvelopeProfile {

    /**
     * `schemas/envelope-1.0.json`: four always-emitted reserved leaves, plus the conditional
     * `roax.issuer.keyId`. This is what the committed conformance corpus was built under, and it
     * still governs every envelope issued under it.
     */
    V1_NO_TYPE_MAP_BINDING,

    /**
     * `schemas/envelope-2.0.json`, which is what ROAX-CANON/1 section 11.2 now describes: five
     * always-emitted reserved leaves, `roax.typeMap.id` being the addition, so the tree floor
     * rises from five to six.
     */
    V2_TYPE_MAP_BOUND,
    ;

    val bindsTypeMapId: Boolean get() = this == V2_TYPE_MAP_BOUND
}

/**
 * The identity an envelope commits **inside** the root, per ROAX-CANON/1 section 11.2.
 *
 * Only genuinely mutable routing hints stay outside; section 11.3 states normatively that anything
 * outside the root is a hint and never authority.
 */
data class RecordIdentity(
    val recordType: String,
    val schemaVersion: String,
    val recordId: String,
    val issuerId: String,
    /** A reserved leaf whose *presence* varies (section 11.2). Absent means **no leaf**. */
    val issuerKeyId: String? = null,
    /** Required under [EnvelopeProfile.V2_TYPE_MAP_BOUND], absent under V1. */
    val typeMapId: String? = null,
    /**
     * The artifact's own three-part version, carried beside [typeMapId] in the envelope.
     *
     * NOT a leaf and not committed: the content ID transitively binds every artifact byte,
     * including this version (specification section 12.1). It is here because
     * `schemas/envelope-1.0.json` requires BOTH members whenever `typeMap` is present, so an
     * issuance emitting the identifier alone produces a schema-invalid envelope.
     */
    val typeMapVersion: String? = null,
    /**
     * The record's leaf ordering, committed at `roax.ordering` (specification section 11.2).
     *
     * The SECOND conditional reserved leaf. It is emitted only when the ordering is not the default
     * [Ordering.PATH]; a path-ordered record emits NO ordering leaf and must not emit `"path"`, a
     * NULL or an empty string in its place, because those are different roots and only one can be
     * right. The conditionality is the same `ROAX-CANON/1` compatibility rule that gives `path` an
     * empty domain suffix, and section 11.2 argues it.
     *
     * THIS LEAF IS NOT AUTHORITY. It is written from the ordering supplied here and is never read
     * back to select one: a verifier takes the ordering from the anchoring registry (section 9.5,
     * H2). Section 11.2 argues why committing it is not section 7.4's rejected `roax.hashAlg` leaf
     * under a new name - weak hash algorithms exist so that leaf enabled a downgrade, whereas both
     * orderings are equally strong, so this one is redundant rather than dangerous and what it buys
     * is committed issuer intent.
     */
    val ordering: Ordering = Ordering.PATH,
)

/** ROAX-CANON/1 section 11.2. Every reserved leaf is a STRING at a single `KEY` segment. */
object Reserved {

    const val PREFIX: String = "roax."

    const val RECORD_TYPE = "roax.recordType"
    const val SCHEMA_VERSION = "roax.schemaVersion"
    const val TYPE_MAP_ID = "roax.typeMap.id"
    const val RECORD_ID = "roax.recordId"
    const val ISSUER_ID = "roax.issuer.id"
    const val ISSUER_KEY_ID = "roax.issuer.keyId"
    const val ORDERING = "roax.ordering"

    /**
     * The reserved leaves for [identity] under [profile], in declaration order.
     *
     * **Each reserved path is a SINGLE `KEY` segment whose key is the literal dotted string.**
     * `roax.recordType` is one segment `KEY("roax.recordType")`, not two segments `KEY("roax")`
     * then `KEY("recordType")`. Under the per-component reading an ordinary top-level field named
     * `roax` would collide with the reserved namespace, and these record families already carry
     * non-clinical top-level keys such as `$template`, `notarisationMetadata` and `issuers`.
     */
    fun leavesFor(identity: RecordIdentity, profile: EnvelopeProfile): List<Pair<List<Segment>, String>> {
        val out = ArrayList<Pair<List<Segment>, String>>(6)
        out.add(listOf(Segment.Key(RECORD_TYPE)) to identity.recordType)
        out.add(listOf(Segment.Key(SCHEMA_VERSION)) to identity.schemaVersion)
        if (profile.bindsTypeMapId) {
            val id = identity.typeMapId ?: fail(
                Reason.ENVELOPE_SHAPE,
                "envelope profile $profile requires typeMap.id, which selects and authenticates " +
                    "the exact artifact (specification section 4.2)",
            )
            out.add(listOf(Segment.Key(TYPE_MAP_ID)) to id)
        }
        out.add(listOf(Segment.Key(RECORD_ID)) to identity.recordId)
        out.add(listOf(Segment.Key(ISSUER_ID)) to identity.issuerId)
        // An absent issuer.keyId emits NO leaf. It MUST NOT be emitted as a NULL leaf or as an
        // empty string, because those are three different roots and only one of them is right.
        identity.issuerKeyId?.let { out.add(listOf(Segment.Key(ISSUER_KEY_ID)) to it) }
        // The second conditional leaf, on the same rule: a non-default ordering emits it and the
        // default emits nothing at all.
        if (identity.ordering != Ordering.PATH) {
            out.add(listOf(Segment.Key(ORDERING)) to identity.ordering.id)
        }
        return out
    }

    /**
     * The reserved-namespace guard of ROAX-CANON/1 section 11.2.
     *
     * > No record-supplied path may have, as its **first segment**, a `KEY` whose NFC-normalized
     * > key begins with the ASCII prefix `roax.`.
     *
     * Three ways to get this wrong, and all three are guarded against here:
     *
     * - **Running it against a rendered display path.** Section 5.2 forbids reasoning over display
     *   paths; this takes the decoded key of one segment.
     * - **Applying it to every segment.** `[KEY("a"), KEY("roax.foo")]` differs from every reserved
     *   path in segment count and cannot collide, so rejecting it would be over-broad. That is the
     *   most likely over-implementation.
     * - **Checking the raw bytes.** Section 6.1 normalizes keys before they are hashed, so a check
     *   on the received bytes checks a different string from the one committed. The rule is the
     *   general one: check the bytes you commit, not the bytes you received.
     *
     * A key named `roax`, or `roaxX`, with no dot, is **accepted** - it collides with nothing,
     * because no reserved path is the single segment `KEY("roax")`.
     *
     * The normalization half of this MUST is currently unobservable, and that is a fact about
     * today's prefix rather than about the design: no character normalizes into `roax.`. It is
     * applied anyway, because it keeps this guard and the hashing path reasoning about the same
     * string, and because a reserved name that later contained a character with a canonical
     * singleton decomposition would make the ordering observable immediately.
     */
    fun guardFirstSegment(firstKey: String, nfc: Nfc = PlatformNfc) {
        val normalized = nfc.normalize(requirePairedSurrogates(firstKey, "record key"))
        if (normalized.startsWith(PREFIX)) {
            fail(
                Reason.RESERVED_NAMESPACE,
                "record key \"$firstKey\" normalizes to \"$normalized\", which begins with the " +
                    "reserved prefix \"$PREFIX\" (specification section 11.2)",
            )
        }
    }
}

/**
 * A profile's non-redactable path set - the minimum-disclosure floor of ROAX-CANON/1 section 10.2.
 *
 * **A floor path is SEGMENTS, never display notation**, and that is the whole reason this type
 * exists. The tables in `docs/profiles/` print `notarisationMetadata.reference` for humans, and it
 * reads as one token while being **two** segments. A floor holding the dotted string as a single
 * `KEY` asks for a leaf no record has, so it matches nothing and the floor is *silently
 * unenforced* while every fixture built the same way agrees with it. Carrying segments makes that
 * mistake unwritable.
 *
 * Reserved paths are the one genuine single-dotted-key case (section 11.2).
 */
data class Profile(val recordType: String, val profileSpecificPaths: List<List<Segment>>) {

    /**
     * The full floor: the reserved paths plus the profile's own.
     *
     * `roax.issuer.keyId` is deliberately **not** here. Requiring its disclosure would permanently
     * bind an anchored record to the key it was issued under, leaving a holder whose issuer has
     * rotated keys with no path to verify. Section 12.2 rules that out rather than merely
     * preferring against it, and section 10.2 says so in the place an editor would widen it back.
     */
    fun floor(envelopeProfile: EnvelopeProfile): List<List<Segment>> {
        val reserved = ArrayList<List<Segment>>(5)
        reserved.add(listOf(Segment.Key(Reserved.RECORD_TYPE)))
        reserved.add(listOf(Segment.Key(Reserved.SCHEMA_VERSION)))
        if (envelopeProfile.bindsTypeMapId) reserved.add(listOf(Segment.Key(Reserved.TYPE_MAP_ID)))
        reserved.add(listOf(Segment.Key(Reserved.RECORD_ID)))
        reserved.add(listOf(Segment.Key(Reserved.ISSUER_ID)))
        return reserved + profileSpecificPaths
    }
}

/**
 * The verifier's own allow-list of profiles.
 *
 * An unknown profile MUST fail closed with a stated reason and MUST NEVER default to a guess
 * (section 12.2) - "the same rule section 4.2 applies to an unknown path, applied one level up".
 */
class ProfileRegistry(private val byRecordType: Map<String, Profile>) {

    fun require(recordType: String): Profile = byRecordType[recordType] ?: fail(
        Reason.PROFILE_UNKNOWN,
        "'$recordType' is not on this verifier's profile allow-list",
    )

    fun contains(recordType: String): Boolean = byRecordType.containsKey(recordType)

    fun with(profile: Profile): ProfileRegistry =
        ProfileRegistry(byRecordType + (profile.recordType to profile))

    companion object {

        /** The four registered profiles under `docs/profiles/`, with the floors those documents declare. */
        val DEFAULT: ProfileRegistry = ProfileRegistry(
            listOf(
                Profile(
                    "hl7.fhir.bundle",
                    listOf(listOf(Segment.Key("resourceType"))),
                ),
                Profile(
                    "sg.gov.moh.pdt-healthcert",
                    listOf(
                        listOf(Segment.Key("version")),
                        listOf(Segment.Key("type")),
                        listOf(Segment.Key("validFrom")),
                    ),
                ),
                Profile(
                    "sg.gov.moh.recovery-healthcert",
                    listOf(
                        listOf(Segment.Key("version")),
                        listOf(Segment.Key("type")),
                        listOf(Segment.Key("validFrom")),
                        // The recovery-specific addition, and the important one: a recovery
                        // certificate whose expiry can be withheld while the rest verifies is an
                        // expired certificate that presents as valid.
                        listOf(Segment.Key("validUntil")),
                    ),
                ),
                Profile(
                    "sg.gov.moh.vaccination-healthcert",
                    listOf(
                        listOf(Segment.Key("validFrom")),
                        // TWO segments. Printed as `notarisationMetadata.reference` in
                        // `docs/profiles/vaccination-healthcert.md` section 4, which is display
                        // notation for a human reader.
                        listOf(Segment.Key("notarisationMetadata"), Segment.Key("reference")),
                    ),
                ),
            ).associateBy { it.recordType },
        )
    }
}
