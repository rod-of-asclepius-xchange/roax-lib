package io.roax.canon.conformance

import io.roax.canon.Bytes
import io.roax.canon.CANON
import io.roax.canon.EmptyContainerAuthorization
import io.roax.canon.EnvelopeProfile
import io.roax.canon.EnvelopeVerifier
import io.roax.canon.IssuanceContext
import io.roax.canon.Merkle
import io.roax.canon.PlatformNfc
import io.roax.canon.Reason
import io.roax.canon.RecordIdentity
import io.roax.canon.RoaxException
import io.roax.canon.RoaxValue
import io.roax.canon.SALT_LENGTH_BYTES
import io.roax.canon.SaltSource
import io.roax.canon.Segment
import io.roax.canon.Sha256
import io.roax.canon.TypeTag
import io.roax.canon.VerificationResult
import io.roax.canon.commit
import io.roax.canon.displayPath
import io.roax.canon.encodePath
import io.roax.canon.encodeValue
import io.roax.canon.commitWithSaltsByPath
import io.roax.canon.disclose
import io.roax.canon.EnvelopeWriter
import io.roax.canon.json.JsonArray
import io.roax.canon.json.JsonBoolean
import io.roax.canon.json.JsonNull
import io.roax.canon.json.JsonNumber
import io.roax.canon.json.JsonObject
import io.roax.canon.json.JsonReader
import io.roax.canon.json.JsonString
import io.roax.canon.json.JsonValue
import io.roax.canon.leafHash
import org.junit.jupiter.api.AfterAll
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.TestInstance
import java.io.File

/**
 * Runs every vector in the committed conformance corpus.
 *
 * `corpus/README.md` gives the procedure per class in its "Checking an implementation that is not
 * one of these two" table, and this follows it. Two things it insists on are honoured here rather
 * than smoothed over:
 *
 * - **A vector that cannot run is reported NOT RUN and never counted as passed.** Class 10 needs a
 *   reference checkout that lives outside this repository by design.
 * - **A rejection's `reason` is checked, not just its booleanness.** Several fixtures are
 *   rejectable for more than one cause, so a boolean alone would pass an implementation that never
 *   ran the check the vector is about. [ReasonEquivalence] is the declared mapping.
 */
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class ConformanceCorpusTest {

    private val nfc = PlatformNfc

    // ------------------------------------------------------------------ the group guard itself ---

    /**
     * Every vector group the corpus carries must be consumed by some test in this suite.
     *
     * [Corpus.vectors] answers an unknown group with the empty list, so a corpus that grew a group
     * no test reads would contribute zero assertions and report the same green it reported before
     * the group existed. That is the exact defect shape the corpus exists to prevent, and it is
     * invisible to the per-class report as well: a class whose only vectors live in an unconsumed
     * group reads as absent rather than as failed.
     */
    @Test
    fun `every vector group is consumed`() {
        val unconsumed = Corpus.unconsumedGroups()
        assertTrue(
            unconsumed.isEmpty(),
            "the corpus carries vector group(s) this suite does not consume: " +
                "${unconsumed.joinToString(", ")}; a group read as absent reports the same green " +
                "as before it existed",
        )
    }

    // ---------------------------------------------------------------- class 6: path encoding ----

    @Test
    fun `encodePath vectors`() {
        var n = 0
        for (v in Corpus.vectors("encodePath")) {
            val segments = Corpus.readSegments(v["segments"]!!)
            assertEquals(
                Corpus.str(v, "encodedHex"),
                Bytes.toHex(encodePath(segments, nfc)),
                "encodePath ${Corpus.str(v, "name")}",
            )
            // The display path is for humans and is never hashed (section 5.2). It is emitted from
            // the RAW key, which `path-nfc-key` and `path-nfd-key` pin: their display paths differ
            // while their encodings are identical.
            assertEquals(
                Corpus.str(v, "displayPath"),
                displayPath(segments),
                "displayPath ${Corpus.str(v, "name")}",
            )
            n++
        }
        Report.pass("encodePath", n)
    }

    // ------------------------------------------------------------- classes 1-5, 7: value bytes --

    @Test
    fun `encodeValue vectors`() {
        var n = 0
        for (v in Corpus.vectors("encodeValue")) {
            val tag = TypeTag.ofCode(Corpus.int(v, "tag"))
            val value = Corpus.value(tag, v["input"])
            assertEquals(
                Corpus.str(v, "encodedHex"),
                Bytes.toHex(encodeValue(tag, value, nfc)),
                "encodeValue ${Corpus.str(v, "name")}",
            )
            n++
        }
        Report.pass("encodeValue", n)
    }

    // ----------------------------------------------------------------- class 3 etc: rejections --

    @Test
    fun `reject vectors`() {
        var n = 0
        for (v in Corpus.vectors("reject")) {
            val name = Corpus.str(v, "name")
            val expected = ReasonEquivalence.expect(Corpus.str(v, "reason"))
            val actual = runCatching { runRejectVector(v) }
            val e = actual.exceptionOrNull()
            assertTrue(
                e is RoaxException,
                "$name MUST be rejected, but it was accepted" +
                    (if (e != null) " (threw ${e::class.simpleName}: ${e.message})" else ""),
            )
            assertEquals(
                expected,
                (e as RoaxException).reason,
                "$name rejected for the wrong reason: ${e.message}",
            )
            n++
        }
        Report.pass("reject", n)
    }

    /** Dispatches a reject vector to the carrier its fields name (`corpus/README.md`). */
    private fun runRejectVector(v: JsonObject) {
        val input = v["input"]
        val recordType = Corpus.strOrNull(v, "recordType")

        // A reject vector with a `recordType` is a WHOLE-RECORD rejection: the input is record text
        // and the runner MUST flatten it through the COMMITTED type map for that recordType. The
        // shape exists because three of the five type bindings ruled on 2026-07-30 are stated as
        // rejections rather than as tags, and a tag-bearing reject vector arrives at the value
        // encoder already in the carrier form, so it can never exercise a rejection that happens
        // where a RECORD value is converted into that carrier.
        if (recordType != null) {
            val text = Corpus.jsonText(input!!)
                ?: throw IllegalArgumentException("a record-shaped reject vector needs \$jsonText")
            val record = JsonReader.parse(text)
            commit(
                record = record,
                context = IssuanceContext(
                    RecordIdentity(
                        recordType = recordType,
                        schemaVersion = "1.0",
                        recordId = "urn:uuid:11111111-1111-4111-8111-111111111111",
                        issuerId = "did:web:corpus.roax.invalid",
                    ),
                    EnvelopeProfile.V1_NO_TYPE_MAP_BINDING,
                ),
                resolver = Corpus.typeMap(recordType, nfc),
                saltSource = { ByteArray(SALT_LENGTH_BYTES) },
                nfc = nfc,
            )
            return
        }

        // A tag names the value encoder.
        val tagCode = (v["tag"] as? io.roax.canon.json.JsonNumber)?.literal?.toInt()
        if (tagCode != null) {
            val tag = TypeTag.ofCode(tagCode)
            encodeValue(tag, Corpus.value(tag, input), nfc)
            return
        }

        // `$segments` names the path encoder plus the reserved-namespace guard.
        val segmentsEscape = input?.let { Corpus.segmentsEscape(it) } ?: v["segments"]
        if (segmentsEscape != null) {
            val segments = Corpus.readSegments(segmentsEscape)
            // A record-supplied path is guarded on its FIRST segment only (section 11.2), then
            // encoded. Both are attempted so whichever condition the vector is about fires.
            (segments.firstOrNull() as? Segment.Key)?.let {
                io.roax.canon.Reserved.guardFirstSegment(it.key, nfc)
            }
            encodePath(segments, nfc)
            return
        }

        // Otherwise the input is record text handed to the JSON reader, for rejections at the
        // parser boundary rather than at a tag.
        val text = Corpus.jsonText(input!!)
            ?: throw IllegalArgumentException("reject vector carries no recognised carrier")
        JsonReader.parse(text)
    }

    // ------------------------------------------------------------------------ classes 1-7: leaf --

    @Test
    fun `leaf vectors`() {
        var n = 0
        for (v in Corpus.vectors("leaf")) {
            val segments = Corpus.readSegments(v["segments"]!!)
            val tag = TypeTag.ofCode(Corpus.int(v, "tag"))
            val salt = Corpus.hex(Corpus.str(v, "saltHex"))
            Corpus.requireSaltLength(salt)
            // The salt is an INPUT: decision D4 is ruled D4b, so nothing derives one.
            assertEquals(
                Corpus.str(v, "leafHash"),
                Bytes.toHex(leafHash(segments, tag, Corpus.value(tag, v["value"]), salt, Sha256, CANON, nfc)),
                "leafHash ${Corpus.str(v, "name")}",
            )
            n++
        }
        Report.pass("leaf", n)
    }

    // ------------------------------------------------------------------------- class 8: the tree --

    @Test
    fun `tree vectors`() {
        var n = 0
        for (v in Corpus.vectors("tree")) {
            val leaves = Corpus.hexList(v, "leafHashes")
            assertEquals(
                Corpus.str(v, "root"),
                Bytes.toHex(Merkle.merkleTreeHash(leaves, Sha256)),
                "MTH ${Corpus.str(v, "name")}",
            )
            n++
        }
        Report.pass("tree", n)
    }

    @Test
    fun `inclusion vectors`() {
        // Inclusion and negative-proof vectors are derived from the tree vector named `tree-n<size>`,
        // keyed here by its actual leaf count rather than by parsing that name.
        val trees = Corpus.vectors("tree").associateBy { Corpus.hexList(it, "leafHashes").size }
        var n = 0
        for (v in Corpus.vectors("inclusion")) {
            val name = Corpus.str(v, "name")
            val leafHash = Corpus.hex(Corpus.str(v, "leafHash"))
            val index = Corpus.int(v, "index")
            val treeSize = Corpus.int(v, "treeSize")
            val auditPath = Corpus.hexList(v, "auditPath")
            val root = Corpus.hex(Corpus.str(v, "root"))
            val expect = Corpus.bool(v, "expect")

            assertEquals(
                expect,
                Merkle.verifyInclusion(leafHash, index.toLong(), treeSize.toLong(), auditPath, root, Sha256),
                "verifyInclusion $name",
            )

            // Generating the audit path for `index` must reproduce `auditPath`.
            if (expect) {
                trees[treeSize]?.let { tree ->
                    val generated = Merkle.inclusionPath(Corpus.hexList(tree, "leafHashes"), index, Sha256)
                    assertEquals(
                        auditPath.map { Bytes.toHex(it) },
                        generated.map { Bytes.toHex(it) },
                        "generated audit path $name",
                    )
                }
            }
            n++
        }
        Report.pass("inclusion", n)
    }

    @Test
    fun `negative proof vectors`() {
        var n = 0
        for (v in Corpus.vectors("negativeProof")) {
            val ok = Merkle.verifyInclusion(
                Corpus.hex(Corpus.str(v, "leafHash")),
                Corpus.int(v, "index").toLong(),
                Corpus.int(v, "treeSize").toLong(),
                Corpus.hexList(v, "auditPath"),
                Corpus.hex(Corpus.str(v, "root")),
                Sha256,
            )
            assertFalse(ok, "negative proof ${Corpus.str(v, "name")} MUST fail verification")
            n++
        }
        Report.pass("negativeProof", n)
    }

    // ------------------------------------------------------------------ class 11: schema binding --

    @Test
    fun `typeMap vectors`() {
        var n = 0
        for (v in Corpus.vectors("typeMap")) {
            val name = Corpus.str(v, "name")
            val resolver = Corpus.typeMap(Corpus.str(v, "recordType"), nfc)
            val segments = Corpus.readSegments(v["segments"]!!)
            val kind = io.roax.canon.JsonKind.ofLabel(Corpus.str(v, "jsonKind"))
            val resolved = resolver.resolve(segments, kind)
            if (Corpus.boolOrNull(v, "expectFailClosed") == true) {
                assertNull(resolved, "$name MUST fail closed")
            } else {
                assertEquals(TypeTag.ofCode(Corpus.int(v, "expectTag")), resolved, name)
            }
            n++
        }
        Report.pass("typeMap", n)
    }

    // ------------------------------------------------------- classes 5, 7, 10, 13, 15: records ---

    @Test
    fun `record vectors`() {
        var ran = 0
        var notRun = 0
        val specDivergences = ArrayList<String>()

        for (v in Corpus.vectors("record")) {
            val name = Corpus.str(v, "name")
            val recordFile = Corpus.str(v, "recordFile")

            val record = loadRecord(recordFile)
            if (record == null) {
                // Class 10 names the MOH samples by module and export in a checkout that lives
                // outside this repository by design. NOT RUN is reported, never counted as passed.
                Report.notRun(
                    "record/$name",
                    "needs the reference record; set ROAX_REFERENCE_RECORDS to a directory " +
                        "holding ${referenceCandidates(recordFile).joinToString(" or ")}",
                )
                notRun++
                continue
            }

            val identity = RecordIdentity(
                recordType = Corpus.str(v, "recordType"),
                schemaVersion = Corpus.str(v, "schemaVersion"),
                recordId = Corpus.str(v, "recordId"),
                issuerId = Corpus.str(v, "issuerId"),
                issuerKeyId = Corpus.strOrNull(v, "issuerKeyId"),
            )
            val saltSet = Corpus.saltSet(Corpus.str(v, "saltsFile"), nfc)

            // The specification's own reading first (section 3.3: the map must authorize a path
            // before the flattener emits EMPTY_ARRAY or EMPTY_OBJECT).
            val strict = runCatching {
                buildRoot(record, identity, saltSet)
            }
            val commitment = if (strict.isSuccess) {
                strict.getOrThrow()
            } else {
                val e = strict.exceptionOrNull()
                    ?: throw IllegalStateException("failed Result carries no exception")
                if (e !is RoaxException || e.reason != Reason.TYPE_MAP_FAIL_CLOSED) throw e
                // The measured corpus divergence: `corpus/type-maps/org.roax.corpus.synthetic.json`
                // declares `a.b` for jsonKind "null" alone, while these fixtures carry an empty
                // array and an empty object there. Under section 3.3 both records fail closed and
                // have no root; the corpus asserts one. Recorded, then re-run under the reading the
                // corpus was built with so the rest of the vector is still checked.
                specDivergences.add(name)
                buildRoot(record, identity, saltSet, EmptyContainerAuthorization.CORPUS_1_0_COMPATIBILITY)
            }

            assertEquals(Corpus.int(v, "leafCount"), commitment.leafCount, "leafCount $name")
            assertEquals(Corpus.str(v, "root"), commitment.rootHex, "root $name")
            ran++
        }

        // Pinned as a measurement, not tolerated as a range. `python/FINDINGS.md` item 1 and
        // `docs/typescript-implementation-findings.md` both put this at exactly two class-5 vectors.
        assertEquals(
            listOf("record-structure-empty-array", "record-structure-empty-object"),
            specDivergences.sorted(),
            "the set of vectors that fail closed under specification section 3.3 changed",
        )
        Report.pass("record", ran)
        Report.note(
            "record",
            "$notRun NOT RUN; ${specDivergences.size} vectors need the corpus's empty-container " +
                "reading rather than specification section 3.3's",
        )
    }

    private fun buildRoot(
        record: io.roax.canon.json.JsonValue,
        identity: RecordIdentity,
        saltSet: Corpus.SaltSet,
        empty: EmptyContainerAuthorization = EmptyContainerAuthorization.REQUIRED,
    ) = when (saltSet) {
        is Corpus.SaltSet.ByPath -> io.roax.canon.commitWithSaltsByPath(
            record = record,
            context = IssuanceContext(identity, EnvelopeProfile.V1_NO_TYPE_MAP_BINDING),
            resolver = Corpus.typeMap(identity.recordType, nfc),
            saltsByEncodedPath = saltSet.byEncodedPath,
            nfc = nfc,
            emptyContainers = empty,
        )

        is Corpus.SaltSet.Positional -> commit(
            record = record,
            context = IssuanceContext(identity, EnvelopeProfile.V1_NO_TYPE_MAP_BINDING),
            resolver = Corpus.typeMap(identity.recordType, nfc),
            saltSource = SaltSource.replaying(saltSet.salts),
            nfc = nfc,
            emptyContainers = empty,
        )
    }

    /** Loads a record fixture, or a reference record from `ROAX_REFERENCE_RECORDS` if configured. */
    private fun loadRecord(recordFile: String): io.roax.canon.json.JsonValue? {
        if (!recordFile.startsWith("references/")) {
            return JsonReader.parse(Corpus.bytes(recordFile))
        }
        val dir = System.getenv("ROAX_REFERENCE_RECORDS") ?: return null
        for (candidate in referenceCandidates(recordFile)) {
            val f = File(dir, candidate)
            if (f.isFile) return JsonReader.parse(f.readBytes())
        }
        return null
    }

    /**
     * The two committed naming conventions for an extracted reference record.
     *
     * The vector names only the path inside the reference checkout, and
     * `corpus/tools/extract_reference_record.py` writes wherever `--out` says, so the filename is
     * each runner's own contract. The TypeScript runner names by `<authority>.<profile>.json` and
     * the Rust one by its EXPORT. Both are probed here so one directory can satisfy either.
     */
    private fun referenceCandidates(recordFile: String): List<String> {
        val export = recordFile.substringAfterLast('#', "")
        val profile = recordFile.removePrefix("references/schemata/src/")
            .substringBeforeLast('/')
            .substringBeforeLast('/')
            .replace('/', '.')
        return listOfNotNull(
            if (profile.isNotEmpty()) "$profile.json" else null,
            if (export.isNotEmpty()) "$export.json" else null,
        )
    }

    // ------------------------------------------------------ class 12: cross-record unlinkability --

    @Test
    fun `unlinkability vectors`() {
        var n = 0
        for (v in Corpus.vectors("unlinkability")) {
            val name = Corpus.str(v, "name")
            val paths = (v["paths"] as io.roax.canon.json.JsonArray).elements.map { Corpus.readSegments(it) }
            val tag = TypeTag.ofCode(Corpus.int(v, "tag"))
            val value = RoaxValue.Text(Corpus.str(v, "value"))
            val trials = Corpus.int(v, "trials")

            // Nothing is compared against a pinned value, because under D4b there is none to pin:
            // the runner draws with ITS OWN generator and asserts the three relations. This detects
            // a deterministic or reused salt; it cannot detect a weak CSPRNG, and no fixed vector
            // file can.
            val source = SaltSource.secureRandom()
            val saltsPerTrial = ArrayList<List<ByteArray>>(trials)
            val hashesPerTrial = ArrayList<List<ByteArray>>(trials)
            repeat(trials) {
                val salts = paths.map { source.next() }
                saltsPerTrial.add(salts)
                hashesPerTrial.add(
                    paths.mapIndexed { i, p -> leafHash(p, tag, value, salts[i], Sha256, CANON, nfc) },
                )
            }

            if (Corpus.boolOrNull(v, "expectDistinctSaltsWithinIssuance") == true) {
                for (salts in saltsPerTrial) {
                    assertEquals(
                        salts.size,
                        salts.map { Bytes.toHex(it) }.toSet().size,
                        "$name: salts within one issuance must be distinct",
                    )
                }
            }
            if (Corpus.boolOrNull(v, "expectDistinctSaltsAcrossIssuances") == true) {
                for (i in paths.indices) {
                    val across = saltsPerTrial.map { Bytes.toHex(it[i]) }
                    assertEquals(across.size, across.toSet().size, "$name: salts must not repeat across issuances")
                }
            }
            if (Corpus.boolOrNull(v, "expectDistinctLeafHashesAcrossIssuances") == true) {
                for (i in paths.indices) {
                    val across = hashesPerTrial.map { Bytes.toHex(it[i]) }
                    assertEquals(
                        across.size,
                        across.toSet().size,
                        "$name: the same path and value must not produce the same leaf hash twice",
                    )
                }
            }
            n++
        }
        Report.pass("unlinkability", n)
    }

    // ------------------------------------------------------------- class 19: NFC end to end -----

    @Test
    fun `normalization vectors`() {
        var n = 0
        for (v in Corpus.vectors("normalization")) {
            val name = Corpus.str(v, "name")
            val identity = RecordIdentity(
                recordType = Corpus.str(v, "recordType"),
                schemaVersion = Corpus.str(v, "schemaVersion"),
                recordId = Corpus.str(v, "recordId"),
                issuerId = Corpus.str(v, "issuerId"),
            )
            // ONE salt set for both records, so any difference between the two roots is
            // normalization and nothing else.
            val saltSet = Corpus.saltSet(Corpus.str(v, "saltsFile"), nfc)

            val nfd = buildRoot(JsonReader.parse(Corpus.bytes(Corpus.str(v, "recordFileNFD"))), identity, saltSet)
            val composed = buildRoot(
                JsonReader.parse(Corpus.bytes(Corpus.str(v, "recordFileNFC"))), identity, saltSet,
            )

            if (Corpus.bool(v, "expectSameRoot")) {
                assertEquals(nfd.rootHex, composed.rootHex, "$name: the two forms must give one root")
            } else {
                assertNotEquals(nfd.rootHex, composed.rootHex, "$name: the two forms must differ")
            }
            assertEquals(Corpus.str(v, "root"), composed.rootHex, "$name root")
            n++
        }
        Report.pass("normalization", n)
    }

    // ----------------------------------------------- classes 11, 14, 15, 17, 18: whole envelopes --

    @Test
    fun `envelope vectors`() {
        var n = 0
        val config = io.roax.canon.VerifierConfig(
            profiles = Corpus.profiles,
            // The committed corpus and its fixtures are envelope-1.0 documents, which predate the
            // type-map binding, so they carry four always-emitted reserved leaves rather than five.
            // Section 11 requires a verifier to select ONE schema per envelope and never merge them.
            envelopeProfile = EnvelopeProfile.V1_NO_TYPE_MAP_BINDING,
            nfc = nfc,
            resolverFor = { recordType ->
                runCatching { Corpus.typeMap(recordType, nfc) }.getOrNull()
            },
        )

        for (v in Corpus.vectors("envelope")) {
            val name = Corpus.str(v, "name")
            val expectAccept = Corpus.bool(v, "expectAccept")
            val result = EnvelopeVerifier.verify(Corpus.bytes(Corpus.str(v, "envelopeFile")), config)

            if (expectAccept) {
                assertTrue(
                    result is VerificationResult.Accepted,
                    "$name MUST be accepted, but was rejected: ${(result as? VerificationResult.Rejected)?.detail}",
                )
                assertEquals("ok", Corpus.str(v, "reason"), "$name")
            } else {
                assertTrue(result is VerificationResult.Rejected, "$name MUST be rejected")
                // The reason is not decoration: several fixtures are rejectable for more than one
                // cause. `guard-reject-reserved-collision` is the clearest case - the record it
                // carries cannot be hashed at all, so its envelope holds a placeholder root, and an
                // implementation that skips the reserved-namespace guard rejects it on
                // `root-mismatch` and looks correct.
                assertEquals(
                    ReasonEquivalence.expect(Corpus.str(v, "reason")),
                    (result as VerificationResult.Rejected).reason,
                    "$name rejected for the wrong reason: ${result.detail}",
                )
            }
            n++
        }
        Report.pass("envelope", n)
    }

    // ------------------------------ class 20: issue, disclose, verify our OWN output --

    /**
     * Every other test here runs [EnvelopeVerifier] against bytes the corpus generator wrote.
     *
     * That is the gap this class closes: a library can emit a disclosed copy its own verifier
     * refuses and still pass every other vector, because no other vector asks it to PRODUCE one.
     * So this drives the real entry points - [commitWithSaltsByPath], [disclose] and
     * [EnvelopeWriter] - and then puts their output back through [EnvelopeVerifier].
     *
     * The produced envelope is compared with the committed one SEMANTICALLY. JSON member order,
     * `displayPath` and the order of `disclosure.leaves` are not fixed by the specification, so a
     * byte comparison would assert something it does not say; a number's SOURCE TEXT is what must
     * survive, and [JsonNumber] carries it.
     */
    @Test
    fun `round trip vectors`() {
        var n = 0
        for (v in Corpus.vectors("roundTrip")) {
            val name = Corpus.str(v, "name")
            val recordType = Corpus.str(v, "recordType")
            val descriptor = v["typeMap"] as? JsonObject
            val typeMapId = descriptor?.let { Corpus.str(it, "id") }
            val identity = RecordIdentity(
                recordType = recordType,
                schemaVersion = Corpus.str(v, "schemaVersion"),
                recordId = Corpus.str(v, "recordId"),
                issuerId = Corpus.str(v, "issuerId"),
                issuerKeyId = Corpus.strOrNull(v, "issuerKeyId"),
                typeMapId = typeMapId,
                typeMapVersion = descriptor?.let { Corpus.str(it, "version") },
            )
            val envelopeProfile =
                if (typeMapId != null) EnvelopeProfile.V2_TYPE_MAP_BOUND
                else EnvelopeProfile.V1_NO_TYPE_MAP_BINDING
            val recordBytes = Corpus.bytes(Corpus.str(v, "recordFile"))
            val commitment = commitWithSaltsByPath(
                JsonReader.parse(recordBytes),
                IssuanceContext(identity, envelopeProfile, CANON, Sha256.id),
                Corpus.typeMap(recordType, nfc),
                (Corpus.saltSet(Corpus.str(v, "saltsFile"), nfc) as Corpus.SaltSet.ByPath)
                    .byEncodedPath,
                nfc,
                emptyContainers = EmptyContainerAuthorization.CORPUS_1_0_COMPATIBILITY,
            )
            assertEquals(Corpus.int(v, "leafCount"), commitment.leafCount, "$name leafCount")
            assertEquals(Corpus.str(v, "root"), Bytes.toHex(commitment.root), "$name root")

            val reveal = (v["disclosePaths"] as JsonArray).elements.map { Corpus.readSegments(it) }
            val produced = mapOf(
                "expectedFullCopyFile" to EnvelopeWriter.fullCopy(commitment, recordBytes, nfc),
                "expectedDisclosedCopyFile" to
                    EnvelopeWriter.disclosedCopy(commitment.disclose(reveal, nfc), nfc),
            )
            val config = io.roax.canon.VerifierConfig(
                profiles = Corpus.profiles,
                envelopeProfile = envelopeProfile,
                nfc = nfc,
                resolverFor = { type -> runCatching { Corpus.typeMap(type, nfc) }.getOrNull() },
            )
            for ((field, text) in produced) {
                val expected = JsonReader.parse(Corpus.bytes(Corpus.str(v, field)))
                assertEquals(
                    comparable(expected),
                    comparable(JsonReader.parse(text)),
                    "$name $field",
                )
                // And the half no static fixture can assert: this library's verifier over this
                // library's own output. A producer that omitted a per-leaf value carrier fails
                // HERE even though every leaf hash it computed was right.
                val result = EnvelopeVerifier.verify(text.toByteArray(Charsets.UTF_8), config)
                assertTrue(
                    result is VerificationResult.Accepted,
                    "$name $field: this library issued an envelope its own verifier refused: " +
                        "${(result as? VerificationResult.Rejected)?.reason} " +
                        "${(result as? VerificationResult.Rejected)?.detail}",
                )
                n++
            }
        }
        Report.pass("roundTrip", n)
    }

    /**
     * A comparable rendering: object members sorted, `disclosure.leaves` sorted by leaf index,
     * and a number kept as its SOURCE TEXT rather than parsed.
     */
    private fun comparable(value: JsonValue): Any? = when (value) {
        is JsonObject -> value.members
            .sortedBy { it.key }
            .associate { member ->
                val entry = member.value
                member.key to
                    if (member.key == "leaves" && entry is JsonArray) {
                        // Sorted by leaf index: the array order is not fixed by the specification,
                        // so comparing it would assert something the specification does not say.
                        entry.elements
                            .sortedBy { leaf -> ((leaf as JsonObject)["index"] as JsonNumber).literal.toInt() }
                            .map { comparable(it) }
                    } else {
                        comparable(entry)
                    }
            }
        is JsonArray -> value.elements.map { comparable(it) }
        is JsonNumber -> "\$numberLiteral:" + value.literal
        is JsonString -> value.value
        is JsonBoolean -> value.value
        JsonNull -> null
    }

    companion object {
        @JvmStatic
        @AfterAll
        fun summary() = Report.print()
    }
}

/** Collects what ran so the summary distinguishes passed from NOT RUN, as `run.sh` does. */
object Report {
    private val passed = LinkedHashMap<String, Int>()
    private val notRun = ArrayList<Pair<String, String>>()
    private val notes = ArrayList<Pair<String, String>>()

    fun pass(group: String, count: Int) {
        passed[group] = (passed[group] ?: 0) + count
    }

    fun notRun(what: String, why: String) {
        notRun.add(what to why)
    }

    fun note(group: String, text: String) {
        notes.add(group to text)
    }

    fun print() {
        val total = passed.values.sum()
        println()
        println("ROAX-CANON/1 Kotlin - conformance corpus ${Corpus.corpusVersion}")
        println("  canon=${Corpus.canon} hashAlg=${Corpus.hashAlg} unicode=${Corpus.unicodeGate()}")
        for ((group, count) in passed) println("  %-16s %4d passed".format(group, count))
        for ((group, text) in notes) println("  %-16s note: %s".format(group, text))
        println("  %-16s %4d".format("TOTAL PASSED", total))
        if (notRun.isEmpty()) {
            println("  no NOT RUN vectors")
        } else {
            println("  ${notRun.size} NOT RUN:")
            for ((what, why) in notRun) println("    $what - $why")
        }
        println()
    }
}
