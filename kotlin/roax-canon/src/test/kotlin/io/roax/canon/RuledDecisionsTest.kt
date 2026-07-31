package io.roax.canon

import io.roax.canon.conformance.Corpus
import io.roax.canon.json.JsonReader
import org.junit.jupiter.api.Assertions.assertArrayEquals
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test

/**
 * A non-normalizing [Nfc], used only to show what a raw comparison would have done.
 *
 * Nothing in the library may be configured with this in production: it exists so decision D14a is
 * demonstrated rather than asserted.
 */
private object RawNfc : Nfc {
    override val unicodeVersion: String = "none (raw comparison, for D14a demonstration only)"

    override fun normalize(s: String): String = s
}

/**
 * The rulings this library implements, each with a test that would fail under the pre-ruling
 * behaviour.
 *
 * A ruling that is merely stated in prose is one an implementation can pass every other test while
 * violating, which is the shape of failure `docs/spec/roax-canon-1.md` section 11.3 says a
 * normative sentence is not enough to prevent.
 */
class RuledDecisionsTest {

    private val nfc = PlatformNfc

    private val synthetic get() = Corpus.typeMap("org.roax.corpus.synthetic", nfc)

    private val syntheticRaw = DisplayPatternTypeMap.load(
        Corpus.bytes("corpus/type-maps/org.roax.corpus.synthetic.json"),
        RawNfc,
    )

    private fun identity() = RecordIdentity(
        recordType = "org.roax.corpus.synthetic",
        schemaVersion = "1.0",
        recordId = "urn:uuid:11111111-1111-4111-8111-111111111111",
        issuerId = "did:web:corpus.roax.invalid",
    )

    private fun rootOf(recordFile: String, resolver: TypeResolver, saltsFile: String): String {
        val saltSet = Corpus.saltSet(saltsFile, nfc) as Corpus.SaltSet.ByPath
        return commitWithSaltsByPath(
            record = JsonReader.parse(Corpus.bytes(recordFile)),
            context = IssuanceContext(identity(), EnvelopeProfile.V1_NO_TYPE_MAP_BINDING),
            resolver = resolver,
            saltsByEncodedPath = saltSet.byEncodedPath,
            nfc = nfc,
        ).rootHex
    }

    // ------------------------------------------------------------------------ D14a: NORMALIZE ----

    @Test
    fun `D14a - the Kelvin key resolves under NFC and fails closed under raw matching`() {
        // `record-guard-kelvin-key` carries the key U+212A KELVIN SIGN, and the synthetic map
        // declares only the ASCII pattern `Kelvin`. `corpus/README.md` lists this as one of the two
        // committed vectors that discriminate the two readings of decision D14.
        //
        // Only the RESOLVER is switched to raw here. Path encoding still normalizes, so this
        // isolates the lookup - which is the site the ruling is about.
        val kelvinKey = "Kelvin"
        assertEquals("Kelvin", nfc.normalize(kelvinKey))

        assertEquals(
            TypeTag.STRING,
            synthetic.resolve(listOf(Segment.Key(kelvinKey)), JsonKind.STRING),
            "under D14a the decomposed spelling reaches the ASCII pattern",
        )
        assertNull(
            syntheticRaw.resolve(listOf(Segment.Key(kelvinKey)), JsonKind.STRING),
            "under raw matching it does not, and fail-closed refuses the record",
        )

        // End to end: the ruled reading produces the committed root; the raw reading has no root.
        assertEquals(
            "d913e52ad4c918f87466d9fbd40070119379f8d293ab85ce1a7ad50f79313107",
            rootOf(
                "corpus/fixtures/records/guard-kelvin-key.json",
                synthetic,
                "corpus/fixtures/salts/record-guard-kelvin-key.json",
            ),
        )
        val e = assertThrows(RoaxException::class.java) {
            rootOf(
                "corpus/fixtures/records/guard-kelvin-key.json",
                syntheticRaw,
                "corpus/fixtures/salts/record-guard-kelvin-key.json",
            )
        }
        assertEquals(Reason.TYPE_MAP_FAIL_CLOSED, e.reason)
    }

    @Test
    fun `D14a - a decomposed key resolves, and both spellings give ONE root`() {
        // The other discriminating vector. This is also the invisible failure D12 was ruled to
        // prevent, arriving one layer up: under raw matching the decomposed key is REFUSED while
        // its composed twin commits, and the two render identically to whoever typed the key.
        val decomposed = "é"
        val composed = "é"
        assertEquals(composed, nfc.normalize(decomposed))

        assertEquals(TypeTag.STRING, synthetic.resolve(listOf(Segment.Key(decomposed)), JsonKind.STRING))
        assertNull(syntheticRaw.resolve(listOf(Segment.Key(decomposed)), JsonKind.STRING))

        val nfd = rootOf(
            "corpus/fixtures/records/nfc-key-nfd.json", synthetic,
            "corpus/fixtures/salts/normalization-nfc-key.json",
        )
        val nfcRoot = rootOf(
            "corpus/fixtures/records/nfc-key-nfc.json", synthetic,
            "corpus/fixtures/salts/normalization-nfc-key.json",
        )
        assertEquals(nfcRoot, nfd, "the two spellings must produce one root")
        assertEquals("15b5cc28b423f333117d36965366711c2b8dbc4a145ba9a9bbd5966d7a6cb1fb", nfcRoot)
    }

    @Test
    fun `D14a - normalizing the lookup does not widen the map`() {
        // A key whose NFC form is not a declared transition still fails closed.
        assertNull(synthetic.resolve(listOf(Segment.Key("notInTheMap")), JsonKind.STRING))
        assertNull(synthetic.resolve(listOf(Segment.Key("Kelvin")), JsonKind.NUMBER))
    }

    // ------------------------------------------------------- ruled binding: FHIR base64Binary ----

    @Test
    fun `ruled binding - base64Binary is BYTES over the DECODED octets, grade Strong`() {
        // `blob.bytes` is bound BYTES and `blob.text` STRING in the synthetic map, and the
        // `record-fhir-ruled-bindings` fixture gives them the SAME base64 characters. That is the
        // isolated pair separating the two readings: BYTES commits the value, STRING commits the
        // transport spelling, so the two leaves must differ.
        val text = "SGVsbG8sIFJPQVgh"
        val decoded = Base64Strict.decode(text)
        assertArrayEquals("Hello, ROAX!".toByteArray(), decoded)

        val asBytes = encodeValue(TypeTag.BYTES, RoaxValue.Bytes(decoded))
        val asString = encodeValue(TypeTag.STRING, RoaxValue.Text(text))
        assertArrayEquals(decoded, asBytes)
        assertNotEquals(Bytes.toHex(asBytes), Bytes.toHex(asString))

        assertEquals(
            "36025461595b5ed9d9d01576fa2f7350fcc3cbe9e4495baa8a3e9d421ae96178",
            rootOf(
                "corpus/fixtures/records/fhir-ruled-bindings.json",
                synthetic,
                "corpus/fixtures/salts/record-fhir-ruled-bindings.json",
            ),
        )
    }

    @Test
    fun `ruled binding - canonical base64 is an INPUT-ADMISSIBILITY condition, not the committed value`() {
        // The pin has to survive the BYTES ruling rather than become redundant under it. Three of
        // these four spellings decode to the accepted fixture's octets under a permissive decoder,
        // which is the RFC 4648 section 3.5 hazard exhibited rather than described.
        val canonical = "SGVsbG8sIFJPQVgh"
        for (spelling in listOf("SGVsbG8sIFJPQVg", "-_8=", "aGl=", "SGVs\nbG8=")) {
            val e = assertThrows(RoaxException::class.java, { Base64Strict.decode(spelling) }, spelling)
            assertEquals(Reason.BASE64_NOT_CANONICAL, e.reason, spelling)
        }
        // And the octets, once admitted, are what is hashed.
        assertArrayEquals("Hello, ROAX!".toByteArray(), Base64Strict.decode(canonical))
    }

    // ------------------------------------------------------- ruled binding: FHIR Narrative.div ---

    @Test
    fun `ruled binding - Narrative div is STRING over the ESCAPED XHTML, unparsed, grade Decisive`() {
        // The tag is a carrier type and nothing more: STRING selects utf8(NFC(s)), so an
        // implementation MUST NOT parse the XHTML, normalize it as markup, or reserialize it.
        val div = "<div xmlns=\"http://www.w3.org/1999/xhtml\">a &amp; b &lt;ok&gt;</div>"
        assertEquals(TypeTag.STRING, synthetic.resolve(
            listOf(Segment.Key("narrative"), Segment.Key("div")), JsonKind.STRING,
        ))
        // The entity references survive verbatim. A markup-aware layer would have turned `&amp;`
        // into `&`, which is a different leaf.
        assertArrayEquals(
            div.toByteArray(Charsets.UTF_8),
            encodeValue(TypeTag.STRING, RoaxValue.Text(div)),
        )
        assertNotEquals(
            Bytes.toHex(encodeValue(TypeTag.STRING, RoaxValue.Text(div))),
            Bytes.toHex(encodeValue(TypeTag.STRING, RoaxValue.Text("<div xmlns=\"http://www.w3.org/1999/xhtml\">a & b <ok></div>"))),
        )
    }

    // -------------------------------------------- ruled binding: FHIR primitive-array null -------

    @Test
    fun `ruled binding - a primitive-array null placeholder is REJECTED, not bound, grade Decisive`() {
        // The ruling is expressed as an ABSENCE: the synthetic map binds `name[*].given[*]` for
        // `string` and declares nothing for `null`. Complete profile validation runs before map
        // resolution, so a map may not widen a record its own selected schema refuses.
        assertEquals(
            TypeTag.STRING,
            synthetic.resolve(
                listOf(Segment.Key("name"), Segment.Index(0), Segment.Key("given"), Segment.Index(0)),
                JsonKind.STRING,
            ),
        )
        assertNull(
            synthetic.resolve(
                listOf(Segment.Key("name"), Segment.Index(0), Segment.Key("given"), Segment.Index(1)),
                JsonKind.NULL,
            ),
            "no NULL binding exists at a primitive-array item, and none may be inferred",
        )

        val record = JsonReader.parse("""{"name": [{"given": ["Ada", null]}], "marker": "m"}""")
        val e = assertThrows(RoaxException::class.java) {
            commit(
                record = record,
                context = IssuanceContext(identity(), EnvelopeProfile.V1_NO_TYPE_MAP_BINDING),
                resolver = synthetic,
                saltSource = { ByteArray(SALT_LENGTH_BYTES) },
                nfc = nfc,
            )
        }
        assertEquals(Reason.TYPE_MAP_FAIL_CLOSED, e.reason)
    }

    // ------------------------------------------------ ruled binding: vaccination dose and expiry --

    @Test
    fun `ruled binding - vaccination dose is INTEGER, grade Strong`() {
        val vaccination = Corpus.typeMap("sg.gov.moh.vaccination-healthcert", nfc)
        val dose = listOf(
            Segment.Key("notarisationMetadata"),
            Segment.Key("signedEuHealthCerts"),
            Segment.Index(0),
            Segment.Key("dose"),
        )
        assertEquals(TypeTag.INTEGER, vaccination.resolve(dose, JsonKind.NUMBER))
        // INTEGER rather than DECIMAL is what makes `1` and `1.0` different records: under DECIMAL
        // they would both canonicalize, under INTEGER the fractional spelling is refused outright
        // by the section 6.2 grammar.
        assertEquals("1", Numbers.canonicalInteger("1"))
        assertThrows(RoaxException::class.java) { Numbers.canonicalInteger("1.0") }
    }

    @Test
    fun `ruled binding - the dose positive-integer narrowing is NOT in this layer, and that is ruled`() {
        // A value-domain rule is not a type map and not in the canonicalization layer. Section 4.2
        // orders profile validation BEFORE map resolution, and decision D13a keeps value-domain
        // validation in a separate, independently versioned conformance layer.
        //
        // So the canonicalization layer ACCEPTS `0` and the negatives as grammar-valid INTEGERs.
        // The narrowing is declared by `docs/profiles/vaccination-healthcert.md` section 6 and
        // enforced by the profile validator; a fractional value is already refused one layer down.
        assertEquals("0", Numbers.canonicalInteger("0"))
        assertEquals("-1", Numbers.canonicalInteger("-1"))
        assertThrows(RoaxException::class.java) { Numbers.canonicalInteger("0.5") }
    }

    @Test
    fun `ruled binding - expiryDateTime is STRING by explicit profile declaration, grade Moderate`() {
        val vaccination = Corpus.typeMap("sg.gov.moh.vaccination-healthcert", nfc)
        val expiry = listOf(
            Segment.Key("notarisationMetadata"),
            Segment.Key("signedEuHealthCerts"),
            Segment.Index(0),
            Segment.Key("expiryDateTime"),
        )
        assertEquals(TypeTag.STRING, vaccination.resolve(expiry, JsonKind.STRING))
        // Moderate rather than Strong: the schema carries `format: "date-time"` and NO type, and
        // under JSON Schema draft-07 sections 7.2 and 7.3.1 a format annotation neither creates a
        // string type nor rejects a non-string instance. So the schema admits every JSON kind and
        // the tag comes from the profile declaration. The map still fails closed for other kinds,
        // which is what keeps the declaration from silently widening.
        assertNull(vaccination.resolve(expiry, JsonKind.NUMBER))
        assertNull(vaccination.resolve(expiry, JsonKind.BOOLEAN))
    }

    // ------------------------------------------------------------------ D9: BLOB_REF registered --

    @Test
    fun `D9 - tag 8 BLOB_REF is registered, refused by every v1 path, and its byte layout is pinned`() {
        // Section 6.5: no version-1 profile selects BLOB_REF, and an implementation MUST reject a
        // record whose type map binds any path to tag 8 and MUST reject an envelope carrying a
        // tag-8 leaf.
        val digest = Sha256.digest("blob".toByteArray())
        val value = RoaxValue.BlobRef(14314L, digest)

        val refused = assertThrows(RoaxException::class.java) {
            encodeValue(TypeTag.BLOB_REF, value)
        }
        assertEquals(Reason.BLOB_REF_NOT_DECLARED, refused.reason)

        // The construction is defined now so it does not have to be retrofitted after five
        // independent implementations exist - the change that splits a library family.
        val encoded = encodeValue(TypeTag.BLOB_REF, value, allowBlobRef = true)
        val expected = Bytes.u64be(14314L) + Bytes.u32be(32L) + digest
        assertArrayEquals(expected, encoded)
        assertEquals(8 + 4 + 32, encoded.size)

        // A type map that binds tag 8 is refused at load, so the record never reaches the encoder.
        val mapWithBlobRef = """
            {"typeMapVersion":"1.0.0","recordType":"org.roax.corpus.synthetic","schemaVersion":"1.0",
             "entries":[{"pattern":"blob","jsonKind":"string","tag":8}]}
        """.trimIndent()
        val rejected = assertThrows(RoaxException::class.java) {
            DisplayPatternTypeMap.load(mapWithBlobRef.toByteArray(), nfc)
        }
        assertEquals(Reason.BLOB_REF_NOT_DECLARED, rejected.reason)
    }

    // --------------------------------------------------------- B: Poseidon registered, forbidden --

    @Test
    fun `B - Poseidon-BN254 is registered and MUST NOT be issued against`() {
        // Section 7.4: registered because both hash families are first-class and selectable per
        // record, but its parameterization is not pinned - the field, the rate and capacity, the
        // round constants, and the encoding from a length-prefixed byte string to field elements.
        assertThrows(RoaxException::class.java) {
            PoseidonBn254Unparameterized.digest(ByteArray(0))
        }
        // A v1 verifier's allow-list excludes it, so it fails closed with a stated reason rather
        // than as an unknown algorithm.
        val e = assertThrows(RoaxException::class.java) {
            HashAlgorithmAllowList.DEFAULT.resolve("Poseidon-BN254")
        }
        assertEquals(Reason.HASH_ALG_NOT_ALLOWED, e.reason)
        assertEquals(Sha256, HashAlgorithmAllowList.DEFAULT.resolve("SHA-256"))
    }
}
