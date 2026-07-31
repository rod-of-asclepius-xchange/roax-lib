package io.roax.canon

import io.roax.canon.conformance.Corpus
import io.roax.canon.json.JsonReader
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Assumptions.assumeTrue
import org.junit.jupiter.api.Test
import java.io.File

/**
 * The whole library against a REAL health record, end to end, in one transcript.
 *
 * Class 10 asserts a root and a leaf count for the two MOH samples and stops there, and
 * `SpecificationGapTest` generates a disclosure only over a nine-leaf synthetic fixture. Neither
 * covers the shape a consumer of this library actually runs - a real 92-leaf healthcert committed,
 * selectively disclosed, serialized, verified by a party that never saw the record, and refused
 * when it has been altered - so this test carries it, and prints what it did so the behaviour is
 * readable rather than inferred from an assertion count.
 *
 * The record lives outside this repository by design, so this reports NOT RUN through a JUnit
 * assumption rather than passing vacuously when `ROAX_REFERENCE_RECORDS` is unset, exactly as the
 * corpus runner does for the same four vectors.
 */
class ReferenceRecordDisclosureTest {

    private val nfc = PlatformNfc

    private val vectorName = "record-sg.gov.moh.vaccination-healthcert-with-key-id"

    private val candidates =
        listOf("sg.gov.moh.vaccination-healthcert.json", "sampleVaccineHealthCert.json")

    @Test
    fun `a real vaccination healthcert commits, discloses selectively, verifies, and refuses a tamper`() {
        val dir = System.getenv("ROAX_REFERENCE_RECORDS")
        val file = dir?.let { d -> candidates.map { File(d, it) }.firstOrNull { it.isFile } }
        assumeTrue(
            file != null,
            "NOT RUN: needs the MOH sample; set ROAX_REFERENCE_RECORDS to a directory holding " +
                candidates.joinToString(" or "),
        )
        val recordBytes = file!!.readBytes()

        val v = Corpus.vectors("record").first { Corpus.str(it, "name") == vectorName }
        val identity = RecordIdentity(
            recordType = Corpus.str(v, "recordType"),
            schemaVersion = Corpus.str(v, "schemaVersion"),
            recordId = Corpus.str(v, "recordId"),
            issuerId = Corpus.str(v, "issuerId"),
            issuerKeyId = Corpus.strOrNull(v, "issuerKeyId"),
        )
        val salts = Corpus.saltSet(Corpus.str(v, "saltsFile"), nfc) as Corpus.SaltSet.Positional

        val commitment = commit(
            record = JsonReader.parse(recordBytes),
            context = IssuanceContext(identity, EnvelopeProfile.V1_NO_TYPE_MAP_BINDING),
            resolver = Corpus.typeMap(identity.recordType, nfc),
            saltSource = SaltSource.replaying(salts.salts),
            nfc = nfc,
        )

        say("record      ${identity.recordType} (${recordBytes.size} bytes, real MOH sample)")
        say("committed   ${commitment.leafCount} leaves, root ${commitment.rootHex}")
        say("corpus      $vectorName expects ${Corpus.str(v, "root")}")

        // The roots the corpus carries were computed by two reference implementations written
        // independently of this one, so this equality is the cross-language agreement itself.
        assertEquals(Corpus.int(v, "leafCount"), commitment.leafCount, "leafCount")
        assertEquals(Corpus.str(v, "root"), commitment.rootHex, "root")
        say("            MATCH - byte-identical to the roots the reference implementations computed")

        // What a border officer or a venue needs: the floor this profile declares, plus the two
        // clinical facts. Everything identifying the holder stays withheld.
        val disclosedPaths = listOf(
            listOf(Segment.Key(Reserved.RECORD_TYPE)),
            listOf(Segment.Key(Reserved.SCHEMA_VERSION)),
            listOf(Segment.Key(Reserved.RECORD_ID)),
            listOf(Segment.Key(Reserved.ISSUER_ID)),
            listOf(Segment.Key("validFrom")),
            // TWO segments, never the dotted display string `notarisationMetadata.reference`.
            listOf(Segment.Key("notarisationMetadata"), Segment.Key("reference")),
            listOf(
                Segment.Key("notarisationMetadata"),
                Segment.Key("signedEuHealthCerts"),
                Segment.Index(0),
                Segment.Key("dose"),
            ),
            listOf(
                Segment.Key("fhirBundle"),
                Segment.Key("entry"),
                Segment.Index(3),
                Segment.Key("vaccineCode"),
                Segment.Key("coding"),
                Segment.Index(0),
                Segment.Key("display"),
            ),
        )
        val disclosed = commitment.disclose(disclosedPaths, nfc)
        val json = EnvelopeWriter.disclosedCopy(disclosed, nfc)

        say("")
        say("disclosed   ${disclosed.leaves.size} of ${commitment.leafCount} leaves")
        for (leaf in disclosed.leaves) {
            say("  #%-3d %-9s %-58s %s".format(leaf.index, leaf.tag.name, leaf.displayPath, show(leaf.value)))
        }

        // `dose` is the ruled INTEGER binding of 2026-07-30 (grade Strong). A tag of STRING here
        // would still verify against this root, and would mean the five libraries disagreed.
        val dose = disclosed.leaves.first { it.displayPath.endsWith("dose") }
        assertEquals(TypeTag.INTEGER, dose.tag, "the ruled dose binding is INTEGER")

        val accepted = EnvelopeVerifier.verify(json.toByteArray(), verifierConfig())
        say("")
        say("verifier    $accepted".take(160))
        assertTrue(
            accepted is VerificationResult.Accepted,
            "the honest disclosure was rejected: ${(accepted as? VerificationResult.Rejected)?.detail}",
        )
        assertEquals(identity.recordType, (accepted as VerificationResult.Accepted).recordType)
        assertEquals(disclosedPaths.size, accepted.disclosedPaths.size)
        say("            ACCEPTED - every disclosed leaf recomputed and proved against the root")

        // The point of the exercise: what the verifier never receives. A disclosed copy carries the
        // salt of the leaves it reveals and of no others, so a withheld low-entropy field is not
        // open to a dictionary search (section 10.1).
        val withheld = mapOf(
            "notarisationMetadata.passportNumber" to "E2352363K",
            "fhirBundle.entry[0].identifier[1].value (NRIC)" to "T****111J",
            "fhirBundle.entry[0].birthDate" to "1965-08-09",
            "fhirBundle.entry[0].name[0].text" to "Vaccinated Citizen",
        )
        say("")
        say("withheld    ${commitment.leafCount - disclosed.leaves.size} leaves, including:")
        for ((path, value) in withheld) {
            assertFalse(json.contains(value), "the withheld value at $path reached the wire")
            say("  %-46s value \"%s\" absent from the envelope".format(path, value))
        }
        val revealedIndices = disclosed.leaves.map { it.index }.toSet()
        var saltsChecked = 0
        commitment.leaves.forEachIndexed { i, leaf ->
            if (i in revealedIndices) return@forEachIndexed
            assertFalse(
                json.contains(Bytes.toHex(leaf.salt)),
                "the salt of withheld leaf ${leaf.displayPath} leaked into the disclosed copy",
            )
            saltsChecked++
        }
        assertFalse(json.contains("\"salts\""), "a disclosed copy must carry no `salts` array")
        say("  and the salt of every one of those $saltsChecked withheld leaves is absent too")

        // A holder who edits the copy after issuance.
        val tampered = json.replace("\"2021-12-28T08:32:48.435Z\"", "\"2031-12-28T08:32:48.435Z\"")
        assertTrue(tampered != json, "the substitution must actually have applied")
        val rejected = EnvelopeVerifier.verify(tampered.toByteArray(), verifierConfig())
        say("")
        say("tamper      validFrom 2021-12-28 -> 2031-12-28 in the disclosed copy")
        assertTrue(rejected is VerificationResult.Rejected, "an altered validFrom must be rejected")
        assertEquals(Reason.INCLUSION_PROOF_FAILED, (rejected as VerificationResult.Rejected).reason)
        say("            REJECTED ${rejected.reason.code}")

        // A holder who drops a floor path instead of altering one. `notarisationMetadata.reference`
        // is non-redactable for this profile, and it is the two-segment case the floor table prints
        // as one dotted token.
        val floorShort = commitment.disclose(disclosedPaths.filterIndexed { i, _ -> i != 5 }, nfc)
        val floorResult = EnvelopeVerifier.verify(
            EnvelopeWriter.disclosedCopy(floorShort, nfc).toByteArray(),
            verifierConfig(),
        )
        say("floor       withhold notarisationMetadata.reference, which the profile forbids")
        assertTrue(floorResult is VerificationResult.Rejected, "the floor must be enforced")
        assertEquals(
            Reason.MINIMUM_DISCLOSURE_FLOOR,
            (floorResult as VerificationResult.Rejected).reason,
        )
        say("            REJECTED ${floorResult.reason.code}")
        say("")
    }

    private fun verifierConfig() = VerifierConfig(
        profiles = Corpus.profiles,
        envelopeProfile = EnvelopeProfile.V1_NO_TYPE_MAP_BINDING,
        nfc = nfc,
        resolverFor = { runCatching { Corpus.typeMap(it, nfc) }.getOrNull() },
    )

    private fun show(v: RoaxValue): String = when (v) {
        is RoaxValue.Text -> "\"${v.value.take(48)}\""
        is RoaxValue.Integer -> v.literal
        is RoaxValue.Decimal -> v.literal
        is RoaxValue.Bool -> v.value.toString()
        else -> v.toString()
    }

    private fun say(line: String) = println(line)
}
