package io.roax.canon

import io.roax.canon.conformance.Corpus
import io.roax.canon.json.JsonReader
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/**
 * The envelope shape ROAX-CANON/1 section 11 actually describes, which is this library's default
 * and which **no corpus vector reaches**.
 *
 * The committed corpus and all 54 of its envelope fixtures are `schemas/envelope-1.0.json`
 * documents: they predate the type-map binding, so they carry four always-emitted reserved leaves
 * where section 11.2 now specifies five. Section 11 requires a verifier to select one schema per
 * envelope and MUST NOT merge them, so this library models the choice explicitly - and this suite
 * is the only thing exercising the side it ships as the default.
 */
class EnvelopeProfileV2Test {

    private val nfc = PlatformNfc

    private val typeMapVersion = "1.0.0"

    private val typeMapId =
        "sha256:de7bb92226af5fa5dc5064d9cb203329abc69160f4280fdf739e66e5e0151e93"

    private fun identity(withTypeMap: Boolean = true, keyId: String? = null) = RecordIdentity(
        recordType = "org.roax.corpus.synthetic",
        schemaVersion = "1.0",
        recordId = "urn:uuid:11111111-1111-4111-8111-111111111111",
        issuerId = "did:web:corpus.roax.invalid",
        issuerKeyId = keyId,
        typeMapId = if (withTypeMap) typeMapId else null,
        // `schemas/envelope-1.0.json` requires BOTH members whenever `typeMap` is present, so an
        // issuance naming the identifier alone emits a schema-invalid envelope.
        typeMapVersion = if (withTypeMap) typeMapVersion else null,
    )

    private fun record() = JsonReader.parse(Corpus.bytes("corpus/fixtures/records/typed-scalars.json"))

    private fun commitV2(keyId: String? = null): Commitment = commit(
        record = record(),
        context = IssuanceContext(identity(keyId = keyId), EnvelopeProfile.V2_TYPE_MAP_BOUND),
        resolver = Corpus.typeMap("org.roax.corpus.synthetic", nfc),
        saltSource = SaltSource.secureRandom(),
        nfc = nfc,
    )

    private fun configV2() = VerifierConfig(
        profiles = Corpus.profiles,
        envelopeProfile = EnvelopeProfile.V2_TYPE_MAP_BOUND,
        nfc = nfc,
        resolverFor = { runCatching { Corpus.typeMap(it, nfc) }.getOrNull() },
    )

    @Test
    fun `V2 emits five always-emitted reserved leaves, and six with an issuer key id`() {
        // The record contributes 5 leaves. Section 4 of `docs/type-maps.md`: the `roax.typeMap.id`
        // leaf raises the tree floor from five to six.
        assertEquals(5 + 5, commitV2().leafCount)
        assertEquals(5 + 6, commitV2(keyId = "did:web:corpus.roax.invalid#key-1").leafCount)

        // V1 is the same record with one fewer reserved leaf.
        val v1 = commit(
            record = record(),
            context = IssuanceContext(identity(withTypeMap = false), EnvelopeProfile.V1_NO_TYPE_MAP_BINDING),
            resolver = Corpus.typeMap("org.roax.corpus.synthetic", nfc),
            saltSource = SaltSource.secureRandom(),
            nfc = nfc,
        )
        assertEquals(5 + 4, v1.leafCount)
    }

    @Test
    fun `the type-map binding changes the root, so it is a real commitment and not a header field`() {
        // Same record, same salts, differing only in whether `roax.typeMap.id` is committed.
        val fixed = ByteArray(SALT_LENGTH_BYTES) { 7 }
        fun rootUnder(profile: EnvelopeProfile, withTypeMap: Boolean) = commit(
            record = record(),
            context = IssuanceContext(identity(withTypeMap = withTypeMap), profile),
            resolver = Corpus.typeMap("org.roax.corpus.synthetic", nfc),
            saltSource = { fixed },
            nfc = nfc,
        ).rootHex

        assertNotEquals(
            rootUnder(EnvelopeProfile.V1_NO_TYPE_MAP_BINDING, false),
            rootUnder(EnvelopeProfile.V2_TYPE_MAP_BOUND, true),
            "committing the exact artifact ID must change the root",
        )
    }

    @Test
    fun `V2 refuses to issue without a typeMap id`() {
        // The exact ID selects and authenticates the artifact bytes, so there is nothing sensible
        // to commit in its place. Failing at issuance is better than committing an empty string.
        val e = assertThrows(RoaxException::class.java) {
            commit(
                record = record(),
                context = IssuanceContext(identity(withTypeMap = false), EnvelopeProfile.V2_TYPE_MAP_BOUND),
                resolver = Corpus.typeMap("org.roax.corpus.synthetic", nfc),
                saltSource = SaltSource.secureRandom(),
                nfc = nfc,
            )
        }
        assertEquals(Reason.ENVELOPE_SHAPE, e.reason)
    }

    @Test
    fun `a V2 disclosed copy round-trips, and its floor requires roax typeMap id`() {
        val commitment = commitV2()
        val floor = listOf(
            listOf(Segment.Key(Reserved.RECORD_TYPE)),
            listOf(Segment.Key(Reserved.SCHEMA_VERSION)),
            listOf(Segment.Key(Reserved.TYPE_MAP_ID)),
            listOf(Segment.Key(Reserved.RECORD_ID)),
            listOf(Segment.Key(Reserved.ISSUER_ID)),
        )
        val json = EnvelopeWriter.disclosedCopy(commitment.disclose(floor, nfc), nfc)
        assertTrue(json.contains("\"typeMap\":{\"id\":\"$typeMapId\",\"version\":\"$typeMapVersion\"}"))
        val ok = EnvelopeVerifier.verify(json.toByteArray(), configV2())
        assertTrue(
            ok is VerificationResult.Accepted,
            "V2 disclosed copy rejected: ${(ok as? VerificationResult.Rejected)?.detail}",
        )

        // Withhold `roax.typeMap.id`. Under V2 the outer-identity binding fires, exactly as it does
        // for the other four reserved leaves - the binding subsumes the reserved half of the floor.
        val stripped = EnvelopeWriter.disclosedCopy(
            commitment.disclose(floor.filter { it != listOf(Segment.Key(Reserved.TYPE_MAP_ID)) }, nfc),
            nfc,
        )
        val rejected = EnvelopeVerifier.verify(stripped.toByteArray(), configV2())
        assertTrue(rejected is VerificationResult.Rejected)
        assertEquals(
            Reason.OUTER_IDENTITY_MISMATCH,
            (rejected as VerificationResult.Rejected).reason,
        )
    }

    @Test
    fun `a V2 envelope verified under the V1 profile is refused rather than silently merged`() {
        // Section 11: "A verifier selects one schema per envelope and MUST NOT merge them." A V1
        // verifier reading a V2 envelope recomputes a different reserved set, so the tree it
        // rebuilds is not the one that was committed.
        val commitment = commitV2()
        val json = EnvelopeWriter.fullCopy(
            commitment, Corpus.bytes("corpus/fixtures/records/typed-scalars.json"), nfc,
        )
        assertTrue(EnvelopeVerifier.verify(json.toByteArray(), configV2()) is VerificationResult.Accepted)

        val v1Config = configV2().copy(envelopeProfile = EnvelopeProfile.V1_NO_TYPE_MAP_BINDING)
        val result = EnvelopeVerifier.verify(json.toByteArray(), v1Config)
        assertTrue(result is VerificationResult.Rejected, "a V1 verifier must not accept a V2 envelope")
        // It derives 9 leaves where the envelope declares 10, which section 11.1 requires to be a
        // rejection rather than a warning.
        assertEquals(Reason.LEAF_COUNT_MISMATCH, (result as VerificationResult.Rejected).reason)
    }

    @Test
    fun `the anchoring registry overrides the envelope's hashAlg, which is mechanism H2`() {
        // Section 7.4: a verifier MUST take `hashAlg` from the registry, never from the envelope.
        // H2 is the one binding that works, and this is the seam a deployment plugs it into.
        val commitment = commitV2()
        val json = EnvelopeWriter.fullCopy(
            commitment, Corpus.bytes("corpus/fixtures/records/typed-scalars.json"), nfc,
        )
        // The envelope says SHA-256 and the registry agrees.
        assertTrue(
            EnvelopeVerifier.verify(
                json.toByteArray(), configV2().copy(anchorHashAlg = "SHA-256"),
            ) is VerificationResult.Accepted,
        )
        // The registry says an algorithm this verifier has retired: H3 refuses it, even though the
        // envelope asked for one that is still allowed.
        val result = EnvelopeVerifier.verify(
            json.toByteArray(), configV2().copy(anchorHashAlg = "Poseidon-BN254"),
        )
        assertEquals(
            Reason.HASH_ALG_NOT_ALLOWED,
            (result as VerificationResult.Rejected).reason,
        )
    }

    @Test
    fun `issuance fails closed when the artifact version is missing, rather than emitting one`() {
        // `schemas/envelope-1.0.json` requires `id` and `version` together whenever `typeMap` is
        // present, so the two are refused on the same terms. Coercing an absent version to the
        // empty string wrote `"version":""`, which fails that schema's
        // `^[0-9]+\.[0-9]+\.[0-9]+$` - and no verifier here reads the member, so this library
        // would have accepted its own invalid output. Every class-20 vector supplies a version,
        // so the corpus cannot reach this.
        val versionless = identity().copy(typeMapVersion = null)
        val commitment = commit(
            record = record(),
            context = IssuanceContext(versionless, EnvelopeProfile.V2_TYPE_MAP_BOUND),
            resolver = Corpus.typeMap("org.roax.corpus.synthetic", nfc),
            saltSource = SaltSource.secureRandom(),
            nfc = nfc,
        )
        val thrown = assertThrows(RoaxException::class.java) {
            EnvelopeWriter.fullCopy(
                commitment, Corpus.bytes("corpus/fixtures/records/typed-scalars.json"), nfc,
            )
        }
        assertEquals(Reason.ENVELOPE_SHAPE, thrown.reason)
    }

    @Test
    fun `a wrongly typed typeMap member is malformed rather than absent`() {
        // A KNOWN member present with the WRONG JSON TYPE must never read as ABSENT: absence is
        // the one shape the binding treats as a pre-binding envelope-1.0 copy, so a reader
        // answering `null` here would let malformed input switch off the check it gates. Both
        // reference implementations refuse this shape and no vector carries it, because only the
        // `salts` instance of the same rule got a fixture.
        val commitment = commitV2()
        val json = EnvelopeWriter.fullCopy(commitment, Corpus.bytes("corpus/fixtures/records/typed-scalars.json"), nfc)
        for (mangled in listOf("[]", "null", "\"sha256:00\"", "{\"id\":7,\"version\":\"1.0.0\"}",
            "{\"id\":\"$typeMapId\"}")) {
            val hostile = json.replace(
                "\"typeMap\":{\"id\":\"$typeMapId\",\"version\":\"$typeMapVersion\"}",
                "\"typeMap\":$mangled",
            )
            assertNotEquals(json, hostile, "the typeMap member was not replaced by $mangled")
            val result = EnvelopeVerifier.verify(hostile.toByteArray(), configV2())
            assertTrue(result is VerificationResult.Rejected, "accepted a typeMap of $mangled")
            assertEquals(
                Reason.ENVELOPE_SHAPE,
                (result as VerificationResult.Rejected).reason,
                "wrong reason for a typeMap of $mangled",
            )
        }
    }

    @Test
    fun `the anchored root is checked when the deployment supplies one`() {
        // Section 11.3: `root` in the envelope is a hint until the anchoring layer confirms it.
        val commitment = commitV2()
        val json = EnvelopeWriter.fullCopy(
            commitment, Corpus.bytes("corpus/fixtures/records/typed-scalars.json"), nfc,
        )
        assertTrue(
            EnvelopeVerifier.verify(
                json.toByteArray(), configV2().copy(anchorRoot = commitment.root),
            ) is VerificationResult.Accepted,
        )
        val result = EnvelopeVerifier.verify(
            json.toByteArray(), configV2().copy(anchorRoot = ByteArray(32)),
        )
        assertEquals(Reason.ROOT_MISMATCH, (result as VerificationResult.Rejected).reason)
    }
}
