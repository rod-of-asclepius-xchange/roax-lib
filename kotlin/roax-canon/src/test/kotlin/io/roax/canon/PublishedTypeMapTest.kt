package io.roax.canon

import io.roax.canon.conformance.Corpus
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertThrows
import org.junit.jupiter.api.Test

/**
 * The **operative** resolver, exercised against the four published artifacts in `type-maps/`.
 *
 * The conformance corpus cannot reach this code at all: every committed vector resolves against a
 * `corpus/type-maps/` display-pattern file, and no published artifact exists for
 * `org.roax.corpus.synthetic`. So without this suite the structured-path DFA that ROAX-CANON/1
 * section 4.2 actually mandates would ship untested, and the superseded format would be the only
 * one under test - which is precisely the inversion
 * `docs/typescript-implementation-findings.md` warns about.
 */
class PublishedTypeMapTest {

    private val nfc = PlatformNfc

    private fun load(file: String): DfaTypeMap =
        DfaTypeMap.load(Corpus.bytes("type-maps/$file"), nfc)

    /** The identity table in `docs/type-maps.md` section 2.1. */
    private val pinned = mapOf(
        "hl7.fhir.bundle-4.0.1.json" to
            "sha256:0e9e642bc89c081e2e6faf651acdc25c46fac83201248ef53a7c812181279807",
        "sg.gov.moh.pdt-healthcert-2.0.json" to
            "sha256:4f8cecc59c85101b8b567658c90651bcbf8f9d4dc279571aa40a03cf04f434ff",
        "sg.gov.moh.recovery-healthcert-2.0.json" to
            "sha256:db935b67a3a82754921267e3af237b606f7489b46e05aa892d175b8d87504177",
        "sg.gov.moh.vaccination-healthcert-1.0.json" to
            "sha256:de7bb92226af5fa5dc5064d9cb203329abc69160f4280fdf739e66e5e0151e93",
    )

    @Test
    fun `every published artifact reproduces its pinned content ID from its exact bytes`() {
        // `docs/type-maps.md` section 2.1: SHA-256 over utf8("ROAX-TYPE-MAP/1") followed by a NUL
        // byte and then the exact artifact bytes. Section 4.2 requires the fetched bytes to
        // reproduce `typeMap.id`, so getting this construction wrong means every record fails to
        // select its map - or, worse, selects one whose bytes were never authenticated.
        for ((file, expected) in pinned) {
            assertEquals(expected, DfaTypeMap.contentIdOf(Corpus.bytes("type-maps/$file")), file)
            assertEquals(expected, load(file).contentId, file)
        }
    }

    @Test
    fun `the artifact selectors are exactly what the registry says`() {
        val vaccination = load("sg.gov.moh.vaccination-healthcert-1.0.json")
        assertEquals("sg.gov.moh.vaccination-healthcert", vaccination.recordType)
        // `schemaVersion` is opaque and matched only for equality - never parsed, never ordered.
        assertEquals("1.0", vaccination.schemaVersion)
        // `typeMapVersion` is one of ROAX's own identifiers, so it legitimately keeps semver shape,
        // but it is exact metadata and MUST NOT select a latest or compatible artifact.
        assertEquals("1.0.0", vaccination.typeMapVersion)

        val fhir = load("hl7.fhir.bundle-4.0.1.json")
        assertEquals("hl7.fhir.bundle", fhir.recordType)
        assertEquals("4.0.1", fhir.schemaVersion)
    }

    @Test
    fun `the DFA resolves declared paths and fails closed everywhere else`() {
        val vaccination = load("sg.gov.moh.vaccination-healthcert-1.0.json")

        assertEquals(TypeTag.STRING, vaccination.resolve(listOf(Segment.Key("validFrom")), JsonKind.STRING))
        assertEquals(TypeTag.STRING, vaccination.resolve(listOf(Segment.Key("logo")), JsonKind.STRING))
        assertEquals(
            TypeTag.STRING,
            vaccination.resolve(
                listOf(
                    Segment.Key("fhirBundle"), Segment.Key("entry"),
                    Segment.Index(0), Segment.Key("fullUrl"),
                ),
                JsonKind.STRING,
            ),
        )
        // An INDEX segment takes `anyIndex`, so any index reaches the same state.
        assertEquals(
            TypeTag.STRING,
            vaccination.resolve(
                listOf(
                    Segment.Key("fhirBundle"), Segment.Key("entry"),
                    Segment.Index(4_294_967_295L), Segment.Key("fullUrl"),
                ),
                JsonKind.STRING,
            ),
        )
        // An empty container is authorized by the map, not assumed from the observed kind.
        assertEquals(TypeTag.EMPTY_ARRAY, vaccination.resolve(listOf(Segment.Key("attachments")), JsonKind.ARRAY))

        // Fail closed: an unknown transition, and a declared path with no output for the kind.
        assertNull(vaccination.resolve(listOf(Segment.Key("notDeclared")), JsonKind.STRING))
        assertNull(vaccination.resolve(listOf(Segment.Key("validFrom")), JsonKind.NUMBER))
        assertNull(
            vaccination.resolve(listOf(Segment.Key("fhirBundle"), Segment.Index(0)), JsonKind.STRING),
            "an INDEX where the map declares only KEY transitions must fail closed",
        )

        val fhir = load("hl7.fhir.bundle-4.0.1.json")
        assertEquals(TypeTag.STRING, fhir.resolve(listOf(Segment.Key("resourceType")), JsonKind.STRING))
        assertNull(fhir.resolve(listOf(Segment.Key("notDeclared")), JsonKind.STRING))
    }

    @Test
    fun `the published artifacts still LAG the four ruled bindings, which section 1-6 states`() {
        // This is the documented gap, asserted so that regenerating the artifacts without updating
        // `docs/type-maps.md` section 1.6 fails here rather than passing silently.
        //
        // "Four of the five rulings are bindings, and not one of those four is in the four
        // published artifacts. All four artifacts lag, not three."
        val vaccination = load("sg.gov.moh.vaccination-healthcert-1.0.json")
        val signed = listOf(
            Segment.Key("notarisationMetadata"),
            Segment.Key("signedEuHealthCerts"),
            Segment.Index(0),
        )
        assertNull(
            vaccination.resolve(signed + Segment.Key("dose"), JsonKind.NUMBER),
            "`dose` is RULED INTEGER but the published artifact still carries an `unresolved` row",
        )
        assertNull(
            vaccination.resolve(signed + Segment.Key("expiryDateTime"), JsonKind.STRING),
            "`expiryDateTime` is RULED STRING but the published artifact still lags",
        )
        // The corpus-side map is a DIFFERENT artifact with a different version line, and it DOES
        // carry both - which is why the shipped vaccination sample commits at all. A sample
        // committing is not evidence that a published artifact carries a binding.
        val corpusSide = Corpus.typeMap("sg.gov.moh.vaccination-healthcert", nfc)
        assertEquals(TypeTag.INTEGER, corpusSide.resolve(signed + Segment.Key("dose"), JsonKind.NUMBER))
        assertEquals(
            TypeTag.STRING,
            corpusSide.resolve(signed + Segment.Key("expiryDateTime"), JsonKind.STRING),
        )
    }

    @Test
    fun `no published artifact emits NULL, BYTES or BLOB_REF`() {
        // `docs/type-maps.md` section 2.3 states this as a MEASURED claim, and it stays true after
        // the rulings for three different reasons: the ruled null-placeholder outcome IS "publish
        // no NULL binding", so the absence of NULL is the ruling being in force; BYTES is absent
        // because the `base64Binary` ruling is not in these bytes yet; and no version-1 profile
        // selects BLOB_REF.
        //
        // Re-measured here rather than trusted, over every reachable binding in all four artifacts.
        for (file in pinned.keys) {
            val artifact = Corpus.bytes("type-maps/$file")
            val tags = tagsUsedIn(artifact)
            for (forbidden in listOf(TypeTag.NULL, TypeTag.BYTES, TypeTag.BLOB_REF)) {
                assertEquals(
                    false,
                    forbidden in tags,
                    "$file emits ${forbidden.name}, which section 2.3 measures as absent",
                )
            }
            // Vaccination exposes STRING outputs and no numeric output at all.
            if (file.startsWith("sg.gov.moh.vaccination")) {
                assertEquals(
                    setOf(TypeTag.STRING, TypeTag.EMPTY_ARRAY, TypeTag.EMPTY_OBJECT),
                    tags,
                    "the vaccination artifact's output tag set changed",
                )
            }
        }
    }

    /** Reads every `bindings[*].tag` out of an artifact's raw bytes. */
    private fun tagsUsedIn(artifactBytes: ByteArray): Set<TypeTag> {
        val root = io.roax.canon.json.JsonReader.parse(artifactBytes) as io.roax.canon.json.JsonObject
        val automaton = root["automaton"] as io.roax.canon.json.JsonObject
        val states = (automaton["states"] as io.roax.canon.json.JsonArray).elements
        val out = HashSet<TypeTag>()
        for (s in states) {
            val state = s as io.roax.canon.json.JsonObject
            val bindings = (state["bindings"] as? io.roax.canon.json.JsonArray)?.elements ?: continue
            for (b in bindings) {
                val binding = b as io.roax.canon.json.JsonObject
                val tag = (binding["tag"] as io.roax.canon.json.JsonNumber).literal
                out.add(TypeTag.ofCode(tag.toInt()))
            }
        }
        return out
    }

    @Test
    fun `an artifact whose transition key is not NFC is refused at load`() {
        // Both sides of the D14a comparison normalize. A conforming artifact's transition keys are
        // already NFC, so a non-NFC one would be permanently DEAD under a normalizing lookup -
        // silently accepting it would hide a map that can never match.
        val decomposedKey = "é"
        val artifact = """
            {"format":"roax-type-map-artifact/1","typeMapVersion":"1.0.0",
             "recordType":"org.roax.corpus.synthetic","schemaVersion":"1.0",
             "automaton":{"representation":"structured-path-dfa","start":"s0","states":[
               {"id":"s0","keys":[{"key":"$decomposedKey","to":"s1"}]},
               {"id":"s1","bindings":[{"jsonKind":"string","tag":2}]}]}}
        """.trimIndent().toByteArray()
        val e = assertThrows(RoaxException::class.java) { DfaTypeMap.load(artifact, nfc) }
        assertEquals(Reason.TYPE_MAP_FAIL_CLOSED, e.reason)

        // The composed spelling loads, and a decomposed SEGMENT then reaches it - which is D14a.
        val composed = artifact.decodeToString().replace(decomposedKey, "é").toByteArray()
        val map = DfaTypeMap.load(composed, nfc)
        assertNotNull(map.resolve(listOf(Segment.Key(decomposedKey)), JsonKind.STRING))
        assertEquals(TypeTag.STRING, map.resolve(listOf(Segment.Key("é")), JsonKind.STRING))
    }

    @Test
    fun `an artifact binding tag 8 is refused at load`() {
        val artifact = """
            {"format":"roax-type-map-artifact/1","typeMapVersion":"1.0.0",
             "recordType":"org.roax.corpus.synthetic","schemaVersion":"1.0",
             "automaton":{"representation":"structured-path-dfa","start":"s0","states":[
               {"id":"s0","keys":[{"key":"blob","to":"s1"}]},
               {"id":"s1","bindings":[{"jsonKind":"string","tag":8}]}]}}
        """.trimIndent().toByteArray()
        val e = assertThrows(RoaxException::class.java) { DfaTypeMap.load(artifact, nfc) }
        assertEquals(Reason.BLOB_REF_NOT_DECLARED, e.reason)
    }

    @Test
    fun `an artifact with two outputs for one observed kind is refused`() {
        // The DFA intentionally carries no first-match rule: each state has at most one output per
        // observed kind, and generation fails on a conflict rather than picking one.
        val artifact = """
            {"format":"roax-type-map-artifact/1","typeMapVersion":"1.0.0",
             "recordType":"org.roax.corpus.synthetic","schemaVersion":"1.0",
             "automaton":{"representation":"structured-path-dfa","start":"s0","states":[
               {"id":"s0","keys":[{"key":"x","to":"s1"}]},
               {"id":"s1","bindings":[{"jsonKind":"number","tag":3},{"jsonKind":"number","tag":4}]}]}}
        """.trimIndent().toByteArray()
        val e = assertThrows(RoaxException::class.java) { DfaTypeMap.load(artifact, nfc) }
        assertEquals(Reason.TYPE_MAP_FAIL_CLOSED, e.reason)
    }

    @Test
    fun `unresolved rows never supply a tag`() {
        // `docs/type-maps.md` section 3: a resolver MUST read outputs only from `bindings`. An
        // `unresolved` row is operative for the EXTENSION lifecycle and never a tag source, so a
        // path represented only by that metadata remains unknown and fails closed.
        val artifact = """
            {"format":"roax-type-map-artifact/1","typeMapVersion":"1.0.0",
             "recordType":"org.roax.corpus.synthetic","schemaVersion":"1.0",
             "automaton":{"representation":"structured-path-dfa","start":"s0","states":[
               {"id":"s0","keys":[{"key":"dose","to":"s1"}]},
               {"id":"s1","unresolved":[{"jsonKinds":["number"],"reason":"schema chooses neither tag"}]}]}}
        """.trimIndent().toByteArray()
        val map = DfaTypeMap.load(artifact, nfc)
        assertNull(map.resolve(listOf(Segment.Key("dose")), JsonKind.NUMBER))
    }
}
