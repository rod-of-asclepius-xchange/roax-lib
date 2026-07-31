package io.roax.canon

import io.roax.canon.conformance.Corpus
import io.roax.canon.json.JsonReader
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/**
 * Behaviours the committed corpus does **not** discriminate.
 *
 * Under ruled decision D (five independent builds) the corpus is the entire enforcement mechanism
 * for cross-language agreement, so a behaviour it does not cover is a place the five libraries may
 * silently diverge. Each test below names the gap, states what this library does, and - where the
 * gap is closable with a vector rather than a ruling - gives the exact input a corpus row would
 * carry. `kotlin/FINDINGS.md` collects them for corpus-side work.
 *
 * These are deliberately **library-local regressions and not corpus edits**. Specification section
 * 1.1 requires a canonicalization rule and the vectors asserting it to land in the same change, and
 * `docs/conformance-corpus.md` section 1.2 forbids a corpus row from deciding an open question, so
 * adding rows here from a library build would settle several of these from inside a data file.
 */
class SpecificationGapTest {

    private val nfc = PlatformNfc

    private val synthetic get() = Corpus.typeMap("org.roax.corpus.synthetic", nfc)

    private fun identity(keyId: String? = null) = RecordIdentity(
        recordType = "org.roax.corpus.synthetic",
        schemaVersion = "1.0",
        recordId = "urn:uuid:11111111-1111-4111-8111-111111111111",
        issuerId = "did:web:corpus.roax.invalid",
        issuerKeyId = keyId,
    )

    private fun typedScalars(): Commitment {
        val saltSet = Corpus.saltSet(
            "corpus/fixtures/salts/record-typed-scalars.json", nfc,
        ) as Corpus.SaltSet.ByPath
        return commitWithSaltsByPath(
            record = JsonReader.parse(Corpus.bytes("corpus/fixtures/records/typed-scalars.json")),
            context = IssuanceContext(identity(), EnvelopeProfile.V1_NO_TYPE_MAP_BINDING),
            resolver = synthetic,
            saltsByEncodedPath = saltSet.byEncodedPath,
            nfc = nfc,
        )
    }

    private fun verifierConfig() = VerifierConfig(
        profiles = Corpus.profiles,
        envelopeProfile = EnvelopeProfile.V1_NO_TYPE_MAP_BINDING,
        nfc = nfc,
        resolverFor = { runCatching { Corpus.typeMap(it, nfc) }.getOrNull() },
    )

    // -------------------------- GAP: hashAlg is carried twice and the two must agree ------------

    @Test
    fun `GAP - a hashAlg disagreeing with the anchoring registry is rejected, not silently preferred`() {
        // `docs/conformance-corpus.md` class 18 states this row and it is UNBUILT, because
        // specification section 2.2 leaves the anchoring registry undesigned and section 1.2 of the
        // corpus document forbids the corpus from inventing that interface. So no vector reaches
        // it, and this test is what stands in for one.
        //
        // The defect it pins is a real one this library had: `effectiveHashAlg` read
        // `config.anchorHashAlg ?: env["hashAlg"]` and never compared the two, so an envelope
        // declaring `Poseidon-BN254` verified under SHA-256 and its declared value was discarded
        // without a word - an issuance specification section 7.4 forbids, accepted silently.
        // H2 says authority comes from the registry; it does not say a disagreement is a shrug.
        val commitment = typedScalars()
        val json = EnvelopeWriter.fullCopy(
            commitment,
            Corpus.bytes("corpus/fixtures/records/typed-scalars.json"),
            nfc,
        )

        // The same envelope verifies when the registry agrees with it.
        val agreeing = VerifierConfig(
            profiles = Corpus.profiles,
            envelopeProfile = EnvelopeProfile.V1_NO_TYPE_MAP_BINDING,
            nfc = nfc,
            resolverFor = { runCatching { Corpus.typeMap(it, nfc) }.getOrNull() },
            anchorHashAlg = "SHA-256",
        )
        assertTrue(
            EnvelopeVerifier.verify(json.toByteArray(), agreeing) is VerificationResult.Accepted,
            "a registry that agrees with the envelope must not change the outcome",
        )

        // And is rejected when it does not.
        //
        // **THE DIRECTION IS THE DISCRIMINATOR AND THE OBVIOUS ONE PROVES NOTHING.** Setting the
        // REGISTRY to `Poseidon-BN254` is rejected with or without the comparison, because the
        // allow-list (H3) refuses to resolve an algorithm ROAX-CANON/1 defines no construction
        // for - so that shape passes an implementation with no H2 comparison at all. This is the
        // same trap `docs/conformance-corpus.md` class 18 records about its own allow-list row,
        // and writing this test the wrong way round first is how it was found here: reverting the
        // guard left the test green.
        //
        // The shape that discriminates is the DANGEROUS one: the ENVELOPE declares
        // `Poseidon-BN254` while the registry records `SHA-256`. Without the comparison the
        // registry's value is simply preferred, the envelope verifies under SHA-256, and its
        // declared algorithm is discarded without a word - a record specification section 7.4
        // says MUST NOT be issued, accepted silently.
        val forged = json.replace("\"hashAlg\":\"SHA-256\"", "\"hashAlg\":\"Poseidon-BN254\"")
        assertNotEquals(json, forged, "the envelope under test must actually have been rewritten")
        val rejected = EnvelopeVerifier.verify(forged.toByteArray(), agreeing)
        assertTrue(rejected is VerificationResult.Rejected, "the disagreement MUST be a rejection")
        assertEquals(
            Reason.HASH_ALG_NOT_ALLOWED,
            (rejected as VerificationResult.Rejected).reason,
        )
    }

    // ------------------------------------------------ GAP 1: class 9's forged-tree-size row ------

    @Test
    fun `GAP - the forged-tree-size attack, which no committed negativeProof row carries`() {
        // `corpus/README.md` marks class 9 STALE for exactly this: no committed `negativeProof` row
        // has attack `forged-tree-size`, and that carrier holds only a supplied `leafHash`, not the
        // path, tag, value and salt needed to drive the full disclosed-copy verification path that
        // `docs/conformance-corpus.md` class 9 now requires.
        //
        // First half: reproduce the measurement specification section 11.1 records.
        val leaves = (0 until 8).map { Sha256.digest("ROAX-CANON/1 gap test leaf $it".toByteArray()) }
        val root = Merkle.merkleTreeHash(leaves, Sha256)
        val internalNode = Merkle.merkleTreeHash(leaves.subList(0, 4), Sha256)
        val sibling = Merkle.merkleTreeHash(leaves.subList(4, 8), Sha256)

        assertTrue(
            Merkle.verifyInclusion(internalNode, 0, 2, listOf(sibling), root, Sha256),
            "the RFC 9162 fold accepts an internal node under a FORGED tree size of 2 - this is " +
                "the measurement that corrected section 11.1, and it is why `leafCount` is not a " +
                "binding in a disclosed copy",
        )
        assertFalse(
            Merkle.verifyInclusion(internalNode, 0, 8, listOf(sibling), root, Sha256),
            "under the honest tree size the same node fails, which is why a RANDOM wrong " +
                "leafCount is usually caught and a CHOSEN one is not",
        )

        // Second half, and the one the corpus cannot express: through whole-envelope verification
        // the attack has no purchase, because section 10 step 2 recomputes every leaf hash from the
        // disclosed fields and never accepts a supplied one.
        val commitment = typedScalars()
        val floor = listOf(
            listOf(Segment.Key(Reserved.RECORD_TYPE)),
            listOf(Segment.Key(Reserved.SCHEMA_VERSION)),
            listOf(Segment.Key(Reserved.RECORD_ID)),
            listOf(Segment.Key(Reserved.ISSUER_ID)),
        )
        val honest = EnvelopeWriter.disclosedCopy(commitment.disclose(floor, nfc), nfc)
        assertTrue(
            EnvelopeVerifier.verify(honest.toByteArray(), verifierConfig()) is VerificationResult.Accepted,
            "the honest disclosed copy must verify",
        )

        // Forge the tree size. Every disclosed leaf hash is recomputed, so it is 0x00-domained by
        // construction and cannot be walked to the root from an internal node's position.
        val forged = honest.replace("\"leafCount\":${commitment.leafCount}", "\"leafCount\":2")
        assertNotEquals(honest, forged, "the leafCount substitution must actually have applied")
        val result = EnvelopeVerifier.verify(forged.toByteArray(), verifierConfig())
        assertTrue(result is VerificationResult.Rejected, "a forged leafCount must be rejected")
        assertEquals(Reason.INCLUSION_PROOF_FAILED, (result as VerificationResult.Rejected).reason)
    }

    // ---------------------------------------------- GAP 2: a disclosure this library generated ---

    @Test
    fun `GAP - a disclosed copy generated here round-trips, which every corpus fixture pre-dates`() {
        // Every class-14, 15, 17 and 18 envelope vector consumes a PRE-BUILT fixture. Nothing in
        // the corpus asks an implementation to GENERATE a disclosure and then verify it, so an
        // implementation whose issuance and verification halves disagree passes the corpus.
        val commitment = typedScalars()
        assertEquals(9, commitment.leafCount)
        assertEquals(
            "7846cbd141f123da932004f049303eaa8bd7180d329bfc2c74d54f484f688c4f",
            commitment.rootHex,
        )

        val paths = listOf(
            listOf(Segment.Key(Reserved.RECORD_TYPE)),
            listOf(Segment.Key(Reserved.SCHEMA_VERSION)),
            listOf(Segment.Key(Reserved.RECORD_ID)),
            listOf(Segment.Key(Reserved.ISSUER_ID)),
            listOf(Segment.Key("counts"), Segment.Key("decimal")),
            listOf(Segment.Key("flag")),
        )
        val disclosed = commitment.disclose(paths, nfc)
        val json = EnvelopeWriter.disclosedCopy(disclosed, nfc)

        val result = EnvelopeVerifier.verify(json.toByteArray(), verifierConfig())
        assertTrue(
            result is VerificationResult.Accepted,
            "generated disclosure rejected: ${(result as? VerificationResult.Rejected)?.detail}",
        )
        // A disclosed copy carries the salt of every leaf it reveals and the salt of NO other.
        assertEquals(6, disclosed.leaves.size)
        assertFalse(json.contains("\"salts\""), "a disclosed copy must carry no `salts` array")
        for (leaf in commitment.leaves) {
            val revealed = disclosed.leaves.any { it.index == commitment.leaves.indexOf(leaf) }
            if (!revealed) {
                assertFalse(
                    json.contains(Bytes.toHex(leaf.salt)),
                    "the salt of withheld leaf ${leaf.displayPath} leaked into the disclosed copy",
                )
            }
        }
        // The decimal survived as its committed literal rather than as a float. The fixture's value
        // is `0.010`, so this also pins the trailing zero FHIR R4 says SHALL be preserved: a writer
        // that round-tripped it through any numeric type would have emitted `0.01`, which is a
        // different leaf and would not have verified.
        assertTrue(json.contains("\"value\":\"0.010\""), "the decimal literal must round-trip verbatim")
        assertFalse(json.contains("\"value\":\"0.01\""), "the trailing zero must not be stripped")
    }

    @Test
    fun `GAP - a full copy generated here round-trips, with the record bytes verbatim`() {
        val commitment = typedScalars()
        val recordBytes = Corpus.bytes("corpus/fixtures/records/typed-scalars.json")
        val json = EnvelopeWriter.fullCopy(commitment, recordBytes, nfc)
        val result = EnvelopeVerifier.verify(json.toByteArray(), verifierConfig())
        assertTrue(
            result is VerificationResult.Accepted,
            "generated full copy rejected: ${(result as? VerificationResult.Rejected)?.detail}",
        )
        // The record body carries its numbers in their ORIGINAL JSON form, so `0.01` is still a
        // JSON number rather than a reserialized one. Section 7.3 says the section 6.4 parser
        // requirement therefore applies to the envelope, not only to a bare record.
        assertTrue(json.contains("\"decimal\": 0.01"), "the record body must be embedded verbatim")
    }

    // ------------------------------------------------ GAP 3: ambiguity 2, the bound's counting ---

    @Test
    fun `GAP - 0e99999 is rejected under the literal reading of the digit bound`() {
        // `corpus/README.md` ambiguity 2: "the expanded positional form" is read as the padded form
        // BEFORE output-grammar normalization, which is the literal reading and the memory-safe
        // one. Under the other reading `0e99999` canonicalizes to `0`. **No vector carries it.**
        //
        // A corpus row would be:
        //   {"name": "reject-decimal-zero-huge-exponent", "class": 3, "tag": 4,
        //    "input": "0e99999", "reason": "digit-bound-exceeded"}
        // and it settles the ambiguity, so it needs a ruling first rather than a vector first.
        val e = assertThrows(RoaxException::class.java) { Numbers.canonicalDecimal("0e99999") }
        assertEquals(Reason.DIGIT_BOUND_EXCEEDED, e.reason)
        // The neighbouring case that IS covered, so the two readings are visibly different.
        assertEquals("0", Numbers.canonicalDecimal("0e5"))
    }

    @Test
    fun `GAP - ambiguity 1, the digit bound applies to INTEGER as well as DECIMAL`() {
        // Section 6.2 states the bound under *Canonical decimal* while its own justification counts
        // "class 2's 40-digit integer" against it. Both corpus reference implementations and the
        // Rust library apply it to INTEGER; this library follows the family. No vector
        // discriminates, because no committed integer is anywhere near 1024 digits.
        val atBound = "1".repeat(Numbers.MAX_DIGITS)
        assertEquals(atBound, Numbers.canonicalInteger(atBound))
        val overBound = "1".repeat(Numbers.MAX_DIGITS + 1)
        val e = assertThrows(RoaxException::class.java) { Numbers.canonicalInteger(overBound) }
        assertEquals(Reason.DIGIT_BOUND_EXCEEDED, e.reason)
    }

    // -------------------------------------- GAP 4: ambiguity 6, NFC-colliding sibling keys -------

    @Test
    fun `GAP - NFC-colliding sibling keys with DISJOINT descendants are accepted`() {
        // Ambiguity 6. Sections 3.2 and 3.3 require raw map keys to be unique and emit complete
        // leaf paths, while section 5 normalizes each KEY segment, so this shape has neither a
        // duplicate raw key nor a duplicate complete encoded leaf path even though the two
        // INTERMEDIATE paths encode identically. The Rust implementation accepts it; this library
        // matches, and refuses only a duplicate COMPLETE encoded leaf path.
        // The two spellings are written as explicit escapes rather than as literal characters,
        // because an editor or a tool that normalizes this source file would silently turn the
        // test into one about an ordinary duplicate key.
        val composed = "\u00E9" // U+00E9 LATIN SMALL LETTER E WITH ACUTE
        val decomposed = "e\u0301" // 'e' followed by U+0301 COMBINING ACUTE ACCENT
        assertNotEquals(composed, decomposed, "the two spellings must differ as raw strings")
        assertEquals(composed, nfc.normalize(decomposed), "and must agree after NFC")

        val map = DisplayPatternTypeMap.load(
            """
            {"typeMapVersion":"1.0.0","recordType":"org.roax.corpus.synthetic","schemaVersion":"1.0",
             "entries":[{"pattern":"$composed.**","jsonKind":"string","tag":2},
                        {"pattern":"marker","jsonKind":"string","tag":2}]}
            """.trimIndent().toByteArray(),
            nfc,
        )
        val disjoint = """{"$composed":{"a":"1"},"$decomposed":{"b":"2"},"marker":"m"}"""
        val commitment = commit(
            record = JsonReader.parse(disjoint),
            context = IssuanceContext(identity(), EnvelopeProfile.V1_NO_TYPE_MAP_BINDING),
            resolver = map,
            saltSource = SaltSource.secureRandom(),
            nfc = nfc,
        )
        assertEquals(4 + 3, commitment.leafCount)

        // The colliding case that IS decided: two leaves at the same complete encoded path.
        val colliding = """{"$composed":{"a":"1"},"$decomposed":{"a":"2"},"marker":"m"}"""
        val e = assertThrows(RoaxException::class.java) {
            commit(
                record = JsonReader.parse(colliding),
                context = IssuanceContext(identity(), EnvelopeProfile.V1_NO_TYPE_MAP_BINDING),
                resolver = map,
                saltSource = SaltSource.secureRandom(),
                nfc = nfc,
            )
        }
        assertEquals(Reason.DUPLICATE_LEAF_PATH, e.reason)
    }

    // ------------------------------- GAP 5: whether `**` matches a run of zero segments ----------

    @Test
    fun `GAP - the display-pattern star-star matches ONE OR MORE segments here`() {
        // The superseded display-pattern format says `**` "matches any run of segments" and pins
        // no lower bound. The only `**` pattern in the committed corpus is `a.**`, and no fixture
        // carries a scalar at `a`, so no vector discriminates. This library reads "a run" as at
        // least one segment.
        //
        // This gap belongs to a format `schemas/type-map-1.0.json` calls superseded and says MUST
        // NOT be used to resolve, so the right fix is the corpus moving to the structured-path DFA
        // rather than a vector pinning display-pattern semantics.
        val map = DisplayPatternTypeMap.load(
            """
            {"typeMapVersion":"1.0.0","recordType":"org.roax.corpus.synthetic","schemaVersion":"1.0",
             "entries":[{"pattern":"a.**","jsonKind":"string","tag":2}]}
            """.trimIndent().toByteArray(),
            nfc,
        )
        assertEquals(TypeTag.STRING, map.resolve(listOf(Segment.Key("a"), Segment.Key("b")), JsonKind.STRING))
        assertEquals(
            TypeTag.STRING,
            map.resolve(
                listOf(Segment.Key("a"), Segment.Key("b"), Segment.Index(0), Segment.Key("c")),
                JsonKind.STRING,
            ),
        )
        assertEquals(
            null,
            map.resolve(listOf(Segment.Key("a")), JsonKind.STRING),
            "a run of ZERO segments does not match, so `a.**` does not reach `a` itself",
        )
    }

    // ---------------------------------------- GAP 6: an empty-string key inside a record ---------

    @Test
    fun `GAP - an empty-string key is a real segment in a record, not a dropped one`() {
        // `path-empty-string-key` pins the ENCODING, and section 5 says a key may be the empty
        // string and is distinct from an absent segment. No RECORD vector carries one, so nothing
        // checks that a flattener keeps it rather than skipping it - which is one of the
        // OpenAttestation collisions section 5.1 says length prefixing removes.
        val map = DisplayPatternTypeMap.load(
            """
            {"typeMapVersion":"1.0.0","recordType":"org.roax.corpus.synthetic","schemaVersion":"1.0",
             "entries":[{"pattern":"outer.**","jsonKind":"string","tag":2},
                        {"pattern":"marker","jsonKind":"string","tag":2}]}
            """.trimIndent().toByteArray(),
            nfc,
        )
        val withEmptyKey = commit(
            record = JsonReader.parse("""{"outer":{"":"v"},"marker":"m"}"""),
            context = IssuanceContext(identity(), EnvelopeProfile.V1_NO_TYPE_MAP_BINDING),
            resolver = map,
            saltSource = { ByteArray(SALT_LENGTH_BYTES) },
            nfc = nfc,
        )
        val withoutIt = commit(
            record = JsonReader.parse("""{"outer":{"x":"v"},"marker":"m"}"""),
            context = IssuanceContext(identity(), EnvelopeProfile.V1_NO_TYPE_MAP_BINDING),
            resolver = map,
            saltSource = { ByteArray(SALT_LENGTH_BYTES) },
            nfc = nfc,
        )
        assertEquals(withEmptyKey.leafCount, withoutIt.leafCount)
        assertNotEquals(withEmptyKey.rootHex, withoutIt.rootHex, "the empty key must be committed")
        // u32be(1) ‖ 0x01 ‖ u32be(0), and no key bytes: one segment, distinct from none.
        assertEquals("000000010100000000", Bytes.toHex(encodePath(listOf(Segment.Key("")), nfc)))
        assertEquals("00000000", Bytes.toHex(encodePath(emptyList(), nfc)))
    }

    // ------------------------------------- GAP 7: the reserved-namespace guard's ACCEPT cases ----

    @Test
    fun `GAP - the guard's four cases, including the two an earlier draft got wrong`() {
        // Class 15 covers all four, but only through whole records. Asserting them directly keeps
        // the boundary readable, because the over-broad reading - rejecting a bare `roax` - is the
        // one an implementer reaches for.
        Reserved.guardFirstSegment("roax", nfc) // accepted: collides with nothing
        Reserved.guardFirstSegment("roaxX", nfc) // accepted, same reason
        Reserved.guardFirstSegment("roax_recordType", nfc) // accepted: no dot
        for (squat in listOf("roax.recordType", "roax.anythingElse", "roax.recordIdX", "roax.")) {
            val e = assertThrows(RoaxException::class.java, { Reserved.guardFirstSegment(squat, nfc) }, squat)
            assertEquals(Reason.RESERVED_NAMESPACE, e.reason, squat)
        }
        // And the guard is on the FIRST segment only: a nested `roax.foo` differs from every
        // reserved path in segment count and cannot collide, so rejecting it would be over-broad.
        // This is the most likely over-implementation.
        val nested = listOf(Segment.Key("a"), Segment.Key("roax.foo"))
        encodePath(nested, nfc) // must not raise
        assertEquals("a.roax.foo", displayPath(nested))
    }

    // ----------------------------------------------- GAP 8: leafCount is not a check ------------

    @Test
    fun `GAP - a full copy REJECTS a derived leaf count that disagrees, and a disclosed copy has no such check`() {
        // Section 11.1 requires the full-copy equality to be a rejection rather than a warning or a
        // silent preference, and requires `leafCount` NOT to be used as a check on anything else.
        val commitment = typedScalars()
        val json = EnvelopeWriter.fullCopy(
            commitment, Corpus.bytes("corpus/fixtures/records/typed-scalars.json"), nfc,
        )
        // The declared count is raised while the salts array is padded to match, so the
        // salts-length check passes and the DERIVED-count check is the one that fires.
        val tampered = json
            .replace("\"leafCount\":9", "\"leafCount\":10")
            .replace(
                "\"salts\":[",
                "\"salts\":[{\"segments\":[{\"key\":\"not-a-leaf\"}]," +
                    "\"salt\":\"00000000000000000000000000000000\"},",
            )
        val result = EnvelopeVerifier.verify(tampered.toByteArray(), verifierConfig())
        assertTrue(result is VerificationResult.Rejected)
        assertEquals(Reason.LEAF_COUNT_MISMATCH, (result as VerificationResult.Rejected).reason)
    }
}
