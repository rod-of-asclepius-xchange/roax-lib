package io.roax.canon

import io.roax.canon.json.JsonArray
import io.roax.canon.json.JsonBoolean
import io.roax.canon.json.JsonNumber
import io.roax.canon.json.JsonObject
import io.roax.canon.json.JsonReader
import io.roax.canon.json.JsonString
import io.roax.canon.json.JsonValue

/** The outcome of verifying an envelope. */
sealed interface VerificationResult {

    data class Accepted(
        val recordType: String,
        val leafCount: Int,
        val disclosedPaths: List<List<Segment>>,
    ) : VerificationResult

    data class Rejected(val reason: Reason, val detail: String) : VerificationResult
}

/**
 * A verifier's own configuration.
 *
 * Two members carry the parts ROAX-CANON/1 deliberately leaves outside this document, and they are
 * nullable rather than absent so that a deployment which has them can supply them and one which
 * does not can see in the type that it is trusting a hint.
 */
data class VerifierConfig(
    val profiles: ProfileRegistry = ProfileRegistry.DEFAULT,
    val hashAlgorithms: HashAlgorithmAllowList = HashAlgorithmAllowList.DEFAULT,
    val envelopeProfile: EnvelopeProfile = EnvelopeProfile.V2_TYPE_MAP_BOUND,
    val nfc: Nfc = PlatformNfc,
    /** Resolves a `recordType` to the exact selected map. Needed to verify a full copy. */
    val resolverFor: (String) -> TypeResolver? = { null },
    /**
     * `hashAlg` **as the anchoring registry reports it** (section 7.4, mechanism H2).
     *
     * H2 is the one binding that works: authority for which hash to run then comes from the same
     * place authority for the root comes from. Section 2.2 leaves the anchoring registry
     * undesigned, so this library cannot fetch it. When this is null the envelope's own `hashAlg`
     * is used, which is a **hint being trusted** - [hashAlgorithms] (mechanism H3) is then the only
     * defence, and it does not cover an attacker who computed an entire record under a weak
     * algorithm that is still on the list.
     */
    val anchorHashAlg: String? = null,
    /** The root as the anchoring layer reports it (section 11.3). Null skips the check. */
    val anchorRoot: ByteArray? = null,
    val emptyContainers: EmptyContainerAuthorization = EmptyContainerAuthorization.REQUIRED,
)

/**
 * ROAX-CANON/1 sections 10 and 11.
 *
 * **The order below is derived, not chosen**, and `corpus/README.md` measures what breaks if it is
 * changed. Section 11.3 says a field outside the root is never authority, so authority has to be
 * established before an outer field is used to *select* anything. Choosing the floor from the
 * envelope's `recordType` and validating it afterwards is trust-then-verify - the same shape as
 * the dogtag scar section 11.3 records.
 *
 * 1. every disclosed leaf is recomputed and its inclusion proof checked against the root;
 * 2. the outer `recordType`, `schemaVersion`, `recordId` and `issuer.id` are bound to the reserved
 *    leaves the root commits;
 * 3. the floor is selected from the **committed** `roax.recordType` leaf and enforced.
 *
 * A consequence that is easy to miss: **the binding subsumes the reserved half of the floor.** If
 * one of those reserved leaves is absent, the binding fires first, so the floor loop can only ever
 * reject on a profile-specific path, and the corpus's 16 `floor-<profile>-omits-roax-*` vectors
 * assert `outer-identity-mismatch` rather than `minimum-disclosure-floor`. That is also the honest
 * code: a copy that withheld `roax.recordType` never told the verifier what it is, so no floor
 * could have been selected for it, and `minimum-disclosure-floor` would claim one was.
 *
 * `profile-unknown` stays ahead of all of it. It is the verifier's own allow-list - the same shape
 * as the `hashAlg` allow-list of section 7.4 H3 - and settles whether this verifier can proceed at
 * all rather than which policy to apply.
 */
object EnvelopeVerifier {

    /** The leaves the root actually commits, as far as this copy reveals them. */
    private class CommittedLeaves(
        /** NFC-normalized single-KEY-segment STRING leaves, by key. Reserved leaves live here. */
        val singleKeyStrings: Map<String, String>,
        val allPaths: List<List<Segment>>,
    )

    fun verify(envelopeBytes: ByteArray, config: VerifierConfig): VerificationResult = try {
        verifyOrThrow(envelopeBytes, config)
    } catch (e: RoaxException) {
        VerificationResult.Rejected(e.reason, e.message ?: e.reason.code)
    }

    private fun verifyOrThrow(envelopeBytes: ByteArray, config: VerifierConfig): VerificationResult {
        val env = JsonReader.parse(envelopeBytes) as? JsonObject
            ?: fail(Reason.ENVELOPE_SHAPE, "envelope is not a JSON object")

        // --- 0. structural invariants (sections 7.3 and 11.1) ---
        val canon = str(env, "canon")
        if (canon != CANON) {
            fail(
                Reason.CANON_MISMATCH,
                "envelope declares canon '$canon'; this library implements $CANON",
            )
        }

        val hasRecord = env["record"] != null
        val hasDisclosure = env["disclosure"] != null
        if (hasRecord && hasDisclosure) {
            fail(
                Reason.BOTH_RECORD_AND_DISCLOSURE,
                "exactly one of 'record' and 'disclosure' MUST be present",
            )
        }
        if (!hasRecord && !hasDisclosure) {
            fail(
                Reason.NEITHER_RECORD_NOR_DISCLOSURE,
                "exactly one of 'record' and 'disclosure' MUST be present",
            )
        }

        // Rule 3 of section 7.3: no envelope may carry any value from which the salt of an
        // undisclosed leaf could be obtained. Under section 7 no such value exists, which is what
        // makes the rule cheap - but it binds any revision that brings derivation back, so it is
        // enforced rather than assumed vacuous.
        for (seedish in listOf("masterSalt", "saltSeed", "seed", "kdfKey")) {
            if (env[seedish] != null) {
                fail(
                    Reason.MASTER_SALT_IN_ENVELOPE,
                    "envelope carries '$seedish'; decision D4 was ruled D4b and no such value " +
                        "exists in this design (specification section 7.3 rule 3)",
                )
            }
        }
        if (hasDisclosure && env["salts"] != null) {
            fail(
                Reason.DISCLOSED_COPY_CARRIES_SALTS,
                "a disclosed copy MUST carry the salt of every leaf it reveals and the salt of no " +
                    "other leaf; the 'salts' array is forbidden alongside 'disclosure'",
            )
        }
        if (hasRecord && env["salts"] == null) {
            fail(Reason.ENVELOPE_SHAPE, "a full copy MUST carry the salt of every leaf")
        }

        // --- 1. hashAlg: the anchoring registry if the deployment has one (H2), then the
        //        verifier's own allow-list (H3) ---
        //
        // `hashAlg` IS CARRIED TWICE when a registry is configured - once by the envelope and
        // once by the registry - and a DISAGREEMENT IS A REJECTION rather than a silent
        // preference. This used to read `config.anchorHashAlg ?: str(env, "hashAlg")` and never
        // compare the two, so an envelope declaring `Poseidon-BN254` was verified under SHA-256
        // and its declared value was simply discarded: that is an issuance specification section
        // 7.4 forbids, accepted without a word. Preferring the registry silently is not what H2
        // asks for either - `docs/conformance-corpus.md` class 18 states the row as "an envelope
        // whose hashAlg disagrees with the (root, hashAlg) pair the verifier's anchoring registry
        // records MUST be rejected", and the Rust, TypeScript and Python libraries all reject it.
        //
        // The registry rows of class 18 are still UNBUILT, because specification section 2.2
        // leaves the anchoring registry undesigned and the corpus may not invent that interface,
        // so no vector reaches this today. It is stated here rather than left to one.
        val declaredHashAlg = str(env, "hashAlg")
        val anchored = config.anchorHashAlg
        if (anchored != null && anchored != declaredHashAlg) {
            fail(
                Reason.HASH_ALG_NOT_ALLOWED,
                "the anchoring registry records '$anchored' against this root and the envelope " +
                    "declares '$declaredHashAlg'; authority for which hash to run comes from the " +
                    "registry, and a self-describing document cannot authenticate its own " +
                    "description (section 7.4, H2)",
            )
        }
        val hash = config.hashAlgorithms.resolve(anchored ?: declaredHashAlg)

        // --- 2. the verifier's profile allow-list, on the OUTER recordType ---
        val outerRecordType = str(env, "recordType")
        if (!config.profiles.contains(outerRecordType)) {
            fail(
                Reason.PROFILE_UNKNOWN,
                "'$outerRecordType' is not on this verifier's profile allow-list",
            )
        }

        val declaredLeafCount = intOf(env, "leafCount")
        val declaredRoot = hexOf(env, "root")
        val issuer = env["issuer"] as? JsonObject
            ?: fail(Reason.ENVELOPE_SHAPE, "envelope has no 'issuer' object")

        val identity = RecordIdentity(
            recordType = outerRecordType,
            schemaVersion = str(env, "schemaVersion"),
            recordId = str(env, "recordId"),
            issuerId = str(issuer, "id"),
            issuerKeyId = (issuer["keyId"] as? JsonString)?.value,
            typeMapId = ((env["typeMap"] as? JsonObject)?.get("id") as? JsonString)?.value,
        )

        val committed = if (hasRecord) {
            verifyFullCopy(env, identity, canon, hash, declaredLeafCount, declaredRoot, config)
        } else {
            verifyDisclosedCopy(env, canon, hash, declaredLeafCount, declaredRoot, config)
        }

        // --- step 2: bind the outer identity to what the root commits (section 11.3) ---
        //
        // `roax.typeMap.id` is bound whenever EITHER side names a type map, and never on the
        // verifier's configured [EnvelopeProfile] alone. THE TRIGGER IS THE POINT. Gating it on
        // the configuration left the check switched off for a V1-configured verifier, and gating
        // it on the outer `typeMap` member instead would hand the trigger to the party the check
        // constrains: a holder deletes the member, withholds the leaf, and the binding never runs
        // while every remaining inclusion proof stays genuine. Section 11.2 makes that leaf
        // mandatory to disclose BY ARITHMETIC, because it selects and authenticates the exact
        // map, so skipping it yields no proof of which map applies rather than a weaker one.
        // **A check whose execution is controlled by the party it constrains is not a check.**
        //
        // The one case no envelope can evidence is a copy dropping BOTH: it is
        // byte-indistinguishable from a legitimate 1.0 copy issued before the binding existed,
        // because the only signal a further reserved leaf was committed is `leafCount`, which
        // section 11.1 measured is NOT authenticated in a disclosed copy. Requiring the binding
        // regardless is what [EnvelopeProfile.V2_TYPE_MAP_BOUND] is for.
        val typeMapBound = config.envelopeProfile.bindsTypeMapId ||
            identity.typeMapId != null ||
            committed.singleKeyStrings.containsKey(Reserved.TYPE_MAP_ID)
        bindOuterIdentity(identity, committed, config, typeMapBound)

        // --- step 3: the floor, selected from the COMMITTED recordType leaf (section 10.2) ---
        val committedRecordType = committed.singleKeyStrings[Reserved.RECORD_TYPE] ?: fail(
            Reason.OUTER_IDENTITY_MISMATCH,
            "this copy reveals no ${Reserved.RECORD_TYPE} leaf, so no floor can be selected",
        )
        // The `profile-unknown` branch here is unreachable while step 2 stands: the binding has
        // just proved the outer field NFC-equal to this leaf, so both sources yield the same floor
        // table and no vector can tell them apart. It is kept so that a later edit cannot quietly
        // restore the trust-then-verify shape.
        val profile = config.profiles.require(committedRecordType)
        // The floor's reserved half follows the binding above rather than the configured profile,
        // for the same reason. Unreachable today, since step 2 has already rejected a copy naming
        // a type map on one side and withholding the leaf on the other; it stays because deleting
        // it leaves the floor's membership implicit in step 2's ordering, which is the coupling
        // that let the check be skipped in the first place.
        val floorProfile =
            if (typeMapBound) EnvelopeProfile.V2_TYPE_MAP_BOUND else config.envelopeProfile
        for (floorPath in profile.floor(floorProfile)) {
            val target = encodePath(floorPath, config.nfc)
            val present = committed.allPaths.any {
                Bytes.compareUnsigned(encodePath(it, config.nfc), target) == 0
            }
            if (!present) {
                fail(
                    Reason.MINIMUM_DISCLOSURE_FLOOR,
                    "non-redactable path ${displayPath(floorPath)} is not disclosed",
                )
            }
        }

        // --- section 11.3: the anchoring layer, when the deployment has one ---
        config.anchorRoot?.let {
            if (!Bytes.constantTimeEquals(it, declaredRoot)) {
                fail(Reason.ROOT_MISMATCH, "the envelope's root is not the anchored root")
            }
        }

        return VerificationResult.Accepted(committedRecordType, declaredLeafCount, committed.allPaths)
    }

    private fun verifyDisclosedCopy(
        env: JsonObject,
        canon: String,
        hash: HashAlgorithm,
        declaredLeafCount: Int,
        declaredRoot: ByteArray,
        config: VerifierConfig,
    ): CommittedLeaves {
        val disclosure = env["disclosure"] as? JsonObject
            ?: fail(Reason.ENVELOPE_SHAPE, "'disclosure' is not an object")
        val leaves = (disclosure["leaves"] as? JsonArray)?.elements
            ?: fail(Reason.ENVELOPE_SHAPE, "'disclosure' has no 'leaves' array")

        val singleKeyStrings = LinkedHashMap<String, String>()
        val allPaths = ArrayList<List<Segment>>(leaves.size)

        for (element in leaves) {
            val leaf = element as? JsonObject
                ?: fail(Reason.ENVELOPE_SHAPE, "a disclosed leaf is not an object")
            val segments = readSegments(leaf["segments"])
            val tag = tagOf(leaf)
            val salt = hexOf(leaf, "salt")
            val index = intOf(leaf, "index")
            val value = readDisclosedValue(leaf, tag, segments)

            // Section 10 step 2, and it is where dogtag's most expensive scar lives: RECOMPUTE the
            // leaf hash from the disclosed path, tag, value and salt. A caller-supplied leaf hash
            // is never accepted, which is also what defeats the forged-tree-size attack section
            // 11.1 records - a recomputed leaf hash is 0x00-domained by construction while an
            // internal node is 0x01-domained, so it cannot equal one except by defeating
            // second-preimage resistance.
            val recomputed = leafHash(segments, tag, value, salt, hash, canon, config.nfc)

            val auditPath = ((leaf["auditPath"] as? JsonArray)?.elements ?: emptyList()).map {
                val h = it as? JsonString
                    ?: fail(Reason.ENVELOPE_SHAPE, "an audit-path entry is not a hex string")
                parseHex(h.value, "auditPath entry")
            }

            // `leafCount` is the tree size INPUT here and is NOT authenticated in a disclosed copy
            // (section 11.1). It is deliberately not used as a check on anything else.
            val ok = Merkle.verifyInclusion(
                recomputed,
                index.toLong(),
                declaredLeafCount.toLong(),
                auditPath,
                declaredRoot,
                hash,
            )
            if (!ok) {
                fail(
                    Reason.INCLUSION_PROOF_FAILED,
                    "inclusion proof for ${displayPath(segments)} at index $index does not reach " +
                        "the declared root",
                )
            }

            allPaths.add(segments)
            val only = segments.singleOrNull()
            if (only is Segment.Key && value is RoaxValue.Text) {
                singleKeyStrings[config.nfc.normalize(only.key)] = value.value
            }
        }
        return CommittedLeaves(singleKeyStrings, allPaths)
    }

    private fun verifyFullCopy(
        env: JsonObject,
        identity: RecordIdentity,
        canon: String,
        hash: HashAlgorithm,
        declaredLeafCount: Int,
        declaredRoot: ByteArray,
        config: VerifierConfig,
    ): CommittedLeaves {
        val saltEntries = (env["salts"] as? JsonArray)?.elements
            ?: fail(Reason.ENVELOPE_SHAPE, "'salts' is not an array")

        // The structural salt checks run before any hashing, so each of the three failure modes is
        // reported as itself rather than as whichever downstream check happens to fire first.
        if (saltEntries.size != declaredLeafCount) {
            fail(
                Reason.SALTS_LENGTH_NOT_LEAF_COUNT,
                "'salts' carries ${saltEntries.size} entries against a declared leafCount of " +
                    "$declaredLeafCount",
            )
        }
        val saltsByEncodedPath = LinkedHashMap<String, ByteArray>()
        for (element in saltEntries) {
            val entry = element as? JsonObject
                ?: fail(Reason.ENVELOPE_SHAPE, "a salt entry is not an object")
            val segments = readSegments(entry["segments"])
            val hex = Bytes.toHex(encodePath(segments, config.nfc))
            if (saltsByEncodedPath.put(hex, hexOf(entry, "salt")) != null) {
                fail(
                    Reason.SALTS_DUPLICATE_PATH,
                    "'salts' carries two entries for ${displayPath(segments)}",
                )
            }
        }

        val resolver = config.resolverFor(identity.recordType) ?: fail(
            Reason.TYPE_MAP_FAIL_CLOSED,
            "no type map is installed for '${identity.recordType}', so no leaf can be resolved",
        )

        val record = env["record"] ?: fail(Reason.ENVELOPE_SHAPE, "full copy has no 'record'")

        val commitment = commitWithSaltsByPath(
            record = record,
            context = IssuanceContext(identity, config.envelopeProfile, canon, hash.id),
            resolver = resolver,
            saltsByEncodedPath = saltsByEncodedPath,
            nfc = config.nfc,
            hash = hash,
            emptyContainers = config.emptyContainers,
        )

        // Section 11.1: in a full copy the verifier derives the leaf count itself, and a derived
        // count that disagrees with the field MUST be a rejection - not a warning, and not a
        // silent preference for either value.
        if (commitment.leafCount != declaredLeafCount) {
            fail(
                Reason.LEAF_COUNT_MISMATCH,
                "derived leaf count ${commitment.leafCount} disagrees with the declared " +
                    "$declaredLeafCount",
            )
        }
        if (!Bytes.constantTimeEquals(commitment.root, declaredRoot)) {
            fail(
                Reason.ROOT_MISMATCH,
                "recomputed root ${commitment.rootHex} does not match the declared " +
                    Bytes.toHex(declaredRoot),
            )
        }

        val singleKeyStrings = LinkedHashMap<String, String>()
        for (leaf in commitment.leaves) {
            val only = leaf.segments.singleOrNull()
            val v = leaf.value
            if (only is Segment.Key && v is RoaxValue.Text) {
                singleKeyStrings[config.nfc.normalize(only.key)] = v.value
            }
        }
        return CommittedLeaves(singleKeyStrings, commitment.leaves.map { it.segments })
    }

    private fun readDisclosedValue(
        leaf: JsonObject,
        tag: TypeTag,
        segments: List<Segment>,
    ): RoaxValue {
        val raw = leaf["value"]
        val valueless =
            tag == TypeTag.NULL || tag == TypeTag.EMPTY_ARRAY || tag == TypeTag.EMPTY_OBJECT
        if (raw == null && !valueless) {
            // Naming a leaf while withholding its value hands over a salt for a value the verifier
            // cannot recompute, which is the shape section 10.1 exists to prevent.
            fail(
                Reason.DISCLOSED_LEAF_NAMED_WITHOUT_VALUE,
                "disclosed leaf ${displayPath(segments)} carries a salt but no value",
            )
        }

        fun text(): String = (raw as? JsonString)?.value
            ?: fail(
                Reason.ENVELOPE_SHAPE,
                "leaf ${displayPath(segments)} has tag ${tag.code} ${tag.name} but its value is " +
                    "not a JSON string",
            )

        return when (tag) {
            TypeTag.NULL -> RoaxValue.Null
            TypeTag.EMPTY_ARRAY -> RoaxValue.EmptyArray
            TypeTag.EMPTY_OBJECT -> RoaxValue.EmptyObject
            TypeTag.BOOL -> RoaxValue.Bool(
                (raw as? JsonBoolean)?.value ?: fail(
                    Reason.ENVELOPE_SHAPE,
                    "leaf ${displayPath(segments)} has tag 1 BOOL but its value is not a boolean",
                ),
            )

            TypeTag.STRING -> RoaxValue.Text(text())
            // The corpus carries numeric leaf values as STRINGS, because a JSON number in a vector
            // file would be destroyed by the very parser under test (section 6.4). A number is
            // accepted too, since a real envelope may legitimately carry one.
            TypeTag.INTEGER -> RoaxValue.Integer(numericLiteral(raw!!, segments))
            TypeTag.DECIMAL -> RoaxValue.Decimal(numericLiteral(raw!!, segments))
            // LOWERCASE HEX, not base64, and this used to be base64.
            //
            // The disclosure carrier is per tag and is NOT the record's own spelling.
            // `schemas/envelope-1.0.json` pins tag 5 to "lowercase hex of even length"; base64 is
            // how a RECORD spells `base64Binary`, and the pinned RFC 4648 form is an
            // input-admissibility condition there rather than the committed value (section 6.3).
            // Reader and writer were both wrong in the same direction, so they agreed with each
            // other and disagreed with every other implementation - and no committed disclosed
            // fixture carries a BYTES leaf, so nothing could see it until conformance corpus
            // class 20 made this library produce one and verify it.
            TypeTag.BYTES -> {
                // Validated before decoding rather than by catching: `AndroidApiSurfaceTest`
                // holds this library to an Android-safe JDK type set, and `runCatching` pulls in
                // `java.lang.Throwable`.
                val hex = text()
                if (hex.length % 2 != 0 || hex.any { it !in '0'..'9' && it !in 'a'..'f' }) {
                    fail(
                        Reason.ENVELOPE_SHAPE,
                        "leaf ${displayPath(segments)} has tag 5 BYTES but its value is not " +
                            "lowercase hex of even length",
                    )
                }
                RoaxValue.Bytes(Bytes.fromHex(hex))
            }
            TypeTag.BLOB_REF -> fail(
                Reason.BLOB_REF_NOT_DECLARED,
                "envelope carries a tag-8 leaf, which no version-1 profile declares " +
                    "(specification section 6.5)",
            )
        }
    }

    private fun numericLiteral(v: JsonValue, segments: List<Segment>): String = when (v) {
        is JsonNumber -> v.literal
        is JsonString -> v.value
        else -> fail(
            Reason.ENVELOPE_SHAPE,
            "numeric leaf ${displayPath(segments)} is neither a number nor a string",
        )
    }

    /**
     * ROAX-CANON/1 section 11.3: the envelope's outer identity is not authority and must be bound
     * to what the root commits.
     *
     * The concrete attack: PDT's floor is a strict **subset** of recovery's, which adds
     * `validUntil`, so a holder of a recovery copy who relabels the envelope as PDT discloses PDT's
     * floor, withholds the expiry, and every inclusion proof still verifies against the genuine
     * recovery root. Measured in `corpus/README.md`: with this binding removed, all four class-18
     * vectors are **accepted**.
     *
     * Compared under NFC on both sides, because a STRING leaf commits its normalized form.
     * `roax.issuer.keyId` is deliberately NOT bound: it is the one conditional leaf, so binding it
     * would turn an absent key identifier into a mismatch and break key rotation on an
     * already-anchored record (section 11.2).
     */
    private fun bindOuterIdentity(
        identity: RecordIdentity,
        committed: CommittedLeaves,
        config: VerifierConfig,
        typeMapBound: Boolean,
    ) {
        fun bind(reservedKey: String, outer: String?) {
            val leafValue = committed.singleKeyStrings[reservedKey] ?: fail(
                Reason.OUTER_IDENTITY_MISMATCH,
                "this copy reveals no $reservedKey leaf, so the envelope's outer value cannot be " +
                    "bound to what the root commits",
            )
            if (outer == null) {
                fail(
                    Reason.OUTER_IDENTITY_MISMATCH,
                    "the envelope carries no outer value for $reservedKey",
                )
            }
            if (config.nfc.normalize(outer) != config.nfc.normalize(leafValue)) {
                fail(
                    Reason.OUTER_IDENTITY_MISMATCH,
                    "outer $reservedKey '$outer' does not equal the committed leaf '$leafValue'",
                )
            }
        }

        bind(Reserved.RECORD_TYPE, identity.recordType)
        bind(Reserved.SCHEMA_VERSION, identity.schemaVersion)
        bind(Reserved.RECORD_ID, identity.recordId)
        bind(Reserved.ISSUER_ID, identity.issuerId)
        if (typeMapBound) bind(Reserved.TYPE_MAP_ID, identity.typeMapId)
    }

    // --- small readers -------------------------------------------------------------------------

    internal fun readSegments(v: JsonValue?): List<Segment> {
        val array = v as? JsonArray ?: fail(Reason.ENVELOPE_SHAPE, "'segments' is not an array")
        return array.elements.map { element ->
            val o = element as? JsonObject
                ?: fail(Reason.ENVELOPE_SHAPE, "a path segment is not an object")
            val k = o["key"]
            val i = o["index"]
            when {
                k is JsonString && i == null -> Segment.Key(k.value)
                i is JsonNumber && k == null -> Segment.Index(
                    Numbers.canonicalInteger(i.literal).toLongOrNull() ?: fail(
                        Reason.INDEX_OUT_OF_32_BIT_RANGE,
                        "array index ${i.literal} is outside [0, 2^32)",
                    ),
                )

                else -> fail(
                    Reason.ENVELOPE_SHAPE,
                    "a path segment must carry exactly one of 'key' and 'index'",
                )
            }
        }
    }

    private fun tagOf(leaf: JsonObject): TypeTag {
        val code = intOf(leaf, "tag")
        return try {
            TypeTag.ofCode(code)
        } catch (e: IllegalArgumentException) {
            fail(Reason.ENVELOPE_SHAPE, "no ROAX type tag with code $code")
        }
    }

    private fun str(o: JsonObject, name: String): String = (o[name] as? JsonString)?.value
        ?: fail(Reason.ENVELOPE_SHAPE, "envelope has no string member '$name'")

    private fun hexOf(o: JsonObject, name: String): ByteArray = parseHex(str(o, name), name)

    private fun parseHex(s: String, what: String): ByteArray = try {
        Bytes.fromHex(s)
    } catch (e: IllegalArgumentException) {
        fail(Reason.ENVELOPE_SHAPE, "'$what' is not hex: ${e.message}")
    }

    private fun intOf(o: JsonObject, name: String): Int {
        val n = o[name] as? JsonNumber
            ?: fail(Reason.ENVELOPE_SHAPE, "envelope has no numeric member '$name'")
        return Numbers.canonicalInteger(n.literal).toIntOrNull()
            ?: fail(Reason.ENVELOPE_SHAPE, "'$name' is not representable as an Int")
    }
}
